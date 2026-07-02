from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import add_flash, authenticate_by_pin, get_current_user, pop_flashes
from ..database import get_db
from ..models import User
from ..templating import render


router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return render(
        request,
        "login.html",
        {"user": None, "flashes": pop_flashes(request)},
    )


@router.post("/login")
def login(request: Request, pin: str = Form(...), db: Session = Depends(get_db)):
    user = authenticate_by_pin(db, pin)
    if user is None:
        add_flash(request, "PIN non valido", "error")
        return RedirectResponse("/login", status_code=303)
    request.session["user_id"] = user.id
    add_flash(request, f"Accesso effettuato come {user.name}", "success")
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
