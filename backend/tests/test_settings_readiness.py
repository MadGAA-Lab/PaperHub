import pytest

from paperhub import settings_readiness as sr
from paperhub.settings_registry import provider_for_credential_key


def test_provider_for_credential_key_known_and_fallback() -> None:
    assert provider_for_credential_key("GEMINI_API_KEY") == "gemini"
    assert provider_for_credential_key("OPENAI_API_KEY") == "openai"
    assert provider_for_credential_key("TOGETHERAI_API_KEY") == "together_ai"
    assert provider_for_credential_key("PERPLEXITYAI_API_KEY") == "perplexity"
    # Unknown *_API_KEY falls back to the lowercased prefix.
    assert provider_for_credential_key("NOVELPROVIDER_API_KEY") == "novelprovider"
    # Non-key credentials (config-only) map to no provider.
    assert provider_for_credential_key("AZURE_API_BASE") is None


def test_configured_providers_dedups_and_skips_non_keys() -> None:
    providers = sr.configured_providers(
        ["GEMINI_API_KEY", "OPENAI_API_KEY", "AZURE_API_BASE"]
    )
    assert providers == ["gemini", "openai"]


def test_compute_readiness_not_ready_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Default gate models are gemini/* — strip every Google key so they fail.
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "VERTEXAI_PROJECT"):
        monkeypatch.delenv(key, raising=False)
    result = sr.compute_readiness([])
    assert result["ready"] is False
    assert result["credentials_set"] is False
    assert result["models"]["small"]["key_ok"] is False
    assert "GEMINI_API_KEY" in result["models"]["small"]["missing_keys"]


def test_compute_readiness_ready_with_gemini_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    result = sr.compute_readiness(["GEMINI_API_KEY"])
    assert result["ready"] is True
    assert result["credentials_set"] is True
    assert result["models"]["flagship"]["key_ok"] is True


@pytest.mark.asyncio
async def test_fetch_model_options_normalizes_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sr._reset_cache_for_tests()
    calls = {"n": 0}

    def fake_valid_models(**_kwargs: object) -> list[str]:
        calls["n"] += 1
        # Mix bare + prefixed ids — the helper must normalize both to prefixed.
        return ["gemini/gemini-2.5-pro", "gemini-3.1-flash-lite"]

    monkeypatch.setattr(sr.litellm, "get_valid_models", fake_valid_models)

    first = await sr.fetch_model_options(["gemini"])
    assert first["gemini"] == ["gemini/gemini-2.5-pro", "gemini/gemini-3.1-flash-lite"]
    # Second call within TTL is served from cache (no extra live fetch).
    second = await sr.fetch_model_options(["gemini"])
    assert second == first
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_fetch_model_options_falls_back_to_static(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sr._reset_cache_for_tests()
    monkeypatch.setattr(
        sr.litellm, "get_valid_models", lambda **_k: []
    )  # live yields nothing
    monkeypatch.setattr(
        sr.litellm, "models_by_provider", {"gemini": ["gemini/gemini-2.5-pro"]}
    )
    out = await sr.fetch_model_options(["gemini"])
    assert out["gemini"] == ["gemini/gemini-2.5-pro"]
