import pytest
from pydantic import ValidationError

from app.config import Settings


def make(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_development_defaults_to_header_mode_with_a_throwaway_secret():
    settings = make()
    assert settings.auth_mode == "header"
    assert len(settings.demo_token_secret) >= 32
    assert make().demo_token_secret != settings.demo_token_secret  # not a constant anyone could know


def test_signed_mode_needs_a_secret():
    with pytest.raises(ValidationError, match="DEMO_TOKEN_SECRET"):
        make(auth_mode="signed")


def test_production_refuses_to_start_without_signed_auth():
    with pytest.raises(ValidationError, match="AUTH_MODE"):
        make(environment="production", demo_token_secret="x" * 40)


def test_production_refuses_a_short_secret():
    with pytest.raises(ValidationError, match="32"):
        make(environment="production", auth_mode="signed", demo_token_secret="short")


def test_production_with_signed_auth_and_a_long_secret_is_fine():
    settings = make(environment="production", auth_mode="signed", demo_token_secret="x" * 40)
    assert settings.auth_mode == "signed"
