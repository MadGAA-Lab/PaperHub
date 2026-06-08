"""GET/PATCH /settings — runtime config panel (Plan G / FR-14)."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from paperhub.config import load_settings
from paperhub.db.connection import open_db
from paperhub.settings_registry import (
    PROVIDER_CREDENTIAL_SUGGESTIONS,
    SETTINGS_REGISTRY,
    field_by_key,
    is_allowed_credential_key,
)

router = APIRouter(prefix="/settings", tags=["settings"])

_CATEGORY_LABELS = {
    "provider_credentials": "Provider credentials",
    "llm_models": "LLM models",
    "agent_tunables": "Agent tunables",
    "memory": "Memory / recall",
    "external_services": "External services",
    "external_lookup": "External lookup",
    "storage": "Workspace / storage",
    "logging": "Logging",
    "marker": "Marker",
    "slides": "Slide style",
}

# Order categories deterministically for the modal's left-nav.
_CATEGORY_ORDER = [
    "provider_credentials", "llm_models", "agent_tunables", "memory",
    "external_services", "external_lookup", "storage", "logging", "marker", "slides",
]


async def _db_rows(db_path: Any) -> dict[str, str]:
    async with open_db(db_path) as conn, conn.execute(
        "SELECT key, value FROM settings"
    ) as cur:
        return {r[0]: r[1] for r in await cur.fetchall()}


@router.get("")
async def get_settings() -> dict[str, Any]:
    settings = load_settings()
    rows = await _db_rows(settings.db_path)

    cats: dict[str, list[dict[str, Any]]] = {k: [] for k in _CATEGORY_ORDER}

    # Free-form provider credentials: every DB row that is an allowed credential
    # key (and not a structured registry field). Values are NEVER returned.
    for key in sorted(rows):
        if field_by_key(key) is None and is_allowed_credential_key(key):
            cats["provider_credentials"].append(
                {"key": key, "label": key, "type": "secret",
                 "secret": True, "is_set": True, "restart_required": False}
            )

    # Structured fields from the registry.
    for f in SETTINGS_REGISTRY:
        effective = os.environ.get(f.key, f.default)
        item: dict[str, Any] = {
            "key": f.key, "label": f.label, "type": f.type,
            "secret": f.secret, "restart_required": f.restart_required,
            "read_only": f.read_only, "help": f.help,
            "is_default": f.key not in rows,
        }
        if f.choices:
            item["choices"] = list(f.choices)
        if f.min is not None:
            item["min"] = f.min
        if f.max is not None:
            item["max"] = f.max
        if f.secret:
            item["is_set"] = bool(effective)
        else:
            item["value"] = effective
        cats[f.category].append(item)

    return {
        "categories": [
            {
                "key": c,
                "label": _CATEGORY_LABELS[c],
                "free_form": c == "provider_credentials",
                "suggestions": list(PROVIDER_CREDENTIAL_SUGGESTIONS)
                if c == "provider_credentials" else [],
                "fields": cats[c],
            }
            for c in _CATEGORY_ORDER
        ]
    }
