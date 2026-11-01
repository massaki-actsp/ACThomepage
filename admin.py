from __future__ import annotations

from dataclasses import dataclass

from validation import ValidationError, validate_contact_payload


@dataclass(frozen=True)
class KanbanColumn:
    key: str
    label: str


KANBAN_COLUMNS = (
    KanbanColumn(key="Aberto", label="Aberto"),
    KanbanColumn(key="Contato_Pendente", label="Contato Pendente"),
    KanbanColumn(key="Concluído", label="Concluído"),
    KanbanColumn(key="Cancelado", label="Cancelado"),
)

KANBAN_PRIORITIES = ("Baixa", "Normal", "Alta", "Urgente")


def is_valid_status(status: str) -> bool:
    return status in {column.key for column in KANBAN_COLUMNS}


def is_valid_priority(priority: str) -> bool:
    return priority in KANBAN_PRIORITIES


def validate_admin_message_payload(payload: dict) -> dict:
    clean_payload = validate_contact_payload(payload)
    status = str(payload.get("status", "")).strip()
    priority = str(payload.get("priority", "")).strip()

    if not is_valid_status(status):
        raise ValidationError("Status inválido.")
    if not is_valid_priority(priority):
        raise ValidationError("Prioridade inválida.")

    clean_payload["status"] = status
    clean_payload["priority"] = priority
    return clean_payload
