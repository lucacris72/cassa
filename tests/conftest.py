from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture()
def test_env(tmp_path, monkeypatch) -> Generator[dict[str, str], None, None]:
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    print_output_dir = tmp_path / "print_output"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("PRINT_OUTPUT_DIR", str(print_output_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BUSINESS_DAY_RESET_HOUR", "4")

    from restaurant_pos.app.config import get_settings
    from restaurant_pos.app.database import Base, configure_database_for_tests, get_engine, get_session_factory, init_db
    from restaurant_pos.app.seed import seed_initial_data

    get_settings.cache_clear()
    configure_database_for_tests(database_url)
    init_db()
    Base.metadata.create_all(bind=get_engine())
    with get_session_factory()() as db:
        seed_initial_data(db)

    yield {"database_url": database_url, "print_output_dir": str(print_output_dir)}

    get_settings.cache_clear()


@pytest.fixture()
def db_session(test_env) -> Generator[Session, None, None]:
    from restaurant_pos.app.database import get_session_factory

    with get_session_factory()() as db:
        yield db


@pytest.fixture()
def client(test_env) -> Generator[TestClient, None, None]:
    from restaurant_pos.app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_client(client: TestClient) -> TestClient:
    response = client.post("/login", data={"pin": "1234"}, follow_redirects=False)
    assert response.status_code == 303
    return client


@pytest.fixture()
def cashier_client(client: TestClient) -> TestClient:
    response = client.post("/login", data={"pin": "1111"}, follow_redirects=False)
    assert response.status_code == 303
    return client
