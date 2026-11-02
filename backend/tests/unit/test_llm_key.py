"""BUG-040: the Claude key in the repo's .env must reach the worker, like every other setting there."""

from pathlib import Path

import pytest

from konboro.pipeline.worker import providers_for
from konboro.settings import Settings
from konboro_llm.providers import FakeProvider
from konboro_llm.providers.anthropic_provider import AnthropicProvider

KEY = "sk-ant-test-key-not-real"


@pytest.fixture(autouse=True)
def no_exported_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("KONBORO_ANTHROPIC_API_KEY", raising=False)


def env_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text)
    return path


def test_the_key_in_dotenv_gives_the_worker_real_claude(tmp_path: Path) -> None:
    settings = Settings(_env_file=env_file(tmp_path, f"ANTHROPIC_API_KEY={KEY}\n"))  # type: ignore[call-arg]
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == KEY
    assert isinstance(providers_for(settings)["anthropic"], AnthropicProvider)


def test_an_exported_key_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    settings = Settings(_env_file=env_file(tmp_path, ""))  # type: ignore[call-arg]
    assert isinstance(providers_for(settings)["anthropic"], AnthropicProvider)


def test_without_a_key_a_local_worker_uses_the_stand_in(tmp_path: Path) -> None:
    settings = Settings(_env_file=env_file(tmp_path, ""))  # type: ignore[call-arg]
    assert isinstance(providers_for(settings)["anthropic"], FakeProvider)


def test_without_a_key_a_production_worker_has_no_model(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=env_file(tmp_path, ""), env="production", dev_login_enabled=False
    )
    assert providers_for(settings) == {}


def test_the_key_never_shows_in_the_settings_repr(tmp_path: Path) -> None:
    settings = Settings(_env_file=env_file(tmp_path, f"ANTHROPIC_API_KEY={KEY}\n"))  # type: ignore[call-arg]
    assert KEY not in repr(settings)
