from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from paperhub import settings_overlay as ov
from paperhub.app import create_app
from paperhub.db.migrate import apply_schema

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def settings_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncClient:
    monkeypatch.setenv("PAPERHUB_PREWARM_MODELS", "0")
    monkeypatch.setenv("PAPERHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PAPERHUB_BOOT_BANNER", "0")
    db_path = tmp_path / "paperhub.db"
    async with aiosqlite.connect(db_path) as conn:
        await apply_schema(conn)
    ov.reset_for_tests()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    ov.reset_for_tests()


async def test_get_settings_returns_categories(settings_client: AsyncClient) -> None:
    resp = await settings_client.get("/settings")
    assert resp.status_code == 200
    body = resp.json()
    cats = {c["key"] for c in body["categories"]}
    assert {"provider_credentials", "llm_models", "logging"} <= cats


async def test_get_settings_masks_secret_value(settings_client: AsyncClient) -> None:
    resp = await settings_client.get("/settings")
    fields = [
        f
        for c in resp.json()["categories"]
        for f in c["fields"]
        if f["key"] == "PAPERHUB_SEMANTIC_SCHOLAR_API_KEY"
    ]
    assert fields and fields[0]["secret"] is True
    assert "value" not in fields[0]  # secret value never returned
    assert "is_set" in fields[0]
