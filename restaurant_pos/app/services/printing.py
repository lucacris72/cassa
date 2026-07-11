from __future__ import annotations

import os
import socket
import textwrap
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings, resolve_project_path
from ..models import Order, OrderItem, Printer, PrintJob
from ..utils import format_money


class PrintError(RuntimeError):
    pass


class NetworkPrintError(PrintError):
    pass


@dataclass
class PrintResult:
    jobs: list[PrintJob]
    warnings: list[str]


@dataclass(frozen=True)
class UsbPrinterDevice:
    ref: str
    label: str
    vendor_id: int
    product_id: int
    serial_number: str | None
    interface_class: int | None


CUSTOMER_TICKET_WIDTH = 38
PRODUCTION_TICKET_WIDTH = 42
NETWORK_RETRY_DELAYS_SECONDS = (0.5, 1.5)
PRODUCTION_PRODUCT_TEXT_SIZE = 0x01


def _order_label(order: Order) -> str:
    if order.order_number is None:
        return "S/N"
    return f"{order.order_number:03d}"


def _center(text: str, width: int = CUSTOMER_TICKET_WIDTH) -> str:
    return text.center(width)


def _money_line(label: str, cents: int, width: int = CUSTOMER_TICKET_WIDTH) -> str:
    price = format_money(cents)
    available = max(1, width - len(price) - 1)
    return f"{label[:available]:<{available}} {price}"


def _wrap_prefixed(prefix: str, text: str, width: int = CUSTOMER_TICKET_WIDTH) -> list[str]:
    body_width = max(10, width - len(prefix))
    wrapped = textwrap.wrap(text, width=body_width, break_long_words=False, break_on_hyphens=False) or [""]
    return [f"{prefix}{wrapped[0]}"] + [f"{' ' * len(prefix)}{line}" for line in wrapped[1:]]


def _line_item_summary(item: OrderItem) -> list[str]:
    unit = format_money(item.unit_price_cents)
    total = format_money(item.line_total_cents)
    lines = _wrap_prefixed(f"{item.quantity:>2} x ", item.product_name.upper(), CUSTOMER_TICKET_WIDTH)
    lines.append(f"     {item.quantity} x {unit} = {total}")
    if item.notes:
        lines.extend(_wrap_prefixed("     Nota: ", item.notes, CUSTOMER_TICKET_WIDTH))
    return lines


def _production_item_summary(item: OrderItem) -> list[str]:
    lines = [
        f"QTA {item.quantity}",
        *_wrap_prefixed("", item.product_name.upper(), PRODUCTION_TICKET_WIDTH),
    ]
    if item.notes:
        lines.extend(["", "NOTE:", *_wrap_prefixed("  ", item.notes, PRODUCTION_TICKET_WIDTH)])
    return lines


def _pickup_later_banner(width: int) -> list[str]:
    return ["!" * width, _center("RITIRA PIU TARDI", width), "!" * width, ""]


def build_customer_ticket(order: Order) -> str:
    label = _order_label(order)
    total = format_money(order.total_cents)
    lines = [
        "=" * CUSTOMER_TICKET_WIDTH,
        _center("COMANDA CLIENTE"),
        _center("ORDINE"),
        _center(label),
        "=" * CUSTOMER_TICKET_WIDTH,
        "",
    ]
    if order.pickup_later:
        lines.extend(_pickup_later_banner(CUSTOMER_TICKET_WIDTH))
    for item in order.items:
        lines.extend(_line_item_summary(item))
        lines.append("")
    lines.extend(
        [
            "*" * CUSTOMER_TICKET_WIDTH,
            _center("TOTALE"),
            _center(total),
            "*" * CUSTOMER_TICKET_WIDTH,
            "",
            _center("RITIRO ORDINE"),
            _center(label),
            "",
            _center("Grazie!"),
            "",
            "",
            "",
        ]
    )
    return "\n".join(lines)


