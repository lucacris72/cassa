from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, OrderItem, Product, User
from ..templating import render
from ..utils import parse_price_to_cents


router = APIRouter(prefix="/products", tags=["products"])


def _categories(db: Session):
    return db.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.sort_order, Category.name)).all()


def _safe_products_redirect(return_to: str | None) -> str:
    if return_to and return_to.startswith("/products"):
        return return_to
    return "/products"


def _group_products(products: list[Product]) -> list[dict[str, object]]:
    groups: dict[int, dict[str, object]] = {}
    for product in products:
        category = product.category
        category_id = category.id if category else 0
        category_name = category.name if category else "Senza categoria"
        if category_id not in groups:
            groups[category_id] = {"name": category_name, "products": []}
        groups[category_id]["products"].append(product)
    return list(groups.values())


@router.get("", response_class=HTMLResponse)
def products_page(
    request: Request,
    category_id: int = Query(0),
    show: str = Query("all"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    query = select(Product).join(Product.category).options(selectinload(Product.category))
    if category_id:
        query = query.where(Product.category_id == category_id)
    if show == "active":
        query = query.where(Product.active.is_(True))
    elif show == "inactive":
        query = query.where(Product.active.is_(False))
    products = db.scalars(
        query.order_by(Category.sort_order, Category.name, Product.sort_order, Product.name)
    ).all()
    return render(
        request,
        "products.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "products": products,
            "grouped_products": _group_products(products),
            "categories": _categories(db),
            "selected_category_id": category_id,
            "selected_show": show,
        },
    )


@router.post("")
def create_product(
    request: Request,
    name: str = Form(...),
    price: str = Form(...),
    category_id: int = Form(...),
    sort_order: int = Form(0),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    try:
        db.add(
            Product(
                name=name.strip(),
                price_cents=parse_price_to_cents(price),
                category_id=category_id,
                sort_order=sort_order,
                description=description.strip() or None,
            )
        )
        db.commit()
        add_flash(request, "Prodotto creato", "success")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Prodotto non creato: {exc}", "error")
    return RedirectResponse("/products", status_code=303)


@router.get("/{product_id}/edit", response_class=HTMLResponse)
def edit_product_page(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    product = db.get(Product, product_id)
    if product is None:
        add_flash(request, "Prodotto non trovato", "error")
        return RedirectResponse("/products", status_code=303)
    return render(
        request,
        "product_edit.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "product": product,
            "categories": _categories(db),
        },
    )


@router.post("/{product_id}/edit")
def edit_product(
    product_id: int,
    request: Request,
    name: str = Form(...),
    price: str = Form(...),
    category_id: int = Form(...),
    sort_order: int = Form(0),
    active: bool = Form(False),
    description: str = Form(""),
    return_to: str = Form("/products"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    product = db.get(Product, product_id)
    if product is None:
        add_flash(request, "Prodotto non trovato", "error")
        return RedirectResponse(_safe_products_redirect(return_to), status_code=303)
    try:
        product.name = name.strip()
        product.price_cents = parse_price_to_cents(price)
        product.category_id = category_id
        product.sort_order = sort_order
        product.active = active
        product.description = description.strip() or None
        db.commit()
        add_flash(request, "Prodotto aggiornato", "success")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Prodotto non aggiornato: {exc}", "error")
    return RedirectResponse(_safe_products_redirect(return_to), status_code=303)


@router.post("/{product_id}/toggle-active")
def toggle_product_active(
    product_id: int,
    request: Request,
    return_to: str = Form("/products"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    product = db.get(Product, product_id)
    if product is None:
        add_flash(request, "Prodotto non trovato", "error")
        return RedirectResponse(_safe_products_redirect(return_to), status_code=303)
    product.active = not product.active
    db.commit()
    add_flash(request, f"{product.name}: {'attivo' if product.active else 'disattivo'}", "success")
    return RedirectResponse(_safe_products_redirect(return_to), status_code=303)


def _delete_product(db: Session, product: Product) -> None:
    db.execute(update(OrderItem).where(OrderItem.product_id == product.id).values(product_id=None))
    db.delete(product)


@router.post("/{product_id}/delete")
def delete_product(
    product_id: int,
    request: Request,
    return_to: str = Form("/products"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    product = db.get(Product, product_id)
    if product is None:
        add_flash(request, "Prodotto non trovato", "error")
        return RedirectResponse(_safe_products_redirect(return_to), status_code=303)
    product_name = product.name
    try:
        _delete_product(db, product)
        db.commit()
        add_flash(request, f"Prodotto eliminato: {product_name}", "success")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Prodotto non eliminato: {exc}", "error")
    return RedirectResponse(_safe_products_redirect(return_to), status_code=303)


@router.post("/bulk")
def bulk_products(
    request: Request,
    action: str = Form(...),
    product_ids: Annotated[list[int] | None, Form()] = None,
    return_to: str = Form("/products"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    selected_ids = product_ids or []
    if not selected_ids:
        add_flash(request, "Seleziona almeno un prodotto", "warning")
        return RedirectResponse(_safe_products_redirect(return_to), status_code=303)

    products = db.scalars(select(Product).where(Product.id.in_(selected_ids))).all()
    try:
        if action == "activate":
            for product in products:
                product.active = True
            message = f"Prodotti attivati: {len(products)}"
        elif action == "deactivate":
            for product in products:
                product.active = False
            message = f"Prodotti disattivati: {len(products)}"
        elif action == "delete":
            for product in products:
                _delete_product(db, product)
            message = f"Prodotti eliminati: {len(products)}"
        else:
            add_flash(request, "Azione non valida", "error")
            return RedirectResponse(_safe_products_redirect(return_to), status_code=303)
        db.commit()
        add_flash(request, message, "success")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Azione di gruppo fallita: {exc}", "error")
    return RedirectResponse(_safe_products_redirect(return_to), status_code=303)


@router.post("/{product_id}/disable")
def disable_product(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    product = db.get(Product, product_id)
    if product is not None:
        product.active = False
        db.commit()
        add_flash(request, "Prodotto disattivato", "success")
    return RedirectResponse("/products", status_code=303)
