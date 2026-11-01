import csv
from io import BytesIO, StringIO

import pytest
from openpyxl import load_workbook

from app import create_app
from database import ContactRepository


@pytest.fixture()
def export_client(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "export-test-secret",
        "ADMIN_USERNAME": "export-admin",
        "ADMIN_PASSWORD": "export-password",
        "ADMIN_PASSWORD_HASH": "",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'exports.db'}",
        "CREATE_TABLES": True,
    })
    with app.test_client() as client:
        yield client


def login(client):
    response = client.post("/admin/login", data={
        "username": "export-admin", "password": "export-password",
    })
    assert response.status_code == 302


@pytest.mark.parametrize("file_format", ["csv", "xlsx"])
def test_exports_require_admin_login(export_client, file_format):
    response = export_client.get(f"/admin/messages/export?format={file_format}")
    assert response.status_code == 302
    assert "/admin/login" in response.location


@pytest.mark.parametrize("file_format", ["csv", "xlsx"])
def test_download_contains_all_saved_messages(export_client, file_format):
    repository = ContactRepository(export_client.application.config["DATABASE_URL"])
    for name, text in [
        ("João Silva", "Olá; preciso de uma proposta.\nCom detalhes."),
        ("=HYPERLINK(\"https://example.com\")", "\t=1+1"),
    ]:
        repository.create({
            "name": name, "phone": "+55 11 98810-9797",
            "email": "contato@example.com", "message": text,
        }, ip_address="", user_agent="")
    login(export_client)
    response = export_client.get(
        f"/admin/messages/export?format={file_format}&name=ausente&status=Cancelado"
    )
    assert response.status_code == 200
    assert f".{file_format}" in response.headers["Content-Disposition"]
    assert "attachment" in response.headers["Content-Disposition"]
    assert "no-store" in response.headers["Cache-Control"]
    if file_format == "csv":
        assert response.mimetype == "text/csv"
        assert response.data.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
        assert rows[1][1].startswith("'=HYPERLINK")
        assert rows[1][4] == "'\t=1+1"
        assert rows[2][2] == "'+55 11 98810-9797"
    else:
        assert response.mimetype.endswith("spreadsheetml.sheet")
        workbook = load_workbook(BytesIO(response.data))
        sheet = workbook.active
        rows = list(sheet.values)
        assert sheet["B2"].data_type == "s"
        assert sheet["E2"].data_type == "s"
        assert rows[1][4] == "\t=1+1"
        assert rows[2][2] == "+55 11 98810-9797"
        assert sheet.freeze_panes == "A2"
        workbook.close()
    assert len(rows) == 3
    assert tuple(rows[0]) == (
        "ID", "Nome", "Telefone", "E-mail", "Mensagem", "Status", "Prioridade",
        "Recebida em", "Atualizada em",
    )
    assert rows[2][1] == "João Silva"
    assert rows[2][4] == "Olá; preciso de uma proposta.\nCom detalhes."
    assert tuple(rows[2][5:7]) == ("Aberto", "Normal")
    assert rows[2][7] and rows[2][8]


@pytest.mark.parametrize("file_format", ["csv", "xlsx"])
def test_empty_export_has_headers(export_client, file_format):
    login(export_client)
    response = export_client.get(f"/admin/messages/export?format={file_format}")
    assert response.status_code == 200
    if file_format == "csv":
        rows = list(csv.reader(StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
    else:
        workbook = load_workbook(BytesIO(response.data))
        rows = list(workbook.active.values)
        workbook.close()
    assert len(rows) == 1
    assert len(rows[0]) == 9


def test_admin_has_download_controls_and_rejects_invalid_format(export_client):
    login(export_client)
    page = export_client.get("/admin").get_data(as_text=True)
    assert 'action="/admin/messages/export"' in page
    assert 'value="xlsx"' in page
    assert 'value="csv"' in page
    assert export_client.get("/admin/messages/export?format=pdf").status_code == 400
