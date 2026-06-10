# backend/src/paperhub/settings_readiness.py
"""First-run readiness + live model discovery (frontend onboarding gate).

Two concerns, kept separate by reliability:

* **Readiness (hard gate)** — can the configured small + flagship models actually
  run right now? ``litellm.validate_environment`` resolves each model's provider
  and reports whether its required keys are present in ``os.environ`` (the live
  settings overlay). This is what the missing-``GEMINI_API_KEY`` /
  no-provider-prefix errors come down to, so it gates the composer.

* **Model options (soft assist)** — autocomplete suggestions for the model-name
  fields. Best-effort live fetch via ``get_valid_models`` for providers that
  support discovery, falling back to LiteLLM's bundled static map. NEVER blocks:
  not every provider supports a list, so the model name stays free text.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import litellm

from paperhub.settings_registry import (
    LIVE_DISCOVERY_PROVIDERS,
    field_by_key,
    provider_for_credential_key,
)

# The two model fields that must be runnable before the app is usable.
_GATE_MODEL_KEYS: tuple[tuple[str, str], ...] = (
    ("small", "PAPERHUB_MODEL_SMALL"),
    ("flagship", "PAPERHUB_MODEL_FLAGSHIP"),
)

_OPTIONS_TIMEOUT_S = 8.0
_OPTIONS_TTL_S = 600.0
# provider -> (fetched_at_monotonic, models). Live discovery is slow, so cache it.
_options_cache: dict[str, tuple[float, list[str]]] = {}


def _effective_model(env_key: str) -> str:
    field = field_by_key(env_key)
    default = field.default if field is not None else None
    return os.environ.get(env_key) or default or ""


def _model_check(model: str) -> dict[str, Any]:
    """validate_environment for one model id; never raises."""
    if not model:
        return {"model": "", "key_ok": False, "missing_keys": []}
    try:
        env = litellm.validate_environment(model=model)
        return {
            "model": model,
            "key_ok": bool(env.get("keys_in_environment")),
            "missing_keys": list(env.get("missing_keys") or []),
        }
    except Exception:  # noqa: BLE001 — discovery must never break the gate
        return {"model": model, "key_ok": False, "missing_keys": []}


def configured_providers(credential_keys: list[str]) -> list[str]:
    """LiteLLM providers unlocked by the currently-set credential keys."""
    seen: dict[str, None] = {}  # ordered de-dup
    for key in credential_keys:
        provider = provider_for_credential_key(key)
        if provider is not None:
            seen.setdefault(provider, None)
    return list(seen)


def compute_readiness(credential_keys: list[str]) -> dict[str, Any]:
    """Synchronous, no-network gate. ``ready`` iff both gate models are runnable."""
    models = {name: _model_check(_effective_model(key)) for name, key in _GATE_MODEL_KEYS}
    return {
        "ready": all(m["key_ok"] for m in models.values()),
        "credentials_set": len(credential_keys) > 0,
        "models": models,
    }


def _fetch_provider_models(provider: str) -> list[str]:
    """Live list for one provider with a static fallback. Blocking — run in a
    thread. Returns [] only if both live + static yield nothing."""
    models: list[str] = []
    if provider in LIVE_DISCOVERY_PROVIDERS:
        try:
            models = litellm.get_valid_models(
                check_provider_endpoint=True, custom_llm_provider=provider
            )
        except Exception:  # noqa: BLE001 — fall through to static
            models = []
    if not models:
        models = list(litellm.models_by_provider.get(provider, []))
    # LiteLLM mixes bare ("gemini-2.0-flash") and prefixed ("gemini/...") ids;
    # normalize every suggestion to the prefixed form the app expects.
    prefix = f"{provider}/"
    normalized = {m if "/" in m else f"{prefix}{m}" for m in models}
    return sorted(normalized)


async def fetch_model_options(providers: list[str]) -> dict[str, list[str]]:
    """Usable models per configured provider (cached, best-effort)."""
    now = time.monotonic()
    out: dict[str, list[str]] = {}
    stale = []
    for provider in providers:
        cached = _options_cache.get(provider)
        if cached is not None and now - cached[0] < _OPTIONS_TTL_S:
            out[provider] = cached[1]
        else:
            stale.append(provider)

    for provider in stale:
        try:
            models = await asyncio.wait_for(
                asyncio.to_thread(_fetch_provider_models, provider),
                timeout=_OPTIONS_TIMEOUT_S,
            )
        except Exception:  # noqa: BLE001 — timeout/network never breaks the panel
            models = list(_options_cache.get(provider, (0.0, []))[1])
        _options_cache[provider] = (time.monotonic(), models)
        out[provider] = models
    return out


def _reset_cache_for_tests() -> None:
    _options_cache.clear()
