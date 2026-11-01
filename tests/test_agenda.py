from urllib.parse import parse_qs, urlsplit
from datetime import datetime
from html.parser import HTMLParser

import pytest

from agenda_repository import AgendaRepository
from app import create_app
from database import ContactRepository


@pytest.fixture()
def agenda_client(tmp_path):
    app = create_app({
        "TESTING": True, "SECRET_KEY": "agenda-test",
        "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "test-password", "ADMIN_PASSWORD_HASH": "",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'agenda.db'}", "CREATE_TABLES": True,
    })
    with app.test_client() as client:
        yield client


def authenticate(client):
    client.post("/admin/login", data={"username": "admin", "password": "test-password"})
    assert client.get("/admin/agenda/").status_code == 200


def form_data(client, **overrides):
    with client.session_transaction() as state:
        token = state["agenda_csrf"]
    data = {
        "csrf_token": token, "title": "Reunião com João", "event_type": "reuniao",
        "start_at": "2026-10-20T14:00", "end_at": "2026-10-20T15:30",
        "location": "São Paulo & Online", "description": "Proposta & implantação\nPróximos passos.",
    }
    data.update(overrides)
    return data


def repository(client):
    return AgendaRepository(client.application.config["DATABASE_URL"])


def create_contact(client):
    return ContactRepository(client.application.config["DATABASE_URL"]).create({
        "name": "João Silva", "email": "joao@example.com", "phone": "+55 11 99999-1234",
        "message": "Quero agendar uma demonstração do sistema.",
    }, "", "")


@pytest.mark.parametrize("path", ["/admin/agenda/", "/admin/agenda/new", "/admin/agenda/1/edit", "/admin/agenda/1/google"])
def test_agenda_routes_require_login(agenda_client, path):
    response = agenda_client.get(path)
    assert response.status_code == 302
    assert "/admin/login" in response.location


def test_create_import_update_google_link_and_delete(agenda_client):
    client = agenda_client
    message_id = create_contact(client)
    authenticate(client)
    page = client.get(f"/admin/agenda/new?message_id={message_id}").get_data(as_text=True)
    assert "João Silva" in page and "joao@example.com" in page
    assert "Atendimento: João Silva" in page
    response = client.post("/admin/agenda/new", data=form_data(client, message_id=str(message_id)))
    assert response.status_code == 302
    event = repository(client).get(1)
    assert event["contacts"][0]["id"] == message_id
    assert event["description"].endswith("Próximos passos.")
    page = client.get("/admin/agenda/?mes=2026-10").get_data(as_text=True)
    assert "Reunião com João" in page and "Google Agenda" in page
    assert "has-events" in page
    link = client.get("/admin/agenda/1/google")
    params = parse_qs(urlsplit(link.location).query)
    assert urlsplit(link.location).hostname == "calendar.google.com"
    assert params["dates"] == ["20261020T170000Z/20261020T183000Z"]
    assert params["ctz"] == ["America/Sao_Paulo"]
    assert "joao@example.com" in params["details"][0]
    assert "Quero agendar uma demonstração" in params["details"][0]
    assert params["location"] == ["São Paulo & Online"]
    assert "add" not in params
    contacts = ContactRepository(client.application.config["DATABASE_URL"])
    contacts.delete(message_id)
    response = client.post("/admin/agenda/1/edit", data=form_data(client, title="Reunião atualizada"))
    assert response.status_code == 302
    assert repository(client).get(1)["contacts"][0]["email"] == "joao@example.com"
    assert client.post("/admin/agenda/1/delete", data=form_data(client)).status_code == 302
    assert repository(client).get(1) is None


@pytest.mark.parametrize("overrides", [
    {"title": ""}, {"title": "x" * 161}, {"event_type": "invalid"},
    {"start_at": "invalid"}, {"start_at": "2026-02-30T14:00"},
    {"end_at": "2026-10-20T13:00"}, {"end_at": "2026-10-20T14:00"},
    {"start_at": "2026-10-20T14:00+03:00"}, {"location": "x" * 181},
    {"message_id": "9999"}, {"message_id": "invalid"},
])
def test_invalid_events_are_not_saved(agenda_client, overrides):
    authenticate(agenda_client)
    response = agenda_client.post("/admin/agenda/new", data=form_data(agenda_client, **overrides))
    assert response.status_code == 400
    assert repository(agenda_client).list_month("2026-01-01T00:00", "2027-01-01T00:00") == []


