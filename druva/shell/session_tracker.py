"""Session tracker for Druva admin shell.

This module provides Session-Buddy MCP integration for tracking
Druva admin shell sessions.
"""

from __future__ import annotations

import logging

from oneiric.shell.session_tracker import SessionEventEmitter

logger = logging.getLogger(__name__)


class DruvaSessionTracker(SessionEventEmitter):
    """Session tracker for Druva admin shell.

    Extends Oneiric SessionEventEmitter with Druva-specific metadata
    for session tracking via Session-Buddy MCP.
    """

    def __init__(
        self,
        component_name: str = "druva",
    ):
        """Initialize Druva session tracker.

        Args:
            component_name: Component name for session tracking
        """
        super().__init__(component_name=component_name)


__all__ = ["DruvaSessionTracker"]
