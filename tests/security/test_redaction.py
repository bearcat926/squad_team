"""Tests for sensitive data redaction."""

from __future__ import annotations

from squad_runtime.security.redaction import redact_dict, redact_text


def test_redact_sk_token():
    text = "Using key sk-abc1234567890123456789012 for API"
    result = redact_text(text)

    assert "sk-abc1234567890123456789012" not in result
    assert "***REDACTED***" in result


def test_redact_aws_key():
    text = "Access key AKIAIOSFODNN7EXAMPLE found"
    result = redact_text(text)

    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert "***REDACTED***" in result


def test_redact_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = redact_text(text)

    assert "Bearer" not in result or "***REDACTED***" in result


def test_redact_github_token():
    text = "Using ghp_abcdefghijklmnopqrstuvwxyz123456 for push"
    result = redact_text(text)

    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in result
    assert "***REDACTED***" in result


def test_redact_dict_sensitive_keys():
    data = {
        "token": "secret-value",
        "password": "hunter2",
        "api_key": "sk-1234",
        "normal_field": "keep this",
    }

    result = redact_dict(data)

    assert result["token"] == "***REDACTED***"
    assert result["password"] == "***REDACTED***"
    assert result["api_key"] == "***REDACTED***"
    assert result["normal_field"] == "keep this"


def test_redact_dict_nested():
    data = {
        "config": {
            "authorization": "Bearer my-token-value",
            "name": "safe",
        }
    }

    result = redact_dict(data)
    nested = result["config"]

    assert isinstance(nested, dict)
    assert nested["authorization"] == "***REDACTED***"
    assert nested["name"] == "safe"


def test_redact_text_no_false_positive():
    text = "The quick brown fox jumps over the lazy dog"
    result = redact_text(text)

    assert result == text


def test_redact_dict_preserves_non_string_values():
    data = {"count": 42, "active": True, "name": "test"}

    result = redact_dict(data)

    assert result["count"] == 42
    assert result["active"] is True
    assert result["name"] == "test"
