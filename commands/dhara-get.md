---
description: Retrieve a stored value from Dhara by key.
---

# /dhara:get

Fetch a previously stored value from Dhara state by its key.

## Usage

```
/dhara:get
```

## What This Command Does

1. **Collects the key** — identifies which stored value to retrieve.
2. **Reads from Dhara** — fetches the value via the Dhara state MCP server.
3. **Returns the payload** — surfaces the stored value (or a not-found signal).

## Technical Implementation

This command uses the `mcp__dhara__get` MCP tool which:
- reads a single key path from Dhara state
- returns the stored JSON value or indicates absence

## When to Use

- verifying that a previous `/dhara:put` (or external write) landed correctly
- reading shared state before starting a multi-step task
- inspecting cached values when debugging cross-repo orchestration
