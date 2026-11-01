from __future__ import annotations

import re


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+() .-]{8,30}$")


class ValidationError(ValueError):
    pass


def clean_text(value: object, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValidationError("Formato de dados inválido.")

    cleaned = " ".join(value.strip().split())

    if len(cleaned) > max_length:
        raise ValidationError("Um ou mais campos excedem o tamanho permitido.")

    return cleaned


def validate_contact_payload(payload: dict) -> dict:
    name = clean_text(payload.get("name"), 120)
    phone = clean_text(payload.get("phone"), 30)
    email = clean_text(payload.get("email"), 254).lower()
    message = clean_text(payload.get("message"), 2000)

    if len(name) < 2:
        raise ValidationError("Informe um nome válido.")

    if not PHONE_RE.match(phone):
        raise ValidationError("Informe um telefone válido.")

    if not EMAIL_RE.match(email):
        raise ValidationError("Informe um e-mail válido.")

    if len(message) < 10:
        raise ValidationError("A mensagem deve ter pelo menos 10 caracteres.")

    return {
        "name": name,
        "phone": phone,
        "email": email,
        "message": message,
    }
