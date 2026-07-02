from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

PIN_ITERATIONS = 260_000


def hash_pin(pin: str, salt: str | None = None) -> str:
    if not pin or not pin.isdigit():
        raise ValueError("Il PIN deve contenere solo cifre")
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("ascii"), PIN_ITERATIONS)
    return f"pbkdf2_sha256${PIN_ITERATIONS}${salt}${digest.hex()}"


def verify_pin(pin: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations_text),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected_hex)


def authenticate_by_pin(db: Session, pin: str) -> User | None:
    users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.id)).all()
    for user in users:
        if verify_pin(pin, user.pin_hash):
            return user
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, int(user_id))


def require_user(*roles: str) -> Callable:
    allowed = set(roles)

    def dependency(user: User | None = Depends(get_current_user)) -> User:
        if user is None or not user.active:
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        if allowed and user.role not in allowed:
            raise HTTPException(status_code=403, detail="Permesso negato")
        return user

    return dependency


def add_flash(request: Request, message: str, category: str = "info") -> None:
    flashes = list(request.session.get("flashes", []))
    flashes.append({"message": message, "category": category})
    request.session["flashes"] = flashes


def pop_flashes(request: Request) -> list[dict[str, str]]:
    flashes = list(request.session.get("flashes", []))
    request.session["flashes"] = []
    return flashes
