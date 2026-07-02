from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from .utils import format_money


templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.filters["money"] = format_money


def render(request: Request, name: str, context: dict[str, object]) -> Response:
    context.setdefault("request", request)
    return templates.TemplateResponse(request, name, context)
