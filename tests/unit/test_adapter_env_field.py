from __future__ import annotations

import json

import pytest

from dhara.mcp.adapter_tools import Adapter

pytestmark = pytest.mark.unit


class TestAdapterEnvField:
    """Plan 4 Phase B: Adapter.env field for cross-environment comparison."""

    def test_adapter_with_explicit_env(self) -> None:
        """Adapter(env='prod') creates an adapter with env populated."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            env="prod",
        )
        assert adapter.env == "prod"

    def test_adapter_without_env_defaults_to_none(self) -> None:
        """Adapter() (no env) defaults to None."""
        adapter = Adapter(domain="adapter", key="cache", provider="redis")
        assert adapter.env is None

    def test_from_env_factory_reads_mahavishnu_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adapter.from_env() reads from MAHAVISHNU_ENV env var."""
        monkeypatch.setenv("MAHAVISHNU_ENV", "staging")
        adapter = Adapter.from_env(
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert adapter.env == "staging"

    def test_from_env_factory_returns_none_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adapter.from_env() returns None when MAHAVISHNU_ENV is not set."""
        monkeypatch.delenv("MAHAVISHNU_ENV", raising=False)
        adapter = Adapter.from_env(
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert adapter.env is None

    def test_with_env_returns_new_instance_immutable(self) -> None:
        """Adapter.with_env(value) returns a copy with env set; original unchanged."""
        original = Adapter(domain="adapter", key="cache", provider="redis")
        assert original.env is None

        derived = original.with_env("prod")
        assert derived.env == "prod"
        assert derived is not original
        assert derived.domain == "adapter"
        assert derived.key == "cache"
        assert derived.provider == "redis"
        # original must not be mutated
        assert original.env is None

    def test_with_env_preserves_existing_env_when_called_again(self) -> None:
        """Subsequent with_env calls override the env, not stack."""
        adapter = Adapter(domain="adapter", key="cache", provider="redis", env="dev")
        new_adapter = adapter.with_env("prod")
        assert new_adapter.env == "prod"
        # original keeps its env
        assert adapter.env == "dev"

    def test_env_field_serialized_in_to_dict(self) -> None:
        """to_dict() includes the env field so it round-trips through persistence."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            env="prod",
        )
        data = adapter.to_dict()
        assert "env" in data
        assert data["env"] == "prod"

    def test_env_field_serialized_as_none_when_unset(self) -> None:
        """to_dict() with no env returns env=None in the dict (not absent)."""
        adapter = Adapter(domain="adapter", key="cache", provider="redis")
        data = adapter.to_dict()
        assert "env" in data
        assert data["env"] is None

    def test_env_field_round_trips_through_json(self) -> None:
        """The env field survives a JSON dump/load cycle for persistent storage."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            env="prod",
        )
        payload = json.dumps(adapter.to_dict())
        loaded = json.loads(payload)
        assert loaded["env"] == "prod"
