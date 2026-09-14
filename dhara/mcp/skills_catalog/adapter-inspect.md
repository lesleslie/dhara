---
name: adapter-inspect
description: Use ONLY when the user explicitly types `/dhara:adapter-inspect` or selects this Skill from the picker to inspect a Oneiric adapter, list its versions, or walk the rotation-key flow. Do not auto-trigger. Routes through `mcp__dhara__dhara_get_adapter` and `mcp__dhara__dhara_list_adapter_versions` to surface factory paths, configs, dependencies, and health for a (domain, key, provider) tuple.
allowed-tools: mcp__dhara__dhara_get_adapter, mcp__dhara__dhara_list_adapter_versions, mcp__dhara__dhara_get_adapter_health, Read
---

# adapter-inspect

## When to use

This Skill is the right entry point when the user wants to understand
which concrete Oneiric adapter Dhara will resolve for a given
`(domain, key, provider)` tuple — and what the rotation history looks
like when the same tuple has multiple registered versions. Common cases:

- "Which cache adapter is Dhara using right now?"
- "Show me every version of the `cache.redis` adapter that's been
  registered."
- "What's the factory path for the S3 storage adapter?"
- "Is the current `mailer.sendgrid` adapter marked healthy?"
- "Walk me through what happens when an adapter version is rotated."

The Skill drives `mcp__dhara__dhara_get_adapter` and
`mcp__dhara__dhara_list_adapter_versions` with sensible defaults and
explains how Dhara picks the active version.

## What `dhara_get_adapter` returns

The tool accepts `(domain, key, provider, version=None)` and returns a
single record:

```json
{
  "ok": true,
  "adapter": {
    "domain": "adapter",
    "key": "cache",
    "provider": "memory",
    "version": "1.2.0",
    "factory_path": "oneiric.adapters.cache.memory:MemoryCacheAdapter",
    "config": {"ttl": 300},
    "dependencies": [],
    "capabilities": ["ttl", "async"],
    "metadata": {"registered_by": "akosha"},
    "registered_at": "2026-09-08T12:34:56Z",
    "checksum": "sha256:..."
  }
}
```

- `factory_path`: the Python import path Dhara resolves at adapter
  load. If this class is missing or fails to import, Dhara falls back
  to the next-most-recent version (per Oneiric's resolver contract).
- `config`: kwargs passed verbatim to the factory callable.
- `dependencies`: adapter-level dependency list (other adapter keys
  that must be present for this one to function).
- `checksum`: opaque fingerprint Dhara uses to detect silent
  on-disk mutation.

When `version` is omitted, Dhara returns the **latest registered
version** for that tuple. The "latest" is registration-time
descending, not semantic-version descending — if the user expects
strict semver, they should query
`mcp__dhara__dhara_list_adapter_versions` first.

## Walking the rotation-key flow

When the same `(domain, key, provider)` has been registered multiple
times (typical during a rolling deploy or a rollback), Dhara keeps
every version reachable. The Skill walks the rotation flow as:

1. **List versions** —
   `mcp__dhara__dhara_list_adapter_versions(domain, key, provider)`
   returns every registered version in registration-time descending
   order. The first entry is the "current" version Dhara will return
   from `dhara_get_adapter` with no version arg.

2. **Inspect each version** — loop over the result and call
   `dhara_get_adapter(version=...)` to surface `factory_path`,
   `config`, and `checksum`. Two versions with the same `factory_path`
   but different `checksum` are the same code with different config
   blobs (often a tuning change, not a code change).

3. **Check health** — for the version that will actually be loaded,
   call `mcp__dhara__dhara_get_adapter_health(domain, key, provider)`.
   The health record carries `{last_resolved_at, last_error,
   resolution_count, recent_failures}` so the Skill can surface "this
   version failed to resolve at <timestamp>" without paging through
   logs.

4. **Compare checksums** — if the operator rotated the underlying
   library but kept the same `factory_path`, the `checksum` field will
   differ across versions. A change here is a strong signal that the
   rotation was a real change, not a no-op re-registration.

## When NOT to use

- For Oneiric-wide resolution rules (how the resolver picks one
  adapter among many), use Akosha's
  `mcp__akosha__akosha_get_resolution_rules`.
- For OTel traces of adapter resolution, use the OTel ingester's
  `search_traces("adapter resolution")` call.
- For raw key-value storage of an arbitrary dict, use
  `mcp__dhara__dhara_put` / `mcp__dhara__dhara_get` instead — the
  adapter registry is for **typed** adapter records only.

## Failure modes

- **Empty list from `list_adapter_versions`**: the tuple has never
  been registered. Surface "no registrations for
  `<domain>.<key>.<provider>`" — the user almost certainly wanted a
  different tuple.
- **`ok=False` from `dhara_get_adapter`**: the version they asked for
  is registered but Dhara can't deserialize it. Surface the `error`
  field verbatim.
- **`get_adapter_health` reports `last_error`**: surface the error
  AND the `resolution_count`. A version that has resolved 0 times
  since its `last_error` is effectively dead; suggest a rollback.

## Example flow

User: "What cache adapter is Dhara using, and is it healthy?"

Skill action:

```python
latest = await mcp__dhara__dhara_list_adapter_versions(
    domain="adapter",
    key="cache",
    provider="memory",
)
current_version = latest[0]["version"]

adapter = await mcp__dhara__dhara_get_adapter(
    domain="adapter",
    key="cache",
    provider="memory",
    version=current_version,
)
health = await mcp__dhara__dhara_get_adapter_health(
    domain="adapter",
    key="cache",
    provider="memory",
)
```

Synthesize: factory path, config, last-resolved-at, any recent
failures. If `last_error` is non-null, surface it FIRST.
