from __future__ import annotations

import pytest

SECRET = "dhara-test-secret-that-is-at-least-32-chars"


@pytest.fixture(autouse=True)
def _reset_dhara_config():
    try:
        from dhara.mcp.auth import _reset_config
        _reset_config()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        from dhara.mcp.auth import _reset_config
        _reset_config()
    except (ImportError, AttributeError):
        pass


def test_dhara_permission_extends_base():
    from dhara.mcp.auth import DharaPermission
    assert DharaPermission.CHECKPOINT.value == "checkpoint"
    assert DharaPermission.RESTORE.value == "restore"


@pytest.mark.asyncio
async def test_require_dhara_auth_passes_when_disabled(monkeypatch):
    monkeypatch.delenv("DHARA_AUTH_SECRET", raising=False)
    monkeypatch.delenv("BODAI_SHARED_SECRET", raising=False)

    from dhara.mcp.auth import require_dhara_auth

    @require_dhara_auth()
    async def my_tool(**kwargs):
        return "ok"

    result = await my_tool()
    assert result == "ok"
