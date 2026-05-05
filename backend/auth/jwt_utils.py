"""JWT helpers — issue / decode session tokens."""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt  # PyJWT

JWT_SECRET    = os.environ.get("JWT_SECRET", "dev-only-please-change-in-prod")
JWT_ALGORITHM = "HS256"
SESSION_COOKIE = "hr_session"
SESSION_DAYS   = 7


def issue_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=SESSION_DAYS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def cookie_kwargs() -> dict:
    """kwargs comuni per Response.set_cookie."""
    return {
        "key":       SESSION_COOKIE,
        "httponly":  True,
        "secure":    os.environ.get("COOKIE_INSECURE") != "1",  # True in prod, False solo se esplicito
        "samesite":  "lax",
        "max_age":   SESSION_DAYS * 24 * 3600,
        "path":      "/",
    }
