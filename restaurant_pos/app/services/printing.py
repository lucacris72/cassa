from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings, resolve_project_path
from ..models import Order, OrderItem, Printer, PrintJob
from ..utils import format_money


class PrintError(RuntimeError):
    pass


@dataclass
class PrintResult:
    jobs: list[PrintJob]
    warnings: list[str]


def _order_label(order: Order) -> str:
    if order.order_number is None:
        return "S/N"
    return f"{order.order_number:03d}"


def _line_item_with_price(item: OrderItem) -> str:
    left = f"{item.quantity} x {item.product_name}"
    return f"{left[:24]:<24}{format_money(item.line_total_cents):>10}"


def build_customer_ticket(order: Order) -> str:
    lines = [
        "==============================",
        f"        ORDINE N. {_order_label(order)}",
        "==============================",
        "",
    ]
    for item in order.items:
        lines.append(_line_item_with_price(item))
        if item.notes:
            lines.append(f"  Nota: {item.notes}")
    lines.extend(
        [
            "",
            "------------------------------",
            f"{'TOTALE':<24}{format_money(order.total_cents):>10}",
            "",
            "Ritira quando viene chiamato:",
            f"        {_order_label(order)}",
            "",
            "Grazie!",
            "",
        ]
    )
    return "\n".join(lines)


def build_production_ticket(order: Order, printer: Printer, items: list[OrderItem]) -> str:
    title = printer.name.upper()
    lines = [
        f"====== {title} ======",
        f"ORDINE N. {_order_label(order)}",
        f"Ora: {datetime.now().strftime('%H:%M')}",
        "",
    ]
    for item in items:
        lines.append(f"{item.quantity} x {item.product_name}")
    notes = [f"- {item.product_name}: {item.notes}" for item in items if item.notes]
    if notes:
        lines.extend(["", "Note:", *notes])
    lines.append("")
    return "\n".join(lines)


def group_items_by_printer(order: Order) -> tuple[dict[int, list[OrderItem]], list[OrderItem]]:
    grouped: dict[int, list[OrderItem]] = {}
    unassigned: list[OrderItem] = []
    for item in order.items:
        if item.printer_id is None:
            unassigned.append(item)
        else:
            grouped.setdefault(item.printer_id, []).append(item)
    return grouped, unassigned


def _fake_output_path(job: PrintJob, order: Order, printer: Printer) -> Path:
    base = resolve_project_path(get_settings().print_output_dir)
    safe_printer = "".join(ch.lower() if ch.isalnum() else "_" for ch in printer.name).strip("_")
    label = _order_label(order)
    return base / f"{order.business_date}_order_{label}_{job.job_type}_{safe_printer}_job_{job.id}.txt"


def _write_fake(job: PrintJob, order: Order, printer: Printer) -> None:
    output_path = _fake_output_path(job, order, printer)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(job.payload_text, encoding="utf-8")


def _send_network_escpos(job: PrintJob, printer: Printer) -> None:
    if not printer.ip:
        raise PrintError("IP stampante mancante")
    payload = job.payload_text.encode("cp858", errors="replace")
    data = b"\x1b@" + payload + b"\n\n\n\x1dV\x00"
    try:
        with socket.create_connection((printer.ip, printer.port), timeout=5) as conn:
            conn.sendall(data)
    except OSError as exc:
        raise PrintError(str(exc)) from exc


def _dispatch(job: PrintJob, order: Order, printer: Printer) -> None:
    if not printer.enabled:
        raise PrintError("Stampante disabilitata")
    if printer.type == "fake":
        _write_fake(job, order, printer)
        return
    if printer.type == "network_escpos":
        _send_network_escpos(job, printer)
        return
    raise PrintError(f"Tipo stampante non supportato: {printer.type}")


def _save_and_attempt(db: Session, order: Order, printer: Printer, job_type: str, payload_text: str) -> PrintJob:
    job = PrintJob(order_id=order.id, printer_id=printer.id, job_type=job_type, status="pending", payload_text=payload_text)
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        _dispatch(job, order, printer)
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
    else:
        job.status = "printed"
        job.printed_at = datetime.now(UTC)
        job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def load_order_for_printing(db: Session, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.print_jobs))
    )
    if order is None:
        raise PrintError("Ordine non trovato")
    return order


def print_order(
    db: Session,
    order_id: int,
    *,
    include_customer: bool = True,
    include_production: bool = True,
) -> PrintResult:
    order = load_order_for_printing(db, order_id)
    jobs: list[PrintJob] = []
    warnings: list[str] = []

    if include_customer:
        customer_printer = db.scalar(
            select(Printer)
            .where(Printer.is_customer_printer.is_(True), Printer.enabled.is_(True))
            .order_by(Printer.id)
        )
        if customer_printer is None:
            warnings.append("Nessuna stampante cliente abilitata configurata")
        else:
            jobs.append(_save_and_attempt(db, order, customer_printer, "customer", build_customer_ticket(order)))

    if include_production:
        grouped, unassigned = group_items_by_printer(order)
        for item in unassigned:
            warnings.append(f"Nessuna stampante di produzione per {item.product_name}")
        for printer_id, items in grouped.items():
            printer = db.get(Printer, printer_id)
            if printer is None:
                warnings.append(f"Stampante produzione non trovata per {items[0].category_name}")
                continue
            payload = build_production_ticket(order, printer, items)
            jobs.append(_save_and_attempt(db, order, printer, "production", payload))

    for job in jobs:
        if job.status == "failed":
            warnings.append(f"Stampa {job.job_type} fallita su {job.printer.name if job.printer else 'N/D'}: {job.error_message}")

    return PrintResult(jobs=jobs, warnings=warnings)


def test_printer(printer: Printer) -> None:
    payload = f"TEST STAMPANTE\n{printer.name}\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    dummy_order = Order(id=0, order_number=0, business_date=datetime.now().date().isoformat(), status="test", total_cents=0, source="test")
    dummy_job = PrintJob(id=0, order_id=0, printer_id=printer.id, job_type="test", status="pending", payload_text=payload)
    _dispatch(dummy_job, dummy_order, printer)
