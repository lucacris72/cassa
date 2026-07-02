from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Order, OrderItem, Product
from .numbering import begin_immediate_if_sqlite, business_date_for, current_register_session, next_order_number


class OrderError(ValueError):
    pass


class OrderNumberConflict(OrderError):
    pass


@dataclass(frozen=True)
class CartLine:
    product_id: int
    quantity: int
    notes: str | None = None


def parse_cart_json(cart_json: str) -> list[CartLine]:
    try:
        raw_lines = json.loads(cart_json)
    except json.JSONDecodeError as exc:
        raise OrderError("Carrello non valido") from exc
    if not isinstance(raw_lines, list) or not raw_lines:
        raise OrderError("Il carrello e vuoto")
    lines: list[CartLine] = []
    for raw in raw_lines:
        try:
            product_id = int(raw["product_id"])
            quantity = int(raw["quantity"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OrderError("Riga carrello non valida") from exc
        if quantity <= 0:
            raise OrderError("Quantita non valida")
        notes = str(raw.get("notes") or "").strip() or None
        lines.append(CartLine(product_id=product_id, quantity=quantity, notes=notes))
    return lines


def _build_order_items(db: Session, lines: list[CartLine]) -> tuple[list[OrderItem], int]:
    items: list[OrderItem] = []
    total_cents = 0
    for line in lines:
        product = db.get(Product, line.product_id)
        if product is None or not product.active:
            raise OrderError("Prodotto non disponibile")
        if product.category is None:
            raise OrderError(f"Prodotto senza categoria: {product.name}")
        line_total = product.price_cents * line.quantity
        total_cents += line_total
        items.append(
            OrderItem(
                product_id=product.id,
                product_name=product.name,
                category_name=product.category.name,
                printer_id=product.category.printer_id,
                quantity=line.quantity,
                unit_price_cents=product.price_cents,
                line_total_cents=line_total,
                notes=line.notes,
            )
        )
    return items, total_cents


def create_confirmed_order(
    db: Session,
    lines: list[CartLine],
    *,
    source: str,
    notes: str | None = None,
    mark_paid: bool = False,
) -> Order:
    try:
        begin_immediate_if_sqlite(db)
        business_date = business_date_for()
        register_session = current_register_session(db, business_date)
        order = Order(
            order_number=next_order_number(db, business_date, register_session),
            business_date=business_date,
            register_session=register_session,
            status="paid" if mark_paid else "confirmed",
            total_cents=0,
            source=source,
            notes=notes,
            paid_at=datetime.now(UTC) if mark_paid else None,
        )
        items, total_cents = _build_order_items(db, lines)
        order.total_cents = total_cents
        order.items = items
        db.add(order)
        db.commit()
        db.refresh(order)
        return order
    except IntegrityError as exc:
        db.rollback()
        raise OrderNumberConflict("Numero ordine duplicato, riprovare") from exc
    except Exception:
        db.rollback()
        raise


def create_pending_order(db: Session, lines: list[CartLine], *, source: str, notes: str | None = None) -> Order:
    try:
        business_date = business_date_for()
        items, total_cents = _build_order_items(db, lines)
        order = Order(
            order_number=None,
            business_date=business_date,
            register_session=current_register_session(db, business_date),
            status="pending_confirmation",
            total_cents=total_cents,
            source=source,
            notes=notes,
            items=items,
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order
    except Exception:
        db.rollback()
        raise


def confirm_pending_order(db: Session, order_id: int) -> Order:
    try:
        begin_immediate_if_sqlite(db)
        order = db.get(Order, order_id)
        if order is None:
            raise OrderError("Ordine non trovato")
        if order.status != "pending_confirmation":
            raise OrderError("L'ordine non e in attesa di conferma")
        business_date = business_date_for()
        register_session = current_register_session(db, business_date)
        order.business_date = business_date
        order.register_session = register_session
        order.order_number = next_order_number(db, business_date, register_session)
        order.status = "confirmed"
        db.commit()
        db.refresh(order)
        return order
    except IntegrityError as exc:
        db.rollback()
        raise OrderNumberConflict("Numero ordine duplicato, riprovare") from exc
    except Exception:
        db.rollback()
        raise


def mark_paid(db: Session, order: Order) -> None:
    order.status = "paid"
    order.paid_at = order.paid_at or datetime.now(UTC)
    db.commit()


def mark_delivered(db: Session, order: Order) -> None:
    order.status = "delivered"
    order.completed_at = order.completed_at or datetime.now(UTC)
    db.commit()


def cancel_order(db: Session, order: Order) -> None:
    order.status = "cancelled"
    db.commit()
