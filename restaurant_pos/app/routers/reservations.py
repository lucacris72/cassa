from __future__ import annotations

from typing import Annotated

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


def _safe_reservations_redirect(return_to: str | None) -> str:
    if return_to and return_to.startswith("/reservations"):
        return return_to
    return "/reservations"


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


@router.post("/bulk")
def bulk_reservations(
    request: Request,
    action: str = Form(...),
    reservation_ids: Annotated[list[int] | None, Form()] = None,
    q: str = Form(""),
    status: str = Form("open"),
    return_to: str = Form("/reservations"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        if action == "delete_selected":
            selected_ids = reservation_ids or []
            if not selected_ids:
                add_flash(request, "Seleziona almeno una prenotazione", "warning")
                return RedirectResponse(_safe_reservations_redirect(return_to), status_code=303)
            deleted_count = reservation_service.delete_reservations(db, selected_ids)
            add_flash(request, f"Prenotazioni eliminate: {deleted_count}", "success")
        elif action == "delete_filtered":
            deleted_count = reservation_service.delete_reservations_by_filter(db, query=q, status=status)
            add_flash(request, f"Prenotazioni eliminate: {deleted_count}", "success")
        else:
            add_flash(request, "Azione non valida", "error")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Azione di gruppo fallita: {exc}", "error")
    return RedirectResponse(_safe_reservations_redirect(return_to), status_code=303)


@router.post("/{reservation_id}/create-order")
def create_order_from_reservation(
    reservation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        reservation = reservation_service.load_reservation_for_checkout(db, reservation_id)
        if reservation.status == "converted" and reservation.order_id is not None:
            add_flash(request, "Prenotazione gia convertita in comanda", "warning")
            return RedirectResponse(f"/orders/{reservation.order_id}", status_code=303)
    except OrderError as exc:
        add_flash(request, str(exc), "error")
        return RedirectResponse("/reservations", status_code=303)
    except Exception as exc:
        add_flash(request, f"Prenotazione non aperta: {exc}", "error")
        return RedirectResponse("/reservations", status_code=303)
    add_flash(request, "Prenotazione aperta in cassa", "success")
    return RedirectResponse(f"/?reservation_id={reservation.id}", status_code=303)
