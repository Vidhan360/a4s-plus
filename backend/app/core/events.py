"""EventBus abstraction for real-time fan-out.

``RedisEventBus`` is used when Redis is reachable; otherwise the application
degrades to ``InMemoryEventBus`` so a single-process deployment (and the test
suite) keeps working. Publishers only ever depend on the abstract interface.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
CHANNEL_PREFIX = "a4s:events:"


class Topic(StrEnum):
    VITALS = "vitals"
    ALERTS = "alerts"
    DRONES = "drones"
    SECURITY = "security"
    SIMULATION = "simulation"
    DASHBOARD = "dashboard"


ALL_TOPICS: tuple[str, ...] = tuple(t.value for t in Topic)


def envelope(topic: str, event: str, payload: Any) -> dict[str, Any]:
    return {
        "topic": topic,
        "event": event,
        "payload": payload,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


class EventBus(ABC):
    """Publish/subscribe interface used by every real-time producer."""

    @abstractmethod
    async def publish(self, topic: str, event: str, payload: Any) -> None: ...

    @abstractmethod
    def subscribe(self, topics: list[str]) -> AsyncIterator[dict[str, Any]]: ...

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None

    @property
    def backend(self) -> str:
        return type(self).__name__


class InMemoryEventBus(EventBus):
    """Process-local bus. Correct for one worker; used as the Redis fallback."""

    def __init__(self, max_queue: int = 500) -> None:
        self._subscribers: list[tuple[set[str], asyncio.Queue[dict[str, Any]]]] = []
        self._max_queue = max_queue

    async def publish(self, topic: str, event: str, payload: Any) -> None:
        message = envelope(topic, event, payload)
        for topics, queue in list(self._subscribers):
            if topic in topics:
                if queue.qsize() >= self._max_queue:
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()  # drop oldest: liveness over history
                queue.put_nowait(message)

    async def _iterate(
        self, topics: set[str], queue: asyncio.Queue[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers = [s for s in self._subscribers if s[1] is not queue]

    def subscribe(self, topics: list[str]) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        selected = set(topics)
        self._subscribers.append((selected, queue))
        return self._iterate(selected, queue)


class RedisEventBus(EventBus):
    """Redis pub/sub bus: safe across multiple uvicorn workers."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(url, decode_responses=True)

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    async def publish(self, topic: str, event: str, payload: Any) -> None:
        try:
            await self._redis.publish(
                CHANNEL_PREFIX + topic, json.dumps(envelope(topic, event, payload))
            )
        except Exception:
            logger.warning("event_publish_failed", extra={"topic": topic})

    async def _iterate(self, topics: list[str]) -> AsyncIterator[dict[str, Any]]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(*[CHANNEL_PREFIX + t for t in topics])
        try:
            async for raw in pubsub.listen():
                if raw.get("type") != "message":
                    continue
                try:
                    yield json.loads(raw["data"])
                except (ValueError, TypeError):
                    continue
        finally:
            with contextlib_suppress():
                await pubsub.unsubscribe()
                await pubsub.aclose()

    def subscribe(self, topics: list[str]) -> AsyncIterator[dict[str, Any]]:
        return self._iterate(topics)

    async def close(self) -> None:
        with contextlib_suppress():
            await self._redis.aclose()


class contextlib_suppress:
    """Tiny inline suppressor usable in ``finally`` blocks of async generators."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True


_bus: EventBus | None = None


async def init_event_bus() -> EventBus:
    """Create the process event bus, preferring Redis when available."""
    global _bus
    if _bus is not None:
        return _bus
    url = settings.redis_url
    if url:
        candidate = RedisEventBus(url)
        if await candidate.ping():
            logger.info("event_bus_ready", extra={"backend": "redis"})
            _bus = candidate
            return _bus
        await candidate.close()
        logger.warning("redis_unavailable_using_memory_bus", extra={"url": url})
    _bus = InMemoryEventBus()
    logger.info("event_bus_ready", extra={"backend": "memory"})
    return _bus


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = InMemoryEventBus()
    return _bus


async def shutdown_event_bus() -> None:
    global _bus
    if _bus is not None:
        await _bus.close()
        _bus = None
