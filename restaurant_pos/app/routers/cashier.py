from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, Product, User
from ..services import orders as order_service
from ..services.printing import print_order
from ..templating import render


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def cashier_screen(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    categories = db.scalars(
        select(Category)
        .where(Category.active.is_(True))
        .options(selectinload(Category.products))
        .order_by(Category.sort_order, Category.name)
    ).all()
    products = db.scalars(
        select(Product)
        .where(Product.active.is_(True))
        .options(selectinload(Product.category))
        .order_by(Product.sort_order, Product.name)
    ).all()
    return render(
        request,
        "cashier.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "categories": categories,
            "products": products,
        },
    )


@router.post("/orders")
def create_order(
    request: Request,
    cart_json: str = Form(...),
    notes: str = Form(""),
    mark_paid: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        lines = order_service.parse_cart_json(cart_json)
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
        add_flash(request, "Ordine creato e stampa avviata", "success")
    return RedirectResponse(f"/orders/{order.id}", status_code=303)
