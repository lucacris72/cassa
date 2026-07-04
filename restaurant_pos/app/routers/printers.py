from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Category, OrderItem, Printer, PrintJob, User
from ..services.printing import PrintError, list_usb_printer_devices, test_printer
from ..templating import render


router = APIRouter(prefix="/printers", tags=["printers"])


def _usb_devices_for_page(request: Request):
    try:
        return list_usb_printer_devices()
    except PrintError as exc:
        add_flash(request, f"Dispositivi USB non disponibili: {exc}", "error")
    except Exception as exc:
        add_flash(request, f"Dispositivi USB non disponibili: {exc}", "error")
    return []


def _normalize_port(type: str, port: int) -> int:
    if type == "usb_escpos" and port == 9100:
        return 0
    return port


def _printer_address(printer: Printer) -> str:
    if printer.type == "usb_escpos":
        return printer.ip or "-"
    if printer.ip:
        return f"{printer.ip}:{printer.port}"
    return "-"


@router.get("", response_class=HTMLResponse)
def printers_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin")),
):
    printers = db.scalars(select(Printer).order_by(Printer.name)).all()
    usb_devices = _usb_devices_for_page(request)
    return render(
        request,
        "printers.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "printers": printers,
            "usb_devices": usb_devices,
            "printer_address": _printer_address,
        },
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
    db.add(
        Printer(
            name=name.strip(),
            type=type,
            ip=ip.strip() or None,
            port=_normalize_port(type, port),
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
    usb_devices = _usb_devices_for_page(request)
    return render(
        request,
        "printer_edit.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "printer": printer,
            "usb_devices": usb_devices,
        },
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
    printer.name = name.strip()
    printer.type = type
    printer.ip = ip.strip() or None
    printer.port = _normalize_port(type, port)
    printer.enabled = enabled
    printer.is_customer_printer = is_customer_printer
    db.commit()
    add_flash(request, "Stampante aggiornata", "success")
    return RedirectResponse("/printers", status_code=303)


def _delete_printer(db: Session, printer: Printer) -> None:
    db.execute(update(Category).where(Category.printer_id == printer.id).values(printer_id=None))
    db.execute(update(OrderItem).where(OrderItem.printer_id == printer.id).values(printer_id=None))
    db.execute(update(PrintJob).where(PrintJob.printer_id == printer.id).values(printer_id=None))
    db.execute(update(User).where(User.customer_printer_id == printer.id).values(customer_printer_id=None))
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
