"""Dhara MCP (Model Context Protocol) server package."""

import importlib.metadata

from dhara.mcp.server_core import DharaMCPServer

__all__ = [
    "DharaMCPServer",
]

# Version is read from the installed package metadata so ``dhara.mcp.__version__``
# always matches ``pyproject.toml`` (currently 0.15.1). ``importlib.metadata``
# is the canonical way to introspect installed distributions without
# importing the package; this avoids the constant-drift trap when the
# version is bumped via ``crackerjack run -p minor``.
try:
    __version__ = importlib.metadata.version("dhara")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0+unknown"