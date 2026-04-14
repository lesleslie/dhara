# Dhara Migration Guide

## Overview

Dhara is the canonical package and service identity. Older `Durus` and `Druva`
names remain only where compatibility is still required.

This guide covers the supported migration path for:

- package/module imports
- runtime configuration
- CLI usage
- MCP integration

## Package And Import Migration

### Canonical Imports

Use these paths for new code:

```python
from dhara.core.config import DharaSettings
from dhara.core.connection import Connection
from dhara.core.persistent import Persistent
from dhara.storage.file import FileStorage
from dhara.storage.client import ClientStorage
from dhara.collections.dict import PersistentDict
from dhara.collections.list import PersistentList
from dhara.mcp import DharaMCPServer
```

### Deprecated Compatibility Imports

These still work in `0.8.x` but emit deprecation warnings:

- `dhara.file_storage`
- `dhara.connection`
- `dhara.persistent`
- `dhara.persistent_dict`
- `dhara.persistent_list`
- `dhara.mcp.server`
- `druva`

## Configuration Migration

### Canonical Runtime Settings

Use:

```python
from dhara.core.config import DharaSettings

settings = DharaSettings.load("dhara")
```

### Legacy Helper Layer

`dhara.config` remains available for lightweight dataclass helpers and
compatibility scenarios, but it is not the canonical runtime settings surface.

### Environment Variables

Preferred:

- `DHARA_*`

Still supported for compatibility:

- `DRUVA_*`
- `DURUS_*`

## CLI Migration

### Canonical Commands

```bash
dhara mcp start
dhara mcp status
dhara mcp health --probe
dhara mcp stop

dhara db start
dhara db client
dhara db pack
```

### Deprecated Historical Forms

Do not use these in new docs or scripts:

- `dhara-mcp ...`
- `dhara -s`
- `dhara -c`
- `dhara db server`

## MCP Migration

### Canonical MCP Surface

Use:

- `dhara.mcp`
- `dhara.mcp.server_core`
- `dhara mcp start`

### Deprecated MCP Surface

- `dhara.mcp.server`
- `dhara.mcp.oneiric_server`
- legacy `durus_*` tool names

### Current Supported Tool Groups

- adapter registry
- durable KV/time-series
- ecosystem service registry
- ecosystem event log
- standardized health tools

Use `get_contract_info` to inspect the supported MCP contract at runtime.

### Authentication Clarification

The canonical FastMCP runtime supports bearer-token auth when
`authentication.enabled` is set and a Dhara token file is configured. Legacy
auth helper classes remain available for compatibility and library use, and the
older `dhara.mcp.oneiric_server` module remains in the repo as a legacy path
rather than the supported runtime surface.

## Persistence Contract Notes

Current explicit schema versions:

- adapter registry records: `schema_version = 1`
- ecosystem service records: `schema_version = 1`
- ecosystem event records: `schema_version = 1`

These version markers are the basis for future migration handling as the
ecosystem contract evolves.

## Deprecation Schedule

See:

- `docs/LEGACY_COMPATIBILITY_AND_REMOVAL_PLAN.md`

Current plan:

- `0.8.x`: deprecated surfaces still work, with warnings
- `0.9.x`: stronger enforcement and migration pressure
- `1.0.0`: convenience compatibility shims become removal candidates
