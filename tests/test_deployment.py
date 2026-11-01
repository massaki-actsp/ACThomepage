from html.parser import HTMLParser
from pathlib import Path

import pytest

import app as application_module
from app import create_app


class AssetParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.assets = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"img", "script"} and attrs.get("src"):
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append(attrs["href"])


@pytest.fixture()
def deployment_app(tmp_path):
    return create_app({
        "TESTING": True, "APP_ENV": "development", "CREATE_TABLES": True,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'deployment.db'}",
        "SECRET_KEY": "deployment-tests", "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "test-password", "ADMIN_PASSWORD_HASH": "",
        "TRUSTED_PROXY_COUNT": 0,
    })


def test_public_and_admin_assets_use_static_prefix_on_custom_host(deployment_app):
    with deployment_app.test_client() as client:
        client.post("/admin/login", data={"username": "admin", "password": "test-password"},
                    base_url="https://www.example.com")
        for path in ("/", "/about.html", "/we_do.html", "/portfolio.html", "/contact.html", "/mural.html",
                     "/admin", "/admin/login", "/admin/agenda/", "/admin/logs", "/admin/security"):
            response = client.get(path, base_url="https://www.example.com")
            assert response.status_code == 200
            assets = AssetParser(response.get_data(as_text=True)).assets
            assert assets
            for asset in assets:
                if asset.startswith(("http://", "https://", "//", "data:")):
                    continue
                assert asset.startswith("/static/"), (path, asset)
                assert client.get(asset).status_code == 200, (path, asset)
        mural = client.get("/mural.html").get_data(as_text=True)
        assert 'data-image-base="/static/images/"' in mural
        assert client.get("/static/images/Check-List%20Digital.png").status_code == 200
        assert client.get("/.env").status_code == 404
        assert client.get("/css/style.css").status_code == 404


def test_wsgi_exposes_both_entrypoints():
    from wsgi import app, application
    assert application is app


def test_sqlite_path_is_relative_to_project_not_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(application_module, "BASE_DIR", tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    app = create_app({"TESTING": True, "APP_ENV": "development", "CREATE_TABLES": True,
                      "DATABASE_URL": "sqlite:///instance/path-test.db"})
    assert Path(app.config["DATABASE_URL"].removeprefix("sqlite:///")) == tmp_path / "instance/path-test.db"
    assert not (other / "instance").exists()


def production_settings(**overrides):
    return {"TESTING": True, "APP_ENV": "production", "CREATE_TABLES": False,
            "DATABASE_URL": "postgresql://test:password@example.invalid:5432/postgres?sslmode=require",
            "SECRET_KEY": "a" * 64, "ADMIN_PASSWORD": "strong-test-password", "ADMIN_PASSWORD_HASH": "",
            **overrides}


def test_production_requires_secrets_database_and_ssl_without_connecting():
    for overrides in ({"SECRET_KEY": "short"}, {"DATABASE_URL": "sqlite:///instance/test.db"},
                      {"DATABASE_URL": ""}, {"DATABASE_URL": "postgresql://user:password@example.invalid/db"},
                      {"ADMIN_PASSWORD": "admin"}):
        with pytest.raises(RuntimeError):
            create_app(production_settings(**overrides))
    app = create_app(production_settings(DEBUG=True, SESSION_COOKIE_SECURE=False))
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["DEBUG"] is False


def test_contact_ignores_forged_forwarded_ip_without_proxy(deployment_app):
    with deployment_app.test_client() as client:
        response = client.post("/api/contact", json={"name": "Teste IP", "phone": "11999991234",
            "email": "teste@example.com", "message": "Mensagem para testar captura de IP."},
            headers={"X-Forwarded-For": "1.2.3.4"}, environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
        assert response.status_code == 201
    from database import connect
    with connect(deployment_app.config["DATABASE_URL"]) as connection:
        assert connection.execute("SELECT ip_address FROM contact_messages").fetchone()[0] == "192.0.2.10"
