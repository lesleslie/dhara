"""Regression test for Plan 7 Phase 2: explicit ``transport=`` kwarg.

FastMCP 3.x made ``transport=`` a required kwarg for ``server.run()``
(in 2.x it was optional / positional-friendly). The breaking-change table
in the plan flags ``dhara/mcp/__main__.py:16`` as the lone remaining
implicit call site.

This test inspects the source of ``dhara.mcp.__main__`` and asserts the
``server.run(...)`` call passes the transport kwarg explicitly so that
the runtime intent is unambiguous on FastMCP 3.x.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "dhara" / "mcp" / "__main__.py"


def _read_source() -> str:
    return MAIN_PY.read_text(encoding="utf-8")


def test_main_module_uses_transport_kwarg() -> None:
    """``dhara/mcp/__main__.py`` must call ``server.run(transport=...)`` explicitly."""
    source = _read_source()
    # Match server.run(...) — transport= may be inside the parens.
    run_calls = re.findall(r"server\.run\([^)]*\)", source)
    assert run_calls, "expected at least one server.run(...) call in __main__.py"
    for call in run_calls:
        assert "transport=" in call, (
            f"server.run() call {call!r} in dhara/mcp/__main__.py is missing "
            f"the explicit transport= kwarg required by FastMCP 3.x."
        )


def test_main_function_signature_still_simple() -> None:
    """``main()`` in dhara.mcp.__main__ should still be a no-arg callable."""
    import dhara.mcp.__main__ as main_mod

    sig = inspect.signature(main_mod.main)
    assert list(sig.parameters) == [], (
        f"dhara.mcp.__main__.main should take no arguments; got {sig.parameters!r}"
    )
