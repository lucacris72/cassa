from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Order


def business_date_for(now: datetime | None = None, reset_hour: int | None = None) -> str:
    now = now or datetime.now()
    reset_hour = get_settings().business_day_reset_hour if reset_hour is None else reset_hour
    if now.hour < reset_hour:
        now = now - timedelta(days=1)
    return now.date().isoformat()


def begin_immediate_if_sqlite(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def next_order_number(db: Session, business_date: str) -> int:
    current_max = db.scalar(
        select(func.max(Order.order_number)).where(
            Order.business_date == business_date,
            Order.order_number.is_not(None),
        )
    )
    return int(current_max or 0) + 1
