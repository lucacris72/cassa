from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings, resolve_project_path
from .database import get_session_factory, init_db
from .routers import auth, cashier, categories, closures, mobile, orders, printers, products
from .seed import seed_initial_data


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolve_project_path(settings.print_output_dir).mkdir(parents=True, exist_ok=True)
        resolve_project_path(Path("data")).mkdir(parents=True, exist_ok=True)
        init_db()
        with get_session_factory()() as db:
            seed_initial_data(db)
        yield

    app = FastAPI(title="Cassa Ristorante Locale", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")

    static_dir = resolve_project_path(Path("restaurant_pos/app/static"))
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(auth.router)
    app.include_router(cashier.router)
    app.include_router(products.router)
    app.include_router(categories.router)
    app.include_router(printers.router)
    app.include_router(orders.router)
    app.include_router(closures.router)
    app.include_router(mobile.router)

    return app


app = create_app()
