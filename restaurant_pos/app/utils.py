from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def format_money(cents: int) -> str:
    return f"{cents / 100:.2f} EUR"


def parse_price_to_cents(value: str) -> int:
    normalized = value.strip().replace(",", ".")
    try:
        decimal_value = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("Prezzo non valido") from exc
    if decimal_value < 0:
        raise ValueError("Il prezzo non puo essere negativo")
    return int((decimal_value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
