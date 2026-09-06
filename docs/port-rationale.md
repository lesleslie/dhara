# Dhara Port Rationale

Why the Dhara storage server defaults to `8685`, and how that number
was chosen against the [Bodai port map](https://github.com/lesleslie/bodai/blob/main/docs/portmap.md).

## Tl;dr

| Dhara service | Default port | Status |
|--------------------------------|--------------|-----------------------------------------|
| **Dhara Storage Server** | `8685` | This document explains the choice |
| **Dhara MCP Server** | `8683` | Documented in the Bodai port map |

The two services share a project but answer on different ports. Inside
a Bodai deployment the MCP server is the externally-addressable surface;
the storage server is reachable in-process or via this dedicated socket
when a non-MCP client needs raw object-DB access.

## The previous default (pre-standardisation)

Before this change, Dhara's storage server defaulted to `2972`. That was
a legacy carry-over from the original Durus project, not a Bodai-ecosystem
allocation. It was never updated when Dhara became the curator component
of the Bodai control plane, and the Bodai port map only enumerates `8683`
for "Druva / Dhara Curator" without mentioning the storage-server port.

This caused two observable drift signals:

1. The port map's "Available" column for `8684-8699` listed `8684` as
   unallocated. In practice, **port `8684` was already taken by
   `fastblocks`** — discovered via grep against `mahavishnu/tests/integration/`,
   WebSocket deployment docs, and active `fastblocks/` repo integrations.
1. Dhara itself contained the same latent collision in `modes/standard.py`
   and `modes/lite.py` — startup-error hint strings referenced
   `dhara start --mode={...} --port=8684` against that already-allocated
   port. The hint would have failed any real-world user who tried it.

Akosha had an equivalent collision in `akosha/docs/guides/operational-modes.md`.

## The selection process

Three candidate slots were considered after ruling out conflicts:

| Slot | Band | Notes |
|---------|------------------------------|----------------------------------------------------------------------------------------|
| `8684` | 868x core services | **Ruled out — owned by fastblocks** |
| `8685` | 868x core services | **Chosen.** One slot to the right of MCP `:8683`, paired adjacency with breathing room|
| `8679` | 867x infrastructure | Technically free, but the port map convention says 868x is for storage-class services |

Choosing a slot in the same `868x` core-services band as the MCP server
keeps Dhara-related ports visually grouped in the port map. Picking `8685`
(one past `8684` to honour fastblocks' existing allocation) preserves
the "Dhara MCP :8683, Dhara Storage :8685" pair-reading with a one-port
buffer that documents the boundary.

## The conflict scan

A grep across the live Bodai workspace (`akosha`, `dhara`, `session-buddy`,
`crackerjack`, `mahavishnu`, `oneiric`, `bodai`, `mcp-common`) plus the
user-level config roots (`~/Library/LaunchAgents`, `~/.config`,
`~/.claude`) produced this list of references to `8684`:

| Reference | Verdict |
|-------------------------------------------------------------|---------------------------------------------------|
| `mahavishnu/tests/integration/test_cross_service_websocket.py:17,76` | Real conflict — fastblocks active service |
| `mahavishnu/tests/integration/test_websocket_integration.py:10,68` | Real conflict |
| `mahavishnu/.claude/worktrees/.../docs/WEBSOCKET_DEPLOYMENT.md` | Real conflict — `ufw allow 8684/tcp # fastblocks` |
| `dhara/dhara/modes/standard.py:358`, `modes/lite.py:125` | Latent internal collision — defer to follow-up |
| `akosha/docs/guides/operational-modes.md:525` | Latent internal collision (Akosha) |

The Dhara-internal collisions in `modes/*.py` are deferred to a follow-up
commit so this change stays scoped to the storage-server default-port
migration. The Akosha collision is out of scope for this repo.

## What this change does and does not do

**Does:**

- Change `DEFAULT_PORT` and the related `typer.Option` defaults in
  `dhara/server/server.py`, `dhara/cli.py`, `dhara/config/defaults.py`,
  and `dhara/config/loader.py`.
- Update the `test_config_defaults.py` canary that asserts
  `StorageConfig.port == 8685`.
- Refresh deployment configs (Kubernetes, `production.yaml`,
  `healthcheck.sh`, `deploy.sh`), the disaster recovery runbook, and the
  service-dependencies reference doc.
- Add a `CHANGELOG.md` entry under `[Unreleased]` — version bump
  sequencing left to the maintainer.

**Does not (deferred):**

- Fix the `dhara/modes/{standard,lite}.py` startup-hint strings still
  referencing `:8684`. Those are error-message strings, not behavioural
  defaults — a separate commit reduces review burden.
- Touch any `uv.lock` hash bytes that incidentally contain `2972`.
  Lockfile integrity beats port consistency.
- Update the Bodai port map (`bodai/docs/portmap.md`). That doc still
  names the curator as "Druva" — a separate name-drift item worth flagging.

## Operations notes

If you ran a Dhara deployment that was explicitly pinned to `2972`
(via `DHARA_PORT` env var, `port:` in your `production.yaml`, or
`--port` CLI flag), **no action is required on your part.** The default
shift only affects fresh `dhara db start` invocations without overrides.
Documented overrides continue to win.

If you did rely on the storage server speaking on `2972` and you want
to keep that port — set `DHARA_PORT=2972` in the environment for the
storage-server process. There is no deprecation window for the explicit
override; the default is just no longer `2972`.
