"""Tests for Oneiric action-kit adoption in Dhara.

Wave 3 (W3) migration:
- ``dhara.mcp.auth.generate_token`` -> oneiric.actions.security.SecuritySecureAction
  (mode ``token``)
- ``dhara.config.loader.save_config`` -> oneiric.actions.serialization.SerializationAction
  (mode ``encode``, json/yaml)
"""

from __future__ import annotations

import asyncio
import secrets

import pytest

from dhara.config.loader import _serialization_action, save_config
from dhara.config.defaults import DharaConfig
from dhara.mcp.auth import _secure_token_action, generate_token


@pytest.fixture(autouse=True)
def _reset_action_caches() -> None:
    _secure_token_action.cache_clear()
    _serialization_action.cache_clear()
    yield
    _secure_token_action.cache_clear()
    _serialization_action.cache_clear()


def _run(coro):
    return asyncio.run(coro)


def test_secure_token_action_uses_canonical_envelope() -> None:
    action = _secure_token_action()
    assert action._settings.token_length == 32
    assert action.metadata.key == "security.secure"


def test_generate_token_uses_kit() -> None:
    tok = generate_token(32)
    # SecuritySecureAction uses secrets.token_urlsafe so the output is base64
    # url-safe alphabet (~43 chars for 32 bytes).
    assert len(tok) >= 40
    assert all(c.isalnum() or c in "-_" for c in tok)


def test_generate_token_is_unique() -> None:
    tokens = {generate_token(32) for _ in range(8)}
    assert len(tokens) == 8


def test_serialization_action_uses_canonical_envelope() -> None:
    action = _serialization_action()
    assert action._settings.default_format == "json"
    assert action._settings.sort_keys is False
    assert action.metadata.key == "serialization.encode"


def test_save_config_json_uses_kit(tmp_path) -> None:
    cfg = DharaConfig()
    path = tmp_path / "config.json"
    save_config(cfg, path, format="json")
    text = path.read_text()
    assert text.startswith("{")
    # 2-space indent matches the kit's json.dumps(indent=2).
    assert '":\n  "' in text or '": ' in text


def test_save_config_yaml_uses_kit(tmp_path) -> None:
    cfg = DharaConfig()
    path = tmp_path / "config.yaml"
    save_config(cfg, path, format="yaml")
    text = path.read_text()
    assert "storage:" in text or "storage" in text


def test_serialization_encode_round_trip() -> None:
    """The kit encodes and decodes symmetrically."""
    payload = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
    encoded = _run(
        _serialization_action().execute(
            {"mode": "encode", "format": "json", "value": payload}
        )
    )
    decoded = _run(
        _serialization_action().execute(
            {"mode": "decode", "format": "json", "text": encoded["text"]}
        )
    )
    assert decoded["data"] == payload
