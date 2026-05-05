"""FastAPI dependencies per autenticazione e paywall."""

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

from .jwt_utils import decode_token, SESSION_COOKIE
from .users_db import get_user_by_id, has_paid_access


class AuthRedirect(HTTPException):
    """Eccezione speciale che il middleware traduce in Redirect 303."""
    def __init__(self, location: str):
        super().__init__(status_code=303, detail=location)
        self.location = location


def _current_user_optional(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    return get_user_by_id(user_id)


def current_user(request: Request):
    """Optional auth — ritorna user dict o None."""
    return _current_user_optional(request)


def require_auth(request: Request):
    """Richiede auth. Se assente, redirect a /accedi."""
    user = _current_user_optional(request)
    if not user:
        raise AuthRedirect("/accedi?next=" + request.url.path)
    return user


def require_paid(request: Request):
    """Richiede auth + (founder OR subscription attiva/trial)."""
    user = _current_user_optional(request)
    if not user:
        raise AuthRedirect("/accedi?next=" + request.url.path)
    if not has_paid_access(user):
        raise AuthRedirect("/pricing?upgrade=1")
    return user