def build_production_ticket(order: Order, printer: Printer, items: list[OrderItem]) -> str:
    title = printer.name.upper()
    label = _order_label(order)
    lines = [
        "=" * PRODUCTION_TICKET_WIDTH,
        _center(title, PRODUCTION_TICKET_WIDTH),
        _center("ORDINE", PRODUCTION_TICKET_WIDTH),
        _center(label, PRODUCTION_TICKET_WIDTH),
        _center(f"Ora {datetime.now().strftime('%H:%M')}", PRODUCTION_TICKET_WIDTH),
        "=" * PRODUCTION_TICKET_WIDTH,
        "",
    ]
    if order.pickup_later:
        lines.extend(_pickup_later_banner(PRODUCTION_TICKET_WIDTH))
    for item in items:
        lines.extend(_production_item_summary(item))
        lines.extend(["", "-" * PRODUCTION_TICKET_WIDTH, ""])
    lines.extend([_center("FINE COMANDA", PRODUCTION_TICKET_WIDTH), ""])
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


def _escpos_text(text: str, *, align: str = "left", bold: bool = False, size: int = 0) -> bytes:
    align_value = {"left": 0, "center": 1, "right": 2}.get(align, 0)
    return (
        b"\x1ba"
        + bytes([align_value])
        + b"\x1bE"
        + (b"\x01" if bold else b"\x00")
        + b"\x1d!"
        + bytes([size])
        + text.encode("cp858", errors="replace")
        + b"\n"
    )


def _escpos_reset_text() -> bytes:
    return b"\x1ba\x00\x1bE\x00\x1d!\x00"


def _escpos_finish(printer: Printer) -> bytes:
    cut_mode = b"\x01" if printer.partial_cut else b"\x00"
    return b"\n\n\n\x1dV" + cut_mode


def _is_separator_line(text: str) -> bool:
    return bool(text) and len(set(text)) == 1 and text[0] in {"=", "-", "*", "!"}


def _is_item_title_line(text: str) -> bool:
    if " x " not in text or "=" in text:
        return False
    quantity, _, _ = text.partition(" x ")
    return quantity.strip().isdigit()


def _build_customer_escpos(job: PrintJob, order: Order, printer: Printer) -> bytes:
    label = _order_label(order)
    total = format_money(order.total_cents)
    parts = [b"\x1b@"]
    for raw_line in job.payload_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            parts.append(b"\n")
        elif _is_separator_line(stripped):
            parts.append(_escpos_text(stripped, align="center"))
        elif stripped == "COMANDA CLIENTE":
            parts.append(_escpos_text(stripped, align="center", bold=True))
        elif stripped == "RITIRA PIU TARDI":
            parts.append(_escpos_text(stripped, align="center", bold=True, size=0x11))
        elif stripped == "ORDINE":
            parts.append(_escpos_text(stripped, align="center", bold=True, size=0x01))
        elif stripped == label:
            parts.append(_escpos_text(stripped, align="center", bold=True, size=0x22))
        elif stripped == "TOTALE":
            parts.append(_escpos_text(stripped, align="center", bold=True, size=0x01))
        elif stripped == total:
            parts.append(_escpos_text(stripped, align="center", bold=True, size=0x11))
        elif stripped == "RITIRO ORDINE":
            parts.append(_escpos_text(stripped, align="center", bold=True))
        elif stripped == "Grazie!":
            parts.append(_escpos_text(stripped, align="center"))
        elif _is_item_title_line(stripped):
            parts.append(_escpos_text(line, bold=True))
        else:
            parts.append(_escpos_text(line))
    parts.extend([_escpos_reset_text(), _escpos_finish(printer)])
    return b"".join(parts)


