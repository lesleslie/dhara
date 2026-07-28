"""Minimal key/value and time-series storage for Dhara MCP tools.

Implements:
- put/get with optional TTL
- time-series append/query with retention

Storage is backed by Dhara persistent objects (PersistentDict/List).
"""

from __future__ import annotations

import operator
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from dhara.collections.dict import PersistentDict
from dhara.collections.list import PersistentList
from dhara.core.connection import AsyncConnection, Connection


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_iso(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:  # noqa: BLE001  # deliberate None coercion for bad input
        return None


@dataclass
class TimeSeriesRetention:
    retention_days: int = 60

    def cutoff(self) -> datetime:
        return _utcnow() - timedelta(days=self.retention_days)


def _purge_ts(ts_list: PersistentList, retention: TimeSeriesRetention) -> None:
    """Standalone purge — stateless and CPU-bound; used by async class."""
    cutoff = retention.cutoff()
    if not ts_list:
        return
    kept = []
    for item in ts_list:
        ts_raw = item.get("ts")
        ts_dt = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
        if ts_dt is None or ts_dt >= cutoff:
            kept.append(item)
    if len(kept) != len(ts_list):
        ts_list[:] = kept


class AsyncKVTimeSeriesStore:
    """Async Dhara-backed KV and time-series store using AsyncConnection."""

    def __init__(
        self,
        connection: AsyncConnection,
        retention: TimeSeriesRetention | None = None,
    ) -> None:
        self.connection = connection
        self.retention = retention or TimeSeriesRetention()
        self._initialized = False

    async def _ensure_root_async(self) -> None:
        if self._initialized:
            return
        root = await self.connection.get_root()
        changed = False

        if "kv" not in root:
            root["kv"] = PersistentDict()  # type: ignore[assignment]
            changed = True
        if "kv_ttl" not in root:
            root["kv_ttl"] = PersistentDict()  # type: ignore[assignment]
            changed = True
        if "time_series" not in root:
            root["time_series"] = PersistentDict()  # type: ignore[assignment]
            changed = True

        if changed:
            await self.connection.commit()
        self._initialized = True

    async def _kv(self) -> PersistentDict:
        root = await self.connection.get_root()
        return root["kv"]  # type: ignore[no-any-return]

    async def _kv_ttl(self) -> PersistentDict:
        root = await self.connection.get_root()
        return root["kv_ttl"]  # type: ignore[no-any-return]

    async def put_async(
        self, key: str, value: Any, ttl: int | None = None
    ) -> dict[str, Any]:
        await self._ensure_root_async()
        kv = await self._kv()
        ttl_map = await self._kv_ttl()

        kv[key] = value
        if ttl is not None:
            ttl_map[key] = int(time.time()) + int(ttl)
        elif key in ttl_map:
            del ttl_map[key]

        await self.connection.commit()
        return {"ok": True, "key": key}

    async def get_async(self, key: str) -> dict[str, Any]:
        await self._ensure_root_async()
        kv = await self._kv()
        ttl_map = await self._kv_ttl()

        if key not in kv:
            return {"ok": True, "key": key, "value": None}

        expires_at = ttl_map.get(key)
        if expires_at and int(time.time()) >= int(expires_at):
            del kv[key]
            del ttl_map[key]
            await self.connection.commit()
            return {"ok": True, "key": key, "value": None, "expired": True}

        return {"ok": True, "key": key, "value": kv[key]}

    async def list_prefix_async(self, prefix: str) -> list[dict[str, Any]]:
        """List all key/value records under a key prefix (async)."""
        await self._ensure_root_async()
        kv = await self._kv()
        results: list[dict[str, Any]] = []
        for key in kv:
            if key.startswith(prefix):
                value = kv[key]
                ttl_map = await self._kv_ttl()
                expires_at = ttl_map.get(key)
                if expires_at and int(time.time()) >= int(expires_at):
                    continue
                results.append({"key": key, "value": value})
        return results

    async def _get_ts_list(self, metric_type: str, entity_id: str) -> PersistentList:
        await self._ensure_root_async()
        root = await self.connection.get_root()
        ts_map: PersistentDict = root["time_series"]  # type: ignore[assignment]
        key = f"{metric_type}:{entity_id}"

        if key not in ts_map:
            ts_map[key] = PersistentList()  # type: ignore[assignment]
            await self.connection.commit()

        return ts_map[key]  # type: ignore[no-any-return]

    async def record_time_series_async(
        self,
        metric_type: str,
        entity_id: str,
        record: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_root_async()
        ts_list = await self._get_ts_list(metric_type, entity_id)
        ts = timestamp or _utcnow().isoformat()

        payload = {"ts": ts}
        if record:
            payload.update(record)
        ts_list.append(payload)

        _purge_ts(ts_list, self.retention)
        await self.connection.commit()
        return {"ok": True, "metric_type": metric_type, "entity_id": entity_id}

    async def query_time_series_async(
        self,
        metric_type: str,
        entity_id: str,
        start_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        await self._ensure_root_async()
        ts_list = await self._get_ts_list(metric_type, entity_id)
        cutoff = self.retention.cutoff()
        start_dt = _parse_iso(start_date) if start_date else None

        results: list[dict[str, Any]] = []
        for item in ts_list:
            ts_raw = item.get("ts")
            ts_dt = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
            if ts_dt and ts_dt < cutoff:
                continue
            if start_dt and ts_dt and ts_dt < start_dt:
                continue
            results.append(item)

        if limit is not None:
            results = results[-int(limit) :]
        return results

    async def aggregate_patterns_async(
        self,
        start_date: str,
        min_occurrences: int = 2,
    ) -> list[dict[str, Any]]:
        await self._ensure_root_async()
        root = await self.connection.get_root()
        ts_map: PersistentDict = root["time_series"]  # type: ignore[assignment]
        start_dt = _parse_iso(start_date) if start_date else None
        cutoff = self.retention.cutoff()

        counts: dict[str, int] = {}

        for ts_list in ts_map.values():
            for item in ts_list:
                ts_raw = item.get("ts")
                ts_dt = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
                if ts_dt and ts_dt < cutoff:
                    continue
                if start_dt and ts_dt and ts_dt < start_dt:
                    continue

                pattern = (
                    item.get("pattern")
                    or item.get("issue_type")
                    or item.get("event")
                    or item.get("category")
                )
                if not pattern:
                    continue
                counts[str(pattern)] = counts.get(str(pattern), 0) + 1

        results = [
            {"pattern": pattern, "count": count}
            for pattern, count in counts.items()
            if count >= min_occurrences
        ]
        results.sort(key=operator.itemgetter("count"), reverse=True)
        return results


# Backward-compatible alias (tests / external callers expect the unprefixed name).
# Async-only callers should use AsyncKVTimeSeriesStore explicitly.
class KVTimeSeriesStore:
    """Sync Dhara-backed KV and time-series store using ``Connection``.

    The original sync API; preserved for tests and external callers that
    use a sync ``Connection``. New code that runs against an
    ``AsyncConnection`` should use ``AsyncKVTimeSeriesStore`` directly.
    """

    def __init__(
        self,
        connection: Connection,
        retention: TimeSeriesRetention | None = None,
    ) -> None:
        self.connection = connection
        self.retention = retention or TimeSeriesRetention()
        self._ensure_root()

    def _ensure_root(self) -> None:
        root = self.connection.get_root()
        changed = False
        if "kv" not in root:
            root["kv"] = PersistentDict()  # type: ignore[assignment]
            changed = True
        if "kv_ttl" not in root:
            root["kv_ttl"] = PersistentDict()  # type: ignore[assignment]
            changed = True
        if "time_series" not in root:
            root["time_series"] = PersistentDict()  # type: ignore[assignment]
            changed = True
        if changed:
            self.connection.commit()

    def _kv(self) -> PersistentDict:
        root = self.connection.get_root()
        return root["kv"]  # type: ignore[no-any-return]

    def _kv_ttl(self) -> PersistentDict:
        root = self.connection.get_root()
        return root["kv_ttl"]  # type: ignore[no-any-return]

    def put(self, key: str, value: Any, ttl: int | None = None) -> dict[str, Any]:
        kv = self._kv()
        ttl_map = self._kv_ttl()

        kv[key] = value
        if ttl is not None:
            ttl_map[key] = int(time.time()) + int(ttl)
        elif key in ttl_map:
            del ttl_map[key]

        self.connection.commit()
        return {"ok": True, "key": key}

    def get(self, key: str) -> dict[str, Any]:
        kv = self._kv()
        ttl_map = self._kv_ttl()

        if key not in kv:
            return {"ok": True, "key": key, "value": None}

        expires_at = ttl_map.get(key)
        if expires_at and int(time.time()) >= int(expires_at):
            del kv[key]
            del ttl_map[key]
            self.connection.commit()
            return {"ok": True, "key": key, "value": None, "expired": True}

        return {"ok": True, "key": key, "value": kv[key]}

    def list_prefix(self, prefix: str) -> list[dict[str, Any]]:
        """List all key/value records under a key prefix.

        Used by Akosha FitnessAnalyzer to discover component endpoints
        registered under ``component_endpoint/`` prefix.

        Args:
            prefix: Key prefix to scan (e.g. ``"component_endpoint/"``).

        Returns:
            List of dicts with ``key``/``value`` for each matching record.
        """
        kv = self._kv()
        results: list[dict[str, Any]] = []
        for key in kv:
            if key.startswith(prefix):
                value = kv[key]
                ttl_map = self._kv_ttl()
                expires_at = ttl_map.get(key)
                if expires_at and int(time.time()) >= int(expires_at):
                    continue
                results.append({"key": key, "value": value})
        return results

    def _ts_key(self, metric_type: str, entity_id: str) -> str:
        return f"{metric_type}:{entity_id}"

    def _get_ts_list(self, metric_type: str, entity_id: str) -> PersistentList:
        root = self.connection.get_root()
        ts_map: PersistentDict = root["time_series"]  # type: ignore[assignment]
        key = self._ts_key(metric_type, entity_id)
        if key not in ts_map:
            ts_map[key] = PersistentList()  # type: ignore[assignment]
            self.connection.commit()
        return ts_map[key]  # type: ignore[no-any-return]

    def record_time_series(
        self,
        metric_type: str,
        entity_id: str,
        record: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        ts_list = self._get_ts_list(metric_type, entity_id)
        ts = timestamp or _utcnow().isoformat()

        payload = {"ts": ts}
        if record:
            payload.update(record)
        ts_list.append(payload)

        _purge_ts(ts_list, self.retention)
        self.connection.commit()
        return {"ok": True, "metric_type": metric_type, "entity_id": entity_id}

    def _purge_time_series(self, ts_list: PersistentList) -> None:
        """Backwards-compatible instance wrapper for the module-level purge.

        Earlier versions exposed ``_purge_time_series`` as an instance
        method; tests and external callers still rely on that shape.
        """
        _purge_ts(ts_list, self.retention)

    def query_time_series(
        self,
        metric_type: str,
        entity_id: str,
        start_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        ts_list = self._get_ts_list(metric_type, entity_id)
        cutoff = self.retention.cutoff()
        start_dt = _parse_iso(start_date) if start_date else None

        results: list[dict[str, Any]] = []
        for item in ts_list:
            ts_raw = item.get("ts")
            ts_dt = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
            if ts_dt and ts_dt < cutoff:
                continue
            if start_dt and ts_dt and ts_dt < start_dt:
                continue
            results.append(item)

        if limit is not None:
            results = results[-int(limit) :]
        return results

    def aggregate_patterns(
        self,
        start_date: str,
        min_occurrences: int = 2,
    ) -> list[dict[str, Any]]:
        root = self.connection.get_root()
        ts_map: PersistentDict = root["time_series"]  # type: ignore[assignment]
        start_dt = _parse_iso(start_date) if start_date else None
        cutoff = self.retention.cutoff()

        counts: dict[str, int] = {}

        for ts_list in ts_map.values():
            for item in ts_list:
                ts_raw = item.get("ts")
                ts_dt = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
                if ts_dt and ts_dt < cutoff:
                    continue
                if start_dt and ts_dt and ts_dt < start_dt:
                    continue

                pattern = (
                    item.get("pattern")
                    or item.get("issue_type")
                    or item.get("event")
                    or item.get("category")
                )
                if not pattern:
                    continue
                counts[str(pattern)] = counts.get(str(pattern), 0) + 1

        results = [
            {"pattern": pattern, "count": count}
            for pattern, count in counts.items()
            if count >= min_occurrences
        ]
        results.sort(key=operator.itemgetter("count"), reverse=True)
        return results
