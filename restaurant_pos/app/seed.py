from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_pin
from .models import Category, Printer, Product, User


def seed_initial_data(db: Session) -> None:
    if not db.scalars(select(Printer)).first():
        customer = Printer(name="Customer Printer", type="fake", enabled=True, is_customer_printer=True)
        kitchen = Printer(name="Kitchen Printer", type="fake", enabled=True)
        bar = Printer(name="Bar Printer", type="fake", enabled=True)
        db.add_all([customer, kitchen, bar])
        db.flush()

        cucina = Category(name="Cucina", printer_id=kitchen.id, sort_order=10)
        bar_category = Category(name="Bar", printer_id=bar.id, sort_order=20)
        bevande = Category(name="Bevande", printer_id=bar.id, sort_order=30)
        db.add_all([cucina, bar_category, bevande])
        db.flush()

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
