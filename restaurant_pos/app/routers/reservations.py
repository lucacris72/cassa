from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import User
from ..services import reservations as reservation_service
from ..services.orders import OrderError
from ..templating import render


router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.get("", response_class=HTMLResponse)
def reservations_page(
    request: Request,
    q: str = Query(""),
    status: str = Query("open"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    reservations = reservation_service.search_reservations(db, query=q, status=status)
    return render(
        request,
        "reservations.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "reservations": reservations,
            "q": q,
            "status": status,
            "default_import_path": "prenotazioni.xlsx",
        },
    )


@router.post("/import")
def import_reservations(
    request: Request,
    import_path: str = Form("prenotazioni.xlsx"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        result = reservation_service.import_reservations_from_xlsx(db, import_path)
    except Exception as exc:
        add_flash(request, f"Import prenotazioni fallito: {exc}", "error")
    else:
        add_flash(
            request,
            (
                f"Import completato: {result.created} nuove, {result.updated} aggiornate, "
                f"{result.skipped} saltate. Prodotti: {result.products_created} creati, "
                f"{result.products_updated} aggiornati."
            ),
            "success",
        )
    return RedirectResponse("/reservations", status_code=303)


@router.post("/{reservation_id}/create-order")
def create_order_from_reservation(
    reservation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        order = reservation_service.create_order_from_reservation(db, reservation_id)
    except OrderError as exc:
        add_flash(request, str(exc), "error")
        return RedirectResponse("/reservations", status_code=303)
    except Exception as exc:
        add_flash(request, f"Comanda non creata: {exc}", "error")
        return RedirectResponse("/reservations", status_code=303)
    add_flash(request, "Comanda creata in revisione", "success")
    return RedirectResponse(f"/orders/{order.id}", status_code=303)
