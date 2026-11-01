from __future__ import annotations

import os
import hmac
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from admin import KANBAN_COLUMNS, KANBAN_PRIORITIES, is_valid_status, validate_admin_message_payload
from admin_security import (
    AdminCredentialRepository, admin_csrf_token, ensure_admin_credentials_table,
    require_admin_csrf, validate_new_password,
)
from agenda import create_agenda_blueprint
from agenda_repository import ensure_agenda_table
from database import ContactRepository, ensure_contact_table, is_sqlite
from message_exports import export_csv, export_xlsx
from validation import ValidationError, validate_contact_payload
from mural import get_video_categories, list_videos
from mural_logs import create_mural_logs_blueprint, ensure_mural_logs_table
from werkzeug.middleware.proxy_fix import ProxyFix


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def resolve_project_path(value: str) -> str:
    path = Path(value)

    if path.is_absolute():
        return str(path)

    return str(BASE_DIR / path)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / "static"),
        static_url_path="/static",
        template_folder=str(BASE_DIR / "templates"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "actsp-dev-secret-change-me"),
        APP_ENV=os.getenv("APP_ENV", "development"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        ADMIN_USERNAME=os.getenv("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", "admin"),
        ADMIN_PASSWORD_HASH=os.getenv("ADMIN_PASSWORD_HASH", ""),
        DATABASE_URL=os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'actsp.db'}"),
        CREATE_TABLES=os.getenv("CREATE_TABLES", "false").lower() == "true",
        MAX_CONTENT_LENGTH=32 * 1024,
        TRUSTED_PROXY_COUNT=int(os.getenv("TRUSTED_PROXY_COUNT", "0")),
        MURAL_LIBRARY_PATH=resolve_project_path(os.getenv("MURAL_LIBRARY_PATH", os.getenv("VIDEO_LIBRARY_PATH", "static/videos"))),
        MURAL_DATA_PATH=resolve_project_path(os.getenv("MURAL_DATA_PATH", os.getenv("VIDEO_DATA_PATH", "data/mural.csv"))),
        VIDEO_METADATA_PATH=resolve_project_path(os.getenv("VIDEO_METADATA_PATH", "data/mural.csv")),
    )

    if test_config:
        app.config.update(test_config)
        if "VIDEO_LIBRARY_PATH" in test_config and "MURAL_LIBRARY_PATH" not in test_config:
            app.config["MURAL_LIBRARY_PATH"] = app.config["VIDEO_LIBRARY_PATH"]
        if "VIDEO_METADATA_PATH" in test_config and "MURAL_DATA_PATH" not in test_config:
            app.config["MURAL_DATA_PATH"] = app.config["VIDEO_METADATA_PATH"]
        if "VIDEO_DATA_PATH" in test_config and "MURAL_DATA_PATH" not in test_config:
            app.config["MURAL_DATA_PATH"] = app.config["VIDEO_DATA_PATH"]

    if is_sqlite(app.config["DATABASE_URL"]):
        db_path = app.config["DATABASE_URL"].removeprefix("sqlite:///")
        app.config["DATABASE_URL"] = "sqlite:///" + resolve_project_path(db_path)
    if app.config["APP_ENV"] == "production":
        if len(app.config["SECRET_KEY"]) < 32 or app.config["SECRET_KEY"] == "actsp-dev-secret-change-me":
            raise RuntimeError("Defina SECRET_KEY com pelo menos 32 caracteres para produção.")
        parsed_database = urlsplit(app.config["DATABASE_URL"])
        if parsed_database.scheme not in {"postgresql", "postgres"}:
            raise RuntimeError("Configure DATABASE_URL com PostgreSQL para produção.")
        if parse_qs(parsed_database.query).get("sslmode", [""])[0] not in {"require", "verify-ca", "verify-full"}:
            raise RuntimeError("Configure SSL obrigatório na conexão PostgreSQL de produção.")
        if not app.config["ADMIN_PASSWORD_HASH"] and len(app.config["ADMIN_PASSWORD"]) < 12:
            raise RuntimeError("Defina ADMIN_PASSWORD_HASH ou uma senha inicial forte para produção.")
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["DEBUG"] = False

    if app.config["CREATE_TABLES"]:
        ensure_contact_table(app.config["DATABASE_URL"])
    if app.config["CREATE_TABLES"] or is_sqlite(app.config["DATABASE_URL"]):
        ensure_agenda_table(app.config["DATABASE_URL"])
        ensure_mural_logs_table(app.config["DATABASE_URL"])
        ensure_admin_credentials_table(app.config["DATABASE_URL"])

    proxy_count = app.config["TRUSTED_PROXY_COUNT"]
    if proxy_count:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count, x_proto=proxy_count, x_host=0)

    repository = ContactRepository(app.config["DATABASE_URL"])
    credentials = AdminCredentialRepository(app.config["DATABASE_URL"])

    def credential_version() -> str:
        stored = credentials.get(app.config["ADMIN_USERNAME"])
        return stored["version"] if stored else ""

    def is_admin_logged_in() -> bool:
        return (
            session.get("admin_authenticated") is True
            and session.get("admin_username") == app.config["ADMIN_USERNAME"]
            and session.get("admin_credential_version", "") == credential_version()
        )

    def verify_admin_credentials(username: str, password: str) -> bool:
        expected_username = app.config["ADMIN_USERNAME"]
        if not hmac.compare_digest(username.strip().encode(), expected_username.encode()):
            return False

        stored = credentials.get(expected_username)
        password_hash = stored["password_hash"] if stored else app.config.get("ADMIN_PASSWORD_HASH", "")
        if password_hash:
            return check_password_hash(password_hash, password)

        expected_password = app.config.get("ADMIN_PASSWORD", "")
        return bool(expected_password) and hmac.compare_digest(password.encode(), expected_password.encode())

    def safe_local_redirect(target: str | None) -> str:
        if target and target.startswith("/") and not target.startswith("//"):
            return target
        return url_for("admin")

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not is_admin_logged_in():
                session.clear()
                flash("Faça login como administrador para acessar esta área.", "error")
                return redirect(url_for("admin_login", next=request.full_path))
            return view(*args, **kwargs)

        return wrapped

    app.register_blueprint(create_agenda_blueprint(app.config["DATABASE_URL"], repository, admin_required))
    app.register_blueprint(create_mural_logs_blueprint(app, admin_required, verify_admin_credentials))

    @app.context_processor
    def security_template_helpers():
        return {"admin_csrf_token": admin_csrf_token}

    @app.after_request
    def apply_security_headers(response):
        if request.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store, private"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.get("/")
    @app.get("/index.html")
    def index():
        return render_template("index.html")

    @app.get("/about")
    @app.get("/about.html")
    def about():
        return render_template("about.html")

    @app.get("/we-do")
    @app.get("/we_do")
    @app.get("/we_do.html")
    def we_do():
        return render_template("we_do.html")

    @app.get("/portfolio")
    @app.get("/portfolio.html")
    def portfolio():
        return render_template("portfolio.html")

    @app.get("/mural")
    @app.get("/mural.html")
    def mural():
        video_items = list_videos(
            app.config["MURAL_LIBRARY_PATH"],
            app.config["MURAL_DATA_PATH"],
        )
        return render_template(
            "mural.html",
            videos=video_items,
            categories=get_video_categories(video_items),
        )

    @app.get("/api/mural")
    def api_mural():
        category = request.args.get("category", "").strip()
        name = request.args.get("name", "").strip().lower()
        video_items = list_videos(
            app.config["MURAL_LIBRARY_PATH"],
            app.config["MURAL_DATA_PATH"],
        )

        if category:
            video_items = [item for item in video_items if item.category == category]
        if name:
            video_items = [item for item in video_items if name in item.title.lower()]

        return jsonify({"ok": True, "items": [item.to_dict() for item in video_items]})

    @app.get("/media/mural/<path:filename>")
    def mural_media(filename: str):
        safe_filename = secure_filename(filename)

        if safe_filename != filename or not safe_filename.lower().endswith(".mp4"):
            abort(404)

        return send_from_directory(app.config["MURAL_LIBRARY_PATH"], safe_filename)

    @app.get("/contact")
    @app.get("/contact.html")
    def contact():
        return render_template("contact.html")

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            login_version = credential_version()
            if verify_admin_credentials(username, password):
                session.clear()
                session["admin_authenticated"] = True
                session["admin_username"] = username.strip()
                session["admin_credential_version"] = login_version
                flash("Login administrativo realizado com sucesso.", "success")
                return redirect(safe_local_redirect(request.args.get("next")))

            flash("Usuário ou senha de administrador inválidos.", "error")
            return render_template("admin_login.html", username=username), 401

        return render_template("admin_login.html", username="")

    @app.get("/admin/security")
    @admin_required
    def admin_security():
        return render_template("admin_security.html", error=None)

    @app.post("/admin/security/password")
    @admin_required
    def admin_change_password():
        require_admin_csrf()
        username = app.config["ADMIN_USERNAME"]
        expected_version = credential_version()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        try:
            if not verify_admin_credentials(username, current_password):
                raise ValidationError("Senha atual incorreta.")
            validate_new_password(new_password, request.form.get("confirm_password", ""))
            if verify_admin_credentials(username, new_password):
                raise ValidationError("A nova senha deve ser diferente da senha atual.")
            if not credentials.change_password(username, generate_password_hash(new_password), expected_version):
                raise ValidationError("A senha foi alterada em outra sessão. Faça login novamente.")
        except ValidationError as error:
            return render_template("admin_security.html", error=str(error)), 400
        session.clear()
        flash("Senha alterada com sucesso. Faça login com a nova senha.", "success")
        return redirect(url_for("admin_login"))

    @app.post("/admin/logout")
    @admin_required
    def admin_logout():
        session.clear()
        flash("Sessão administrativa encerrada.", "success")
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    @admin_required
    def admin():
        status_filter = request.args.get("status", "")
        name_filter = request.args.get("name", "")
        status = status_filter if status_filter and is_valid_status(status_filter) else None
        messages = repository.list_messages(status=status, name=name_filter or None)
        grouped_messages = {
            column.key: [message for message in messages if message["status"] == column.key]
            for column in KANBAN_COLUMNS
        }

        return render_template(
            "admin.html",
            messages=messages,
            grouped_messages=grouped_messages,
            kanban_columns=KANBAN_COLUMNS,
            priorities=KANBAN_PRIORITIES,
            current_status=status_filter,
            current_name=name_filter,
        )

    @app.get("/admin/messages/export")
    @admin_required
    def admin_export_messages():
        file_format = request.args.get("format", "xlsx").lower()
        if file_format not in {"csv", "xlsx"}:
            abort(400, description="Formato de exportação inválido. Use CSV ou XLSX.")

        messages = repository.list_messages()
        output = export_csv(messages) if file_format == "csv" else export_xlsx(messages)
        mimetype = (
            "text/csv"
            if file_format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        response = send_file(
            output,
            mimetype=mimetype,
            as_attachment=True,
            download_name=f"actsp-mensagens-{timestamp}.{file_format}",
        )
        response.headers["Cache-Control"] = "no-store, private"
        return response

    @app.post("/admin/messages/<int:message_id>/edit")
    @admin_required
    def admin_edit_message(message_id: int):
        try:
            payload = validate_admin_message_payload(request.form)
            updated = repository.update(message_id, payload)
            if not updated:
                flash("Mensagem não encontrada.", "error")
            else:
                flash("Mensagem atualizada com sucesso.", "success")
        except ValidationError as error:
            flash(str(error), "error")
        return redirect(url_for("admin"))

    @app.post("/admin/messages/<int:message_id>/delete")
    @admin_required
    def admin_delete_message(message_id: int):
        if repository.delete(message_id):
            flash("Mensagem excluída com sucesso.", "success")
        else:
            flash("Mensagem não encontrada.", "error")
        return redirect(url_for("admin"))

    @app.post("/admin/messages/reset")
    @admin_required
    def admin_reset_messages():
        deleted = repository.delete_all()
        flash(f"{deleted} mensagem(ns) apagada(s) com sucesso.", "success")
        return redirect(url_for("admin"))

    @app.get("/api/admin/messages")
    @admin_required
    def api_admin_messages():
        status = request.args.get("status") or None
        name = request.args.get("name") or None
        if status and not is_valid_status(status):
            return jsonify({"ok": False, "errors": ["Status inválido."]}), 400

        return jsonify({"ok": True, "items": repository.list_messages(status=status, name=name)})

    @app.patch("/api/admin/messages/<int:message_id>/status")
    @admin_required
    def api_admin_update_message_status(message_id: int):
        payload = request.get_json(silent=True) or {}
        status = str(payload.get("status", "")).strip()
        if not is_valid_status(status):
            return jsonify({"ok": False, "errors": ["Status inválido."]}), 400

        updated = repository.update_status(message_id, status)
        if not updated:
            return jsonify({"ok": False, "errors": ["Mensagem não encontrada."]}), 404

        return jsonify({"ok": True, "item": updated})

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.post("/api/contact")
    def create_contact_message():
        if not request.is_json:
            return jsonify({"error": "Envie os dados em JSON."}), 415

        try:
            payload = validate_contact_payload(request.get_json(silent=True) or {})
            message_id = repository.create(
                payload,
                ip_address=request.remote_addr or "",
                user_agent=request.headers.get("User-Agent", "")[:255],
            )
        except ValidationError as error:
            return jsonify({"error": str(error)}), 400

        return jsonify({"id": message_id, "message": "Mensagem recebida."}), 201

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_RUN_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_RUN_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
