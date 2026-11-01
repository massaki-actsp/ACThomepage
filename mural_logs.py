"""First-party click analytics for the Mural, restricted reports for administrators."""

from __future__ import annotations

import ipaddress
import math
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from database import connect, is_sqlite
from mural import list_videos
from message_exports import export_csv, export_xlsx
from admin_security import require_admin_csrf


SOURCES = {"carousel": "Carrossel", "catalog": "Catálogo", "player": "Assistir agora"}
COLORS = ("#187d70", "#d64c73", "#277dc0", "#c78316", "#7b57b0", "#b64739",
          "#51872c", "#bb478b", "#357a8b", "#8b703c", "#6556a3", "#ae5930")
LOCAL_ZONE = ZoneInfo("America/Sao_Paulo")
LOG_EXPORT_COLUMNS = (
    ("id", "ID"), ("time", "Data e hora (Brasília)"), ("video_id", "ID do vídeo"),
    ("title", "Vídeo"), ("source", "Origem"), ("ip", "IP"),
)


def utc_stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def parse_log_period(start_value: str, end_value: str):
    start_date = datetime.strptime(start_value, "%Y-%m-%d").date() if start_value else None
    end_date = datetime.strptime(end_value, "%Y-%m-%d").date() if end_value else None
    if start_date and end_date and end_date < start_date:
        raise ValueError("Período inválido.")
    start = utc_stamp(datetime.combine(start_date, time.min, LOCAL_ZONE)) if start_date else None
    end = (utc_stamp(datetime.combine(end_date + timedelta(days=1), time.min, LOCAL_ZONE))
           if end_date else None)
    return start, end


