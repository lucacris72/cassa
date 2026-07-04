from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, Printer, Product, User
from ..templating import render


router = APIRouter(prefix="/categories", tags=["categories"])


def _printers(db: Session):
    return db.scalars(select(Printer).order_by(Printer.name)).all()


@router.get("", response_class=HTMLResponse)
def categories_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    categories = db.scalars(
        select(Category)
        .options(selectinload(Category.printer), selectinload(Category.products))
        .order_by(Category.active.desc(), Category.sort_order, Category.name)
    ).all()
    return render(
        request,
        "categories.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "categories": categories,
            "printers": _printers(db),
        },
    )


@router.post("")
def create_category(
    request: Request,
    name: str = Form(...),
    printer_id: int = Form(0),
    sort_order: int = Form(0),
    show_in_cashier: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    db.add(
        Category(
            name=name.strip(),
            printer_id=printer_id or None,
            sort_order=sort_order,
            show_in_cashier=show_in_cashier,
        )
    )
    db.commit()
    add_flash(request, "Categoria creata", "success")
    return RedirectResponse("/categories", status_code=303)


@router.get("/{category_id}/edit", response_class=HTMLResponse)
def edit_category_page(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    category = db.scalar(
        select(Category)
        .where(Category.id == category_id)
        .options(selectinload(Category.products))
    )
    if category is None:
        add_flash(request, "Categoria non trovata", "error")
        return RedirectResponse("/categories", status_code=303)
    return render(
        request,
        "category_edit.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "category": category,
            "printers": _printers(db),
        },
    )


@router.post("/{category_id}/edit")
def edit_category(
    category_id: int,
    request: Request,
    name: str = Form(...),
    printer_id: int = Form(0),
    sort_order: int = Form(0),
    active: bool = Form(False),
    show_in_cashier: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    category = db.get(Category, category_id)
    if category is None:
        add_flash(request, "Categoria non trovata", "error")
        return RedirectResponse("/categories", status_code=303)
    category.name = name.strip()
    category.printer_id = printer_id or None
    category.sort_order = sort_order
    category.active = active
    category.show_in_cashier = show_in_cashier
    db.commit()
    add_flash(request, "Categoria aggiornata", "success")
    return RedirectResponse("/categories", status_code=303)


@router.post("/{category_id}/delete")
def delete_category(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    category = db.get(Category, category_id)
    if category is None:
        add_flash(request, "Categoria non trovata", "error")
        return RedirectResponse("/categories", status_code=303)

    products_count = db.scalar(select(func.count(Product.id)).where(Product.category_id == category.id)) or 0
    if products_count:
        add_flash(
            request,
            f"Categoria non eliminata: contiene {products_count} prodotti. Spostali o eliminali prima.",
            "error",
        )
        return RedirectResponse("/categories", status_code=303)

    category_name = category.name
    try:
        db.delete(category)
        db.commit()
        add_flash(request, f"Categoria eliminata: {category_name}", "success")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Categoria non eliminata: {exc}", "error")
    return RedirectResponse("/categories", status_code=303)


@router.post("/{category_id}/toggle-cashier-visibility")
def toggle_cashier_visibility(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    category = db.get(Category, category_id)
    if category is None:
        add_flash(request, "Categoria non trovata", "error")
        return RedirectResponse("/categories", status_code=303)
    category.show_in_cashier = not category.show_in_cashier
    db.commit()
    state = "visibile in cassa" if category.show_in_cashier else "nascosta dalla cassa"
    add_flash(request, f"{category.name}: {state}", "success")
    return RedirectResponse("/categories", status_code=303)
