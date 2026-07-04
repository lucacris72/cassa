from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, Order, PrintJob, Product, User
from ..services import orders as order_service
from ..services.numbering import business_date_for
from ..services.printing import print_order
from ..templating import render


router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_class=HTMLResponse)
def orders_page(
    request: Request,
    date: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    selected_date = date or business_date_for()
    orders = db.scalars(
        select(Order)
        .where(Order.business_date == selected_date)
        .order_by(Order.created_at.desc())
        .options(selectinload(Order.items))
    ).all()
    pending_orders = db.scalars(
        select(Order)
        .where(Order.status == "pending_confirmation")
        .order_by(Order.created_at.asc())
        .options(selectinload(Order.items))
    ).all()
    return render(
        request,
        "orders.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "orders": orders,
            "pending_orders": pending_orders,
            "selected_date": selected_date,
        },
    )


@router.get("/{order_id}", response_class=HTMLResponse)
def order_detail(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.print_jobs).selectinload(PrintJob.printer))
    )
    if order is None:
        add_flash(request, "Ordine non trovato", "error")
        return RedirectResponse("/orders", status_code=303)
    categories = []
    products = []
    if order.status == "pending_confirmation":
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
        "order_detail.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "order": order,
            "categories": categories,
            "products": products,
        },
    )


@router.post("/{order_id}/edit")
def edit_pending_order(
    order_id: int,
    request: Request,
    cart_json: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        lines = order_service.parse_cart_json(cart_json)
        order_service.update_pending_order(db, order_id, lines, notes=notes.strip() or None)
    except order_service.OrderError as exc:
        add_flash(request, str(exc), "error")
    except Exception as exc:
        add_flash(request, f"Comanda non aggiornata: {exc}", "error")
    else:
        add_flash(request, "Comanda aggiornata", "success")
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.post("/{order_id}/confirm")
def confirm_pending(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        order = order_service.confirm_pending_order(db, order_id)
        result = print_order(db, order.id)
    except Exception as exc:
        add_flash(request, f"Conferma fallita: {exc}", "error")
        return RedirectResponse(f"/orders/{order_id}", status_code=303)
    for warning in result.warnings:
        add_flash(request, warning, "warning")
    add_flash(request, "Ordine confermato", "success")
    return RedirectResponse(f"/orders/{order.id}", status_code=303)


@router.post("/{order_id}/reprint/customer")
def reprint_customer(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    result = print_order(db, order_id, include_customer=True, include_production=False)
    for warning in result.warnings:
        add_flash(request, warning, "warning")
    add_flash(request, "Ristampa cliente richiesta", "success")
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.post("/{order_id}/reprint/production")
def reprint_production(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    result = print_order(db, order_id, include_customer=False, include_production=True)
    for warning in result.warnings:
        add_flash(request, warning, "warning")
    add_flash(request, "Ristampa produzione richiesta", "success")
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.post("/{order_id}/mark-paid")
def mark_paid(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    order = db.get(Order, order_id)
    if order is not None:
        order_service.mark_paid(db, order)
        add_flash(request, "Ordine segnato pagato", "success")
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.post("/{order_id}/mark-delivered")
def mark_delivered(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    order = db.get(Order, order_id)
    if order is not None:
        order_service.mark_delivered(db, order)
        add_flash(request, "Ordine consegnato", "success")
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    order = db.get(Order, order_id)
    if order is not None:
        order_service.cancel_order(db, order)
        add_flash(request, "Ordine annullato", "success")
    return RedirectResponse(f"/orders/{order_id}", status_code=303)