def test_csrf_and_missing_event_protection(agenda_client):
    authenticate(agenda_client)
    for endpoint in ("/admin/agenda/new", "/admin/agenda/1/edit", "/admin/agenda/1/delete"):
        assert agenda_client.post(endpoint, data=form_data(agenda_client, csrf_token="wrong")).status_code == 400
    for suffix in ("edit", "google"):
        assert agenda_client.get(f"/admin/agenda/999/{suffix}").status_code == 404
    assert agenda_client.post("/admin/agenda/999/delete", data=form_data(agenda_client)).status_code == 404


def test_default_duration_month_boundaries_and_xss(agenda_client):
    authenticate(agenda_client)
    response = agenda_client.post("/admin/agenda/new", data=form_data(
        agenda_client, title="<script>alert(1)</script>", start_at="2026-10-31T23:30", end_at="",
    ))
    assert response.status_code == 302
    assert repository(agenda_client).get(1)["end_at"] == "2026-11-01T00:30"
    page = agenda_client.get("/admin/agenda/?mes=2026-11").get_data(as_text=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert agenda_client.get("/admin/agenda/?mes=invalid").status_code == 200


def test_multiple_imports_and_preserved_form_values(agenda_client):
    ids = [create_contact(agenda_client) for _ in range(2)]
    authenticate(agenda_client)
    response = agenda_client.get("/admin/agenda/new", query_string={
        "message_id": [str(value) for value in ids], "title": "Título editado",
        "description": "Observação preservada",
    })
    assert "Título editado" in response.get_data(as_text=True)
    assert "Observação preservada" in response.get_data(as_text=True)
    response = agenda_client.post("/admin/agenda/new", data=form_data(
        agenda_client, message_id=[str(value) for value in ids],
    ))
    assert response.status_code == 302
    assert len(repository(agenda_client).get(1)["contacts"]) == 2


class EventFormParser(HTMLParser):
    """Read actual submitted controls instead of manufacturing a valid payload."""

    def __init__(self, html):
        super().__init__()
        self.active = False
        self.action = None
        self.fields = {}
        self.select = None
        self.textarea = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.active = attrs.get("class") == "agenda-event-form"
            if self.active:
                self.action = attrs.get("action")
        if not self.active:
            return
        if tag == "input" and "name" in attrs:
            self.fields[attrs["name"]] = attrs.get("value", "")
        elif tag == "select":
            self.select = attrs["name"]
        elif tag == "option" and self.select:
            if "selected" in attrs or self.select not in self.fields:
                self.fields[self.select] = attrs["value"]
        elif tag == "textarea":
            self.textarea = attrs["name"]
            self.fields[self.textarea] = ""

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = False
        elif tag == "select":
            self.select = None
        elif tag == "textarea":
            self.textarea = None

    def handle_data(self, data):
        if self.active and self.textarea:
            self.fields[self.textarea] += data


def test_imported_message_form_saves_without_missing_required_fields(agenda_client):
    message_id = create_contact(agenda_client)
    authenticate(agenda_client)
    page = agenda_client.get(f"/admin/agenda/new?message_id={message_id}")
    form = EventFormParser(page.get_data(as_text=True))
    assert form.action == "/admin/agenda/new"
    suggested = datetime.fromisoformat(form.fields["start_at"])
    assert suggested.minute in (0, 30)
    assert form.fields["title"] == "Atendimento: João Silva"
    assert form.fields["message_id"] == str(message_id)
    response = agenda_client.post(form.action, data=form.fields)
    assert response.status_code == 302
    assert response.location.endswith("#compromisso-1")
    event = repository(agenda_client).get(1)
    assert event["contacts"][0]["id"] == message_id
    result = agenda_client.get(response.location).get_data(as_text=True)
    assert "Compromisso salvo com sucesso." in result
    assert 'id="compromisso-1"' in result


def test_import_with_blank_preserved_fields_keeps_suggested_start_and_title(agenda_client):
    message_id = create_contact(agenda_client)
    authenticate(agenda_client)
    response = agenda_client.get("/admin/agenda/new", query_string={
        "message_id": message_id, "title": "", "start_at": "",
    })
    form = EventFormParser(response.get_data(as_text=True))
    assert form.fields["title"] == "Atendimento: João Silva"
    assert form.fields["start_at"]
    assert agenda_client.post(form.action, data=form.fields).status_code == 302


def test_failed_import_save_keeps_user_values_and_shows_error(agenda_client):
    message_id = create_contact(agenda_client)
    authenticate(agenda_client)
    response = agenda_client.post("/admin/agenda/new", data=form_data(
        agenda_client, message_id=str(message_id), title="Meu compromisso", start_at="",
    ))
    assert response.status_code == 400
    page = response.get_data(as_text=True)
    assert "Informe datas e horários válidos." in page
    form = EventFormParser(page)
    assert form.fields["title"] == "Meu compromisso"
    assert form.fields["message_id"] == str(message_id)
    assert repository(agenda_client).get(1) is None
