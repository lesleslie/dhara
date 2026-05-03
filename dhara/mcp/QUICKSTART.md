# Dhara MCP Quick Start

Dhara's supported MCP surface is the FastMCP server implemented in
`dhara.mcp.server_core` and exposed via `dhara mcp start`.

## 1. Start The MCP Server

```bash
dhara mcp start
```

Useful lifecycle commands:

```bash
dhara mcp status
dhara mcp health --probe
dhara mcp stop
```

## 2. Runtime Configuration

The canonical runtime settings surface is:

```python
from dhara.core.config import DharaSettings

settings = DharaSettings.load("dhara")
```

Dhara reads committed settings files plus `DHARA_*` environment variables.

## 3. Supported Tool Categories

The FastMCP server currently exposes these supported tool groups:

- Adapter registry: `store_adapter`, `get_adapter`, `list_adapters`, `list_adapter_versions`, `validate_adapter`, `get_adapter_health`
- Durable KV/time-series: `put`, `get`, `record_time_series`, `query_time_series`, `aggregate_patterns`
- Ecosystem state: `upsert_service`, `get_service`, `list_services`, `record_event`, `list_events`
- Contract introspection: `get_contract_info`
- Standardized health tools from `mcp-common`

Legacy `durus_*` MCP tool names are part of a deprecated compatibility surface,
not the canonical contract.

## 3a. Authentication Status

The canonical FastMCP runtime currently does not wire the legacy auth helpers
into request handling automatically. Instead, when enabled, it uses bearer
tokens backed by Dhara's token store. Legacy auth helpers remain importable for
compatibility and library use:

- `TokenAuth`
- `HMACAuth`
- `EnvironmentAuth`
- `AuthMiddleware`

Use `get_contract_info` to inspect the active runtime contract and current auth
status.

Example settings:

```yaml
authentication:
  enabled: true
  method: token
  token:
    tokens_file: /etc/dhara/tokens.json
```

## 4. Ecosystem State Example

```python
# Example MCP tool inputs

# Register or update a service record
{
  "service_id": "mahavishnu",
  "service_type": "orchestrator",
  "capabilities": ["workflow", "routing"],
  "metadata": {"port": 8680},
  "status": "healthy"
}

# Record an event
{
  "event_type": "workflow_started",
  "source_service": "mahavishnu",
  "related_service": "session-buddy",
  "payload": {"workflow_id": "wf-123"}
}
```

## 5. HTTP Endpoints

Dhara also exposes HTTP endpoints on the same service port:

- `/health`
- `/healthz`
- `/ready`
- `/readyz`
- `/metrics`

These exist alongside the MCP transport and are part of the supported runtime
surface.

## 6. Migration Notes

- Use `dhara.mcp` or `dhara.mcp.server_core` for code-level imports.
- Use `dhara mcp ...` for CLI lifecycle management.
