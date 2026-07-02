from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, Product, User
from ..templating import render
from ..utils import parse_price_to_cents


router = APIRouter(prefix="/products", tags=["products"])


def _categories(db: Session):
    return db.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.sort_order, Category.name)).all()


@router.get("", response_class=HTMLResponse)
def products_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    products = db.scalars(
        select(Product).options(selectinload(Product.category)).order_by(Product.active.desc(), Product.sort_order, Product.name)
    ).all()
    return render(
        request,
        "products.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "products": products,
            "categories": _categories(db),
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
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    product = db.get(Product, product_id)
    if product is None:
        add_flash(request, "Prodotto non trovato", "error")
        return RedirectResponse("/products", status_code=303)
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
    return RedirectResponse("/products", status_code=303)


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
