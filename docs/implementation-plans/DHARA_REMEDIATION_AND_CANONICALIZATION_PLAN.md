# Dhara Remediation And Canonicalization Plan

## Purpose

This plan turns the current Dhara review findings into an execution roadmap that:

- fixes packaging and installability issues
- removes active naming drift across `dhara`, `druva`, and `durus`
- consolidates the MCP server surface
- hardens lifecycle, configuration, and test reliability
- strengthens Dhara's role as the durable storage layer in the Bodai ecosystem

## Working Assumptions

- Canonical runtime identity is `dhara`
- `druva` and `durus` remain only as explicit compatibility layers where needed
- `crackerjack` is the primary quality runner for local validation and CI orchestration
- direct commands such as `pytest`, packaging smoke tests, and import checks still exist, but they should be invoked via `crackerjack` in the standard workflow where practical

## Outcomes

By the end of this plan, Dhara should be:

- installable as a normal package, not only from an editable checkout
- internally consistent in naming and imports
- testable and CI-verifiable with one documented validation path
- safe for Mahavishnu and sibling services to depend on as ecosystem infrastructure
- explicit about compatibility boundaries and migration support

## Guiding Decisions

### Canonical Naming

- Canonical package and service name: `dhara`
- Legacy import compatibility names: `druva`, `durus`
- New active code must not introduce `Druva*` or `Durus*` primary symbols

### Validation And CI

- `crackerjack` is the primary entrypoint for quality gates
- baseline commands should include:
  - `python -m crackerjack qa-health`
  - `python -m crackerjack run-tests`
- direct validation commands remain useful for debugging:
  - `pytest`
  - packaging smoke tests
  - install/import checks
  - focused MCP startup and lifecycle smoke tests

### Compatibility Policy

- Compatibility support must be isolated into dedicated shims and migration code
- Old names may remain only for:
  - import compatibility
  - serialized data compatibility
  - documented migration paths
- Compatibility code must be clearly marked deprecated

## Phase 1: Canonical Identity And Naming Cleanup

### Goals

- eliminate active naming drift
- define explicit compatibility boundaries
- stop new drift from re-entering the codebase

### Tasks

1. Inventory all occurrences of `Dhara`, `Druva`, `Durus`, `dhara`, `druva`, and `durus`
2. Classify occurrences as:
   - active runtime code
   - compatibility shim
   - stale docs/comments/examples
   - tests
   - serialization compatibility
3. Rename active code paths to canonical `Dhara*` names
4. Move legacy aliases behind dedicated compatibility modules
5. Update tests to target canonical symbols first
6. Add lint or grep-based guardrails in CI to prevent new active `Druva*` symbols outside compat zones

### Deliverables

- one canonical naming map
- one explicit compatibility layer for old names
- no active runtime module importing stale `Druva*`/`Durus*` symbols outside compat code

### Acceptance Criteria

- `rg` over active code shows old names only in compat, migration, or serialization-specific files
- CLI, MCP entrypoints, config classes, and docs all use `dhara` naming consistently

## Phase 2: Packaging And Installability

### Goals

- make Dhara installable and runnable from wheel and source distributions
- ensure subpackages are actually shipped

### Tasks

1. Replace manual setuptools package declaration with package discovery
2. Verify all `dhara.*` subpackages are included
3. Confirm console script installation works from built artifacts
4. Add packaging smoke tests:
   - build wheel
   - install in clean environment
   - run `dhara --help`
   - import key modules
5. Add packaging validation to `crackerjack` or CI wrapper jobs

### Deliverables

- corrected `pyproject.toml`
- packaging smoke test job
- documented install path for contributors and downstream consumers

### Acceptance Criteria

- clean environment can install Dhara and access `dhara.core`, `dhara.storage`, `dhara.mcp`, and CLI entrypoints
- package install no longer depends on editable checkout behavior

## Phase 3: Import Hygiene And Optional Dependency Strategy

### Goals

- make core imports reliable
- stop optional features from breaking base imports

### Tasks

1. Audit eager imports from top-level package modules
2. Convert serializer backend loading to lazy import patterns
3. Define optional dependency groups:
   - core
   - mcp
   - admin
   - backup
   - dev
4. Reduce `dhara/__init__.py` import fan-out
5. Ensure missing optional dependencies fail only at point of use with clear messages

### Deliverables

- lazy serializer backend loading
- reduced top-level import coupling
- dependency group documentation

### Acceptance Criteria

- `import dhara` succeeds in a minimal supported install
- optional backends produce clean runtime errors instead of package import failure

## Phase 4: MCP Consolidation

### Goals

- keep one supported MCP server implementation
- align code, tests, and docs around the same contract

### Tasks

1. Make FastMCP server in `dhara/mcp/server_core.py` the canonical MCP implementation
2. Audit `dhara/mcp/server.py` and either:
   - migrate missing features into the canonical server, or
   - move it behind a legacy/deprecated boundary
3. Standardize tool naming and tool semantics
4. Align auth documentation with implemented behavior
5. Add MCP smoke tests for:
   - startup
   - health endpoints
   - basic read/write flow
   - adapter registry operations

### Deliverables

- one canonical MCP entrypoint
- one maintained tool surface
- one current set of docs and examples

### Acceptance Criteria

- no duplicate "current" MCP server implementations remain
- docs reflect the server that actually runs

## Phase 5: Runtime Lifecycle And Operational Hardening

### Goals

- ensure Dhara behaves predictably as a long-running ecosystem service
- fix shutdown, restart, and readiness behavior

### Tasks

