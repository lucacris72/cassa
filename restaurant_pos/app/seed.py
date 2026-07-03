from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_pin
from .models import Category, Printer, Product, User


def _get_or_create_printer(db: Session, name: str, *, is_customer_printer: bool = False) -> Printer:
    printer = db.scalar(select(Printer).where(Printer.name == name))
    if printer is None:
        printer = Printer(name=name, type="fake", enabled=True, is_customer_printer=is_customer_printer)
        db.add(printer)
        db.flush()
    return printer


def _get_or_create_category(db: Session, name: str, printer_id: int | None, sort_order: int) -> Category:
    category = db.scalar(select(Category).where(Category.name == name))
    if category is None:
        category = Category(name=name, printer_id=printer_id, sort_order=sort_order)
        db.add(category)
        db.flush()
    return category


def seed_initial_data(db: Session) -> None:
    if db.scalar(select(Printer).where(Printer.is_customer_printer.is_(True))) is None:
        _get_or_create_printer(db, "Customer Printer", is_customer_printer=True)

    kitchen = _get_or_create_printer(db, "Kitchen Printer")
    bar = _get_or_create_printer(db, "Bar Printer")

    if not db.scalars(select(Category)).first():
        _get_or_create_category(db, "Cucina", kitchen.id, 10)
        _get_or_create_category(db, "Bar", bar.id, 20)
        _get_or_create_category(db, "Bevande", bar.id, 30)

    if not db.scalars(select(Product)).first():
        cucina = _get_or_create_category(db, "Cucina", kitchen.id, 10)
        bar_category = _get_or_create_category(db, "Bar", bar.id, 20)
        bevande = _get_or_create_category(db, "Bevande", bar.id, 30)
        db.add_all(
            [
                Product(name="Panino salamella", price_cents=600, category_id=cucina.id, sort_order=10),
                Product(name="Patatine", price_cents=350, category_id=cucina.id, sort_order=20),
                Product(name="Birra media", price_cents=500, category_id=bar_category.id, sort_order=10),
                Product(name="Caffe", price_cents=120, category_id=bar_category.id, sort_order=20),
                Product(name="Acqua", price_cents=100, category_id=bevande.id, sort_order=10),
            ]
        )

    if not db.scalars(select(User)).first():
        db.add_all(
            [
                User(name="admin", pin_hash=hash_pin("1234"), role="admin", active=True),
                User(name="cashier", pin_hash=hash_pin("1111"), role="cashier", active=True),
            ]
        )

    db.commit()
