from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import psycopg
except ImportError:  # pragma: no cover - optional until PostgreSQL is configured.
    psycopg = None


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Aberto',
    priority TEXT NOT NULL DEFAULT 'Normal',
    ip_address TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS contact_messages (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    phone VARCHAR(30) NOT NULL,
    email VARCHAR(254) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'Aberto',
    priority VARCHAR(20) NOT NULL DEFAULT 'Normal',
    ip_address INET,
    user_agent VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite:///")


@contextmanager
def connect(database_url: str) -> Iterator:
    if is_sqlite(database_url):
        db_path = Path(database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return

    if psycopg is None:
        raise RuntimeError("Instale psycopg[binary] para usar PostgreSQL.")

    connection = psycopg.connect(database_url, connect_timeout=10)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_contact_table(database_url: str) -> None:
    schema = SQLITE_SCHEMA if is_sqlite(database_url) else POSTGRES_SCHEMA

    with connect(database_url) as connection:
        if is_sqlite(database_url):
            connection.executescript(schema)
            _ensure_sqlite_contact_columns(connection)
            return

        with connection.cursor() as cursor:
            cursor.execute(schema)
            cursor.execute("ALTER TABLE contact_messages ADD COLUMN IF NOT EXISTS status VARCHAR(40) NOT NULL DEFAULT 'Aberto'")
            cursor.execute("ALTER TABLE contact_messages ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'Normal'")
            cursor.execute("ALTER TABLE contact_messages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")


def _ensure_sqlite_contact_columns(connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(contact_messages)").fetchall()}
    migrations = {
        "status": "ALTER TABLE contact_messages ADD COLUMN status TEXT NOT NULL DEFAULT 'Aberto'",
        "priority": "ALTER TABLE contact_messages ADD COLUMN priority TEXT NOT NULL DEFAULT 'Normal'",
        "updated_at": "ALTER TABLE contact_messages ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
    }

    for column, statement in migrations.items():
        if column not in columns:
            connection.execute(statement)


class ContactRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create(self, payload: dict, ip_address: str, user_agent: str) -> int:
        if is_sqlite(self.database_url):
            return self._create_sqlite(payload, ip_address, user_agent)

        return self._create_postgres(payload, ip_address, user_agent)

    def _create_sqlite(self, payload: dict, ip_address: str, user_agent: str) -> int:
        with connect(self.database_url) as connection:
            cursor = connection.execute(
                """
                INSERT INTO contact_messages (name, phone, email, message, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["name"],
                    payload["phone"],
                    payload["email"],
                    payload["message"],
                    ip_address or None,
                    user_agent or None,
                ),
            )
            return int(cursor.lastrowid)

    def _create_postgres(self, payload: dict, ip_address: str, user_agent: str) -> int:
        with connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO contact_messages (name, phone, email, message, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, NULLIF(%s, '')::inet, %s)
                    RETURNING id
                    """,
                    (
                        payload["name"],
                        payload["phone"],
                        payload["email"],
                        payload["message"],
                        ip_address,
                        user_agent or None,
                    ),
                )
                row = cursor.fetchone()
                return int(row[0])

    def list_messages(self, status: str | None = None, name: str | None = None) -> list[dict]:
        if is_sqlite(self.database_url):
            return self._list_sqlite(status=status, name=name)
        return self._list_postgres(status=status, name=name)

    def update(self, message_id: int, payload: dict) -> dict | None:
        if is_sqlite(self.database_url):
            return self._update_sqlite(message_id, payload)
        return self._update_postgres(message_id, payload)

    def update_status(self, message_id: int, status: str) -> dict | None:
        current = self.get(message_id)
        if not current:
            return None
        current["status"] = status
        return self.update(message_id, current)

    def delete(self, message_id: int) -> bool:
        with connect(self.database_url) as connection:
            placeholder = "?" if is_sqlite(self.database_url) else "%s"
            cursor = connection.execute(f"DELETE FROM contact_messages WHERE id = {placeholder}", (message_id,))
            return cursor.rowcount > 0

    def delete_all(self) -> int:
        with connect(self.database_url) as connection:
            cursor = connection.execute("DELETE FROM contact_messages")
            return cursor.rowcount

    def get(self, message_id: int) -> dict | None:
        items = self.list_messages()
        return next((item for item in items if item["id"] == message_id), None)

    def _list_sqlite(self, status: str | None, name: str | None) -> list[dict]:
        query = """
            SELECT id, name, phone, email, message, status, priority, created_at, updated_at
            FROM contact_messages
        """
        params = []
        clauses = []

        if status:
            clauses.append("status = ?")
            params.append(status)
        if name:
            clauses.append("LOWER(name) LIKE ?")
            params.append(f"%{name.lower()}%")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, id DESC"

        with connect(self.database_url) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _list_postgres(self, status: str | None, name: str | None) -> list[dict]:
        query = """
            SELECT id, name, phone, email, message, status, priority, created_at, updated_at
            FROM contact_messages
        """
        params = []
        clauses = []

        if status:
            clauses.append("status = %s")
            params.append(status)
        if name:
            clauses.append("LOWER(name) LIKE %s")
            params.append(f"%{name.lower()}%")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, id DESC"

        with connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _update_sqlite(self, message_id: int, payload: dict) -> dict | None:
        with connect(self.database_url) as connection:
            cursor = connection.execute(
                """
                UPDATE contact_messages
                SET name = ?, phone = ?, email = ?, message = ?, status = ?, priority = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    payload["name"],
                    payload["phone"],
                    payload["email"],
                    payload["message"],
                    payload["status"],
                    payload["priority"],
                    message_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(message_id)

    def _update_postgres(self, message_id: int, payload: dict) -> dict | None:
        with connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE contact_messages
                    SET name = %s, phone = %s, email = %s, message = %s, status = %s, priority = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        payload["name"],
                        payload["phone"],
                        payload["email"],
                        payload["message"],
                        payload["status"],
                        payload["priority"],
                        message_id,
                    ),
                )
                if cursor.rowcount == 0:
                    return None
        return self.get(message_id)

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "id": int(row[0]),
            "name": row[1],
            "phone": row[2],
            "email": row[3],
            "message": row[4],
            "status": row[5],
            "priority": row[6],
            "created_at": str(row[7]) if row[7] is not None else None,
            "updated_at": str(row[8]) if row[8] is not None else None,
        }
