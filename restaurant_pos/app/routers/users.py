from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, hash_pin, pop_flashes, require_user
from ..database import get_db
from ..models import Printer, User
from ..templating import render


router = APIRouter(prefix="/users", tags=["users"])

ROLE_OPTIONS = {"admin", "cashier", "waiter"}


def _customer_printers(db: Session) -> list[Printer]:
    return db.scalars(
        select(Printer)
        .where(Printer.is_customer_printer.is_(True))
        .order_by(Printer.enabled.desc(), Printer.name)
    ).all()


def _normalize_role(role: str) -> str:
    role = role.strip()
    if role not in ROLE_OPTIONS:
        raise ValueError("Ruolo non valido")
    return role


def _safe_customer_printer_id(value: int) -> int | None:
    return value or None


@router.get("", response_class=HTMLResponse)
def users_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    users = db.scalars(
        select(User)
        .options(selectinload(User.customer_printer))
        .order_by(User.active.desc(), User.role, User.name)
    ).all()
    return render(
        request,
        "users.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "users": users,
            "customer_printers": _customer_printers(db),
        },
    )


@router.post("")
def create_user(
    request: Request,
    name: str = Form(...),
    pin: str = Form(...),
    role: str = Form("cashier"),
    active: bool = Form(False),
    customer_printer_id: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    try:
        new_user = User(
            name=name.strip(),
            pin_hash=hash_pin(pin.strip()),
            role=_normalize_role(role),
            active=active,
            customer_printer_id=_safe_customer_printer_id(customer_printer_id),
        )
        db.add(new_user)
        db.commit()
        add_flash(request, "Utente creato", "success")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Utente non creato: {exc}", "error")
    return RedirectResponse("/users", status_code=303)


@router.get("/{user_id}/edit", response_class=HTMLResponse)
def edit_user_page(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    edited_user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.customer_printer))
    )
    if edited_user is None:
        add_flash(request, "Utente non trovato", "error")
        return RedirectResponse("/users", status_code=303)
    return render(
        request,
        "user_edit.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "edited_user": edited_user,
            "customer_printers": _customer_printers(db),
        },
    )


@router.post("/{user_id}/edit")
def edit_user(
    user_id: int,
    request: Request,
    name: str = Form(...),
    role: str = Form("cashier"),
    active: bool = Form(False),
    pin: str = Form(""),
    customer_printer_id: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    edited_user = db.get(User, user_id)
    if edited_user is None:
        add_flash(request, "Utente non trovato", "error")
        return RedirectResponse("/users", status_code=303)
    try:
        edited_user.name = name.strip()
        edited_user.role = _normalize_role(role)
        edited_user.active = active or edited_user.id == user.id
        edited_user.customer_printer_id = _safe_customer_printer_id(customer_printer_id)
        if pin.strip():
            edited_user.pin_hash = hash_pin(pin.strip())
        db.commit()
        add_flash(request, "Utente aggiornato", "success")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Utente non aggiornato: {exc}", "error")
    return RedirectResponse("/users", status_code=303)
