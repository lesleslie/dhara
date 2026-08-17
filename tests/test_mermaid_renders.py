"""Wave-11 CI guard: every fenced mermaid block in this repo must parse.

Wraps `dhara.tools.mermaid_validator.renderer.find_broken_mermaid_blocks`,
which uses `mermaid.parse()` via Node.js (no chrome dependency). Mirrors
the ratchet pattern established by `tests/unit/test_mcp_tool_inventory.py`
but for diagram syntax instead of tool counts.

If this test fails, run:
  python -c "from dhara.tools.mermaid_validator.renderer import find_broken_mermaid_blocks; [print(e) for e in find_broken_mermaid_blocks()]"
to see the broken blocks directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dhara.tools.mermaid_validator.renderer import (
    extract_mermaid_blocks,
    find_broken_mermaid_blocks,
)


def test_all_mermaid_blocks_parse() -> None:
    """Every fenced ```mermaid block in the repo must parse via mermaid.parse()."""
    try:
        errors = find_broken_mermaid_blocks(root=Path(__file__).resolve().parent.parent)
    except RuntimeError as exc:
        pytest.fail(f"mermaid validator unavailable: {exc}")
    if errors:
        formatted = "\n".join(f"  {e.relpath}:{e.line}  {e.error}" for e in errors)
        pytest.fail(f"{len(errors)} broken mermaid block(s):\n{formatted}")


def test_extract_mermaid_blocks_finds_expected_count() -> None:
    """Sanity check: the extractor should find at least one block in the repo."""
    repo_root = Path(__file__).resolve().parent.parent
    blocks_path = repo_root / "docs" / "architecture" / "MEMORY_ARCHITECTURE.md"
    if blocks_path.exists():
        blocks = extract_mermaid_blocks(blocks_path)
        assert len(blocks) >= 1, f"expected at least one mermaid block in {blocks_path}"
