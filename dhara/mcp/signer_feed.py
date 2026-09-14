"""Instance-owned signer feed state for Dhara's ``/health`` aggregator.

The :class:`SignerFeedState` is the :class:`DharaMCPServer` instance's
single source of truth for what the skills_signer feed reports to
``/health``. It bundles:

- the manifest itself (pure data, lives in :mod:`dhara.skills_signer`)
- the :class:`SkillsSigner` for producing Phase 1 ``get_skill`` /
  ``get_agent`` response signatures
- the four mandatory feed signals required by
  ``mcp-backend-wiring-discipline.md`` (``feed_entities_count``,
  ``feed_last_updated_timestamp``, ``cycles_total``, ``errors_total``)
- a ``generation`` token so concurrent-app teardown checks can
  verify ownership before clearing state

Why this lives in ``dhara/mcp/`` (not ``dhara/skills_signer/``):

The ``skills_signer`` package is supposed to replicate byte-for-byte
across the 5 Bodai servers. Lifecycle state (counters, timestamps,
generation tokens) is per-server MCP wiring concern. By keeping the
package pure data and adding the feed state here, the cross-server
package stays trivial to copy-paste and the per-server wiring
contract is explicit.

Dhara-specific: per plan §10.3.2, Dhara uses an INSTANCE-based
``_runtime_status`` model (different from both Akosha's async
lifespan AND Mahavishnu's module-level singleton). The state lives
on ``DharaMCPServer.signer_feed_state`` and is initialized inside
``__init__`` (after storage wiring) so the ``/health`` route closure
can already capture it by the time the route fires.

The :func:`init_signer_feed_state` helper is the canonical
constructor — it loads (or generates + persists) the ed25519
keypair, builds the manifest, attaches the :class:`SkillsSigner`,
and installs the state as the module-level singleton. The
``config=None`` lightweight path skips this entirely (the state is
left as ``None``); the audit-only test mode does not need a signing
identity.

Module-level helpers
--------------------

The lifespan constructor (:func:`init_signer_feed_state`) also
installs the state as a module-level singleton so Phase 1
``list_skills`` / ``get_skill`` MCP tools can read the signer
without taking it as a function parameter (mirrors the akosha
pattern). The other 4 Bodai servers (mahavishnu / session-buddy /
akosha / crackerjack) use the same module-level pattern with their
own state classes; Phase 2's installer reads ``/health`` directly,
not these helpers, so the API stays per-server.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dhara.skills_signer import PubkeyManifest, SkillsSigner

logger = logging.getLogger(__name__)


@dataclass
class SignerFeedState:
    """Instance-owned state for the skills_signer ``/health`` feed.

    Constructed at :class:`DharaMCPServer` init time after the keypair
    is loaded/persisted and the manifest is built. Mutation happens
    only via the :meth:`record_cycle` / :meth:`record_error` helpers
    so the ``last_updated_timestamp`` stays consistent with the cycle
    counter.

    Attributes:
        manifest: the :class:`PubkeyManifest` published in ``/health``.
        signer: the :class:`SkillsSigner` for producing Phase 1
            ``get_skill`` / ``get_agent`` response signatures.
        last_updated_timestamp: unix timestamp of the most recent update
            (initial creation or last :meth:`record_cycle`).
        cycles_total: count of successful feed update cycles since startup.
        errors_total: count of failed feed update cycles since startup.
        generation: monotonic token so teardown can detect
            cross-app state contamination. Incremented whenever the
            state is rebuilt (e.g., after a key load failure).
    """

    manifest: PubkeyManifest
    signer: SkillsSigner
    last_updated_timestamp: float = field(default_factory=time.time)
    cycles_total: int = 0
    errors_total: int = 0
    generation: int = 0

    def record_cycle(self) -> None:
        """Mark a successful feed update. Bumps ``cycles_total`` and
        ``last_updated_timestamp``.
        """
        self.cycles_total += 1
        self.last_updated_timestamp = time.time()

    def record_error(self) -> None:
        """Mark a failed feed update. Bumps ``errors_total`` and
        ``last_updated_timestamp`` (the timestamp is updated even on
        errors so operators can see the feed is still being polled).
        """
        self.errors_total += 1
        self.last_updated_timestamp = time.time()

    def is_ok(self) -> bool:
        """True when the feed has at least one entry. Empty manifests
        return False so the ``/health`` endpoint returns 503.
        """
        return not self.manifest.is_empty()

    def as_dict(self) -> dict[str, object]:
        """Serialize for the ``/health`` payload.

        Returns a flat dict compatible with the other Dhara feed
        entries (``ok``, ``feed_entities_count``, ``feed_last_updated_timestamp``,
        ``cycles_total``, ``errors_total``). The manifest data is
        nested under ``key_count`` / ``pubkeys`` for backwards compat
        with Phase 2/6 installers that already parse those fields.
        """
        manifest_dict = self.manifest.as_dict()
        return {
            "ok": self.is_ok(),
            "feed": "skills_signer",
            "feed_entities_count": manifest_dict["key_count"],
            "feed_last_updated_timestamp": self.last_updated_timestamp,
            "cycles_total": self.cycles_total,
            "errors_total": self.errors_total,
            "generation": self.generation,
            "key_count": manifest_dict["key_count"],
            "pubkeys": manifest_dict["pubkeys"],
        }


def init_signer_feed_state() -> SignerFeedState:
    """Load or create the persisted signing keypair, build the manifest,
    attach the :class:`SkillsSigner`, install the module-level
    singleton, and return the populated :class:`SignerFeedState`.

    The returned state is intended to be stored on the
    :class:`DharaMCPServer` instance as ``signer_feed_state``
    (per the plan §10.3.2 instance model). The persistence path is
    resolved by :func:`_resolve_dhara_signer_key_path`.

    This single function combines the akosha-style two-step pattern
    (build state, then install singleton) into one — the original
    dhara constructor already returned a state, and the wiring in
    ``DharaMCPServer.__init__`` only needs a single call site. The
    singleton install is internal; :func:`get_signer_feed_state`
    reads it back, and Phase 1's ``list_skills`` / ``get_skill``
    MCP tools use that helper.

    Raises:
        OSError: when the persistence path cannot be created.
        ValueError: when the persisted file is not a valid ed25519
            PEM private key.
    """
    from dhara.skills_signer import (
        SkillsSigner,
        build_pubkey_manifest,
        load_or_create_keypair,
    )

    key_path = _resolve_dhara_signer_key_path()
    keypair = load_or_create_keypair(key_path)
    manifest = build_pubkey_manifest(keypair)
    signer = SkillsSigner.from_keypair(keypair)
    state = SignerFeedState(manifest=manifest, signer=signer)
    # Install the module-level singleton so Phase 1 tools can read
    # the signer via :func:`get_signer_feed_state` without taking it
    # as a function parameter.
    _install_signer_feed_state(state)
    logger.info(
        "skills_signer feed state initialized key_id=%s key_path=%s",
        keypair.key_id,
        key_path,
    )
    return state


def _resolve_dhara_signer_key_path() -> Path:
    """Resolve the persisted keypair path for Dhara.

    Default: ``~/.dhara/state/skills_signer/private_key.pem``.
    Override via ``DHARA_SKILLS_SIGNER_KEY_PATH`` for tests and
    non-standard locations.
    """
    env_path = os.getenv("DHARA_SKILLS_SIGNER_KEY_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".dhara" / "state" / "skills_signer" / "private_key.pem"


# ---------------------------------------------------------------------------
# Module-level singleton (Phase 1 helper surface).
#
# Phase 1 ``list_skills`` / ``get_skill`` MCP tools read the signer via
# :func:`get_signer_feed_state` so they don't need to thread the
# :class:`DharaMCPServer` instance through every decorator. The lifespan
# populates this after constructing the SignerFeedState. The other 4
# Bodai servers (mahavishnu / session-buddy / akosha / crackerjack) use
# the same module-level pattern with their own state classes; Phase 2's
# installer reads /health directly, not these helpers, so the API stays
# per-server.
# ---------------------------------------------------------------------------

_signer_state: SignerFeedState | None = None
_signer_state_lock = threading.Lock()


def _install_signer_feed_state(state: SignerFeedState) -> None:
    """Install the instance-owned :class:`SignerFeedState` singleton.

    Idempotent: a second call replaces the singleton (used in tests and
    on key load retry). Logs at INFO so the audit trail shows when the
    signer became available.
    """
    global _signer_state
    with _signer_state_lock:
        _signer_state = state
    logger.info(
        "init_signer_feed_state: signer singleton installed (key_id=%s, generation=%d)",
        state.signer.key_id,
        state.generation,
    )


def get_signer_feed_state() -> SignerFeedState | None:
    """Return the active :class:`SignerFeedState`, or ``None`` pre-lifespan."""
    return _signer_state


def reset_signer_feed_state() -> None:
    """Clear the singleton (test-only helper; production never calls this)."""
    global _signer_state
    with _signer_state_lock:
        _signer_state = None


__all__ = [
    "SignerFeedState",
    "_resolve_dhara_signer_key_path",
    "get_signer_feed_state",
    "init_signer_feed_state",
    "reset_signer_feed_state",
]
