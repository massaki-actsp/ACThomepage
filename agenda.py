"""Admin agenda adapted from Agenda_Module_Export's month view and Google links."""

from __future__ import annotations

import calendar
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from agenda_repository import AgendaRepository
from validation import ValidationError


TIMEZONE = "America/Sao_Paulo"
MONTH_NAMES = ("", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
               "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")
EVENT_TYPES = {"geral": "Geral", "reuniao": "Reunião", "visita": "Visita",
               "atendimento": "Atendimento", "vistoria": "Vistoria", "manutencao": "Manutenção"}


def local_now():
    return datetime.now(ZoneInfo(TIMEZONE))


def validate_event(form):
    payload = {}
    for field, limit in (("title", 160), ("location", 180), ("description", 6000)):
        value = form.get(field, "").strip()
        if len(value) > limit:
            raise ValidationError(f"O campo {field} excede o limite de {limit} caracteres.")
        payload[field] = value
    if not payload["title"]:
        raise ValidationError("Informe o título do compromisso.")
    payload["event_type"] = form.get("event_type", "geral")
    if payload["event_type"] not in EVENT_TYPES:
        raise ValidationError("Tipo de compromisso inválido.")
    try:
        start = datetime.strptime(form.get("start_at", ""), "%Y-%m-%dT%H:%M")
        end = (datetime.strptime(form["end_at"], "%Y-%m-%dT%H:%M")
               if form.get("end_at") else start + timedelta(hours=1))
    except (ValueError, OverflowError):
        raise ValidationError("Informe datas e horários válidos.") from None
    if not 1900 <= start.year <= end.year <= 2100:
        raise ValidationError("Use datas entre 1900 e 2100.")
    if end <= start:
        raise ValidationError("O término deve ser posterior ao início.")
    payload.update(start_at=start.isoformat(timespec="minutes"), end_at=end.isoformat(timespec="minutes"))
    return payload


def google_calendar_link(event):
    def utc(value):
        return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(TIMEZONE)).astimezone(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%SZ")

    details = event["description"]
    for contact in event["contacts"]:
        details += (f"\n\nContato: {contact['name']}\nE-mail: {contact['email']}"
                    f"\nTelefone: {contact['phone']}\nMensagem #{contact['id']}: {contact['message']}")
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE", "text": event["title"],
        "dates": f"{utc(event['start_at'])}/{utc(event['end_at'])}",
        "ctz": TIMEZONE, "details": details.strip(), "location": event["location"],
    })


def create_agenda_blueprint(database_url, contacts_repository, admin_required):
    bp = Blueprint("agenda", __name__, url_prefix="/admin/agenda")
    repository = AgendaRepository(database_url)

    @bp.before_request
    def protect_forms():
        if session.get("admin_authenticated") is not True:
            return  # The admin_required decorator handles unauthenticated requests.
        session.setdefault("agenda_csrf", secrets.token_urlsafe(32))
        if request.method == "POST" and not hmac.compare_digest(
            request.form.get("csrf_token", "").encode(), session["agenda_csrf"].encode()
        ):
            abort(400, description="Formulário expirado. Recarregue a página.")

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store, private"
        return response

    @bp.get("")
    @bp.get("/")
    @admin_required
    def index():
        today = local_now().date()
        try:
            month = datetime.strptime(request.args.get("mes", ""), "%Y-%m").date().replace(day=1)
            if not 1900 <= month.year <= 2100:
                raise ValueError
        except ValueError:
            month = today.replace(day=1)
        next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        previous = (month - timedelta(days=1)).replace(day=1)
        events = repository.list_month(month.isoformat() + "T00:00", next_month.isoformat() + "T00:00")
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month)
        event_days = set()
        for event in events:
            current = max(date.fromisoformat(event["start_at"][:10]), month)
            last = min((datetime.fromisoformat(event["end_at"]) - timedelta(minutes=1)).date(),
                       next_month - timedelta(days=1))
            while current <= last:
                event_days.add(current)
                current += timedelta(days=1)
        return render_template("agenda/index.html", events=events, month=month, today=today,
                               month_name=MONTH_NAMES[month.month], weeks=weeks, event_days=event_days,
                               previous=previous, next_month=next_month, event_types=EVENT_TYPES)

    def event_form(event_id=None):
        existing = repository.get(event_id) if event_id else None
        if event_id and not existing:
            abort(404)
        contacts = existing["contacts"] if existing else []
        values = dict(existing) if existing else {
            "event_type": "atendimento", "title": "", "description": "", "location": "",
            "start_at": "", "end_at": "",
        }
        error = None
        status = 200
        source = request.form if request.method == "POST" else request.args
        form_fields = ("title", "event_type", "start_at", "end_at", "location", "description")
        if request.method == "POST":
            values.update({key: request.form.get(key, "") for key in form_fields})
        try:
            ids = list(dict.fromkeys(source.getlist("message_id")))
            if len(ids) > 10:
                raise ValidationError("Selecione no máximo 10 mensagens por compromisso.")
            if not existing:
                for raw_id in ids:
                    try:
                        message_id = int(raw_id)
                    except ValueError:
                        raise ValidationError("Mensagem inválida.") from None
                    message = contacts_repository.get(message_id)
                    if not message:
                        raise ValidationError("Uma mensagem selecionada não está mais disponível.")
                    contacts.append({key: message[key] for key in ("id", "name", "email", "phone", "message")})
                if contacts and request.method == "GET":
                    values["title"] = f"Atendimento: {contacts[0]['name']}"[:160]
                    suggested_start = local_now().replace(tzinfo=None, second=0, microsecond=0)
                    suggested_start += timedelta(minutes=30 - suggested_start.minute % 30)
                    values["start_at"] = suggested_start.isoformat(timespec="minutes")
            if request.method == "POST":
                payload = validate_event(request.form)
                saved_id = repository.save(payload, contacts, event_id)
                flash("Compromisso salvo com sucesso.", "success")
                return redirect(url_for("agenda.index", mes=payload["start_at"][:7],
                                        _anchor=f"compromisso-{saved_id}"))
            if not existing:
                for key in form_fields:
                    if key in request.args:
                        if contacts and key in {"title", "start_at"} and not request.args[key].strip():
                            continue
                        values[key] = request.args[key]
        except ValidationError as exc:
            error, status = str(exc), 400
        return render_template("agenda/form.html", event=values, contacts=contacts,
                               messages=contacts_repository.list_messages() if not existing else [],
                               event_id=event_id, event_types=EVENT_TYPES, error=error), status

    @bp.route("/new", methods=["GET", "POST"])
    @admin_required
    def new():
        return event_form()

    @bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit(event_id):
        return event_form(event_id)

    @bp.post("/<int:event_id>/delete")
    @admin_required
    def delete(event_id):
        event = repository.get(event_id)
        if not event:
            abort(404)
        repository.delete(event_id)
        flash("Compromisso excluído.", "success")
        return redirect(url_for("agenda.index", mes=event["start_at"][:7]))

    @bp.get("/<int:event_id>/google")
    @admin_required
    def google(event_id):
        event = repository.get(event_id)
        if not event:
            abort(404)
        return redirect(google_calendar_link(event))

    return bp
