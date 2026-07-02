from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from restaurant_pos.app.models import Category, Order, Printer, PrintJob, Product, RegisterClosure, User
from restaurant_pos.app.services import printing
from restaurant_pos.app.services.numbering import business_date_for
from restaurant_pos.app.services.orders import create_confirmed_order, parse_cart_json


def test_seed_data(db_session):
    assert db_session.scalar(select(User).where(User.name == "admin")) is not None
    assert db_session.scalar(select(User).where(User.name == "cashier")) is not None
    assert db_session.scalar(select(Printer).where(Printer.is_customer_printer.is_(True))) is not None
    assert db_session.scalar(select(Category).where(Category.name == "Cucina")) is not None
    assert db_session.scalar(select(Product).where(Product.name == "Panino salamella")) is not None


def test_login_valid_and_invalid(client):
    page = client.get("/login")
    assert page.status_code == 200
    assert "Cassa" in page.text

    invalid = client.post("/login", data={"pin": "9999"}, follow_redirects=False)
    assert invalid.status_code == 303
    assert invalid.headers["location"] == "/login"

    valid = client.post("/login", data={"pin": "1234"}, follow_redirects=False)
    assert valid.status_code == 303
    assert valid.headers["location"] == "/"


def test_main_pages_render(admin_client):
    for path in ["/", "/orders", "/closures", "/products", "/categories", "/printers", "/mobile"]:
        response = admin_client.get(path)
        assert response.status_code == 200, path


