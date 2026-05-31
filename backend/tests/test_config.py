"""Tests for Settings / load_settings() env-var wiring (SRS F4.3)."""
from __future__ import annotations

import pytest

from paperhub.config import load_settings

# ---------------------------------------------------------------------------
# 10. External lookup services — unpaywall_email
# ---------------------------------------------------------------------------


def test_unpaywall_email_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PAPERHUB_UNPAYWALL_EMAIL is set to a non-empty string, the setting
    carries that exact value."""
    monkeypatch.setenv("PAPERHUB_UNPAYWALL_EMAIL", "ops@example.com")
    assert load_settings().unpaywall_email == "ops@example.com"


def test_unpaywall_email_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PAPERHUB_UNPAYWALL_EMAIL is absent from the environment, the
    setting is None (Unpaywall fallback is skipped)."""
    monkeypatch.delenv("PAPERHUB_UNPAYWALL_EMAIL", raising=False)
    assert load_settings().unpaywall_email is None


def test_unpaywall_email_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PAPERHUB_UNPAYWALL_EMAIL is set to an empty string (the common
    docker-compose / .env ``KEY=`` form), it is coerced to None so the
    dispatcher skips the call rather than sending an empty email param."""
    monkeypatch.setenv("PAPERHUB_UNPAYWALL_EMAIL", "")
    assert load_settings().unpaywall_email is None


# ---------------------------------------------------------------------------
# 11. Slide style profile — env-var wiring + legacy alias (F4.4 T8)
# ---------------------------------------------------------------------------


def test_slide_style_profile_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither env var set → the resolved profile name is ``"default"``
    (the new canonical name; the yaml registry ships it as the
    Final_Report gold methodology)."""
    monkeypatch.delenv("PAPERHUB_SLIDE_STYLE_PROFILE", raising=False)
    monkeypatch.delenv("PAPERHUB_SLIDE_THEME", raising=False)
    assert load_settings().slide_style_profile == "default"


def test_slide_style_profile_legacy_theme_gold_maps_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy ``PAPERHUB_SLIDE_THEME=gold`` env var (operators may
    still have it set in .env files / docker-compose) maps to the new
    canonical profile name ``"default"``."""
    monkeypatch.delenv("PAPERHUB_SLIDE_STYLE_PROFILE", raising=False)
    monkeypatch.setenv("PAPERHUB_SLIDE_THEME", "gold")
    assert load_settings().slide_style_profile == "default"


def test_slide_style_profile_legacy_theme_metropolis_maps_to_metropolis_minimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy ``PAPERHUB_SLIDE_THEME=metropolis`` → ``"metropolis_minimal"``."""
    monkeypatch.delenv("PAPERHUB_SLIDE_STYLE_PROFILE", raising=False)
    monkeypatch.setenv("PAPERHUB_SLIDE_THEME", "metropolis")
    assert load_settings().slide_style_profile == "metropolis_minimal"


def test_slide_style_profile_unknown_value_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo'd env var must NOT silently emit an unrelated style — the
    operator gets the safe default."""
    monkeypatch.delenv("PAPERHUB_SLIDE_STYLE_PROFILE", raising=False)
    monkeypatch.setenv("PAPERHUB_SLIDE_THEME", "metropolis_minimall")
    assert load_settings().slide_style_profile == "default"


def test_slide_style_profile_new_env_var_wins_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When BOTH are set, ``PAPERHUB_SLIDE_STYLE_PROFILE`` (the new
    preferred name) wins — the legacy alias is for ops who haven't
    migrated their config yet."""
    monkeypatch.setenv("PAPERHUB_SLIDE_STYLE_PROFILE", "metropolis_minimal")
    monkeypatch.setenv("PAPERHUB_SLIDE_THEME", "gold")
    assert load_settings().slide_style_profile == "metropolis_minimal"


def test_slide_style_profile_accepts_canonical_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new preferred env var accepts canonical profile names directly
    (no alias rewrite needed)."""
    monkeypatch.setenv("PAPERHUB_SLIDE_STYLE_PROFILE", "default")
    assert load_settings().slide_style_profile == "default"
    monkeypatch.setenv("PAPERHUB_SLIDE_STYLE_PROFILE", "metropolis_minimal")
    assert load_settings().slide_style_profile == "metropolis_minimal"
