# Repository Guidelines

## Project Structure & Module Organization

- `dhara/` contains the package: core persistence logic in `core/`, storage backends in `storage/`, serialization in `serialize/`, persistent data structures in `collections/`, server code in `server/`, MCP integration in `mcp/`, and configuration or security helpers in `config/` and `security/`.
- Keep backend, serialization, and transport concerns separate; avoid coupling file storage, network client behavior, and MCP-facing features in the same modules.
- Tests live under `test/`; mirror package areas when adding new coverage and keep local build artifacts, compiled extension outputs, and coverage reports out of review.
- Use repo docs and focused design notes when behavior changes affect persistence guarantees, wire protocols, or TLS expectations.

## Build, Test, and Development Commands

- `pip install -e .` or `pip install -e ".[dev]"` installs the package for local development.
- `pytest` runs the full test suite; use `pytest -m unit`, `pytest -m integration`, or `pytest -m "not slow"` for narrower loops.
- `pytest --cov=dhara --cov-report=html` generates local coverage output in `htmlcov/`.
- `python -m crackerjack check`, `python -m crackerjack lint`, `python -m crackerjack format`, `python -m crackerjack typecheck`, and `python -m crackerjack security` cover the main quality workflows.
- `dhara -s`, `dhara -c`, and `dhara -p --file <path>` are the primary local smoke-test commands for server, client, and packing flows.
- `python setup.py build_ext --inplace` rebuilds the optional C extension when you touch `_persistent.c` or related extension wiring.

## Coding Style & Naming Conventions

- Use explicit type hints, narrow interfaces, and clear state transitions for persistence and transaction logic.
- Keep module names snake_case and preserve the layered split between persistence core, storage adapters, serializers, collections, and transports.
- Treat backwards compatibility and on-disk format stability as first-class concerns when changing serialization, storage, or connection behavior.

## Testing Guidelines

- Add tests for every substantive change, especially around transaction behavior, object state transitions, serialization compatibility, storage backends, and TLS-enabled client-server communication.
- Prefer deterministic persistence fixtures and explicit round-trip assertions for storage and serializer changes.
- Run targeted tests for the exact backend or serializer touched before relying on the full suite.
- Review `htmlcov/index.html` after larger changes to catch untested branches in error handling and recovery paths.

## Commit & Pull Request Guidelines

- Use focused commits such as `fix(storage): preserve index rebuild ordering` or `feat(tls): validate client cert chain`.
- PRs should describe compatibility impact, commands run for validation, and whether storage formats, wire behavior, or security defaults changed.
- Include logs, CLI transcripts, or migration notes when changing operator-facing or compatibility-sensitive behavior.

## Ecosystem Notes

- Dhara is the durable storage layer in the Bodai ecosystem and may be used directly by applications or indirectly through orchestrated workflows and MCP integrations.
- Preserve clear boundaries between core persistence features and ecosystem-specific integrations so the storage engine remains broadly reusable.

## Security & Configuration Tips

- Never commit real certificates, private keys, secrets, or machine-specific paths.
- Validate TLS, auth, and storage configuration inputs carefully, and treat persistence corruption or unsafe deserialization regressions as high-severity issues.
