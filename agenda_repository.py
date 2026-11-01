"""Agenda persistence using the project's SQLite/PostgreSQL connections."""

from __future__ import annotations

import json

from database import connect, is_sqlite


def ensure_agenda_table(database_url: str) -> None:
    primary_key = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite(database_url) else "BIGSERIAL PRIMARY KEY"
    with connect(database_url) as connection:
        connection.execute(f"""
            CREATE TABLE IF NOT EXISTS agenda_events (
                id {primary_key},
                title VARCHAR(160) NOT NULL,
                event_type VARCHAR(40) NOT NULL,
                start_at VARCHAR(16) NOT NULL,
                end_at VARCHAR(16) NOT NULL,
                location VARCHAR(180) NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                contacts_json TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (end_at > start_at)
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_agenda_start_at ON agenda_events (start_at)")


class AgendaRepository:
    fields = ("title", "event_type", "start_at", "end_at", "location", "description", "contacts_json")

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.placeholder = "?" if is_sqlite(database_url) else "%s"

    def _select(self, where="", params=()):
        columns = ", ".join(("id", *self.fields))
        with connect(self.database_url) as connection:
            rows = connection.execute(
                f"SELECT {columns} FROM agenda_events {where} ORDER BY start_at, id", params
            ).fetchall()
        events = [dict(zip(("id", *self.fields), row)) for row in rows]
        for event in events:
            event["contacts"] = json.loads(event.pop("contacts_json"))
        return events

    def list_month(self, start: str, end: str):
        return self._select(
            f"WHERE start_at < {self.placeholder} AND end_at > {self.placeholder}",
            (end, start),
        )

    def get(self, event_id: int):
        events = self._select(f"WHERE id = {self.placeholder}", (event_id,))
        return events[0] if events else None

    def save(self, payload: dict, contacts: list[dict], event_id: int | None = None) -> int:
        values = [payload[key] for key in self.fields[:-1]]
        values.append(json.dumps(contacts, ensure_ascii=False))
        with connect(self.database_url) as connection:
            if event_id is not None:
                assignments = ", ".join(f"{key} = {self.placeholder}" for key in self.fields)
                connection.execute(
                    f"UPDATE agenda_events SET {assignments}, updated_at = CURRENT_TIMESTAMP "
                    f"WHERE id = {self.placeholder}", (*values, event_id),
                )
                return event_id
            placeholders = ", ".join([self.placeholder] * len(values))
            query = f"INSERT INTO agenda_events ({', '.join(self.fields)}) VALUES ({placeholders})"
            if not is_sqlite(self.database_url):
                query += " RETURNING id"
            cursor = connection.execute(query, values)
            return int(cursor.lastrowid if is_sqlite(self.database_url) else cursor.fetchone()[0])

    def delete(self, event_id: int) -> bool:
        with connect(self.database_url) as connection:
            cursor = connection.execute(
                f"DELETE FROM agenda_events WHERE id = {self.placeholder}", (event_id,),
            )
            return cursor.rowcount > 0
