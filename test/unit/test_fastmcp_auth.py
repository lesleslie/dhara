from __future__ import annotations

import json
from pathlib import Path

import pytest

from dhara.mcp.fastmcp_auth import DharaTokenVerifier, build_token_verifier


@pytest.mark.unit
class TestDharaTokenVerifier:
    def _write_tokens_file(self, tmp_path: Path) -> Path:
        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text(
            json.dumps(
                {
                    "tokens": {
                        "rw": {
                            "token_hash": "52bfd2de0a2e69dff4517518590ac32a46bd76606ec22a258f99584a6e70aca2",
                            "role": "readwrite",
                            "created_at": "2026-04-03T00:00:00",
                            "expires_at": None,
                            "is_revoked": False,
                            "rate_limit": 1000,
                            "metadata": {},
                        }
                    }
                }
            )
        )
        return tokens_file

    @pytest.mark.asyncio
    async def test_verifier_maps_dhara_permissions_to_scopes(self, tmp_path: Path) -> None:
        tokens_file = self._write_tokens_file(tmp_path)
        verifier = DharaTokenVerifier(tokens_file=tokens_file)

        token = await verifier.verify_token("test_secret")

        assert token is not None
        assert token.client_id == "rw"
        assert "read" in token.scopes
        assert "list" in token.scopes
        assert "write" in token.scopes
        assert "readwrite" in token.scopes

    def test_build_token_verifier_requires_existing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="token file not found"):
            build_token_verifier(
                enabled=True,
                tokens_file=tmp_path / "missing.json",
                require_auth=True,
                default_role="readonly",
            )
