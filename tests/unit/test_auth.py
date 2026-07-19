"""Local JWT verifier + role/scope model (ADR-0010)."""

import time

import jwt
import pytest

from factoryguard.auth import (
    AuthenticationError,
    LocalJwtVerifier,
    build_verifier,
    scopes_for_roles,
)

SECRET = "unit-test-secret"
ISSUER = "factoryguard-local"
AUDIENCE = "factoryguard-api"


def _token(secret: str = SECRET, ttl: int = 600, **overrides: object) -> str:
    now = int(time.time())
    claims = {
        "sub": "tester",
        "roles": ["quality-engineer"],
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + ttl,
        **overrides,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture
def verifier() -> LocalJwtVerifier:
    return LocalJwtVerifier(SECRET, ISSUER, AUDIENCE)


def test_valid_token_maps_roles_to_scopes(verifier: LocalJwtVerifier) -> None:
    principal = verifier.verify(_token())
    assert principal.subject == "tester"
    assert principal.has_scope("recommendations:approve")
    assert principal.has_scope("predictions:write")
    assert not principal.has_scope("audit:read")  # deny by default


def test_expired_token_rejected(verifier: LocalJwtVerifier) -> None:
    with pytest.raises(AuthenticationError, match="expired"):
        verifier.verify(_token(ttl=-120))


def test_wrong_secret_rejected(verifier: LocalJwtVerifier) -> None:
    with pytest.raises(AuthenticationError):
        verifier.verify(_token(secret="other-secret"))


def test_wrong_audience_and_issuer_rejected(verifier: LocalJwtVerifier) -> None:
    with pytest.raises(AuthenticationError):
        verifier.verify(_token(aud="another-api"))
    with pytest.raises(AuthenticationError):
        verifier.verify(_token(iss="rogue-issuer"))


def test_missing_required_claims_rejected(verifier: LocalJwtVerifier) -> None:
    now = int(time.time())
    no_sub = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "exp": now + 600}, SECRET, algorithm="HS256"
    )
    with pytest.raises(AuthenticationError):
        verifier.verify(no_sub)


def test_alg_none_rejected(verifier: LocalJwtVerifier) -> None:
    forged = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 600},
        key="",
        algorithm="none",
    )
    with pytest.raises(AuthenticationError):
        verifier.verify(forged)


def test_unknown_roles_grant_nothing() -> None:
    assert scopes_for_roles(["made-up-role"]) == frozenset()
    assert scopes_for_roles([]) == frozenset()


def test_empty_secret_refused() -> None:
    with pytest.raises(ValueError, match="secret"):
        LocalJwtVerifier("", ISSUER, AUDIENCE)


def test_build_verifier_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown auth provider"):
        build_verifier("api-key", secret="s", issuer="i", audience="a")
