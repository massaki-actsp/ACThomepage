"""Persistent admin credentials and CSRF protection for security actions."""

from __future__ import annotations

import hmac
import secrets
from uuid import uuid4

from flask import abort, request, session

from database import connect, is_sqlite
from validation import ValidationError


def ensure_admin_credentials_table(database_url: str) -> None:
    with connect(database_url) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS admin_credentials (
                username VARCHAR(120) PRIMARY KEY,
                password_hash TEXT NOT NULL,
                credential_version VARCHAR(36) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


class AdminCredentialRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.p = "?" if is_sqlite(database_url) else "%s"

    def get(self, username: str) -> dict | None:
        with connect(self.database_url) as connection:
            row = connection.execute(
                f"SELECT password_hash, credential_version FROM admin_credentials WHERE username = {self.p}",
                (username,),
            ).fetchone()
        return {"password_hash": row[0], "version": row[1]} if row else None

    def change_password(self, username: str, password_hash: str, expected_version: str) -> bool:
        # A concurrent password change must not be overwritten with stale credentials.
        with connect(self.database_url) as connection:
            cursor = connection.execute(
                "INSERT INTO admin_credentials (username, password_hash, credential_version) "
                f"VALUES ({self.p}, {self.p}, {self.p}) ON CONFLICT (username) DO UPDATE SET "
                "password_hash = excluded.password_hash, credential_version = excluded.credential_version, "
                "updated_at = CURRENT_TIMESTAMP "
                f"WHERE admin_credentials.credential_version = {self.p}",
                (username, password_hash, str(uuid4()), expected_version),
            )
            return cursor.rowcount == 1


def admin_csrf_token() -> str:
    if "admin_csrf" not in session:
        session["admin_csrf"] = secrets.token_urlsafe(32)
    return session["admin_csrf"]


def require_admin_csrf() -> None:
    expected = session.get("admin_csrf", "")
    actual = request.form.get("csrf_token", "")
    if not expected or not hmac.compare_digest(expected.encode(), actual.encode()):
        abort(400, description="Formulário expirado. Recarregue a página e tente novamente.")


def validate_new_password(password: str, confirmation: str) -> None:
    if not 12 <= len(password) <= 128:
        raise ValidationError("A nova senha deve ter entre 12 e 128 caracteres.")
    if password.isspace():
        raise ValidationError("A nova senha não pode conter apenas espaços.")
    if not hmac.compare_digest(password.encode(), confirmation.encode()):
        raise ValidationError("A confirmação da nova senha não confere.")
