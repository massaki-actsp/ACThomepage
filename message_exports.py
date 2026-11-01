"""Build downloadable message reports without storing files on disk."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


EXPORT_COLUMNS = (
    ("id", "ID"),
    ("name", "Nome"),
    ("phone", "Telefone"),
    ("email", "E-mail"),
    ("message", "Mensagem"),
    ("status", "Status"),
    ("priority", "Prioridade"),
    ("created_at", "Recebida em"),
    ("updated_at", "Atualizada em"),
)


def _csv_value(value):
    # Quoting alone does not prevent spreadsheet formula execution.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_csv(messages: Iterable[dict], *, columns=EXPORT_COLUMNS) -> BytesIO:
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow([label for _, label in columns])
    for message in messages:
        writer.writerow([_csv_value(message.get(key, "")) for key, _ in columns])
    # BOM lets Excel recognize Portuguese accents when opening the CSV directly.
    return BytesIO(output.getvalue().encode("utf-8-sig"))


def export_xlsx(
    messages: Iterable[dict], *, columns=EXPORT_COLUMNS, sheet_title="Mensagens",
    widths=(10, 28, 24, 36, 70, 22, 16, 28, 28),
) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title
    sheet.append([label for _, label in columns])
    for message in messages:
        values = [message.get(key, "") for key, _ in columns]
        sheet.append([
            ILLEGAL_CHARACTERS_RE.sub("\ufffd", value) if isinstance(value, str) else value
            for value in values
        ])
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="172033")
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    output = BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return output
