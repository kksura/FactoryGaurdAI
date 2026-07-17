from factoryguard.security.redaction import REDACTED, redact_any, redact_text


def test_key_based_redaction() -> None:
    payload = {
        "username": "op-1234",
        "password": "hunter2",
        "Api-Key": "abc123",
        "nested": {"connection_string": "Server=x;Password=y", "count": 3},
    }
    out = redact_any(payload)
    assert out["username"] == "op-1234"
    assert out["password"] == REDACTED
    assert out["Api-Key"] == REDACTED
    assert out["nested"]["connection_string"] == REDACTED
    assert out["nested"]["count"] == 3


def test_bearer_token_redacted_in_text() -> None:
    assert "Bearer" not in redact_text("header was Bearer abcdef123456789") or REDACTED in (
        redact_text("header was Bearer abcdef123456789")
    )


def test_jwt_redacted() -> None:
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )
    assert REDACTED in redact_text(f"token={jwt}")


def test_azure_account_key_redacted() -> None:
    text = "DefaultEndpointsProtocol=https;AccountKey=abcdefghijklmnopqrstuvwxyz0123456789==;x"
    assert "AccountKey=abcdefghijklmnop" not in redact_text(text)


def test_url_credentials_redacted() -> None:
    assert "s3cret" not in redact_text("postgresql://user:s3cret@db:5432/app")


def test_non_sensitive_text_unchanged() -> None:
    text = "unit UNIT-000123 predicted defect probability 0.83"
    assert redact_text(text) == text


def test_lists_and_scalars() -> None:
    assert redact_any([{"token": "x"}, 5, "plain"]) == [{"token": REDACTED}, 5, "plain"]
