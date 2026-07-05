# dhara/storage/redis_cache.py
from __future__ import annotations

import asyncio
import json
import random
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, cast


@dataclass
class RedisCacheSettings:
    redis_url: str = "redis://localhost:6379"
    redis_token: str | None = None
    ttl: int = 3600
    stampede_jitter_ms: int = 0
    key_prefix: str = "dhara:cache:"


class CacheError(Exception):
    """Raised on cache operation failures."""

    pass


class RedisCacheAdapter:
    """Redis-backed cache implementing Dhara's Cache interface.

    Uses coredis for async Redis operations. TTL-based expiration.
    clear() is used for abort invalidation (explicit per-oid DEL).
    shrink() is a no-op in Phase 1 — TTL handles time-based eviction.
    """

    def __init__(self, settings: RedisCacheSettings) -> None:
        self._settings = settings
        # Typed as Any so static checkers don't narrow it to None after first assignment
        self._client: Any = None

    async def init(self) -> None:
        # Import coredis lazily so the module loads even when the optional
        # dependency is absent. Callers that actually use the cache get a
        # CacheError here instead of an ImportError at module import time.
        try:
            import coredis
        except ImportError as exc:
            raise CacheError("coredis is required for RedisCacheAdapter") from exc
        url = self._settings.redis_url
        kwargs: dict[str, Any] = {"decode_responses": False}
        if self._settings.redis_token:
            kwargs["username"] = "default"
            kwargs["password"] = self._settings.redis_token
        self._client = coredis.Redis.from_url(url, **kwargs)
        if self._client is None:
            raise CacheError("Failed to create Redis client")
        await self._client.ping()

    async def health(self) -> bool:
        if self._client is None:
            await self.init()
        if self._client is None:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    async def cleanup(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get(self, oid: str) -> object | None:
        if self._client is None:
            await self.init()
        if self._client is None:
            return None
        try:
            key = f"{self._settings.key_prefix}{oid}"
            data = await self._client.get(key)
            if data is None:
                if self._settings.stampede_jitter_ms > 0:
                    await asyncio.sleep(
                        random.uniform(0, self._settings.stampede_jitter_ms) / 1000.0
                    )
                return None
            return cast(object | None, json.loads(data))
        except Exception:
            return None

    async def set(self, oid: str, obj: object) -> None:
        if self._client is None:
            await self.init()
        if self._client is None:
            return
        with suppress(Exception):
            key = f"{self._settings.key_prefix}{oid}"
            data = json.dumps(obj)
            await self._client.set(key, data, px=self._settings.ttl * 1000)

    async def shrink(self) -> None:
        # Phase 1: no-op. TTL handles time-based expiration.
        pass

    async def clear(self) -> None:
        """Delete all keys with our prefix. Used for abort invalidation."""
        if self._client is None:
            await self.init()
        if self._client is None:
            return
        with suppress(Exception):
            async for key in self._client.scan_iter(
                match=f"{self._settings.key_prefix}*"
            ):
                await self._client.delete(key)
