from datetime import datetime, timezone
from uuid import uuid4
import csv
from io import BytesIO, StringIO

import pytest
from openpyxl import load_workbook

from app import create_app
from database import connect
from mural import list_videos
from mural_logs import MuralLogRepository, pie_layout, utc_stamp


@pytest.fixture()
def logs_app(tmp_path):
    return create_app({
        "TESTING": True, "SECRET_KEY": "logs-tests", "CREATE_TABLES": True,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'logs.db'}",
        "MURAL_DATA_PATH": str(tmp_path / "missing.csv"),
        "ADMIN_USERNAME": "test", "ADMIN_PASSWORD": "test", "ADMIN_PASSWORD_HASH": "",
        "TRUSTED_PROXY_COUNT": 0,
    })


def event(**overrides):
    payload = {"event_id": str(uuid4()), "video_id": 1, "source": "carousel"}
    payload.update(overrides)
    return payload


def login(client):
    client.post("/admin/login", data={"username": "test", "password": "test"})


def test_click_stores_catalog_title_server_time_and_connection_ip(logs_app):
    before = datetime.now(timezone.utc)
    with logs_app.test_client() as client:
        response = client.post("/api/mural/clicks", json=event(
            title="forged", ip_address="1.2.3.4", clicked_at="1900-01-01",
        ), headers={"X-Forwarded-For": "1.2.3.4"}, environ_overrides={"REMOTE_ADDR": "2001:db8::5"})
    assert response.status_code == 201
    with connect(logs_app.config["DATABASE_URL"]) as db:
        row = db.execute("SELECT video_title, ip_address, clicked_at FROM mural_click_logs").fetchone()
    assert row[:2] == ("SindCON ERP", "2001:db8::5")
    assert before <= datetime.fromisoformat(row[2]) <= datetime.now(timezone.utc)


def test_duplicate_events_count_once_but_distinct_clicks_count_separately(logs_app):
    payload = event()
    with logs_app.test_client() as client:
        assert client.post("/api/mural/clicks", json=payload).status_code == 201
        assert client.post("/api/mural/clicks", json=payload).status_code == 200
        assert client.post("/api/mural/clicks", json=event(source="player")).status_code == 201
    with connect(logs_app.config["DATABASE_URL"]) as db:
        assert db.execute("SELECT COUNT(*) FROM mural_click_logs").fetchone()[0] == 2


@pytest.mark.parametrize("payload, status", [
    ([], 400), (None, 400), ({}, 400), (event(video_id=True), 400),
    (event(video_id="1"), 400), (event(source=[]), 400), (event(source="autoplay"), 400),
    (event(event_id="invalid"), 400), (event(video_id=999), 404),
])
def test_invalid_events_rejected(logs_app, payload, status):
    with logs_app.test_client() as client:
        response = client.post("/api/mural/clicks", json=payload, content_type="application/json")
        assert response.status_code == status
    with connect(logs_app.config["DATABASE_URL"]) as db:
        assert db.execute("SELECT COUNT(*) FROM mural_click_logs").fetchone()[0] == 0


