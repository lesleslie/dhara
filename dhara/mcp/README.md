# Dhara MCP

## Overview

Dhara's supported MCP implementation is the FastMCP server in
`dhara.mcp.server_core`, exposed through:

- `dhara mcp start`
- `python -m dhara.mcp`
- imports from `dhara.mcp` or `dhara.mcp.server_core`

The deprecated `dhara.mcp.server` module remains only as a compatibility wrapper.

## Supported Contract

### Canonical Runtime Surface

- Settings: `dhara.core.config.DharaSettings`
- Server class: `dhara.mcp.DharaMCPServer`
- CLI lifecycle: `dhara mcp start|status|health|stop`
- HTTP endpoints: `/health`, `/healthz`, `/ready`, `/readyz`, `/metrics`

### Authentication Status

The canonical FastMCP runtime supports bearer-token auth when
`authentication.enabled: true` and a Dhara token file is configured.

- Runtime auth mode: `none` by default, `token` when enabled
- Token source: `authentication.token.tokens_file`
- Tool authorization scopes use Dhara permission names such as `read`, `list`,
  `write`, and `admin`
- Legacy auth helpers still available as library surfaces:
  `TokenAuth`, `HMACAuth`, `EnvironmentAuth`, `AuthMiddleware`

Use `get_contract_info` to inspect the active runtime contract, including auth
mode, required scopes, token-file path, and deprecated surfaces.

### Tool Groups

#### Adapter Registry

- `store_adapter`
- `get_adapter`
- `list_adapters`
- `list_adapter_versions`
- `validate_adapter`
- `get_adapter_health`

#### Durable KV And Time-Series

- `put`
- `get`
- `record_time_series`
- `query_time_series`
- `aggregate_patterns`

#### Ecosystem State

- `upsert_service`
- `get_service`
- `list_services`
- `record_event`
- `list_events`

#### Contract Introspection

- `get_contract_info`

#### Standard Health Tools

Dhara also registers standardized health tools from `mcp-common`.

## Ecosystem Use

Dhara is intended to complement Mahavishnu and sibling services by providing:

- durable service registration
- capability metadata storage
- heartbeat/lease-like status snapshots
- append-only orchestration event history
- adapter registry persistence
- lightweight persistent KV and time-series data

## Service And Event Schemas

Current ecosystem-state records include explicit schema versions:

- adapter records: `schema_version = 1`
- service records: `schema_version = 1`
- event records: `schema_version = 1`

This is the start of the versioned persistence contract for ecosystem-facing data.

## Example Runtime

```bash
export DHARA_MODE=lite
dhara mcp start
```

```yaml
authentication:
  enabled: true
  method: token
  token:
    tokens_file: /etc/dhara/tokens.json
    require_auth: true
    default_role: readonly
```

```python
from dhara.core.config import DharaSettings
from dhara.mcp import DharaMCPServer

settings = DharaSettings.load("dhara")
server = DharaMCPServer(settings)
```

## Migration Notes

- Prefer `dhara.mcp` or `dhara.mcp.server_core` in active code.
- Treat legacy `durus_*` tool names as deprecated compatibility-only behavior.
- Treat `dhara.mcp.server` as deprecated.

## Related Docs

- `dhara/mcp/QUICKSTART.md`
- `docs/MIGRATION_GUIDE.md`
- `docs/guides/operational-modes.md`
- `docs/reference/service-dependencies.md`