def _build_production_escpos(job: PrintJob, order: Order, printer: Printer) -> bytes:
    label = _order_label(order)
    title = printer.name.upper()
    parts = [b"\x1b@"]
    reading_product_name = False
    for raw_line in job.payload_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            parts.append(b"\n")
            reading_product_name = False
        elif _is_separator_line(stripped):
            parts.append(_escpos_text(stripped, align="center"))
            reading_product_name = False
        elif reading_product_name:
            parts.append(_escpos_text(line, bold=True, size=PRODUCTION_PRODUCT_TEXT_SIZE))
        elif stripped in {title, "ORDINE", "FINE COMANDA"}:
            parts.append(_escpos_text(stripped, align="center", bold=True))
        elif stripped == "RITIRA PIU TARDI":
            parts.append(_escpos_text(stripped, align="center", bold=True, size=0x11))
        elif stripped == label:
            parts.append(_escpos_text(stripped, align="center", bold=True, size=0x22))
        elif stripped.startswith("Ora "):
            parts.append(_escpos_text(stripped, align="center", bold=True))
        elif stripped.startswith("QTA "):
            parts.append(_escpos_text(stripped, bold=True, size=0x01))
            reading_product_name = True
        elif stripped == "NOTE:":
            parts.append(_escpos_text(stripped, bold=True))
        else:
            parts.append(_escpos_text(line, bold=stripped.isupper()))
    parts.extend([_escpos_reset_text(), _escpos_finish(printer)])
    return b"".join(parts)


def _build_plain_escpos(job: PrintJob, printer: Printer) -> bytes:
    payload = job.payload_text.encode("cp858", errors="replace")
    return b"\x1b@" + payload + _escpos_finish(printer)


def _build_escpos_payload(job: PrintJob, order: Order, printer: Printer) -> bytes:
    if job.job_type == "customer":
        return _build_customer_escpos(job, order, printer)
    if job.job_type == "production":
        return _build_production_escpos(job, order, printer)
    return _build_plain_escpos(job, printer)


def _send_network_escpos(job: PrintJob, printer: Printer, order: Order) -> None:
    if not printer.ip:
        raise PrintError("IP stampante mancante")
    data = _build_escpos_payload(job, order, printer)
    try:
        with socket.create_connection((printer.ip, printer.port), timeout=5) as conn:
            conn.sendall(data)
    except OSError as exc:
        raise NetworkPrintError(str(exc)) from exc


def _usb_modules() -> tuple[Any, Any, Any]:
    try:
        import usb.backend.libusb1
        import usb.core
        import usb.util
    except ImportError as exc:
        raise PrintError("Supporto USB non installato: esegui pip install -r requirements.txt") from exc

    backend = None
    try:
        import libusb_package
    except ImportError:
        backend = usb.backend.libusb1.get_backend()
    else:
        backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    if backend is None:
        raise PrintError("Backend libusb non trovato")
    return usb.core, usb.util, backend


def _device_string(usb_util: Any, device: Any, index: int | None) -> str | None:
    if not index:
        return None
    try:
        return usb_util.get_string(device, index)
    except Exception:
        return None


def _device_interface_class(device: Any) -> int | None:
    if getattr(device, "bDeviceClass", None) == 7:
        return 7
    try:
        for config in device:
            for interface in config:
                if getattr(interface, "bInterfaceClass", None) == 7:
                    return 7
    except Exception:
        return None
    return None


def list_usb_printer_devices() -> list[UsbPrinterDevice]:
    usb_core, usb_util, backend = _usb_modules()
    devices: list[UsbPrinterDevice] = []
    try:
        all_devices = list(usb_core.find(find_all=True, backend=backend))
    except Exception as exc:
        raise PrintError(f"Impossibile leggere i dispositivi USB: {exc}") from exc
    for device in all_devices:
        interface_class = _device_interface_class(device)
        if interface_class != 7:
            continue
        manufacturer = _device_string(usb_util, device, getattr(device, "iManufacturer", None))
        product = _device_string(usb_util, device, getattr(device, "iProduct", None))
        serial = _device_string(usb_util, device, getattr(device, "iSerialNumber", None))
        ref = f"{device.idVendor:04x}:{device.idProduct:04x}"
        if serial:
            ref = f"{ref}@{serial}"
        name = " ".join(part for part in [manufacturer, product] if part) or "USB printer"
        devices.append(
            UsbPrinterDevice(
                ref=ref,
                label=f"{name} ({ref})",
                vendor_id=device.idVendor,
                product_id=device.idProduct,
                serial_number=serial,
                interface_class=interface_class,
            )
        )
    return devices


