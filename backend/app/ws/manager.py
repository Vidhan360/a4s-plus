"""WebSocket fan-out.

One task per connection subscribes to the shared :class:`EventBus` (Redis
pub/sub in production, in-process fallback otherwise) and forwards envelopes to
the client. Because the bus is external, this scales to multiple API workers.

Protocol
--------
Client connects to ``/api/v1/ws?token=<access token>&topics=vitals,alerts``.
The server then sends, in order:

1. ``{"type": "connection.ready", ...}`` — negotiated topics and permissions.
2. ``{"type": "snapshot", ...}`` — the current dashboard payload, so a fresh
   client renders immediately instead of waiting for the next tick.
3. ``{"type": "event", "topic": ..., "event": ..., "payload": ...}`` — live.

The client may send ``{"action": "ping"}`` (answered with ``pong``),
``{"action": "subscribe", "topics": [...]}`` or ``{"action": "snapshot"}``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.database import session_scope
from app.core.errors import AuthenticationError
from app.core.events import ALL_TOPICS, get_event_bus
from app.core.logging import get_logger
from app.core.permissions import Perm
from app.core.security import decode_access_token

logger = get_logger(__name__)

#: Which permission gates each topic.
TOPIC_PERMISSIONS: dict[str, str] = {
    "vitals": Perm.VITALS_READ.value,
    "alerts": Perm.ALERT_READ.value,
    "drones": Perm.DRONE_READ.value,
    "security": Perm.SECURITY_READ.value,
    "simulation": Perm.SIMULATION_READ.value,
    "dashboard": Perm.DASHBOARD_READ.value,
}

HEARTBEAT_SECONDS = 25.0


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default)


class WebSocketSession:
    """Lifecycle of one authenticated client connection."""

    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket
        self.claims: dict[str, Any] = {}
        self.permissions: set[str] = set()
        self.topics: list[str] = []

    # ------------------------------------------------------------------- auth

    def authenticate(self, token: str | None) -> None:
        if not token:
            raise AuthenticationError("A valid access token is required.")
        self.claims = decode_access_token(token)
        self.permissions = set(self.claims.get("perms") or [])
        if not self.permissions:
            raise AuthenticationError("Token carries no permissions.")

    def negotiate(self, requested: str | None) -> list[str]:
        wanted = (
            [t.strip() for t in requested.split(",") if t.strip()]
            if requested
            else list(ALL_TOPICS)
        )
        allowed = [
            topic
            for topic in wanted
            if topic in ALL_TOPICS and TOPIC_PERMISSIONS.get(topic, "") in self.permissions
        ]
        self.topics = allowed or []
        return self.topics

    # ------------------------------------------------------------------- run

    async def run(self) -> None:
        bus = get_event_bus()
        await self.ws.send_text(
            _dump(
                {
                    "type": "connection.ready",
                    "topics": self.topics,
                    "backend": bus.backend,
                    "user": {
                        "id": self.claims.get("sub"),
                        "email": self.claims.get("email"),
                        "roles": self.claims.get("roles", []),
                    },
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    "is_simulated": True,
                }
            )
        )
        await self._send_snapshot()

        if not self.topics:
            await self.ws.send_text(
                _dump(
                    {
                        "type": "error",
                        "message": (
                            "Your role does not permit any live topics. "
                            "Connection will stay open for snapshots only."
                        ),
                    }
                )
            )

        reader = asyncio.create_task(self._read_loop())
        writer = asyncio.create_task(self._write_loop(bus))
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            done, pending = await asyncio.wait(
                {reader, writer, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                    raise exc
        finally:
            for task in (reader, writer, heartbeat):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _write_loop(self, bus: Any) -> None:
        if not self.topics:
            await asyncio.Event().wait()
            return
        async for envelope in bus.subscribe(self.topics):
            if self.ws.client_state is not WebSocketState.CONNECTED:
                return
            await self.ws.send_text(
                _dump(
                    {
                        "type": "event",
                        "topic": envelope.get("topic"),
                        "event": envelope.get("event"),
                        "payload": envelope.get("payload"),
                        "ts": envelope.get("ts"),
                    }
                )
            )

    async def _read_loop(self) -> None:
        while True:
            raw = await self.ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await self.ws.send_text(_dump({"type": "error", "message": "Malformed JSON."}))
                continue
            action = str(message.get("action", "")).lower()
            if action == "ping":
                await self.ws.send_text(
                    _dump(
                        {
                            "type": "pong",
                            "server_time": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
            elif action == "snapshot":
                await self._send_snapshot()
            elif action == "subscribe":
                self.negotiate(",".join(message.get("topics") or []))
                await self.ws.send_text(_dump({"type": "subscribed", "topics": self.topics}))
                # The write loop is bound to the previous topic list; ask the
                # client to reconnect rather than silently ignoring the change.
                await self.ws.send_text(
                    _dump(
                        {
                            "type": "notice",
                            "message": "Reconnect to apply the new topic set.",
                        }
                    )
                )
            else:
                await self.ws.send_text(
                    _dump({"type": "error", "message": f"Unknown action {action!r}."})
                )

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if self.ws.client_state is not WebSocketState.CONNECTED:
                return
            await self.ws.send_text(
                _dump(
                    {
                        "type": "heartbeat",
                        "server_time": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )

    async def _send_snapshot(self) -> None:
        if Perm.DASHBOARD_READ.value not in self.permissions:
            return
        from app.services.dashboard_service import dashboard_service

        try:
            async with session_scope() as session:
                payload = await dashboard_service.snapshot(session)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("websocket snapshot failed: %s", exc)
            return
        from app.schemas.system import DashboardOut

        await self.ws.send_text(
            _dump(
                {
                    "type": "snapshot",
                    "payload": json.loads(DashboardOut.model_validate(payload).model_dump_json()),
                }
            )
        )


async def serve(websocket: WebSocket, token: str | None, topics: str | None) -> None:
    """Entry point used by the WebSocket route."""
    session = WebSocketSession(websocket)
    try:
        session.authenticate(token)
    except Exception:
        await websocket.close(code=4401, reason="Unauthorised")
        return
    await websocket.accept()
    session.negotiate(topics)
    try:
        await session.run()
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("websocket closed with error: %s", exc)
        with contextlib.suppress(Exception):
            await websocket.close(code=1011, reason="Internal error")
