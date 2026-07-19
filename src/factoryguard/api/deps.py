"""Auth dependencies: bearer-token verification + deny-by-default scopes.

Every route except ``/health/*`` and ``/version`` declares a required
scope via :func:`require`. Authorization decisions are logged as identity
+ route + decision — token contents never appear in logs (ADR-0010).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from factoryguard.auth import AuthenticationError, Principal, TokenVerifier

log = logging.getLogger("factoryguard.api.auth")


def get_verifier(request: Request) -> TokenVerifier:
    verifier: TokenVerifier = request.app.state.verifier
    return verifier


def get_principal(request: Request, verifier: TokenVerifier = Depends(get_verifier)) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    try:
        principal = verifier.verify(token.strip())
    except AuthenticationError as exc:
        log.info("auth failed path=%s reason=%s", request.url.path, exc)
        raise HTTPException(401, "invalid token") from exc
    request.state.principal = principal
    return principal


def require(scope: str) -> Callable[..., Principal]:
    def _check(request: Request, principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.has_scope(scope):
            log.info(
                "authz deny subject=%s path=%s scope=%s",
                principal.subject,
                request.url.path,
                scope,
            )
            raise HTTPException(403, f"missing scope: {scope}")
        log.debug(
            "authz allow subject=%s path=%s scope=%s",
            principal.subject,
            request.url.path,
            scope,
        )
        return principal

    return _check