def _parse_usb_ref(value: str | None) -> tuple[int, int, str | None]:
    if not value:
        raise PrintError("ID USB mancante")
    device_ref, _, serial = value.strip().partition("@")
    chunks = device_ref.replace("0x", "").replace("0X", "").split(":")
    if len(chunks) != 2:
        raise PrintError("ID USB non valido. Usa il formato VID:PID, esempio 04b8:0e15")
    try:
        vendor_id = int(chunks[0], 16)
        product_id = int(chunks[1], 16)
    except ValueError as exc:
        raise PrintError("ID USB non valido. Usa valori esadecimali VID:PID") from exc
    return vendor_id, product_id, serial or None


def _matching_usb_device(device: Any, usb_util: Any, vendor_id: int, product_id: int, serial: str | None) -> bool:
    if device.idVendor != vendor_id or device.idProduct != product_id:
        return False
    if serial is None:
        return True
    return _device_string(usb_util, device, getattr(device, "iSerialNumber", None)) == serial


def _windows_usb_symbolic_paths(vendor_id: int, product_id: int, serial: str | None) -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    key_path = rf"SYSTEM\CurrentControlSet\Enum\USB\VID_{vendor_id:04X}&PID_{product_id:04X}"
    paths: list[str] = []
    try:
        root_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
    except OSError:
        return []
    with root_key:
        index = 0
        while True:
            try:
                instance = winreg.EnumKey(root_key, index)
            except OSError:
                break
            index += 1
            if serial and serial.lower() not in instance.lower():
                continue
            try:
                params_key = winreg.OpenKey(root_key, rf"{instance}\Device Parameters")
                symbolic_name, _ = winreg.QueryValueEx(params_key, "SymbolicName")
            except OSError:
                continue
            with params_key:
                if symbolic_name.startswith("\\??\\"):
                    paths.append("\\\\?\\" + symbolic_name[4:])
                else:
                    paths.append(symbolic_name)
    return paths


