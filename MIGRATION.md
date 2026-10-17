# Dhara Migration Guide

This guide covers breaking changes and removals in Dhara, focused on
the substrate-decommissioning cleanup waves of 2026-09 through 2026-10.
For background, see the architectural decision record at
[`mahavishnu/docs/adr/019-dhara-decommissioning.md`](../mahavishnu/docs/adr/019-dhara-decommissioning.md).

## Status

**Dhara is no longer a core component of the Bodai fleet as of 2026-10-17.**
It is now maintained as a standalone persistent-object library
([`durus`](https://pypi.org/project/durus/) lineage) and is no longer
wiring into the Bodai control plane. The substrate / orchestration
concerns Dhara used to host have moved to oneiric (`adapters/`,
`settings/`) and the MCP HTTP/serving concern has been retired entirely
from the Dhara package.

If you depend on Dhara through the Bodai substrate or as a Bodai MCP
server, see the replacement table in [Section 3](#section-3-where-to-find-replacements).

## Pinning guidance

This is a **pre-1.0** library (`dhara 0.22.x`). Per the project's
replace-not-extend policy (see ADR), removed APIs are not re-exported
under their old names — there are no deprecation windows. Pin your
consumer to the last release that still exported a given API:

| Removed surface | Last version with the API | Migration target |
|---|---|---|
| `dhara.lock.*` | `dhara<=0.21.0` | `mahavishnu.core._lock_sentinel.Lock` |
| `dhara/mcp/` (server, tools, agents, skills) | `dhara<=0.20.2` | (see [Section 3](#section-3-where-to-find-replacements)) |
| `dhara.audit.*` | `dhara<=0.20.2` | (deleted; no replacement) |
| `dhara.skills_signer.*` | `dhara<=0.20.2` | (deleted; no replacement) |
| `dhara.schema.{approval_log, audit_record, capability_descriptor, ecosystem_run_record, webhook_ingress, workflow_outcome}` | `dhara<=0.20.2` | (deleted; only `channel_session_state` survives in `dhara.schema`) |
| `dhara mcp {start,stop,restart,status,health}` CLI | `dhara<=0.20.2` | (deleted) |
| `OneiricCLIBase` consumers expecting `BodaiCLIBase` | `dhara<=0.19.x` | rename to `OneiricCLIBase` |

## Section 1: API renames

### 1.1 Package renames (historical)

| Old name | New name | Version | Notes |
|---|---|---|---|
| `durus` | `dhara` | 0.1.0 | **BREAKING**. Import path changed everywhere. |
| `Dhruva` (project) | `Druva` (project) | historical | Internal rename, no public API change. |
| `Druva` (project) | `Dhara` (project) | 0.1.0 | Internal rename, no public API change. |

### 1.2 Class renames

| Old name | New name | Module | Notes |
|---|---|---|---|
| `BodaiCLIBase` | `OneiricCLIBase` | `oneiric.cli.base` | **BREAKING**. The shared Typer base class. Consumers must rename their subclass. Hard cutover, no deprecation alias. |
| `DurusKeyError` | `DruvaKeyError` | `dhara.error` | Alias `DurusKeyError = DruvaKeyError` retained inside `dhara/error.py`; import the new name going forward. |

### 1.3 Module path changes

| Old import | New import | Notes |
|---|---|---|
| `from dhara._compat.druva import ...` | (none) | `dhara/_compat/druva.py` existed to ease the `Druva → Dhara` rename; it has since been removed. Inline-replace `druva.*` references with their `dhara.*` equivalents. |
| `from dhara.skills_signer import ...` | (none — package removed) | See [Section 2](#section-2-removed-surfaces). |
| `from dhara.lock import ...` | `from mahavishnu.core._lock_sentinel import Lock` | Lock has been re-homed to `mahavishnu.core._lock_sentinel.Lock`. |

## Section 2: Removed surfaces

The following packages, modules, classes, and CLI surfaces were removed
without deprecation windows. They were Bodai-specific or substrate-
coupled substrate and had no path forward inside Dhara as a standalone
library.

### 2.1 `dhara/mcp/` (entire package, 29 files, ~9,750 lines)

FastMCP-backed application exposing the Dhara substrate as MCP tools,
resources, and prompts. Removed in `0.21.0`. Subpackages affected:

- `dhara/mcp/adapter_tools.py` — `adapter_*` tool registrations
- `dhara/mcp/auth.py` — delegated auth wrappers (replaced by `mcp_common.auth`)
- `dhara/mcp/ecosystem_state.py` — `ecosystem_*` resources
- `dhara/mcp/kv_timeseries.py` — time-series key/value resources
- `dhara/mcp/signer_feed.py` — ed25519 signer feed
- `dhara/mcp/skill_registry.py` / `agent_registry.py` — server-published skill/agent catalogs
- `dhara/mcp/group_registers.py` — grouping registers
- `dhara/mcp/otel_traces.py` — OpenTelemetry trace ingestion (`dhara_query_local_traces`)
- `dhara/mcp/sql_proxy.py` — SQL proxy routes
- `dhara/mcp/substrate_routes.py` — HTTP CRUD routes for substrate (`/adapters/{id}/active-settings-version`, `/tenants/{id}/context-versions`, `/workflows/{id}/progress-snapshots`)
- `dhara/mcp/tools/` — subdirectory of additional tool modules
- `dhara/mcp/server.py` — legacy stub, already a deleted-on-import shim
- `dhara/mcp/agents/*.md` — server-published agent catalogs
- `dhara/mcp/skills_catalog/*.md` — server-published skill catalogs
- `dhara/mcp/README.md`, `dhara/mcp/QUICKSTART.md` — operator docs

The MCP server was Dhara's only public MCP integration. Consumers that
need a Dhara-backed MCP server must re-create it on top of `mcp-common`
(or the replacement noted in [Section 3](#section-3-where-to-find-replacements)).

### 2.2 `dhara/audit/` (entire package)

The Bodai D-AUDIT audit-log substrate. Engine-side `dhara_audit_log`
table (created in migration `0001_initial.sql`) is **untouched** — this
removal only deletes the substrate wrappers, not the SQL table.
Removed in `0.21.0`.

### 2.3 `dhara/skills_signer/` (entire package)

Bodai ed25519 skill/agent distribution infrastructure. Not a general-
purpose Dhara API. Removed in `0.21.0`.

### 2.4 `dhara/lock/` (entire package, 7 modules)

Removed in `0.22.0`. Substrate-compat shim rot cleanup — 1 `DharaLock`
Protocol and 3 implementations (`InMemoryDharaLock`, `SQLBackendLock`,
`PostgresBackendLock`) with **zero active consumers** in `mahavishnu/`,
`akosha/`, `session-buddy/`, `crackerjack/`, `mcp-common/`, `oneiric/`,
or `medium-mcp/`. The lock primitive has been re-homed to
`mahavishnu.core._lock_sentinel.Lock`.

### 2.5 Bodai-flavored schemas (6 files in `dhara/schema/`)

Removed in `0.21.0`. The package's `__init__.` now re-exports only
`channel_session_state`, plus the internal `_base` and `_registry`:

| Removed schema | Last version | Notes |
|---|---|---|
| `dhara.schema.approval_log` | `dhara<=0.20.2` | (deleted) |
| `dhara.schema.audit_record` | `dhara<=0.20.2` | (deleted) |
| `dhara.schema.capability_descriptor` | `dhara<=0.20.2` | (deleted) |
| `dhara.schema.ecosystem_run_record` | `dhara<=0.20.2` | (deleted) |
| `dhara.schema.webhook_ingress` | `dhara<=0.20.2` | (deleted) |
| `dhara.schema.workflow_outcome` | `dhara<=0.20.2` | (deleted) |

`dhara.schema._registry.SCHEMA_REGISTRY` survives with one entry
(`channel_session_state`); only the entity classes are removed.

### 2.6 CLI MCP subcommand group

Removed in `0.21.0`. `dhara mcp {start,stop,restart,status,health}` no
longer exists. The remaining CLI surface is `db` / `admin` / `storage`
/ `adapters` plus the Oneiric-inherited `version` / `doctor` / `health`
helpers on `DharaCLI(OneiricCLIBase)`.

### 2.7 Entry point

Removed in `0.21.0`. The `[project.entry-points."bodai.apps"]` entry
point was dropped — no consumer remained post-Wave-1.

### 2.8 Test files (~50 files exercising deleted modules)

`tests/unit/mcp/`, `tests/integration/mcp/`, `tests/unit/audit/`,
`tests/integration/audit/`, `tests/unit/lock/`, and the top-level
`tests/test_mcp_*.py` / `tests/test_skills_signer*.py` files were all
deleted alongside their substrate.

## Section 3: Where to find replacements

| Old Dhara surface | Replacement | Notes |
|---|---|---|
| `dhara/mcp/` (server, tools, agents, skills) | none — no current Bodai component hosts a Dhara-backed MCP server | The Mahavishnu orchestrator's MCP server (`mahavishnu/mcp/server_core.py`) exposes Bodai-wide capabilities and is the substrate to it. |
| `dhara.lock.{DharaLock, InMemoryDharaLock, SQLBackendLock, PostgresBackendLock}` | `mahavishnu.core._lock_sentinel.Lock` | Re-homed per the MCP retirement plan's Phase 8 Task 5. |
| `dhara.audit.*` (substrate wrappers) | none — the engine-side `dhara_audit_log` table is unchanged | If you depended on the substrate (not just the table), re-implement the wrapper against your own audit pipeline. |
| `dhara.skills_signer.*` | none | Was Bodai-specific skill/agent distribution. Replace with whatever your application uses for skill/agent registry. |
| `dhara.schema.{approval_log, audit_record, capability_descriptor, ecosystem_run_record, webhook_ingress, workflow_outcome}` | none in `dhara.*` | These were Bodai-shaped entities, not general Dhara concepts. The substrate equivalents now live inside the component that owned each one (Mahavishnu, Akosha, Session-Buddy, Crackerjack, mcp-common). |
| `dhara.cli.OneiricCLIBase` (formerly `BodaiCLIBase`) | `oneiric.cli.base.OneiricCLIBase` | Already in `oneiric`; no Dhara-specific replacement. |
| Substrate `settings` / `context` / `progress` writes (formerly `dhara/mcp/substrate_routes.py`) | oneiric's adapter-backed substrate | See `oneiric.adapters.*`. |

## Section 4: Dependency changes

The following runtime / dev dependencies were dropped from `pyproject
when their consumers were removed:

| Dropped dep | Reason | Last version |
|---|---|---|
| `fastmcp` | `dhara/mcp/` deleted | `dhara<=0.20.2` |
| `mcp-common` (runtime) | no consumers after `dhara/mcp/` removal | `dhara<=0.20.2` |
| `uvicorn` | no consumers after `dhara/mcp/` removal | `dhara<=0.20.2` |
| `creosote` (used as exclude-deps plugin) | no longer needed | `dhara<=0.20.2` |
| `[dependency-groups] otel-traces` (whole group: `akosha>=0.17.1` + MCP `query_local_traces` backing) | `dhara_query_local_traces` deleted | `dhara<=0.20.2` |
| `[dependency-groups] dev: session-buddy>=0.19.9` | no consumers after `dhara/mcp/` removal | `dhara<=0.20.2` |

If your consumer pulled Dhara for one of these transitive deps, add
the dep directly to your own `pyproject.toml`.

## Section 5: Reference

- [`mahavishnu/docs/adr/019-dhara-decommissioning.md`](../mahavishnu/docs/adr/019-dhara-decommissioning.md)
  — the architectural decision that retired Dhara from the Bodai core
  fleet as of 2026-10-17.
- [`CHANGELOG.md`](CHANGELOG.md) — full per-release changelog (latest
  removals are in the `0.21.0` and `0.22.0` entries; the `Unreleased`
  section describes the Wave-2 substrate cleanup in detail).
- [`README.md`](README.md) — current standalone-library overview.
- [`oneiric`](https://github.com/lesleslie/oneiric) — substrate, adapter
  registry, settings/context/progress substrate, and `OneiricCLIBase`.