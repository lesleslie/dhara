# Dhara MCP Tool Profile — Rationale (W1.4 backfill, 2026-08-18)

**Status:** Backfilled 2026-08-19 (post-W1.4 wave; this doc was absent during
the original W1.4 dispatch because the rationale-doc convention was formalized
during W2+).

**Wave:** W1 (backfill) — adopted `apply_tool_profile()` before the formal plan.
**Helper:** `mcp_common.tools.dispatch._apply_tool_profile` (mcp-common 0.18.0+).
**Env var:** `DHARA_TOOL_PROFILE` (defaults to `FULL`).

## Context

Dhara is the Bodai ecosystem's curator/state store (port 8683). Pre-W1,
DharaMCPServer.\_register_tools was a 600+ line inline body that registered
~25 tools in five groups unconditionally. W1.4 replaced that body with the
W0 dispatch surface so the four groups can be gated by operator profile.

## Profile Tiers

Defined in `dhara/mcp/profiles.py`:

| Tier | Groups included | Operator profile |
|------|-----------------|------------------|
| **MINIMAL** | `kv_time_series` only | Probe / status-check clients; basic key/value ops |
| **STANDARD** | `kv_time_series` + `adapter_registry` + `ecosystem_state` + `sql_proxy` | Day-to-day state management |
| **FULL** | identical to STANDARD | Trivial alias tier-A mapping (kept for symmetry with other Tier-A adopters) |

Health tools (`get_liveness`, `get_readiness`, `health_check_service`, etc.)
are NOT in any per-profile list — they sit in `DHARA_MANDATORY_GROUPS` so the
W0 helper re-registers them at every profile without duplication.

## Why these groupings

- **MINIMAL = kv_time_series** — the cheapest useful surface. Any LLM that
  needs to read/write ephemeral ecosystem state can do so without paying for
  adapter introspection or SQL proxy schemas.
- **STANDARD = everything else** — `adapter_registry`, `ecosystem_state`,
  `sql_proxy` are the day-to-day surfaces an operator uses when managing
  adapters or running queries through Dhara.
- **FULL = STANDARD** — Dhara has no additional heavy/experimental group
  worth gating separately, so FULL aliases STANDARD. This is consistent with
  the Tier-A trivial mapping convention used across the 9 + 1 (fastblocks opt-out)
  Tier-A adopters.

## Configuration

Env-only. `get_active_profile()` reads from `DHARA_TOOL_PROFILE` via
`ToolProfile.from_env`. Missing or invalid values fall back to `FULL`.

There is no `settings_yaml_loader` — Dhara does not expose a `tool_profile`
key in its YAML.

## Cross-Repo / Architectural Notes

- **No per-group `_register_<group>()` methods:** Dhara's pre-W1
  `_register_tools` was the largest inline body across all W1 backfills.
  W1.4 extracted per-group register functions into
  `dhara/mcp/tools/group_registers.py`. Each takes `(server, instance)` where
  `instance` is the DharaMCPServer (for `self._async_kv_store` and friends).
- **Lazy registration map:** Because per-group registrars need a live
  DharaMCPServer instance (for async stores), `REGISTRATION_MAP` is built
  lazily via `_build_registration_map()` inside
  `DharaMCPServer._register_tools_async` AFTER async stores are initialized.
  This avoids the circular-import trap of building the map at module load.
- **W0.5 fix loop (round 1):** W1.4 had a 52-vs-51 test count slip caught at
  review; fixed before merge.

## Tests

`dhara/tests/unit/test_wiring.py` — 17 wiring tests. Plus the golden fixtures
at `tests/fixtures/{minimal,standard,full}/tool_names.json` (captured before
the refactor per the W1 golden-fixture protocol).

## References

- Master plan: `docs/superpowers/plans/2026-08-18-mcp-tool-profile-adoption.md`
- Helper source: `/Users/les/Projects/mcp-common/mcp_common/tools/dispatch.py`
- Profiles module: `dhara/mcp/profiles.py`
- Per-group register fns: `dhara/mcp/tools/group_registers.py`
- Dispatch call site: `dhara/mcp/server_core.py`
