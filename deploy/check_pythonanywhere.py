"""Run from the project directory: python -m deploy.check_pythonanywhere."""

from __future__ import annotations

import sys
from urllib.parse import parse_qs, urlsplit


def main() -> int:
    try:
        from app import app
        from database import connect, is_sqlite

        database_url = app.config["DATABASE_URL"]
        if is_sqlite(database_url):
            print("ERRO: configure DATABASE_URL com PostgreSQL; o ambiente ainda usa SQLite.")
            return 1
        if parse_qs(urlsplit(database_url).query).get("sslmode", [""])[0] not in {"require", "verify-ca", "verify-full"}:
            print("ERRO: use sslmode=require ou verify-full na URL PostgreSQL.")
            return 1
        with connect(database_url) as connection:
            assert connection.execute("SELECT 1").fetchone()[0] == 1
            for table in ("contact_messages", "agenda_events", "mural_click_logs", "admin_credentials"):
                if connection.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is None:
                    print(f"ERRO: tabela {table} ausente. Execute schema.sql no Supabase.")
                    return 1
        print("OK: conexão PostgreSQL e quatro tabelas disponíveis.")
        with app.test_client() as client:
            for path in ("/healthz", "/mural.html", "/api/mural", "/static/css/style.css", "/static/images/logo.png"):
                response = client.get(path)
                print(f"{response.status_code}: {path}")
                if response.status_code != 200:
                    return 1
        print("OK: importação WSGI/Flask e assets locais. Confira o domínio e o mapeamento estático pelo navegador.")
        return 0
    except Exception as error:
        # Do not print a DSN, password or full driver traceback in a shared console.
        print(f"ERRO: {type(error).__name__}. Confira .env, virtualenv, rede, SSL e schema.sql.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
