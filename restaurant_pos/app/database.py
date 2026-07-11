from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory: sessionmaker[Session] | None = None


def _connect_args(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            connect_args=_connect_args(settings.database_url),
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
            future=True,
        )
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())
    run_sqlite_migrations()


def _table_columns(conn, table_name: str) -> list[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    return [str(row["name"]) for row in rows]


def _unique_index_columns(conn, table_name: str) -> list[list[str]]:
    unique_indexes: list[list[str]] = []
    indexes = conn.execute(text(f"PRAGMA index_list({table_name})")).mappings().all()
    for index in indexes:
        if not index["unique"]:
            continue
        index_name = index["name"]
        columns = conn.execute(text(f"PRAGMA index_info({index_name})")).mappings().all()
        unique_indexes.append([str(column["name"]) for column in columns])
    return unique_indexes


def _table_exists(conn, table_name: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :name"),
            {"name": table_name},
        ).first()
    )


def _rebuild_orders_table(conn) -> None:
    columns = _table_columns(conn, "orders")
    session_expr = "COALESCE(register_session, 1)" if "register_session" in columns else "1"
    pickup_later_expr = "COALESCE(pickup_later, 0)" if "pickup_later" in columns else "0"
    conn.execute(text("DROP TABLE IF EXISTS orders_new"))
    conn.execute(
        text(
            """
            CREATE TABLE orders_new (
              id INTEGER NOT NULL,
              order_number INTEGER,
              business_date VARCHAR(10) NOT NULL,
              register_session INTEGER NOT NULL DEFAULT 1,
              status VARCHAR(40) NOT NULL,
              total_cents INTEGER NOT NULL,
              source VARCHAR(40) NOT NULL,
              notes TEXT,
              pickup_later BOOLEAN NOT NULL DEFAULT 0,
              created_at DATETIME NOT NULL,
              paid_at DATETIME,
              completed_at DATETIME,
              PRIMARY KEY (id),
              CONSTRAINT uq_order_business_session_number UNIQUE (business_date, register_session, order_number)
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            INSERT INTO orders_new (
              id, order_number, business_date, register_session, status, total_cents,
              source, notes, pickup_later, created_at, paid_at, completed_at
            )
            SELECT
              id, order_number, business_date, {session_expr}, status, total_cents,
              source, notes, {pickup_later_expr}, created_at, paid_at, completed_at
            FROM orders
            """
        )
    )
    conn.execute(text("DROP TABLE orders"))
    conn.execute(text("ALTER TABLE orders_new RENAME TO orders"))


def _rebuild_register_closures_table(conn) -> None:
    columns = _table_columns(conn, "register_closures")
    session_expr = "COALESCE(register_session, 1)" if "register_session" in columns else "1"
    conn.execute(text("DROP TABLE IF EXISTS register_closures_new"))
    conn.execute(
        text(
            """
            CREATE TABLE register_closures_new (
              id INTEGER NOT NULL,
              business_date VARCHAR(10) NOT NULL,
              register_session INTEGER NOT NULL DEFAULT 1,
              closed_at DATETIME NOT NULL,
              closed_by_user_id INTEGER,
              order_count INTEGER NOT NULL,
              sales_total_cents INTEGER NOT NULL,
              cash_total_cents INTEGER NOT NULL,
              cancelled_count INTEGER NOT NULL,
              notes TEXT,
              PRIMARY KEY (id),
              CONSTRAINT uq_register_closure_business_session UNIQUE (business_date, register_session),
              FOREIGN KEY(closed_by_user_id) REFERENCES users (id)
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            INSERT INTO register_closures_new (
              id, business_date, register_session, closed_at, closed_by_user_id,
              order_count, sales_total_cents, cash_total_cents, cancelled_count, notes
            )
            SELECT
              id, business_date, {session_expr}, closed_at, closed_by_user_id,
              order_count, sales_total_cents, cash_total_cents, cancelled_count, notes
            FROM register_closures
            """
        )
    )
    conn.execute(text("DROP TABLE register_closures"))
    conn.execute(text("ALTER TABLE register_closures_new RENAME TO register_closures"))


