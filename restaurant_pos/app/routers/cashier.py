from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, Product, User
from ..services import orders as order_service
from ..services import reservations as reservation_service
from ..services.printing import print_order
from ..templating import render


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def cashier_screen(
    request: Request,
    reservation_id: int = Query(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    initial_cart: list[dict[str, object]] = []
    checkout_reservation = None
    if reservation_id:
        try:
            checkout_reservation = reservation_service.load_reservation_for_checkout(db, reservation_id)
            if checkout_reservation.status == "converted" and checkout_reservation.order_id is not None:
                add_flash(request, "Prenotazione gia convertita in comanda", "warning")
                return RedirectResponse(f"/orders/{checkout_reservation.order_id}", status_code=303)
            initial_cart = reservation_service.reservation_cart_items(checkout_reservation)
        except order_service.OrderError as exc:
            add_flash(request, str(exc), "error")
            return RedirectResponse("/reservations", status_code=303)

    categories = db.scalars(
        select(Category)
        .where(Category.active.is_(True), Category.show_in_cashier.is_(True))
        .options(selectinload(Category.products))
        .order_by(Category.sort_order, Category.name)
    ).all()
    products = db.scalars(
        select(Product)
        .join(Product.category)
        .where(
            Product.active.is_(True),
            Category.active.is_(True),
            Category.show_in_cashier.is_(True),
        )
        .options(selectinload(Product.category))
        .order_by(Category.sort_order, Category.name, Product.sort_order, Product.name)
    ).all()
    return render(
        request,
        "cashier.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "categories": categories,
            "products": products,
            "initial_cart": initial_cart,
            "checkout_reservation": checkout_reservation,
        },
    )


@router.post("/orders")
def create_order(
    request: Request,
    cart_json: str = Form(...),
    notes: str = Form(""),
    mark_paid: bool = Form(False),
    reservation_id: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        lines = order_service.parse_cart_json(cart_json)
        if reservation_id:
            order = reservation_service.create_confirmed_order_from_reservation(
                db,
                reservation_id,
                lines,
                notes=notes.strip() or None,
                mark_paid=mark_paid,
            )
        else:
            order = order_service.create_confirmed_order(
                db,
                lines,
                source="cashier",
                notes=notes.strip() or None,
                mark_paid=mark_paid,
            )
        result = print_order(db, order.id)
    except order_service.OrderError as exc:
        add_flash(request, str(exc), "error")
        return RedirectResponse("/", status_code=303)
    except Exception as exc:
        add_flash(request, f"Ordine non salvato: {exc}", "error")
        return RedirectResponse("/", status_code=303)

    if result.warnings:
        for warning in result.warnings:
            add_flash(request, warning, "warning")
    else:
        label = f"{order.order_number:03d}" if order.order_number is not None else str(order.id)
        add_flash(request, f"Ordine N. {label} creato. Pronto per il prossimo ordine.", "success")
    return RedirectResponse("/", status_code=303)
