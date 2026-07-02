from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Order, RegisterClosure, User
from .numbering import current_register_session


class ClosureError(ValueError):
    pass


@dataclass(frozen=True)
class SalesSummary:
    business_date: str
    register_session: int
    order_count: int
    sales_total_cents: int
    cash_total_cents: int
    cancelled_count: int
    pending_count: int
    open_count: int
    closure: RegisterClosure | None


SALE_STATUSES = {"confirmed", "paid", "delivered"}


def get_sales_summary(db: Session, business_date: str, register_session: int | None = None) -> SalesSummary:
    register_session = register_session or current_register_session(db, business_date)
    orders = db.scalars(
        select(Order).where(Order.business_date == business_date, Order.register_session == register_session)
    ).all()
    sales_orders = [order for order in orders if order.status in SALE_STATUSES]
    cash_orders = [order for order in sales_orders if order.paid_at is not None or order.status in {"paid", "delivered"}]
    closure = db.scalar(
        select(RegisterClosure).where(
            RegisterClosure.business_date == business_date,
            RegisterClosure.register_session == register_session,
        )
    )
    return SalesSummary(
        business_date=business_date,
        register_session=register_session,
        order_count=len(sales_orders),
        sales_total_cents=sum(order.total_cents for order in sales_orders),
        cash_total_cents=sum(order.total_cents for order in cash_orders),
        cancelled_count=sum(1 for order in orders if order.status == "cancelled"),
        pending_count=sum(1 for order in orders if order.status == "pending_confirmation"),
        open_count=sum(1 for order in orders if order.status in {"confirmed", "paid"}),
        closure=closure,
    )


def close_register(
    db: Session,
    business_date: str,
    user: User,
    notes: str | None = None,
    register_session: int | None = None,
) -> RegisterClosure:
    register_session = register_session or current_register_session(db, business_date)
    if (
        db.scalar(
            select(RegisterClosure).where(
                RegisterClosure.business_date == business_date,
                RegisterClosure.register_session == register_session,
            )
        )
        is not None
    ):
        raise ClosureError("Turno gia chiuso")

    orders = db.scalars(
        select(Order).where(Order.business_date == business_date, Order.register_session == register_session)
    ).all()
    pending_count = sum(1 for order in orders if order.status == "pending_confirmation")
    if pending_count:
        raise ClosureError("Ci sono ordini mobile da confermare o annullare")

    now = datetime.now(UTC)
    sales_orders = [order for order in orders if order.status in SALE_STATUSES]
    for order in sales_orders:
        order.status = "delivered"
        order.paid_at = order.paid_at or now
        order.completed_at = order.completed_at or now

    closure = RegisterClosure(
        business_date=business_date,
        register_session=register_session,
        closed_at=now,
        closed_by_user_id=user.id,
        order_count=len(sales_orders),
        sales_total_cents=sum(order.total_cents for order in sales_orders),
        cash_total_cents=sum(order.total_cents for order in sales_orders),
        cancelled_count=sum(1 for order in orders if order.status == "cancelled"),
        notes=notes,
    )
    db.add(closure)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ClosureError("Turno gia chiuso") from exc
    db.refresh(closure)
    return closure