def run_sqlite_migrations() -> None:
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        if _table_exists(conn, "orders"):
            order_columns = _table_columns(conn, "orders")
            order_unique_indexes = _unique_index_columns(conn, "orders")
            if "register_session" not in order_columns or ["business_date", "order_number"] in order_unique_indexes:
                _rebuild_orders_table(conn)
                order_columns = _table_columns(conn, "orders")
            if "pickup_later" not in order_columns:
                conn.execute(text("ALTER TABLE orders ADD COLUMN pickup_later BOOLEAN NOT NULL DEFAULT 0"))
        if _table_exists(conn, "register_closures"):
            closure_columns = _table_columns(conn, "register_closures")
            closure_unique_indexes = _unique_index_columns(conn, "register_closures")
            if "register_session" not in closure_columns or ["business_date"] in closure_unique_indexes:
                _rebuild_register_closures_table(conn)
        if _table_exists(conn, "categories"):
            category_columns = _table_columns(conn, "categories")
            if "show_in_cashier" not in category_columns:
                conn.execute(text("ALTER TABLE categories ADD COLUMN show_in_cashier BOOLEAN NOT NULL DEFAULT 1"))
        if _table_exists(conn, "printers"):
            printer_columns = _table_columns(conn, "printers")
            if "partial_cut" not in printer_columns:
                conn.execute(text("ALTER TABLE printers ADD COLUMN partial_cut BOOLEAN NOT NULL DEFAULT 0"))
        if _table_exists(conn, "users"):
            user_columns = _table_columns(conn, "users")
            if "customer_printer_id" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN customer_printer_id INTEGER REFERENCES printers(id)"))
        if _table_exists(conn, "product_import_aliases") and _table_exists(conn, "reservation_items"):
            conn.execute(
                text(
                    """
                    INSERT OR IGNORE INTO product_import_aliases (
                      source_name, product_id, source_price_cents, created_at, updated_at
                    )
                    SELECT DISTINCT
                      ri.product_name,
                      ri.product_id,
                      ri.unit_price_cents,
                      CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP
                    FROM reservation_items ri
                    JOIN products p ON p.id = ri.product_id
                    WHERE ri.product_id IS NOT NULL
                      AND ri.product_name IS NOT NULL
                      AND TRIM(ri.product_name) != ''
                    """
                )
            )
        if (
            _table_exists(conn, "register_closure_products")
            and _table_exists(conn, "register_closures")
            and _table_exists(conn, "orders")
            and _table_exists(conn, "order_items")
        ):
            conn.execute(
                text(
                    """
                    INSERT OR IGNORE INTO register_closure_products (
                      closure_id, category_name, product_name, quantity, sales_total_cents
                    )
                    SELECT
                      closure.id,
                      item.category_name,
                      item.product_name,
                      SUM(item.quantity),
                      SUM(item.line_total_cents)
                    FROM register_closures closure
                    JOIN orders orders_in_closure
                      ON orders_in_closure.business_date = closure.business_date
                     AND orders_in_closure.register_session = closure.register_session
                    JOIN order_items item ON item.order_id = orders_in_closure.id
                    WHERE orders_in_closure.status IN ('confirmed', 'paid', 'delivered')
                      AND NOT EXISTS (
                        SELECT 1
                        FROM register_closure_products existing
                        WHERE existing.closure_id = closure.id
                      )
                    GROUP BY closure.id, item.category_name, item.product_name
                    """
                )
            )
        conn.execute(text("PRAGMA foreign_keys=ON"))


def configure_database_for_tests(database_url: str) -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(
        database_url,
        connect_args=_connect_args(database_url),
        future=True,
    )
    _session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=_engine,
        future=True,
    )
