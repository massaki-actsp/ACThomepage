import csv
from uuid import uuid4

import pytest

from app import create_app
from mural import load_video_items, normalize_external_url, normalize_video_embed_url, video_item_from_row
from pathlib import Path


@pytest.mark.parametrize("url,expected", [
    ("https://youtu.be/Mi7CkzLP38c?si=share", "https://www.youtube.com/embed/Mi7CkzLP38c"),
    ("https://www.youtube.com/watch?v=Mi7CkzLP38c&t=20", "https://www.youtube.com/embed/Mi7CkzLP38c"),
    ("https://m.youtube.com/shorts/Mi7CkzLP38c", "https://www.youtube.com/embed/Mi7CkzLP38c"),
    ("https://www.youtube.com/live/Mi7CkzLP38c", "https://www.youtube.com/embed/Mi7CkzLP38c"),
    ("https://www.youtube-nocookie.com/embed/Mi7CkzLP38c", "https://www.youtube.com/embed/Mi7CkzLP38c"),
    ("https://vimeo.com/76979871", "https://player.vimeo.com/video/76979871"),
    ("http://www.vimeo.com/76979871/", "https://player.vimeo.com/video/76979871"),
    ("https://player.vimeo.com/video/76979871?autoplay=0", "https://player.vimeo.com/video/76979871"),
    ("https://vimeo.com/76979871/5e2d1c1e6d", "https://player.vimeo.com/video/76979871?h=5e2d1c1e6d"),
    ("https://player.vimeo.com/video/76979871?h=5e2d1c1e6d&badge=0", "https://player.vimeo.com/video/76979871?h=5e2d1c1e6d"),
])
def test_normalizes_supported_links(url, expected):
    assert normalize_video_embed_url(url) == expected


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "javascript://www.youtube.com/watch?v=Mi7CkzLP38c",
    "ftp://vimeo.com/76979871", "https://vimeo.com.evil.example/76979871",
    "https://player.vimeo.com@evil.example/video/76979871",
    "https://evil.example@player.vimeo.com/video/76979871",
    "https://vimeo.com:444/76979871", "https://player.vimeo.com/video/not-a-number",
    "https://vimeo.com/0", "https://vimeo.com/76979871?h=javascript:alert(1)",
    "https://vimeo.com/76979871?h=abcdef&h=ghijkl", "//vimeo.com/76979871",
    "https://vimeo.com/7697\n9871", "https://[invalid/video/76979871",
    "https://vimeo.com/76979871?h=",
    "https://vimeo.com\\evil.example/76979871", '<iframe src="https://vimeo.com/76979871"></iframe>',
])
def test_rejects_untrusted_or_malformed_links(url):
    assert normalize_video_embed_url(url) is None


def catalog_row(**overrides):
    return {"id": "1", "title": "Apresentação", "description": "Vídeo de apresentação.",
            "category": "Institucional", "poster": "banner.jpg", "provider": "local",
            "video": "apresentacao.mp4", **overrides}


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "http://aguaviva.actsp.com.br/",
    "https://aguaviva.actsp.com.br.evil.example/",
    "https://aguaviva.actsp.com.br@evil.example/",
    "https://evil@aguaviva.actsp.com.br/", "https://aguaviva.actsp.com.br:444/",
    "https://aguaviva.actsp.com.br/\nunsafe", "https://aguaviva.actsp.com.br\\evil.example/",
])
def test_rejects_unapproved_external_links(url):
    assert normalize_external_url(url) is None
    assert video_item_from_row(catalog_row(provider="external", external_url=url), 1) is None


def test_external_catalog_destination_and_click_logging(tmp_path):
    path = Path(__file__).resolve().parents[1] / "data" / "mural.csv"
    item = next(item for item in load_video_items(path) if item.id == 2)
    assert item.provider == "external"
    assert item.external_url == "https://aguaviva.actsp.com.br/"
    assert item.open_on_select
    assert not item.video and not item.embed_url
    app = create_app({"TESTING": True, "CREATE_TABLES": True,
                      "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}", "MURAL_DATA_PATH": str(path)})
    with app.test_client() as client:
        items = client.get("/api/mural").get_json()["items"]
        assert next(row for row in items if row["id"] == 2)["external_url"] == item.external_url
        assert client.post("/api/mural/clicks", json={"event_id": str(uuid4()), "video_id": 2,
                                                     "source": "carousel"}).status_code == 201


@pytest.mark.parametrize("provider,url,expected", [
    ("vimeo", "https://vimeo.com/76979871", "vimeo"),
    ("embed", "https://vimeo.com/76979871", "vimeo"),
    ("embed", "https://youtu.be/Mi7CkzLP38c", "youtube"),
    ("local", "https://vimeo.com/76979871", "vimeo"),
])
def test_catalog_detects_remote_provider(provider, url, expected):
    item = video_item_from_row(catalog_row(provider=provider, video="", embed_url=url), 1)
    assert item.provider == expected
    assert item.video == ""
    assert item.embed_url


def test_paste_url_into_video_column_and_keep_local_files():
    item = video_item_from_row(catalog_row(video="https://vimeo.com/76979871"), 1)
    assert item.provider == "vimeo"
    assert item.embed_url == "https://player.vimeo.com/video/76979871"
    item = video_item_from_row(catalog_row(), 1)
    assert item.provider == "local" and item.video == "apresentacao.mp4"
    assert item.embed_url is None
    assert video_item_from_row(catalog_row(provider="youtube", embed_url="https://vimeo.com/76979871"), 1) is None
    assert video_item_from_row(catalog_row(provider="vimeo", embed_url="https://youtu.be/Mi7CkzLP38c"), 1) is None


def test_api_mixes_local_youtube_and_vimeo_and_records_clicks(tmp_path):
    path = tmp_path / "catalog.csv"
    rows = [catalog_row(), catalog_row(id="2", provider="youtube", video="", embed_url="https://youtu.be/Mi7CkzLP38c"),
            catalog_row(id="3", provider="vimeo", video="", embed_url="https://vimeo.com/76979871/5e2d1c1e6d")]
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) + ["embed_url"], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    app = create_app({"TESTING": True, "CREATE_TABLES": True,
                      "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}", "MURAL_DATA_PATH": str(path)})
    with app.test_client() as client:
        assert client.get("/mural.html").status_code == 200
        items = client.get("/api/mural").get_json()["items"]
        assert [item["provider"] for item in items] == ["local", "youtube", "vimeo"]
        assert items[2]["embed_url"] == "https://player.vimeo.com/video/76979871?h=5e2d1c1e6d"
        assert client.post("/api/mural/clicks", json={"event_id": str(uuid4()), "video_id": 3,
                                                     "source": "player"}).status_code == 201