def test_admin_crud_pages(admin_client, db_session):
    printer_response = admin_client.post(
        "/printers",
        data={"name": "Expo", "type": "fake", "port": "9100", "enabled": "true"},
        follow_redirects=False,
    )
    assert printer_response.status_code == 303
    printer = db_session.scalar(select(Printer).where(Printer.name == "Expo"))
    assert printer is not None

    category_response = admin_client.post(
        "/categories",
        data={"name": "Dolci", "printer_id": str(printer.id), "sort_order": "40"},
        follow_redirects=False,
    )
    assert category_response.status_code == 303
    category = db_session.scalar(select(Category).where(Category.name == "Dolci"))
    assert category is not None

    product_response = admin_client.post(
        "/products",
        data={"name": "Torta", "price": "4.50", "category_id": str(category.id), "sort_order": "10"},
        follow_redirects=False,
    )
    assert product_response.status_code == 303
    product = db_session.scalar(select(Product).where(Product.name == "Torta"))
    assert product is not None
    assert product.price_cents == 450

    products_page = admin_client.get(f"/products?category_id={category.id}&show=all")
    assert products_page.status_code == 200
    assert "Torta" in products_page.text
    assert "Solo attivi" in products_page.text

    cucina = db_session.scalar(select(Category).where(Category.name == "Cucina"))
    edit_response = admin_client.post(
        f"/products/{product.id}/edit",
        data={
            "name": "Torta aggiornata",
            "price": "5.00",
            "category_id": str(cucina.id),
            "sort_order": "3",
            "active": "false",
            "description": "fetta",
            "return_to": "/products?show=all",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 303
    assert edit_response.headers["location"] == "/products?show=all"
    db_session.refresh(product)
    assert product.name == "Torta aggiornata"
    assert product.price_cents == 500
    assert product.category_id == cucina.id
    assert product.sort_order == 3
    assert product.active is False

    toggle_response = admin_client.post(
        f"/products/{product.id}/toggle-active",
        data={"return_to": "/products?show=inactive"},
        follow_redirects=False,
    )
    assert toggle_response.status_code == 303
    assert toggle_response.headers["location"] == "/products?show=inactive"
    db_session.refresh(product)
    assert product.active is True


def test_product_delete_and_bulk_actions(admin_client, db_session):
    cucina = db_session.scalar(select(Category).where(Category.name == "Cucina"))
    product_a = Product(name="Bulk A", price_cents=100, category_id=cucina.id, active=True, sort_order=99)
    product_b = Product(name="Bulk B", price_cents=200, category_id=cucina.id, active=True, sort_order=100)
    db_session.add_all([product_a, product_b])
    db_session.commit()
    db_session.refresh(product_a)
    db_session.refresh(product_b)
    product_a_id = product_a.id
    product_b_id = product_b.id

    deactivate = admin_client.post(
        "/products/bulk",
        data={"action": "deactivate", "product_ids": [str(product_a_id), str(product_b_id)], "return_to": "/products"},
        follow_redirects=False,
    )
    assert deactivate.status_code == 303
    db_session.refresh(product_a)
    db_session.refresh(product_b)
    assert product_a.active is False
    assert product_b.active is False

    activate = admin_client.post(
        "/products/bulk",
        data={"action": "activate", "product_ids": [str(product_a_id), str(product_b_id)], "return_to": "/products"},
        follow_redirects=False,
    )
    assert activate.status_code == 303
    db_session.refresh(product_a)
    db_session.refresh(product_b)
    assert product_a.active is True
    assert product_b.active is True

    order = create_confirmed_order(
        db_session,
        parse_cart_json(json.dumps([{"product_id": product_a_id, "quantity": 1}])),
        source="test",
    )
    delete = admin_client.post(
        f"/products/{product_a_id}/delete",
        data={"return_to": "/products"},
        follow_redirects=False,
    )
    assert delete.status_code == 303
    db_session.expire_all()
    assert db_session.get(Product, product_a_id) is None
    db_session.refresh(order.items[0])
    assert order.items[0].product_id is None
    assert order.items[0].product_name == "Bulk A"

    bulk_delete = admin_client.post(
        "/products/bulk",
        data={"action": "delete", "product_ids": [str(product_b_id)], "return_to": "/products"},
        follow_redirects=False,
    )
    assert bulk_delete.status_code == 303
    db_session.expire_all()
    assert db_session.get(Product, product_b_id) is None


def test_order_creation_numbering_snapshot_and_fake_output(cashier_client, db_session, test_env):
    product = db_session.scalar(select(Product).where(Product.name == "Panino salamella"))
    response = cashier_client.post(
        "/orders",
        data={"cart_json": json.dumps([{"product_id": product.id, "quantity": 2, "notes": "senza cipolla"}])},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    order = db_session.scalar(select(Order).order_by(Order.id.desc()))
    assert order is not None
    assert order.order_number == 1
    assert order.business_date == business_date_for()
    assert order.items[0].product_name == "Panino salamella"
    assert order.items[0].unit_price_cents == 600
    assert order.items[0].notes == "senza cipolla"

    product.name = "Nome cambiato"
    product.price_cents = 999
    db_session.commit()
    db_session.refresh(order.items[0])
    assert order.items[0].product_name == "Panino salamella"
    assert order.items[0].unit_price_cents == 600

    jobs = db_session.scalars(select(PrintJob).where(PrintJob.order_id == order.id)).all()
    assert len(jobs) == 2
    assert {job.job_type for job in jobs} == {"customer", "production"}
    assert all(job.status == "printed" for job in jobs)

    output_files = list(Path(test_env["print_output_dir"]).glob("*.txt"))
    assert len(output_files) == 2
    assert any("ORDINE N. 001" in path.read_text(encoding="utf-8") for path in output_files)


def test_daily_order_number_increment(db_session):
    product = db_session.scalar(select(Product).where(Product.name == "Panino salamella"))
    order_one = create_confirmed_order(db_session, parse_cart_json(json.dumps([{"product_id": product.id, "quantity": 1}])), source="test")
    order_two = create_confirmed_order(db_session, parse_cart_json(json.dumps([{"product_id": product.id, "quantity": 1}])), source="test")
    assert order_one.order_number == 1
    assert order_two.order_number == 2
    assert order_one.business_date == order_two.business_date


def test_grouping_items_by_printer(db_session):
    product_food = db_session.scalar(select(Product).where(Product.name == "Panino salamella"))
    product_bar = db_session.scalar(select(Product).where(Product.name == "Birra media"))
    order = create_confirmed_order(
        db_session,
        parse_cart_json(
            json.dumps(
                [
                    {"product_id": product_food.id, "quantity": 1},
                    {"product_id": product_bar.id, "quantity": 1},
                ]
            )
        ),
        source="test",
    )
    grouped, unassigned = printing.group_items_by_printer(order)
    assert not unassigned
    assert len(grouped) == 2


def test_failed_network_printer_job_is_recorded(db_session, monkeypatch):
    customer_printer = db_session.scalar(select(Printer).where(Printer.is_customer_printer.is_(True)))
    customer_printer.type = "network_escpos"
    customer_printer.ip = "192.0.2.10"
    db_session.commit()

    def fail_network(job, printer):
        raise printing.PrintError("offline")

    monkeypatch.setattr(printing, "_send_network_escpos", fail_network)
    product = db_session.scalar(select(Product).where(Product.name == "Panino salamella"))
    order = create_confirmed_order(db_session, parse_cart_json(json.dumps([{"product_id": product.id, "quantity": 1}])), source="test")
    result = printing.print_order(db_session, order.id, include_customer=True, include_production=False)
    assert result.jobs[0].status == "failed"
    assert "offline" in result.jobs[0].error_message
    assert db_session.get(Order, order.id) is not None


def test_reprint_customer_and_production(cashier_client, db_session):
    product = db_session.scalar(select(Product).where(Product.name == "Patatine"))
    cashier_client.post(
        "/orders",
        data={"cart_json": json.dumps([{"product_id": product.id, "quantity": 1}])},
        follow_redirects=False,
    )
    order = db_session.scalar(select(Order).order_by(Order.id.desc()))
    initial_jobs = len(db_session.scalars(select(PrintJob).where(PrintJob.order_id == order.id)).all())

    customer = cashier_client.post(f"/orders/{order.id}/reprint/customer", follow_redirects=False)
    production = cashier_client.post(f"/orders/{order.id}/reprint/production", follow_redirects=False)
    assert customer.status_code == 303
    assert production.status_code == 303

    jobs = db_session.scalars(select(PrintJob).where(PrintJob.order_id == order.id)).all()
    assert len(jobs) == initial_jobs + 2

    detail = cashier_client.get(f"/orders/{order.id}")
    assert detail.status_code == 200
    assert "Stampe" in detail.text


def test_close_register_creates_sales_history_and_closes_orders(cashier_client, db_session):
    product = db_session.scalar(select(Product).where(Product.name == "Acqua"))
    cashier_client.post(
        "/orders",
        data={"cart_json": json.dumps([{"product_id": product.id, "quantity": 3}])},
        follow_redirects=False,
    )
    order = db_session.scalar(select(Order).order_by(Order.id.desc()))
    assert order.status == "confirmed"
    assert order.paid_at is None

    response = cashier_client.post(
        "/closures",
        data={"business_date": order.business_date, "register_session": "1", "notes": "fine serata"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    closure = db_session.scalar(select(RegisterClosure).where(RegisterClosure.business_date == order.business_date))
    assert closure is not None
    assert closure.register_session == 1
    assert closure.order_count == 1
    assert closure.sales_total_cents == 300
    assert closure.cash_total_cents == 300

    db_session.refresh(order)
    assert order.status == "delivered"
    assert order.paid_at is not None
    assert order.completed_at is not None

    detail = cashier_client.get(f"/closures/{closure.id}")
    assert detail.status_code == 200
    assert "Chiusura" in detail.text


def test_order_number_resets_after_register_closure(cashier_client, db_session):
    product = db_session.scalar(select(Product).where(Product.name == "Caffe"))
    first_response = cashier_client.post(
        "/orders",
        data={"cart_json": json.dumps([{"product_id": product.id, "quantity": 1}])},
        follow_redirects=False,
    )
    assert first_response.status_code == 303
    first_order = db_session.scalar(select(Order).order_by(Order.id.desc()))
    assert first_order.order_number == 1
    assert first_order.register_session == 1

    close_response = cashier_client.post(
        "/closures",
        data={"business_date": first_order.business_date, "register_session": "1"},
        follow_redirects=False,
    )
    assert close_response.status_code == 303

    second_response = cashier_client.post(
        "/orders",
        data={"cart_json": json.dumps([{"product_id": product.id, "quantity": 1}])},
        follow_redirects=False,
    )
    assert second_response.status_code == 303
    second_order = db_session.scalar(select(Order).order_by(Order.id.desc()))
    assert second_order.business_date == first_order.business_date
    assert second_order.register_session == 2
    assert second_order.order_number == 1


def test_mobile_order_is_confirmed_printed_and_returns_to_mobile(cashier_client, db_session):
    product = db_session.scalar(select(Product).where(Product.name == "Birra media"))
    response = cashier_client.post(
        "/mobile/orders",
        data={"cart_json": json.dumps([{"product_id": product.id, "quantity": 1}])},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/mobile"

    order = db_session.scalar(select(Order).order_by(Order.id.desc()))
    assert order.source == "mobile"
    assert order.status == "confirmed"
    assert order.order_number == 1
    assert db_session.scalars(select(PrintJob).where(PrintJob.order_id == order.id)).all()
