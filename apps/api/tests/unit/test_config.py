from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsError

from app.core.config import API_ROOT, Settings


def test_defaults_are_safe_for_local_development() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.cors_allowed_origins == ["http://localhost:3000"]
    assert settings.database_url.get_secret_value() == (
        f"sqlite:///{(API_ROOT / 'var' / 'easa.db').as_posix()}"
    )


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASA_ENVIRONMENT", "production")
    monkeypatch.setenv("EASA_CORS_ALLOWED_ORIGINS", '["https://easa.example.com"]')

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.is_production
    assert settings.cors_allowed_origins == ["https://easa.example.com"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("EASA_ENVIRONMENT", "staging"),
        ("EASA_LOG_LEVEL", "verbose"),
        ("EASA_DATABASE_URL", "not a url"),
        ("EASA_DATABASE_URL", "mysql://user:pw@localhost/easa"),
        ("EASA_CORS_ALLOWED_ORIGINS", '["*"]'),
        ("EASA_CORS_ALLOWED_ORIGINS", '["https://*.example.com"]'),
        ("EASA_CORS_ALLOWED_ORIGINS", '["localhost:3000"]'),
        ("EASA_CORS_ALLOWED_ORIGINS", '["http://localhost:3000/app"]'),
    ],
)
def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
    monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_rejects_cors_origins_that_are_not_a_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASA_CORS_ALLOWED_ORIGINS", "http://localhost:3000")

    with pytest.raises(SettingsError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_rejects_unknown_keys_in_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EASA_LOG_LEVEL=INFO\nEASA_UNKNOWN_SETTING=1\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)  # type: ignore[call-arg]


def test_validation_errors_do_not_echo_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EASA_DATABASE_URL", "mysql://admin:sup3r-s3cret@db.internal/easa")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "sup3r-s3cret" not in str(exc_info.value)


def test_database_url_is_hidden_from_repr(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'x.db').as_posix()}"
    settings = Settings(_env_file=None, database_url=url)  # type: ignore[call-arg]

    assert url not in repr(settings)


def test_settings_are_immutable() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]
