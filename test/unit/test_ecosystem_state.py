from __future__ import annotations

from pathlib import Path

import pytest

from dhara.collections.dict import PersistentDict
from dhara.core.config import DharaSettings
from dhara.mcp.ecosystem_state import EcosystemStateStore
from dhara.mcp.server_core import DharaMCPServer


@pytest.mark.unit
class TestEcosystemStateStore:
    @pytest.fixture
    def server(self, tmp_path: Path) -> DharaMCPServer:
        settings = DharaSettings(
            server_name="test-dhara",
            storage={"path": tmp_path / "ecosystem.dhara", "read_only": False},
            cache_root=tmp_path / ".cache",
        )
        return DharaMCPServer(settings)

    @staticmethod
    async def _tool(server: DharaMCPServer, name: str):
        return await server.server.get_tool(name)

    def test_store_initializes(self, server: DharaMCPServer) -> None:
        assert isinstance(server.ecosystem_state, EcosystemStateStore)

    @pytest.mark.asyncio
    async def test_upsert_and_get_service(self, server: DharaMCPServer) -> None:
        upsert_tool = await self._tool(server, "upsert_service")
        get_tool = await self._tool(server, "get_service")

        await upsert_tool.run(
            {
                "service_id": "mahavishnu",
                "service_type": "orchestrator",
                "capabilities": ["workflow", "routing"],
                "metadata": {"port": 8680},
                "status": "healthy",
            }
        )
        result = await get_tool.run({"service_id": "mahavishnu"})
        payload = result.structured_content

        assert payload["ok"] is True
        assert payload["service"]["schema_version"] == 1
        assert payload["service"]["service_type"] == "orchestrator"
        assert "workflow" in payload["service"]["capabilities"]

    @pytest.mark.asyncio
    async def test_list_services_filters(self, server: DharaMCPServer) -> None:
        upsert_tool = await self._tool(server, "upsert_service")
        list_tool = await self._tool(server, "list_services")

        await upsert_tool.run(
            {
                "service_id": "mahavishnu",
                "service_type": "orchestrator",
                "capabilities": ["workflow", "routing"],
                "status": "healthy",
            }
        )
        await upsert_tool.run(
            {
                "service_id": "session-buddy",
                "service_type": "memory",
                "capabilities": ["session"],
                "status": "healthy",
            }
        )

        result = await list_tool.run({"capability": "workflow"})
        payload = result.structured_content

        assert payload["ok"] is True
        assert payload["count"] == 1
        assert payload["services"][0]["service_id"] == "mahavishnu"

    @pytest.mark.asyncio
    async def test_record_and_list_events(self, server: DharaMCPServer) -> None:
        record_tool = await self._tool(server, "record_event")
        list_tool = await self._tool(server, "list_events")

        await record_tool.run(
            {
                "event_type": "workflow_started",
                "source_service": "mahavishnu",
                "related_service": "session-buddy",
                "payload": {"workflow_id": "wf-123"},
            }
        )
        result = await list_tool.run({"source_service": "mahavishnu"})
        payload = result.structured_content

        assert payload["ok"] is True
        assert payload["count"] == 1
        assert payload["events"][0]["schema_version"] == 1
        assert payload["events"][0]["event_type"] == "workflow_started"

    def test_get_service_normalizes_legacy_record(self, server: DharaMCPServer) -> None:
        root = server.connection.get_root()
        root["ecosystem_services"]["legacy-service"] = PersistentDict(
            {
                "service_id": "legacy-service",
                "service_type": "worker",
            }
        )
        server.connection.commit()

        payload = server.ecosystem_state.get_service("legacy-service")

        assert payload is not None
        assert payload["schema_version"] == 1
        assert payload["capabilities"] == []
        assert payload["metadata"] == {}
        assert payload["status"] == "unknown"

    def test_list_events_normalizes_legacy_record(self, server: DharaMCPServer) -> None:
        root = server.connection.get_root()
        root["ecosystem_events"].append(
            PersistentDict(
                {
                    "event_type": "legacy_event",
                    "source_service": "mahavishnu",
                    "timestamp": "2026-04-03T00:00:00+00:00",
                }
            )
        )
        server.connection.commit()

        payload = server.ecosystem_state.list_events(source_service="mahavishnu")

        assert payload[0]["schema_version"] == 1
        assert payload[0]["payload"] == {}
