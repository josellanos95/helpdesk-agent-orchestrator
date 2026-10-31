"""The test harness protects development data. These tests protect the protection."""

import pytest

import tests.conftest as harness
from app.config import Settings


def with_settings(monkeypatch, **overrides):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(_env_file=None, **overrides))


def test_the_guard_refuses_a_development_database(monkeypatch):
    with_settings(
        monkeypatch, DATABASE_URL="postgresql+asyncpg://u:p@localhost/helpdesk", redis_url="redis://x/15"
    )
    with pytest.raises(pytest.exit.Exception, match="never see a development database"):
        harness._assert_pointing_at_test_services()


def test_the_guard_refuses_a_non_test_redis_database(monkeypatch):
    with_settings(
        monkeypatch, DATABASE_URL="postgresql+asyncpg://u:p@localhost/helpdesk_test", redis_url="redis://x/0"
    )
    with pytest.raises(pytest.exit.Exception):
        harness._assert_pointing_at_test_services()


def test_the_guard_accepts_the_test_services(monkeypatch):
    with_settings(
        monkeypatch, DATABASE_URL="postgresql+asyncpg://u:p@localhost/helpdesk_test", redis_url="redis://x/15"
    )
    harness._assert_pointing_at_test_services()


def test_the_derived_database_name_is_always_a_test_database(monkeypatch):
    for configured in ("helpdesk", "helpdesk_test", "postgresql://u:p@h/anything"):
        monkeypatch.setenv(
            "DATABASE_URL", configured if "://" in configured else f"postgresql://u:p@h/{configured}"
        )
        assert harness._test_database_url().rsplit("/", 1)[-1].endswith("_test")
