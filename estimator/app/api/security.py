"""API-key authentication for the Session 9 routers + the Session 15 service token.

Two independent keys protect the two Session 9 routers: a ``RETRIEVAL_API_KEY``
holder cannot call the estimate endpoint and vice versa. Keys are compared with
``secrets.compare_digest`` (constant-time) — never ``==``, which leaks length
and prefix information through timing.

Session 15 adds ``require_service_token``: in the containerized deploy the
estimator is unreachable from the host, but anything else on the compose
network could still call it, so ``POST /api/v1/estimate`` (the endpoint the
business backend actually drives) is gated by a shared ``AI_SERVICE_TOKEN``.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings

_API_KEY_HEADER = "X-API-Key"
_SERVICE_TOKEN_HEADER = "X-Service-Token"


def _verify(provided: str | None, expected: str | None, *, header: str = _API_KEY_HEADER) -> None:
    """Raise 401 unless ``provided`` matches the configured ``expected`` key."""
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": header},
        )


async def require_retrieval_key(
    x_api_key: str | None = Header(default=None, alias=_API_KEY_HEADER),
) -> None:
    """FastAPI dependency guarding ``POST /v1/retrieval/search``."""
    _verify(x_api_key, get_settings().RETRIEVAL_API_KEY)


async def require_estimate_key(
    x_api_key: str | None = Header(default=None, alias=_API_KEY_HEADER),
) -> None:
    """FastAPI dependency guarding ``POST /v1/estimate/from-transcript``."""
    _verify(x_api_key, get_settings().ESTIMATE_API_KEY)


async def require_service_token(
    x_service_token: str | None = Header(default=None, alias=_SERVICE_TOKEN_HEADER),
) -> None:
    """FastAPI dependency guarding ``POST /api/v1/estimate`` (Session 15)."""
    _verify(x_service_token, get_settings().AI_SERVICE_TOKEN, header=_SERVICE_TOKEN_HEADER)
