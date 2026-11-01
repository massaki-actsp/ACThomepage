from uuid import uuid4

import pytest
from werkzeug.security import check_password_hash

from admin_security import AdminCredentialRepository
from agenda_repository import AgendaRepository
from app import create_app
from database import ContactRepository, connect


@pytest.fixture()
def security_app(tmp_path):
    return create_app({
        "TESTING": True, "SECRET_KEY": "security-tests", "CREATE_TABLES": True,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'security.db'}",
        "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "old-test-password", "ADMIN_PASSWORD_HASH": "",
        "TRUSTED_PROXY_COUNT": 0,
    })


def sign_in(client, password="old-test-password"):
    return client.post("/admin/login", data={"username": "admin", "password": password})


def security_token(client):
    assert client.get("/admin/security").status_code == 200
    with client.session_transaction() as state:
        return state["admin_csrf"]


def password_form(client, **overrides):
    payload = {"csrf_token": security_token(client), "current_password": "old-test-password",
               "new_password": "new-test-password-123", "confirm_password": "new-test-password-123"}
    return {**payload, **overrides}


def insert_log(app):
    with connect(app.config["DATABASE_URL"]) as db:
        db.execute("INSERT INTO mural_click_logs (event_id,video_id,video_title,source,ip_address,clicked_at) "
                   "VALUES (?,1,'Teste','carousel','127.0.0.1','2026-10-01T12:00:00.000000+00:00')",
                   (str(uuid4()),))


def count_logs(app):
    with connect(app.config["DATABASE_URL"]) as db:
        return db.execute("SELECT COUNT(*) FROM mural_click_logs").fetchone()[0]


def test_security_actions_require_login_and_only_post_can_mutate(security_app):
    with security_app.test_client() as client:
        for method, url in [("get", "/admin/security"), ("post", "/admin/security/password"),
                            ("post", "/admin/logs/reset")]:
            response = getattr(client, method)(url)
            assert response.status_code == 302
            assert "/admin/login" in response.location
        # The static-file fallback may return 404 for GET on POST-only routes.
        assert client.get("/admin/security/password").status_code in (404, 405)
        assert client.get("/admin/logs/reset").status_code in (404, 405)


def test_password_change_hash_persistence_and_session_invalidation(security_app):
    client = security_app.test_client()
    other_client = security_app.test_client()
    sign_in(client)
    sign_in(other_client)
    response = client.post("/admin/security/password", data=password_form(client))
    assert response.status_code == 302 and response.location.endswith("/admin/login")
    stored = AdminCredentialRepository(security_app.config["DATABASE_URL"]).get("admin")
    assert stored["password_hash"] != "new-test-password-123"
    assert check_password_hash(stored["password_hash"], "new-test-password-123")
    assert client.get("/admin").status_code == 302
    assert other_client.get("/admin/logs").status_code == 302
    assert sign_in(client).status_code == 401
    assert sign_in(client, "new-test-password-123").status_code == 302
    assert client.get("/admin").status_code == 200
    assert client.get("/admin/security").headers["Cache-Control"] == "no-store, private"
    restarted = create_app({**security_app.config, "CREATE_TABLES": False})
    with restarted.test_client() as new_client:
        assert sign_in(new_client).status_code == 401
        assert sign_in(new_client, "new-test-password-123").status_code == 302
        assert new_client.get("/admin").status_code == 200


@pytest.mark.parametrize("overrides", [
    {"current_password": "wrong"}, {"new_password": "short", "confirm_password": "short"},
    {"new_password": "x" * 129, "confirm_password": "x" * 129},
    {"confirm_password": "does-not-match"},
    {"new_password": "old-test-password", "confirm_password": "old-test-password"},
    {"new_password": " " * 12, "confirm_password": " " * 12},
])
def test_invalid_password_changes_do_not_change_credentials(security_app, overrides):
    with security_app.test_client() as client:
        sign_in(client)
        response = client.post("/admin/security/password", data=password_form(client, **overrides))
        assert response.status_code == 400
        assert AdminCredentialRepository(security_app.config["DATABASE_URL"]).get("admin") is None
        assert client.get("/admin").status_code == 200
        assert 'value="old-test-password"' not in response.get_data(as_text=True)


def test_security_forms_reject_missing_or_invalid_csrf(security_app):
    insert_log(security_app)
    with security_app.test_client() as client:
        sign_in(client)
        for token in ("", "wrong", "inválido"):
            assert client.post("/admin/security/password", data=password_form(client, csrf_token=token)).status_code == 400
            assert client.post("/admin/logs/reset", data={
                "csrf_token": token, "current_password": "old-test-password", "confirmation": "APAGAR LOGS",
            }).status_code == 400
        assert count_logs(security_app) == 1


def test_reset_logs_preserves_messages_and_agenda_and_zeros_stats(security_app):
    insert_log(security_app)
    insert_log(security_app)
    contacts = ContactRepository(security_app.config["DATABASE_URL"])
    message_id = contacts.create({"name": "Teste", "email": "teste@example.com", "phone": "11999991234",
                                  "message": "Mensagem preservada."}, "", "")
    agenda = AgendaRepository(security_app.config["DATABASE_URL"])
    event_id = agenda.save({"title": "Preservado", "event_type": "geral", "start_at": "2026-10-30T12:00",
                           "end_at": "2026-10-30T13:00", "location": "", "description": ""}, [])
    with security_app.test_client() as client:
        sign_in(client)
        response = client.post("/admin/logs/reset", data={
            "csrf_token": security_token(client), "current_password": "old-test-password",
            "confirmation": "APAGAR LOGS", "start": "2099-01-01",
        })
        assert response.status_code == 302
        assert count_logs(security_app) == 0
        page = client.get("/admin/logs").get_data(as_text=True)
        assert "2 registro(s) de cliques apagado(s)" in page
        assert "Ainda não há cliques" in page
        assert len(client.get("/admin/logs/export?format=csv").data.decode("utf-8-sig").splitlines()) == 1
    assert contacts.get(message_id) is not None
    assert agenda.get(event_id) is not None


@pytest.mark.parametrize("confirmation,password", [("", "old-test-password"), ("APAGAR LOGS", "wrong")])
def test_reset_requires_confirmation_and_password(security_app, confirmation, password):
    insert_log(security_app)
    with security_app.test_client() as client:
        sign_in(client)
        client.post("/admin/logs/reset", data={
            "csrf_token": security_token(client), "current_password": password, "confirmation": confirmation,
        })
    assert count_logs(security_app) == 1


def test_stale_password_change_cannot_overwrite_new_password(security_app):
    repo = AdminCredentialRepository(security_app.config["DATABASE_URL"])
    assert repo.change_password("admin", "first-test-hash", "")
    assert not repo.change_password("admin", "stale-test-hash", "")
    assert repo.get("admin")["password_hash"] == "first-test-hash"
