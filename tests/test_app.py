import sqlite3
import json

import pytest

from app import create_app
from database import ensure_contact_table
from mural import normalize_video_embed_url


@pytest.fixture()
def client(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    ensure_contact_table(database_url)
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "admin",
            "ADMIN_PASSWORD_HASH": "",
            "DATABASE_URL": database_url,
            "CREATE_TABLES": False,
        }
    )
    app.config["TEST_DATABASE_PATH"] = tmp_path / "test.db"

    with app.test_client() as test_client:
        yield test_client


def test_page_routes_are_available(client):
    for route in ["/", "/about.html", "/we_do.html", "/portfolio.html", "/mural.html", "/contact.html"]:
        response = client.get(route)
        assert response.status_code == 200


def test_contact_rejects_invalid_payload(client):
    response = client.post(
        "/api/contact",
        json={
            "name": "A",
            "phone": "123",
            "email": "invalid",
            "message": "curta",
        },
    )

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_contact_stores_valid_message(client):
    response = client.post(
        "/api/contact",
        json={
            "name": "Maria Silva",
            "phone": "+55 11 98810-9797",
            "email": "maria@example.com",
            "message": "Gostaria de conversar sobre um projeto para a minha empresa.",
        },
    )

    assert response.status_code == 201

    database_path = client.application.config["TEST_DATABASE_PATH"]
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT name, phone, email, message FROM contact_messages"
        ).fetchone()

    assert row == (
        "Maria Silva",
        "+55 11 98810-9797",
        "maria@example.com",
        "Gostaria de conversar sobre um projeto para a minha empresa.",
    )


def test_mural_page_lists_configured_mp4(tmp_path):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video_path = video_dir / "apresentacao.mp4"
    video_path.write_bytes(b"fake mp4 content")

    metadata_path = tmp_path / "videos.json"
    metadata_path.write_text(
        json.dumps(
            {
                "videos": [
                    {
                        "filename": "apresentacao.mp4",
                        "title": "Video de apresentacao",
                        "description": "Conteudo de teste.",
                        "category": "Institucional",
                        "duration": "02 min",
                        "info_title": "Detalhes",
                        "info_items": [{"label": "Qualidade", "value": "Full HD"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
            "CREATE_TABLES": False,
            "MURAL_LIBRARY_PATH": str(video_dir),
            "MURAL_DATA_PATH": str(metadata_path),
        }
    )

    with app.test_client() as test_client:
        page_response = test_client.get("/mural.html")
        media_response = test_client.get("/media/mural/apresentacao.mp4")

    assert page_response.status_code == 200
    assert "Video de apresentacao".encode() in page_response.data
    assert media_response.status_code == 200
    assert media_response.data == b"fake mp4 content"


def test_mural_api_returns_csv_catalog_and_filters(client):
    response = client.get("/api/mural?category=Sistema%20ERP&name=SindCON")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert len(payload["items"]) == 1
    assert payload["items"][0]["title"] == "SindCON ERP"
    assert payload["items"][0]["provider"] == "youtube"
    assert payload["items"][0]["video"] == ""
    assert payload["items"][0]["embed_url"] == "https://www.youtube.com/embed/SD5lW53LIE4"


def test_video_embed_url_normalization_rejects_untrusted_links():
    assert normalize_video_embed_url("https://youtu.be/Mi7CkzLP38c") == "https://www.youtube.com/embed/Mi7CkzLP38c"
    assert normalize_video_embed_url("javascript:alert(1)") is None
    assert normalize_video_embed_url("https://evil.example/embed/Mi7CkzLP38c") is None


def test_admin_requires_login_and_lists_contact_messages(client):
    response = client.get("/admin")

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]

    client.post(
        "/api/contact",
        json={
            "name": "Ana Souza",
            "phone": "+55 11 98810-9797",
            "email": "ana@example.com",
            "message": "Gostaria de receber uma proposta detalhada para minha empresa.",
        },
    )
    login = client.post("/admin/login", data={"username": "admin", "password": "admin"})

    assert login.status_code == 302

    page = client.get("/admin").get_data(as_text=True)

    assert "Kanban de mensagens" in page
    assert "Ana Souza" in page
    assert "Contato Pendente" in page


def test_admin_api_updates_message_status(client):
    client.post(
        "/api/contact",
        json={
            "name": "Carlos Lima",
            "phone": "+55 11 97777-1111",
            "email": "carlos@example.com",
            "message": "Preciso falar com a equipe sobre uma implantação.",
        },
    )
    client.post("/admin/login", data={"username": "admin", "password": "admin"})

    messages = client.get("/api/admin/messages").get_json()["items"]
    message_id = messages[0]["id"]
    response = client.patch(f"/api/admin/messages/{message_id}/status", json={"status": "Contato_Pendente"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["item"]["status"] == "Contato_Pendente"
