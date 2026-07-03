from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, OrderItem, Printer, PrintJob, User
from ..services.printing import test_printer
from ..templating import render


router = APIRouter(prefix="/printers", tags=["printers"])


@router.get("", response_class=HTMLResponse)
def printers_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    printers = db.scalars(select(Printer).order_by(Printer.name)).all()
    return render(
        request,
        "printers.html",
        {"user": user, "flashes": pop_flashes(request), "printers": printers},
    )


@router.post("")
def create_printer(
    request: Request,
    name: str = Form(...),
    type: str = Form("fake"),
    ip: str = Form(""),
    port: int = Form(9100),
    enabled: bool = Form(False),
    is_customer_printer: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    if is_customer_printer:
        for printer in db.scalars(select(Printer).where(Printer.is_customer_printer.is_(True))):
            printer.is_customer_printer = False
    db.add(
        Printer(
            name=name.strip(),
            type=type,
            ip=ip.strip() or None,
            port=port,
            enabled=enabled,
            is_customer_printer=is_customer_printer,
        )
    )
    db.commit()
    add_flash(request, "Stampante creata", "success")
    return RedirectResponse("/printers", status_code=303)


@router.get("/{printer_id}/edit", response_class=HTMLResponse)
def edit_printer_page(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    printer = db.get(Printer, printer_id)
    if printer is None:
        add_flash(request, "Stampante non trovata", "error")
        return RedirectResponse("/printers", status_code=303)
    return render(
        request,
        "printer_edit.html",
        {"user": user, "flashes": pop_flashes(request), "printer": printer},
    )


@router.post("/{printer_id}/edit")
def edit_printer(
    printer_id: int,
    request: Request,
    name: str = Form(...),
    type: str = Form("fake"),
    ip: str = Form(""),
    port: int = Form(9100),
    enabled: bool = Form(False),
    is_customer_printer: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    printer = db.get(Printer, printer_id)
    if printer is None:
        add_flash(request, "Stampante non trovata", "error")
        return RedirectResponse("/printers", status_code=303)
    if is_customer_printer:
        for other in db.scalars(select(Printer).where(Printer.is_customer_printer.is_(True), Printer.id != printer.id)):
            other.is_customer_printer = False
    printer.name = name.strip()
    printer.type = type
    printer.ip = ip.strip() or None
    printer.port = port
    printer.enabled = enabled
    printer.is_customer_printer = is_customer_printer
    db.commit()
    add_flash(request, "Stampante aggiornata", "success")
    return RedirectResponse("/printers", status_code=303)


def _delete_printer(db: Session, printer: Printer) -> None:
    db.execute(update(Category).where(Category.printer_id == printer.id).values(printer_id=None))
    db.execute(update(OrderItem).where(OrderItem.printer_id == printer.id).values(printer_id=None))
    db.execute(update(PrintJob).where(PrintJob.printer_id == printer.id).values(printer_id=None))
    db.delete(printer)


@router.post("/{printer_id}/delete")
def delete_printer(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    printer = db.get(Printer, printer_id)
    if printer is None:
        add_flash(request, "Stampante non trovata", "error")
        return RedirectResponse("/printers", status_code=303)
    printer_name = printer.name
    try:
        _delete_printer(db, printer)
        db.commit()
        add_flash(request, f"Stampante eliminata: {printer_name}", "success")
    except Exception as exc:
        db.rollback()
        add_flash(request, f"Stampante non eliminata: {exc}", "error")
    return RedirectResponse("/printers", status_code=303)


@router.post("/{printer_id}/test")
def test_printer_route(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    printer = db.get(Printer, printer_id)
    if printer is None:
        add_flash(request, "Stampante non trovata", "error")
    else:
        try:
            test_printer(printer)
        except Exception as exc:
            add_flash(request, f"Test stampante fallito: {exc}", "error")
        else:
            add_flash(request, "Test stampante inviato", "success")
    return RedirectResponse("/printers", status_code=303)
