# backend/src/paperhub/settings_overlay.py
"""Project DB-backed settings onto os.environ (Plan G / FR-14).

``load_settings()`` reads os.environ live per request, so mutating it
hot-applies. The first time a key is overridden we record its prior value so
clearing the override reverts to the .env / built-in default.
"""
from __future__ import annotations

import os

# key -> value held by os.environ BEFORE the first override (None = was unset).
_base: dict[str, str | None] = {}


def _record_base(key: str) -> None:
    if key not in _base:
        _base[key] = os.environ.get(key)


def set_override(key: str, value: str) -> None:
    _record_base(key)
    os.environ[key] = value


def clear_override(key: str) -> None:
    original = _base.pop(key, "__absent__")
    if original == "__absent__" or original is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = original


def apply_overlay(rows: dict[str, str]) -> None:
    """Apply every DB row onto os.environ (records base first)."""
    for key, value in rows.items():
        set_override(key, value)


def reset_for_tests() -> None:
    _base.clear()
