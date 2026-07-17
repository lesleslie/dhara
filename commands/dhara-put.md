---
description: Store a value in Dhara under a key, optionally with TTL.
---

# /dhara:put

Persist a JSON-serializable value to Dhara state under a specified key.

## Usage

```
/dhara:put
```

## What This Command Does

1. **Collects the key and value** — identifies the target key path and the payload to store.
2. **Persists to Dhara** — writes the value via the Dhara state MCP server.
3. **Confirms the write** — returns the key and a confirmation of the stored payload.

## Technical Implementation

This command uses the `mcp__dhara__put` MCP tool which:
- accepts a key path and a JSON-serializable value
- optionally honors a TTL for time-bounded state

## When to Use

- caching a computed result under a stable key
- persisting workflow state across steps or repos
- storing small configuration blobs for other Bodai components to read