def ensure_mural_logs_table(database_url: str) -> None:
    primary_key = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite(database_url) else "BIGSERIAL PRIMARY KEY"
    with connect(database_url) as connection:
        connection.execute(f"""
            CREATE TABLE IF NOT EXISTS mural_click_logs (
                id {primary_key},
                event_id VARCHAR(36) NOT NULL UNIQUE,
                video_id BIGINT NOT NULL,
                video_title VARCHAR(500) NOT NULL,
                source VARCHAR(20) NOT NULL CHECK (source IN ('carousel', 'catalog', 'player')),
                ip_address VARCHAR(45) NOT NULL,
                clicked_at VARCHAR(32) NOT NULL
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_mural_logs_time ON mural_click_logs (clicked_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_mural_logs_video ON mural_click_logs (video_id, clicked_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_mural_logs_ip ON mural_click_logs (ip_address, clicked_at)")


class MuralLogRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.p = "?" if is_sqlite(database_url) else "%s"

    def reset(self) -> int:
        with connect(self.database_url) as connection:
            return connection.execute("DELETE FROM mural_click_logs").rowcount

    def record(self, event_id: str, video, source: str, ip: str) -> str:
        now = datetime.now(timezone.utc)
        with connect(self.database_url) as connection:
            if connection.execute(
                f"SELECT 1 FROM mural_click_logs WHERE event_id = {self.p}", (event_id,),
            ).fetchone():
                return "duplicate"
            count = connection.execute(
                f"SELECT COUNT(*) FROM mural_click_logs WHERE ip_address = {self.p} AND clicked_at >= {self.p}",
                (ip, utc_stamp(now - timedelta(minutes=1))),
            ).fetchone()[0]
            if count >= 120:
                return "limited"
            values = (event_id, video.id, video.title[:500], source, ip, utc_stamp(now))
            connection.execute(
                "INSERT INTO mural_click_logs (event_id, video_id, video_title, source, ip_address, clicked_at) "
                f"VALUES ({', '.join([self.p] * 6)}) ON CONFLICT (event_id) DO NOTHING", values,
            )
        return "created"

    def _period_filter(self, start, end):
        conditions, params = [], []
        if start:
            conditions.append(f"clicked_at >= {self.p}")
            params.append(start)
        if end:
            conditions.append(f"clicked_at < {self.p}")
            params.append(end)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return where, params

    def iter_history(self, start: str | None, end: str | None):
        where, params = self._period_filter(start, end)
        with connect(self.database_url) as connection:
            cursor = connection.execute(
                "SELECT id, video_title, video_id, source, ip_address, clicked_at "
                f"FROM mural_click_logs{where} ORDER BY clicked_at DESC, id DESC", params,
            )
            while rows := cursor.fetchmany(500):
                for row in rows:
                    yield {"id": row[0], "title": row[1], "video_id": row[2],
                           "source": SOURCES[row[3]], "ip": row[4],
                           "time": datetime.fromisoformat(row[5]).astimezone(LOCAL_ZONE).strftime("%d/%m/%Y %H:%M:%S")}

    def report(self, videos, start: str | None, end: str | None, page: int):
        where, params = self._period_filter(start, end)
        with connect(self.database_url) as connection:
            counts = dict(connection.execute(
                f"SELECT video_id, COUNT(*) FROM mural_click_logs{where} GROUP BY video_id", params,
            ).fetchall())
            total_records = sum(counts.values())
            pages = max(1, (total_records + 49) // 50)
            page = min(page, pages)
            rows = connection.execute(
                "SELECT video_title, video_id, source, ip_address, clicked_at "
                f"FROM mural_click_logs{where} ORDER BY clicked_at DESC, id DESC "
                f"LIMIT {self.p} OFFSET {self.p}", (*params, 50, (page - 1) * 50),
            ).fetchall()
            source_counts = {}
            unique_ips = 0
            ids = list(dict.fromkeys(video.id for video in videos))
            if ids:
                catalog_condition = f"video_id IN ({', '.join([self.p] * len(ids))})"
                catalog_where = where + (" AND " if where else " WHERE ") + catalog_condition
                catalog_params = (*params, *ids)
                source_counts = dict(connection.execute(
                    f"SELECT source, COUNT(*) FROM mural_click_logs{catalog_where} GROUP BY source", catalog_params,
                ).fetchall())
                unique_ips = connection.execute(
                    f"SELECT COUNT(DISTINCT ip_address) FROM mural_click_logs{catalog_where}", catalog_params,
                ).fetchone()[0]
        total = sum(counts.get(video_id, 0) for video_id in ids)
        ranking = [{"id": video.id, "title": video.title, "category": video.category,
                    "count": counts.get(video.id, 0),
                    "percentage": counts.get(video.id, 0) / total * 100 if total else 0}
                   for video in {item.id: item for item in videos}.values()]
        ranking.sort(key=lambda item: (-item["count"], item["title"].casefold()))
        for index, item in enumerate(ranking):
            item["color"] = COLORS[index % len(COLORS)]
        sources = [{"title": label, "count": source_counts.get(key, 0),
                    "percentage": source_counts.get(key, 0) / total * 100 if total else 0,
                    "color": COLORS[index]} for index, (key, label) in enumerate(SOURCES.items())]
        history = [{"title": row[0], "video_id": row[1], "source": SOURCES[row[2]], "ip": row[3],
                    "time": datetime.fromisoformat(row[4]).astimezone(LOCAL_ZONE).strftime("%d/%m/%Y %H:%M:%S")}
                   for row in rows]
        return dict(ranking=ranking, sources=sources, history=history, total=total,
                    total_records=total_records, retired=total_records - total, unique_ips=unique_ips,
                    page=page, pages=pages, clicked_videos=sum(item["count"] > 0 for item in ranking),
                    video_chart=pie_layout(ranking), source_chart=pie_layout(sources))


def pie_layout(items):
    """Place large-slice labels inside; distribute small-slice callouts on each side."""
    slices, position = [], -math.pi / 2
    for item in items:
        if item["count"]:
            end = position + item["percentage"] / 100 * math.tau
            middle = (position + end) / 2
            slices.append({**item, "start": position, "end": end, "middle": middle,
                           "outside": item["percentage"] < 16, "right": math.cos(middle) >= 0})
            position = end
    sides = [[item for item in slices if item["outside"] and item["right"] == right]
             for right in (False, True)]
    height = max(288, 40 * max(map(len, sides), default=0) + 40)
    center_y, radius = height / 2, 112
    for item in slices:
        start_x = 200 + radius * math.cos(item["start"])
        start_y = center_y + radius * math.sin(item["start"])
        end_x = 200 + radius * math.cos(item["end"])
        end_y = center_y + radius * math.sin(item["end"])
        large = int(item["percentage"] > 50)
        item["path"] = (f"M 200 {center_y:.3f} L {start_x:.3f} {start_y:.3f} "
                        f"A {radius} {radius} 0 {large} 1 {end_x:.3f} {end_y:.3f} Z")
        item["label_x"] = 200 + radius * 0.61 * math.cos(item["middle"])
        item["label_y"] = center_y + radius * 0.61 * math.sin(item["middle"])
        item["full_circle"] = len(slices) == 1
        if item["full_circle"]:
            item["label_x"], item["label_y"] = 200, center_y
        item["anchor"] = "middle"
    for side in sides:
        side.sort(key=lambda item: math.sin(item["middle"]))
        previous_y = 0
        for item in side:
            desired_y = center_y + radius * math.sin(item["middle"])
            item["label_y"] = max(desired_y, previous_y + 40)
            previous_y = item["label_y"]
        ceiling = height - 24
        for item in reversed(side):
            item["label_y"] = min(item["label_y"], ceiling)
            ceiling = item["label_y"] - 40
            item["label_x"] = 396 if item["right"] else 4
            item["anchor"] = "end" if item["right"] else "start"
            edge_x = 200 + radius * math.cos(item["middle"])
            edge_y = center_y + radius * math.sin(item["middle"])
            joint_x = 320 if item["right"] else 80
            item["leader"] = f"{edge_x:.3f},{edge_y:.3f} {joint_x},{item['label_y']:.3f}"
    return {"slices": slices, "height": height, "center_y": center_y, "radius": radius}


def create_mural_logs_blueprint(app, admin_required, verify_admin_credentials):
    bp = Blueprint("mural_logs", __name__)
    repository = MuralLogRepository(app.config["DATABASE_URL"])

    def catalog():
        return list_videos(app.config["MURAL_LIBRARY_PATH"], app.config["MURAL_DATA_PATH"])

    @bp.post("/api/mural/clicks")
    def record_click():
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403)
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            abort(403)
        if not request.is_json:
            return jsonify(error="Envie os dados em JSON."), 415
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Dados inválidos."), 400
        video_id, source = payload.get("video_id"), payload.get("source")
        if type(video_id) is not int or not isinstance(source, str) or source not in SOURCES:
            return jsonify(error="Vídeo ou origem inválidos."), 400
        try:
            event_id = str(UUID(str(payload.get("event_id", "")), version=None))
        except ValueError:
            return jsonify(error="Identificador do clique inválido."), 400
        video = next((item for item in catalog() if item.id == video_id), None)
        if not video:
            return jsonify(error="Vídeo não encontrado no catálogo."), 404
        try:
            ip = str(ipaddress.ip_address(request.remote_addr or ""))
        except ValueError:
            ip = ""
        result = repository.record(event_id, video, source, ip)
        if result == "limited":
            return jsonify(error="Limite de cliques por minuto atingido."), 429
        return jsonify(ok=True), 200 if result == "duplicate" else 201

    @bp.get("/admin/logs")
    @admin_required
    def index():
        start_value = request.args.get("start", "")
        end_value = request.args.get("end", "")
        error, start, end = None, None, None
        try:
            start, end = parse_log_period(start_value, end_value)
        except (ValueError, OverflowError):
            error = "Informe um período válido, com término igual ou posterior ao início."
            start = end = None
        page = max(1, request.args.get("page", 1, type=int) or 1)
        report = repository.report(catalog(), start, end, page)
        return render_template("admin_logs.html", **report, error=error,
                               start_value=start_value, end_value=end_value), 400 if error else 200

    @bp.get("/admin/logs/export")
    @admin_required
    def export_history():
        file_format = request.args.get("format", "xlsx").lower()
        if file_format not in {"csv", "xlsx"}:
            abort(400, description="Formato inválido. Use CSV ou XLSX.")
        try:
            start, end = parse_log_period(request.args.get("start", ""), request.args.get("end", ""))
        except (ValueError, OverflowError):
            abort(400, description="Informe um período válido antes de exportar.")
        rows = repository.iter_history(start, end)
        if file_format == "csv":
            output = export_csv(rows, columns=LOG_EXPORT_COLUMNS)
            mimetype = "text/csv"
        else:
            output = export_xlsx(rows, columns=LOG_EXPORT_COLUMNS,
                                 sheet_title="Histórico de cliques", widths=(12, 28, 16, 55, 24, 42))
            mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return send_file(output, mimetype=mimetype, as_attachment=True,
                         download_name=f"actsp-historico-cliques-{timestamp}.{file_format}")

    @bp.post("/admin/logs/reset")
    @admin_required
    def reset_history():
        require_admin_csrf()
        if request.form.get("confirmation", "").strip() != "APAGAR LOGS":
            flash("Digite APAGAR LOGS para confirmar a exclusão de todo o histórico.", "error")
            return redirect(url_for("mural_logs.index"))
        if not verify_admin_credentials(session.get("admin_username", ""), request.form.get("current_password", "")):
            flash("Senha atual incorreta. Nenhum log foi apagado.", "error")
            return redirect(url_for("mural_logs.index"))
        deleted = repository.reset()
        flash(f"Histórico resetado: {deleted} registro(s) de cliques apagado(s).", "success")
        return redirect(url_for("mural_logs.index"))

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store, private"
        return response

    return bp