def _write_windows_usb_path(path: str, data: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    generic_write = 0x40000000
    open_existing = 3
    file_attribute_normal = 0x80
    invalid_handle_value = wintypes.HANDLE(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL

    handle = kernel32.CreateFileW(path, generic_write, 0, None, open_existing, file_attribute_normal, None)
    if handle == invalid_handle_value:
        raise OSError(ctypes.get_last_error(), "CreateFileW failed")
    try:
        written = wintypes.DWORD(0)
        buffer = ctypes.create_string_buffer(data)
        ok = kernel32.WriteFile(handle, buffer, len(data), ctypes.byref(written), None)
        if not ok:
            raise OSError(ctypes.get_last_error(), "WriteFile failed")
        if written.value != len(data):
            raise OSError(0, f"Scrittura USB incompleta: {written.value}/{len(data)} byte")
    finally:
        kernel32.CloseHandle(handle)


def _send_windows_usb_raw(data: bytes, vendor_id: int, product_id: int, serial: str | None) -> bool:
    paths = _windows_usb_symbolic_paths(vendor_id, product_id, serial)
    if not paths:
        return False
    last_error: Exception | None = None
    for path in paths:
        try:
            _write_windows_usb_path(path, data)
            return True
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise PrintError(f"Invio USB Windows fallito: {last_error}") from last_error
    return False


def _find_usb_out_endpoint(device: Any, usb_util: Any, endpoint_address: int | None) -> int:
    try:
        device.set_configuration()
    except Exception:
        pass
    try:
        config = device.get_active_configuration()
    except Exception as exc:
        raise PrintError(f"Configurazione USB non accessibile: {exc}") from exc

    for interface in config:
        if getattr(interface, "bInterfaceClass", None) != 7:
            continue
        for endpoint in interface:
            address = endpoint.bEndpointAddress
            is_out = usb_util.endpoint_direction(address) == usb_util.ENDPOINT_OUT
            if is_out and (endpoint_address is None or address == endpoint_address):
                return address
    raise PrintError("Endpoint USB OUT non trovato")


def _send_usb_escpos(job: PrintJob, printer: Printer, order: Order) -> None:
    vendor_id, product_id, serial = _parse_usb_ref(printer.ip)
    data = _build_escpos_payload(job, order, printer)
    if _send_windows_usb_raw(data, vendor_id, product_id, serial):
        return

    usb_core, usb_util, backend = _usb_modules()
    endpoint_address = printer.port if printer.port > 0 else None
    try:
        candidates = list(usb_core.find(find_all=True, idVendor=vendor_id, idProduct=product_id, backend=backend))
    except Exception as exc:
        raise PrintError(f"Ricerca USB fallita: {exc}") from exc
    device = next((candidate for candidate in candidates if _matching_usb_device(candidate, usb_util, vendor_id, product_id, serial)), None)
    if device is None:
        raise PrintError(f"Stampante USB non trovata: {printer.ip}")
    endpoint = _find_usb_out_endpoint(device, usb_util, endpoint_address)
    try:
        device.write(endpoint, data, timeout=5000)
    except Exception as exc:
        raise PrintError(f"Invio USB fallito: {exc}") from exc
    finally:
        try:
            usb_util.dispose_resources(device)
        except Exception:
            pass


def _dispatch(job: PrintJob, order: Order, printer: Printer) -> None:
    if not printer.enabled:
        raise PrintError("Stampante disabilitata")
    if printer.type == "fake":
        _write_fake(job, order, printer)
        return
    if printer.type == "network_escpos":
        _send_network_escpos(job, printer, order)
        return
    if printer.type == "usb_escpos":
        _send_usb_escpos(job, printer, order)
        return
    raise PrintError(f"Tipo stampante non supportato: {printer.type}")


def _dispatch_with_retries(job: PrintJob, order: Order, printer: Printer) -> None:
    if printer.type != "network_escpos":
        _dispatch(job, order, printer)
        return

    attempts = len(NETWORK_RETRY_DELAYS_SECONDS) + 1
    last_error: NetworkPrintError | None = None
    for attempt in range(attempts):
        try:
            _dispatch(job, order, printer)
            return
        except NetworkPrintError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(NETWORK_RETRY_DELAYS_SECONDS[attempt])
    raise PrintError(f"Connessione stampante fallita dopo {attempts} tentativi: {last_error}") from last_error


def _save_and_attempt(db: Session, order: Order, printer: Printer, job_type: str, payload_text: str) -> PrintJob:
    job = PrintJob(order_id=order.id, printer_id=printer.id, job_type=job_type, status="pending", payload_text=payload_text)
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        _dispatch_with_retries(job, order, printer)
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


def retry_failed_print_jobs(db: Session, order_id: int) -> PrintResult:
    order = load_order_for_printing(db, order_id)
    failed_jobs = [job for job in order.print_jobs if job.status == "failed"]
    jobs: list[PrintJob] = []
    warnings: list[str] = []

    if not failed_jobs:
        return PrintResult(jobs=[], warnings=["Nessuna stampa fallita da ritentare"])

    for failed_job in failed_jobs:
        printer = db.get(Printer, failed_job.printer_id) if failed_job.printer_id is not None else None
        if printer is None:
            warnings.append(f"Stampante non disponibile per job #{failed_job.id}")
            continue

        retry_job = _save_and_attempt(db, order, printer, failed_job.job_type, failed_job.payload_text)
        jobs.append(retry_job)
        failed_job.status = "retried"
        failed_job.error_message = f"Ritentata con job #{retry_job.id}"
        db.commit()

        if retry_job.status == "failed":
            warnings.append(
                f"Ristampa {retry_job.job_type} fallita su {retry_job.printer.name if retry_job.printer else 'N/D'}: "
                f"{retry_job.error_message}"
            )

    return PrintResult(jobs=jobs, warnings=warnings)


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
    customer_printer_id: int | None = None,
) -> PrintResult:
    order = load_order_for_printing(db, order_id)
    jobs: list[PrintJob] = []
    warnings: list[str] = []

    if include_customer:
        customer_printer = None
        if customer_printer_id is not None:
            assigned_printer = db.get(Printer, customer_printer_id)
            if assigned_printer is not None and assigned_printer.enabled and assigned_printer.is_customer_printer:
                customer_printer = assigned_printer
            else:
                warnings.append("Stampante cliente assegnata non disponibile; uso la predefinita")
        customer_printer = customer_printer or db.scalar(
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
