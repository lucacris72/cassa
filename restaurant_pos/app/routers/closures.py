from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import add_flash, pop_flashes, require_user
from ..database import get_db
from ..models import Order, RegisterClosure, User
from ..services.closures import ClosureError, build_closure_excel, close_register, get_sales_summary
from ..services.numbering import business_date_for, current_register_session
from ..templating import render


router = APIRouter(prefix="/closures", tags=["closures"])


@router.get("", response_class=HTMLResponse)
def closures_page(
    request: Request,
    date: str | None = Query(None),
    session: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    selected_date = date or business_date_for()
    selected_session = session or current_register_session(db, selected_date)
    closures = db.scalars(
        select(RegisterClosure).order_by(RegisterClosure.business_date.desc(), RegisterClosure.register_session.desc())
    ).all()
    summary = get_sales_summary(db, selected_date, selected_session)
    return render(
        request,
        "closures.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "selected_date": selected_date,
            "selected_session": selected_session,
            "summary": summary,
            "closures": closures,
        },
    )


@router.post("")
def close_register_route(
    request: Request,
    business_date: str = Form(...),
    register_session: int = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    try:
        closure = close_register(db, business_date, user, notes.strip() or None, register_session=register_session)
    except ClosureError as exc:
        add_flash(request, str(exc), "error")
        return RedirectResponse(f"/closures?date={business_date}&session={register_session}", status_code=303)
    add_flash(request, "Chiusura cassa registrata", "success")
    return RedirectResponse(f"/closures/{closure.id}", status_code=303)


@router.get("/{closure_id}", response_class=HTMLResponse)
def closure_detail(
    closure_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    closure = db.scalar(
        select(RegisterClosure)
        .where(RegisterClosure.id == closure_id)
        .options(selectinload(RegisterClosure.product_summaries), selectinload(RegisterClosure.closed_by))
    )
    if closure is None:
        add_flash(request, "Chiusura non trovata", "error")
        return RedirectResponse("/closures", status_code=303)
    orders = db.scalars(
        select(Order)
        .where(Order.business_date == closure.business_date, Order.register_session == closure.register_session)
        .order_by(Order.order_number, Order.created_at)
        .options(selectinload(Order.items))
    ).all()
    return render(
        request,
        "closure_detail.html",
        {
            "user": user,
            "flashes": pop_flashes(request),
            "closure": closure,
            "orders": orders,
            "product_summaries": closure.product_summaries,
            "product_quantity": sum(product.quantity for product in closure.product_summaries),
        },
    )


@router.get("/{closure_id}/export.xlsx")
def export_closure_excel(
    closure_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user("admin", "cashier")),
):
    closure = db.scalar(
        select(RegisterClosure)
        .where(RegisterClosure.id == closure_id)
        .options(selectinload(RegisterClosure.product_summaries))
    )
    if closure is None:
        return RedirectResponse("/closures", status_code=303)
    filename = f"chiusura-{closure.business_date}-T{closure.register_session}.xlsx"
    return Response(
        content=build_closure_excel(closure, closure.product_summaries),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
