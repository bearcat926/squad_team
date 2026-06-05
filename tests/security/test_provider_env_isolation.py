"""Tests for provider environment isolation."""

from __future__ import annotations

from squad_runtime.env_isolation import BASE_ALLOWED_ENV, ProviderConfig, build_provider_env


def test_aws_secret_not_passed_through():
    config = ProviderConfig(name="test")
    host_env = {"AWS_SECRET_ACCESS_KEY": "secret", "PATH": "/usr/bin"}

    result = build_provider_env(config, host_env)

    assert "AWS_SECRET_ACCESS_KEY" not in result
    assert "PATH" in result


def test_database_url_not_passed_through():
    config = ProviderConfig(name="test")
    host_env = {"DATABASE_URL": "postgres://...", "PATH": "/usr/bin"}

    result = build_provider_env(config, host_env)

    assert "DATABASE_URL" not in result


def test_path_always_passed_through():
    config = ProviderConfig(name="test")
    host_env = {"PATH": "/usr/bin:/usr/local/bin"}

    result = build_provider_env(config, host_env)

    assert result["PATH"] == "/usr/bin:/usr/local/bin"


def test_squad_vars_passed_through():
    config = ProviderConfig(name="test")
    host_env = {"SQUAD_DISPATCH_DIR": "/tmp/dispatch", "SQUAD_RUNTIME_HOME": "/opt/squad"}

    result = build_provider_env(config, host_env)

    assert result["SQUAD_DISPATCH_DIR"] == "/tmp/dispatch"
    assert result["SQUAD_RUNTIME_HOME"] == "/opt/squad"


def test_provider_declared_key_passed_through():
    config = ProviderConfig(name="claude", required_env=["ANTHROPIC_API_KEY"])
    host_env = {"ANTHROPIC_API_KEY": "sk-abc123", "PATH": "/usr/bin"}

    result = build_provider_env(config, host_env)

    assert result["ANTHROPIC_API_KEY"] == "sk-abc123"


def test_undeclared_key_not_passed_through():
    config = ProviderConfig(name="test", required_env=[])
    host_env = {"OPENAI_API_KEY": "sk-xyz789", "PATH": "/usr/bin"}

    result = build_provider_env(config, host_env)

    assert "OPENAI_API_KEY" not in result


def test_blocked_prefixes_filtered():
    config = ProviderConfig(name="test")
    host_env = {
        "AWS_ACCESS_KEY_ID": "AKIA...",
        "AZURE_CLIENT_SECRET": "secret",
        "GCP_PROJECT": "my-project",
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/creds",
        "DATABASE_URL": "postgres://...",
        "POSTGRES_PASSWORD": "pw",
        "MYSQL_ROOT_PASSWORD": "root",
        "SECRET_KEY": "django-secret",
        "TOKEN_ISSUER": "issuer",
        "PATH": "/usr/bin",
    }

    result = build_provider_env(config, host_env)

    for key in host_env:
        if key == "PATH":
            assert key in result
        else:
            assert key not in result, f"{key} should have been filtered"


def test_base_allowed_env_preserved():
    config = ProviderConfig(name="test")
    host_env = {k: "val" for k in BASE_ALLOWED_ENV}

    result = build_provider_env(config, host_env)

    for key in BASE_ALLOWED_ENV:
        assert key in result, f"{key} should be in allowed base env"
