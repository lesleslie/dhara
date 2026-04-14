# Legacy Compatibility And Removal Plan

## Purpose

Dhara still ships a small set of compatibility surfaces for older imports and
rename-transition paths:

- legacy top-level module shims such as `dhara.file_storage`
- rename aliases such as `druva.*`
- compatibility wrappers such as `dhara.mcp.server`

These surfaces remain available to reduce migration risk, but they are no
longer the canonical API. This document defines the deprecation schedule and
removal criteria.

## Canonical Surfaces

Use these paths for all new code:

- `dhara.core.config.DharaSettings`
- `dhara.core.connection.Connection`
- `dhara.core.persistent.Persistent`
- `dhara.storage.file.FileStorage`
- `dhara.storage.client.ClientStorage`
- `dhara.collections.dict.PersistentDict`
- `dhara.collections.list.PersistentList`
- `dhara.mcp` or `dhara.mcp.server_core`

## Deprecated Compatibility Surfaces

The following are deprecated and should not be used in new code:

- `dhara.file_storage`
- `dhara.connection`
- `dhara.persistent`
- `dhara.persistent_dict`
- `dhara.persistent_list`
- `dhara.mcp.server`
- `druva`

The following remain compatibility aliases inside the dataclass config helper
layer and are deprecated as primary names:

- `dhara.config.DruvaConfig`
- `dhara.core.config.DruvaSettings`

## Timeline

### Phase 1: Active Deprecation

Target range: `0.8.x`

- Keep compatibility shims functional.
- Emit `DeprecationWarning` for deprecated import paths.
- Keep active docs on canonical surfaces only.
- Block new internal usage of deprecated shims in tests/CI.

### Phase 2: Escalation

Target range: `0.9.x`

- Keep runtime compatibility for external callers.
- Tighten migration messaging in release notes.
- Consider raising louder warnings in development and test environments.
- Review whether any remaining aliases are still required for serialized-data
  compatibility versus convenience imports.

### Phase 3: Removal

Target: `1.0.0`

- Remove deprecated convenience import shims that are not required for old
  serialized-data compatibility.
- Remove the `druva` forwarding package unless a demonstrated persistence
  compatibility requirement remains.
- Keep migration notes and release-history documentation.

## Removal Criteria

A deprecated surface is removable when all of the following are true:

1. Dhara internals no longer import it.
2. Active docs no longer teach it.
3. Compatibility tests exist for the remaining supported migration paths.
4. The team has decided whether persisted-data compatibility still requires it.

## Enforcement

Crackerjack-driven test runs should enforce these rules:

- active Dhara modules must not import deprecated compatibility shims
- active docs must not teach deprecated command forms or compatibility imports
- deprecated imports must continue to emit warnings until removal

## Notes

- Historical and archived docs may still reference Durus or Druva names.
- Those references are acceptable when clearly marked as historical context.
