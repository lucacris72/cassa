from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, Product, User
from ..services import orders as order_service
from ..templating import render


router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get("", response_class=HTMLResponse)
def mobile_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier", "waiter")),
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
        "mobile.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "categories": categories,
            "products": products,
        },
    )


@router.post("/orders")
def create_mobile_order(
    request: Request,
    cart_json: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier", "waiter")),
):
    try:
        lines = order_service.parse_cart_json(cart_json)
        order = order_service.create_pending_order(db, lines, source="mobile", notes=notes.strip() or None)
    except Exception as exc:
        add_flash(request, f"Ordine mobile non salvato: {exc}", "error")
        return RedirectResponse("/mobile", status_code=303)
    add_flash(request, "Ordine inviato alla cassa", "success")
    return RedirectResponse(f"/orders/{order.id}", status_code=303)