1. Implement full resource cleanup in `DharaMCPServer.close()`
2. Ensure file storage locks and handles are released on shutdown
3. Review and tighten health/readiness semantics
4. Standardize main-port `/health`, `/healthz`, and `/metrics`
5. Retire or clearly deprecate standalone metrics server if no longer needed
6. Add restart-loop smoke tests

### Deliverables

- deterministic shutdown behavior
- lifecycle smoke tests
- updated operator docs for startup and restart behavior

### Acceptance Criteria

- repeated start/stop cycles do not leave stale locks or unusable storage state
- health endpoints reflect real readiness, not only process liveness

## Phase 6: Test System Repair And CI Credibility

### Goals

- make the test suite representative and trustworthy
- converge on one documented quality workflow

### Tasks

1. Normalize test layout under one canonical test root
2. Fix stale imports and broken tests caused by rename drift
3. Repair obvious integration test issues
4. Align `pytest` discovery with actual test layout
5. Define test layers:
   - unit
   - integration
   - compatibility
   - smoke
6. Route standard validation through `crackerjack`
7. Add CI jobs for:
   - lint
   - type check
   - security
   - tests
   - packaging

### Deliverables

- corrected test discovery
- green baseline test suite in documented dev environment
- `crackerjack`-driven CI pipeline

### Acceptance Criteria

- documented validation commands pass in a fresh contributor setup
- CI proves packaging, imports, lifecycle, and tests separately

## Phase 7: Configuration Model Unification

### Goals

- eliminate parallel config systems that drift independently
- define one canonical operator-facing configuration model

### Tasks

1. Choose the canonical settings system
2. Collapse overlapping config implementations where possible
3. Make `DHARA_*` the canonical env var prefix
4. Support `DRUVA_*` and `DURUS_*` only via compatibility if required
5. Align config docs and examples to the canonical model
6. Add config validation tests for:
   - path handling
   - ports
   - storage backend selection
   - auth config
   - backup config

### Deliverables

- one canonical `DharaSettings` path
- compatibility adapter for old config names if needed
- updated operator documentation

### Acceptance Criteria

- contributors and operators have one clear way to configure Dhara
- old prefixes are either supported explicitly or removed deliberately

## Phase 8: Dhara As Ecosystem Infrastructure

### Goals

- make Dhara a reliable substrate for Mahavishnu and sibling services
- turn current useful ideas into supported interfaces

### Tasks

1. Define Dhara's supported ecosystem responsibilities:
   - durable KV state
   - adapter registry
   - time-series records
   - backup and restore substrate
   - event and audit persistence
2. Design stable persisted schemas for:
   - service registrations
   - capabilities
   - health snapshots
   - leases/heartbeats
   - orchestration event logs
3. Add versioning and migration strategy for persisted structures
4. Strengthen backup and restore verification
5. Add documented Mahavishnu integration patterns

### Deliverables

- ecosystem-facing data model
- migration/versioning rules
- backup/recovery validation coverage

### Acceptance Criteria

- Mahavishnu can depend on Dhara for durable shared state with documented interfaces
- restore and recovery workflows are tested and repeatable

## Phase 9: Documentation And Migration Support

### Goals

- remove ambiguity for maintainers and downstream consumers
- make the repo readable again after cleanup

### Tasks

1. Rewrite README around the current truth
2. Add migration guide:
   - `durus` to `druva`
   - `druva` to `dhara`
   - import migration
   - config migration
   - compatibility notes
3. Update MCP docs to match actual implementation
4. Update operator docs for:
   - startup
   - health endpoints
   - backup/restore
   - upgrade flow
5. Archive stale docs that describe superseded implementations

### Deliverables

- current README
- migration guide
- cleaned documentation hierarchy

### Acceptance Criteria

- no current-facing doc points users to stale class names or obsolete workflows

## Milestones

### Milestone 1: Dhara Canonical

- naming cleanup complete
- active code uses canonical `dhara` identity
- compat boundaries defined

### Milestone 2: Dhara Installable

- package discovery fixed
- build/install smoke tests passing
- import hygiene improved

### Milestone 3: Dhara Operational

- MCP surface consolidated
- lifecycle cleanup implemented
- health/metrics behavior stable

### Milestone 4: Dhara Verified

- test layout repaired
- `crackerjack` quality workflow documented and green
- CI reflects real repository health

### Milestone 5: Dhara Ecosystem-Ready

- stable durable-state interfaces defined
- backup/recovery confidence improved
- Mahavishnu integration patterns documented

## Recommended Command Baseline

Use `crackerjack` as the default quality workflow:

```bash
python -m crackerjack qa-health
python -m crackerjack run-tests
```

Keep focused direct commands available for debugging and lower-level verification:

```bash
pytest
pytest -m unit
pytest -m integration
python -m build
python -m pip install dist/*.whl
dhara --help
dhara mcp health
```

## Initial Backlog Recommendation

Start in this order:

1. canonical naming inventory and cleanup
2. packaging fix and clean-install smoke tests
3. lazy import and optional dependency cleanup
4. MCP consolidation
5. lifecycle/shutdown hardening
6. test discovery repair and `crackerjack` CI integration
7. config unification
8. ecosystem API/schema design
9. docs and migration cleanup

## Definition Of Done

This plan is complete when:

- Dhara installs and runs cleanly from packaged artifacts
- active code uses `dhara` naming consistently
- compatibility support is explicit and isolated
- `crackerjack` is the documented and enforced CI workflow
- the test suite is credible and green in a clean environment
- Mahavishnu and related services have a stable, documented Dhara integration surface
