"""Regression test: ``DharaMCPServer.run`` signature.

The cross-checker cleanup in 0.12.0 removed the legacy ``transport=``
keyword from ``DharaMCPServer.run`` (the FastMCP HTTP transport was
migrated to ``run_http_async``; ``run()`` now defaults to the stdio
transport). These tests guard the current shape of the symbol so a
future regression that re-introduces the keyword is detected early.
"""

from __future__ import annotations

import inspect

from dhara.mcp.server_core import DharaMCPServer


def test_run_signature_omits_transport_kwarg() -> None:
    """``DharaMCPServer.run`` should no longer accept a ``transport=`` kwarg.

    The HTTP transport moved to ``run_http_async``; ``run()`` is now
    stdio-only.
    """
    sig = inspect.signature(DharaMCPServer.run)
    assert "transport" not in sig.parameters, (
        "DharaMCPServer.run should not accept transport=; the FastMCP HTTP "
        f"transport was migrated to run_http_async. Got parameters: {list(sig.parameters)!r}"
    )


def test_main_function_signature_still_simple() -> None:
    """``main()`` in dhara.mcp.__main__ should still be a no-arg callable."""
    import dhara.mcp.__main__ as main_mod

    sig = inspect.signature(main_mod.main)
    assert list(sig.parameters) == [], (
        f"dhara.mcp.__main__.main should take no arguments; got {sig.parameters!r}"
    )
