"""Token verification and the role/scope model (ADR-0010).

- ``LocalJwtVerifier``: HS256 dev tokens from ``scripts/issue_dev_token.py``.
  The fail-closed settings validator forbids this provider in hardened
  environments — that check already exists and is tested (Phase 1).
- ``EntraIdVerifier``: RS256 via OIDC/JWKS for cloud deployments. Written
  to the same interface; requires tenant configuration and network access,
  so it is **unexecuted locally** (exercised in Phase 7's cloud phase).

Roles map to scopes here in exactly one place; routes declare required
scopes and are deny-by-default (no scope claim → no access). Authorization
decisions are logged as identity + route + decision, never token contents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import jwt

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "platform-admin": frozenset(
        {
            "predictions:read",
            "predictions:write",
            "feedback:write",
            "models:read",
            "monitoring:read",
            "data-quality:read",
            "recommendations:approve",
            "audit:read",
        }
    ),
    "ml-engineer": frozenset(
        {
            "predictions:read",
            "predictions:write",
            "models:read",
            "monitoring:read",
            "data-quality:read",
        }
    ),
    "data-steward": frozenset({"data-quality:read", "feedback:write", "monitoring:read"}),
    "quality-engineer": frozenset(
        {
            "predictions:read",
            "predictions:write",
            "feedback:write",
            "recommendations:approve",
            "monitoring:read",
            "data-quality:read",
        }
    ),
    "plant-viewer": frozenset({"predictions:read", "monitoring:read"}),
    "auditor": frozenset({"audit:read", "monitoring:read", "models:read"}),
    "service": frozenset({"predictions:write", "feedback:write"}),
}


def scopes_for_roles(roles: list[str]) -> frozenset[str]:
    scopes: set[str] = set()
    for role in roles:
        scopes |= ROLE_SCOPES.get(role, frozenset())  # unknown roles grant nothing
    return frozenset(scopes)


class AuthenticationError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: tuple[str, ...]
    scopes: frozenset[str] = field(default_factory=frozenset)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Principal: ...


class LocalJwtVerifier:
    """HS256 dev verifier (forbidden in hardened envs by settings)."""

    def __init__(self, secret: str, issuer: str, audience: str) -> None:
        if not secret:
            raise ValueError("local JWT secret is empty — set FG_AUTH__LOCAL_JWT_SECRET")
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],  # pinned; 'none'/RS-swap attacks rejected
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
                leeway=30,
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(str(exc)) from exc
        roles = [str(r) for r in claims.get("roles", [])]
        return Principal(
            subject=str(claims["sub"]),
            roles=tuple(roles),
            scopes=scopes_for_roles(roles),
        )


class EntraIdVerifier:
    """RS256 verification against the tenant's JWKS (cloud, Phase 7).

    Structurally identical to the dev verifier: same claims → roles →
    scopes mapping, so the same authorization tests apply. Unexecuted in
    the local environment (no tenant, no network) — see ADR-0010.
    """

    def __init__(self, tenant_id: str, audience: str) -> None:
        self._audience = audience
        self._issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self._jwks = jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )

    def verify(self, token: str) -> Principal:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
                leeway=30,
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(str(exc)) from exc
        roles = [str(r) for r in claims.get("roles", [])]
        return Principal(
            subject=str(claims["sub"]), roles=tuple(roles), scopes=scopes_for_roles(roles)
        )


def build_verifier(provider: str, *, secret: str, issuer: str, audience: str) -> TokenVerifier:
    if provider == "local-jwt":
        return LocalJwtVerifier(secret, issuer, audience)
    if provider == "entra-id":
        # issuer field carries the tenant id for this provider
        return EntraIdVerifier(tenant_id=issuer, audience=audience)
    raise ValueError(f"unknown auth provider: {provider}")
