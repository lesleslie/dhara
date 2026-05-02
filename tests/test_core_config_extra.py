"""Tests for dhara.core.config — DharaSettings.load and legacy env aliases."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from dhara.core.config import DharaSettings


class TestApplyLegacyEnvAliases:
    def test_dhara_env_mirrored_from_druva(self):
        os.environ.pop("DHARA_SERVER_NAME", None)
        os.environ["DRUVA_SERVER_NAME"] = "test-from-druva"
        try:
            DharaSettings._apply_legacy_env_aliases()
            assert os.environ.get("DHARA_SERVER_NAME") == "test-from-druva"
        finally:
            os.environ.pop("DHARA_SERVER_NAME", None)
            os.environ.pop("DRUVA_SERVER_NAME", None)

    def test_durus_env_mirrored_to_dhara(self):
        os.environ.pop("DHARA_MODE", None)
        os.environ["DURUS_MODE"] = "standard"
        try:
            DharaSettings._apply_legacy_env_aliases()
            assert os.environ.get("DHARA_MODE") == "standard"
        finally:
            os.environ.pop("DHARA_MODE", None)
            os.environ.pop("DURUS_MODE", None)

    def test_canonical_dhara_env_not_overridden(self):
        os.environ["DHARA_SERVER_NAME"] = "canonical"
        os.environ["DRURA_SERVER_NAME"] = "legacy"
        try:
            DharaSettings._apply_legacy_env_aliases()
            assert os.environ["DHARA_SERVER_NAME"] == "canonical"
        finally:
            os.environ.pop("DHARA_SERVER_NAME", None)
            os.environ.pop("DRURA_SERVER_NAME", None)

    def test_non_matching_env_ignored(self):
        os.environ["UNRELATED_VAR"] = "value"
        try:
            DharaSettings._apply_legacy_env_aliases()
            # No DHARA_ variable should be created from UNRELATED_VAR
            assert os.environ.get("DHARA_UNRELATED_VAR") is None
        finally:
            os.environ.pop("UNRELATED_VAR", None)


class TestDharaSettingsLoad:
    def test_load_defaults_no_mode(self):
        os.environ.pop("DHARA_MODE", None)
        try:
            settings = DharaSettings.load("dhara")
            assert isinstance(settings, DharaSettings)
            assert settings.server_name == "dhara"
        finally:
            os.environ.pop("DHARA_MODE", None)

    def test_load_with_lite_mode(self):
        os.environ["DHARA_MODE"] = "lite"
        try:
            settings = DharaSettings.load("dhara")
            assert settings.mode == "lite"
        finally:
            os.environ.pop("DHARA_MODE", None)

    def test_load_with_standard_mode(self):
        os.environ["DHARA_MODE"] = "standard"
        try:
            settings = DharaSettings.load("dhara")
            assert settings.mode == "standard"
        finally:
            os.environ.pop("DHARA_MODE", None)

    def test_load_with_unknown_mode_uses_config_name(self):
        os.environ["DHARA_MODE"] = "custom"
        try:
            settings = DharaSettings.load("dhara")
            assert settings.mode == "custom"
        finally:
            os.environ.pop("DHARA_MODE", None)

    def test_load_falls_back_to_defaults_on_error(self):
        os.environ.pop("DHARA_MODE", None)
        try:
            with patch.object(
                DharaSettings.__bases__[0],
                "load",
                side_effect=FileNotFoundError("no config"),
            ):
                settings = DharaSettings.load("nonexistent")
            assert isinstance(settings, DharaSettings)
        finally:
            pass

    def test_load_applies_legacy_aliases(self):
        os.environ.pop("DHARA_MODE", None)
        os.environ["DURUS_SERVER_NAME"] = "from-durus"
        try:
            settings = DharaSettings.load("dhara")
            # Legacy alias should have been applied
            assert "from-durus" in os.environ.get("DHARA_SERVER_NAME", "")
        finally:
            os.environ.pop("DHARA_SERVER_NAME", None)
            os.environ.pop("DURUS_SERVER_NAME", None)