def test_cross_site_and_form_submissions_rejected(logs_app):
    with logs_app.test_client() as client:
        assert client.post("/api/mural/clicks", data=event()).status_code == 415
        assert client.post("/api/mural/clicks", json=event(), headers={"Origin": "https://other.example"}).status_code == 403
        assert client.post("/api/mural/clicks", json=event(), headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert client.post("/api/mural/clicks", json=event(), headers={"Origin": "http://localhost"}).status_code == 201


def test_admin_report_requires_login_and_does_not_publish_ips(logs_app):
    with logs_app.test_client() as client:
        response = client.get("/admin/logs")
        assert response.status_code == 302
        assert "/admin/login" in response.location
        login(client)
        page = client.get("/admin/logs")
        assert page.status_code == 200
        assert "LOGs de usuários" in page.get_data(as_text=True)
        assert "Ainda não há cliques" in page.get_data(as_text=True)
        assert page.headers["Cache-Control"] == "no-store, private"
        assert "logs" not in client.get("/api/mural").get_json()


def test_percentages_all_current_videos_and_retired_exclusion(logs_app):
    with logs_app.test_client() as client:
        for video_id in [1, 1, 1, 2]:
            assert client.post("/api/mural/clicks", json=event(video_id=video_id)).status_code == 201
        login(client)
        page = client.get("/admin/logs").get_data(as_text=True)
        assert "75.00%" in page and "25.00%" in page and "0.00%" in page
        assert 'class="logs-pie"' in page
        assert "75.0%" in page and "(3 cliques)" in page
        assert "25.0%" in page and "(1 clique)" in page
    videos = list_videos(data_path=logs_app.config["MURAL_DATA_PATH"])
    report = MuralLogRepository(logs_app.config["DATABASE_URL"]).report(videos[1:], None, None, 1)
    assert report["total"] == 1 and report["retired"] == 3
    assert report["ranking"][0]["percentage"] == 100
    assert report["unique_ips"] == 1
    assert len(report["ranking"]) == 2


def test_date_range_uses_brasilia_boundaries_and_pagination(logs_app):
    with connect(logs_app.config["DATABASE_URL"]) as db:
        for timestamp in ["2026-10-16T02:59:59.000000+00:00", "2026-10-16T03:00:00.000000+00:00",
                          "2026-10-17T02:59:59.000000+00:00", "2026-10-17T03:00:00.000000+00:00"]:
            db.execute("INSERT INTO mural_click_logs (event_id,video_id,video_title,source,ip_address,clicked_at) VALUES (?,1,?,'catalog','127.0.0.1',?)",
                       (str(uuid4()), "<script>untrusted</script>", timestamp))
    repo = MuralLogRepository(logs_app.config["DATABASE_URL"])
    report = repo.report(list_videos(), "2026-10-16T03:00:00.000000+00:00", "2026-10-17T03:00:00.000000+00:00", 1)
    assert report["total"] == 2
    with logs_app.test_client() as client:
        login(client)
        page = client.get("/admin/logs?start=2026-10-16&end=2026-10-16").get_data(as_text=True)
        assert "16/10/2026 00:00:00" in page and "16/10/2026 23:59:59" in page
        assert "&lt;script&gt;untrusted&lt;/script&gt;" in page
        assert "<script>untrusted</script>" not in page
        assert client.get("/admin/logs?start=invalid").status_code == 400
        assert client.get("/admin/logs?start=2026-10-17&end=2026-10-16").status_code == 400
    with connect(logs_app.config["DATABASE_URL"]) as db:
        for _ in range(51):
            db.execute("INSERT INTO mural_click_logs (event_id,video_id,video_title,source,ip_address,clicked_at) VALUES (?,1,'Teste','catalog','127.0.0.1',?)",
                       (str(uuid4()), utc_stamp(datetime.now(timezone.utc))))
    report = repo.report(list_videos(), None, None, 1)
    assert report["total"] == 55 and report["pages"] == 2 and len(report["history"]) == 50
    assert len(repo.report(list_videos(), None, None, 2)["history"]) == 5


def test_rate_limit_and_trusted_proxy(logs_app):
    with connect(logs_app.config["DATABASE_URL"]) as db:
        for _ in range(120):
            db.execute("INSERT INTO mural_click_logs (event_id,video_id,video_title,source,ip_address,clicked_at) VALUES (?,1,'Teste','catalog','127.0.0.1',?)",
                       (str(uuid4()), utc_stamp(datetime.now(timezone.utc))))
    with logs_app.test_client() as client:
        assert client.post("/api/mural/clicks", json=event()).status_code == 429
    settings = {key: logs_app.config[key] for key in ("DATABASE_URL", "MURAL_DATA_PATH")}
    proxy_app = create_app({**settings, "TESTING": True, "CREATE_TABLES": False, "TRUSTED_PROXY_COUNT": 1})
    with proxy_app.test_client() as client:
        assert client.post("/api/mural/clicks", json=event(), headers={"X-Forwarded-For": "1.2.3.4, 192.0.2.10"}).status_code == 201
    with connect(logs_app.config["DATABASE_URL"]) as db:
        assert db.execute("SELECT ip_address FROM mural_click_logs ORDER BY id DESC LIMIT 1").fetchone()[0] == "192.0.2.10"


def test_pie_labels_for_single_video_empty_data_and_tiny_slices():
    assert pie_layout([])["slices"] == []
    single = pie_layout([{"title": "Único", "count": 5, "percentage": 100, "color": "#187d70"}])
    assert single["slices"][0]["full_circle"] is True
    assert single["slices"][0]["label_x"] == 200
    assert single["slices"][0]["label_y"] == single["center_y"]
    items = [{"title": "Principal", "count": 88, "percentage": 88, "color": "#187d70"}]
    items.extend({"title": f"Vídeo {index}", "count": 1, "percentage": 1, "color": "#d64c73"}
                 for index in range(12))
    chart = pie_layout(items)
    assert len(chart["slices"]) == 13
    assert not any(item["full_circle"] for item in chart["slices"])
    for side in (True, False):
        labels = sorted(item["label_y"] for item in chart["slices"] if item["outside"] and item["right"] == side)
        assert all(y2 - y1 >= 39.99 for y1, y2 in zip(labels, labels[1:]))
        assert all(20 <= y <= chart["height"] - 20 for y in labels)


def read_export(response, file_format):
    if file_format == "csv":
        assert response.data.startswith(b"\xef\xbb\xbf")
        return list(csv.reader(StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
    workbook = load_workbook(BytesIO(response.data))
    assert workbook.active.title == "Histórico de cliques"
    rows = list(workbook.active.values)
    assert all(cell.data_type == "s" for cell in list(workbook.active.rows)[1][3:]) if len(rows) > 1 else True
    workbook.close()
    return rows


@pytest.mark.parametrize("file_format", ["csv", "xlsx"])
def test_history_download_requires_login_and_empty_export_has_headers(logs_app, file_format):
    with logs_app.test_client() as client:
        url = f"/admin/logs/export?format={file_format}"
        assert client.get(url).status_code == 302
        login(client)
        response = client.get(url)
        assert response.status_code == 200
        assert "no-store" in response.headers["Cache-Control"]
        assert "attachment" in response.headers["Content-Disposition"]
        assert f".{file_format}" in response.headers["Content-Disposition"]
        assert tuple(read_export(response, file_format)[0]) == (
            "ID", "Data e hora (Brasília)", "ID do vídeo", "Vídeo", "Origem", "IP",
        )
        assert len(read_export(response, file_format)) == 1


@pytest.mark.parametrize("file_format", ["csv", "xlsx"])
def test_history_download_all_pages_filters_timezone_and_retired_videos(logs_app, file_format):
    with connect(logs_app.config["DATABASE_URL"]) as db:
        for index in range(55):
            db.execute("INSERT INTO mural_click_logs (event_id,video_id,video_title,source,ip_address,clicked_at) VALUES (?,999,?,'catalog','2001:db8::5',?)",
                       (str(uuid4()), '=HYPERLINK("https://example.com")', "2026-10-17T02:59:59.000000+00:00"))
        db.execute("INSERT INTO mural_click_logs (event_id,video_id,video_title,source,ip_address,clicked_at) VALUES (?,1,'Fora do período','carousel','127.0.0.1',?)",
                   (str(uuid4()), "2026-10-17T03:00:00.000000+00:00"))
    with logs_app.test_client() as client:
        login(client)
        response = client.get(f"/admin/logs/export?format={file_format}&start=2026-10-16&end=2026-10-16&page=2")
        assert response.status_code == 200
        rows = read_export(response, file_format)
        assert len(rows) == 56
        assert rows[1][1] == "16/10/2026 23:59:59"
        assert str(rows[1][2]) == "999"
        expected_title = '=HYPERLINK("https://example.com")'
        assert rows[1][3] == ("'" + expected_title if file_format == "csv" else expected_title)
        assert tuple(rows[1][4:]) == ("Catálogo", "2001:db8::5")
        all_rows = read_export(client.get(f"/admin/logs/export?format={file_format}"), file_format)
        assert len(all_rows) == 57
        page = client.get("/admin/logs?start=2026-10-16&end=2026-10-16").get_data(as_text=True)
        assert 'action="/admin/logs/export"' in page
        assert 'name="start" value="2026-10-16"' in page


@pytest.mark.parametrize("query", ["format=pdf", "start=invalid", "start=2026-10-17&end=2026-10-16"])
def test_history_export_rejects_invalid_options(logs_app, query):
    with logs_app.test_client() as client:
        login(client)
        response = client.get("/admin/logs/export?" + query)
        assert response.status_code == 400
        assert "Content-Disposition" not in response.headers
