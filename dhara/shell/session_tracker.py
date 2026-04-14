"""Session tracker for Dhara admin shell.

This module provides Session-Buddy MCP integration for tracking
Dhara admin shell sessions.
"""

from __future__ import annotations

import logging

from oneiric.shell.session_tracker import SessionEventEmitter

logger = logging.getLogger(__name__)


class DharaSessionTracker(SessionEventEmitter):
    """Session tracker for Dhara admin shell.

    Extends Oneiric SessionEventEmitter with Dhara-specific metadata
    for session tracking via Session-Buddy MCP.
    """

    def __init__(
        self,
        component_name: str = "dhara",
    ):
        """Initialize Dhara session tracker.

        Args:
            component_name: Component name for session tracking
        """
        super().__init__(component_name=component_name)


DruvaSessionTracker = DharaSessionTracker

__all__ = ["DharaSessionTracker", "DruvaSessionTracker"]
