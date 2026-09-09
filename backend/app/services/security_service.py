"""Security event recording and simulated security-event injection.

Real application security events (failed logins, lockouts, permission
violations, invalid tokens, refresh-token reuse) and deliberately injected
demonstration events share one table but are separated by the ``origin``
column: ``REAL`` versus ``SIMULATED``. The API and UI never blend the two, and
the distinction is surfaced prominently.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Topic, get_event_bus
from app.core.logging import get_logger
from app.models.enums import (
    SecurityEventOrigin,
    SecurityEventStatus,
    SecurityEventType,
    SecuritySeverity,
)
from app.models.system import SecurityEvent

logger = get_logger(__name__)

#: Default severity for each real event type.
REAL_EVENT_SEVERITY: dict[SecurityEventType, SecuritySeverity] = {
    SecurityEventType.FAILED_LOGIN: SecuritySeverity.WARNING,
    SecurityEventType.ACCOUNT_LOCKOUT: SecuritySeverity.HIGH,
    SecurityEventType.PERMISSION_VIOLATION: SecuritySeverity.HIGH,
    SecurityEventType.INVALID_TOKEN: SecuritySeverity.WARNING,
    SecurityEventType.TOKEN_REUSE_DETECTED: SecuritySeverity.CRITICAL,
    SecurityEventType.SUSPICIOUS_API_ACTIVITY: SecuritySeverity.HIGH,
    SecurityEventType.RATE_LIMIT_TRIPPED: SecuritySeverity.WARNING,
    SecurityEventType.LOGIN_SUCCESS: SecuritySeverity.INFO,
    SecurityEventType.PASSWORD_CHANGED: SecuritySeverity.INFO,
    SecurityEventType.ENCRYPTION_DEMO: SecuritySeverity.INFO,
}

#: Automatic response text recorded for each event type. These describe what
#: the platform actually did, not aspirational capability.
AUTOMATIC_RESPONSE: dict[SecurityEventType, str] = {
    SecurityEventType.FAILED_LOGIN: (
        "Credentials rejected. The failed-attempt counter for this account was incremented."
    ),
    SecurityEventType.ACCOUNT_LOCKOUT: (
        "Account locked for the configured lockout period. Further "
        "authentication attempts are refused until it expires."
    ),
    SecurityEventType.PERMISSION_VIOLATION: (
        "Request denied with HTTP 403 before reaching any handler. No data was returned."
    ),
    SecurityEventType.INVALID_TOKEN: (
        "Request rejected with HTTP 401. The token signature, issuer, type or "
        "expiry did not validate."
    ),
    SecurityEventType.TOKEN_REUSE_DETECTED: (
        "The entire refresh-token family was revoked immediately, forcing "
        "re-authentication on every session derived from it."
    ),
    SecurityEventType.RATE_LIMIT_TRIPPED: (
        "Request throttled with HTTP 429 and a Retry-After header."
    ),
    SecurityEventType.SIMULATED_JAMMING: (
        "Affected UAV switched to autonomous waypoint mode; its command link is "
        "treated as unavailable."
    ),
    SecurityEventType.SIMULATED_SPOOFING: (
        "Reported telemetry from the affected UAV quarantined as untrusted; "
        "dead-reckoned position retained as authoritative."
    ),
    SecurityEventType.SIMULATED_INTRUSION: (
        "Simulated session isolated and flagged for operator review."
    ),
    SecurityEventType.ENCRYPTION_DEMO: (
        "Demonstration key material discarded after the operation; nothing was persisted."
    ),
    SecurityEventType.SUSPICIOUS_API_ACTIVITY: (
        "Flagged for review in the security monitor. The originating session "
        "keeps only the permissions its role already granted; no privileges "
        "are escalated or revoked automatically."
    ),
    SecurityEventType.LOGIN_SUCCESS: "Session established and access token issued.",
    SecurityEventType.PASSWORD_CHANGED: ("Password hash replaced with a fresh Argon2id hash."),
}

#: Catalogue of injectable demonstration events.
SIMULATED_EVENT_CATALOGUE: dict[str, dict[str, Any]] = {
    "jamming": {
        "event_type": SecurityEventType.SIMULATED_JAMMING,
        "severity": SecuritySeverity.CRITICAL,
        "title": "Simulated RF jamming against UAV command link",
        "description": (
            "A simulated wideband interference event has degraded the command "
            "link of one or more UAVs. This is a software simulation: no radio "
            "hardware is involved and no signal is transmitted."
        ),
        "source": "SIMULATION/RF",
    },
    "spoofing": {
        "event_type": SecurityEventType.SIMULATED_SPOOFING,
        "severity": SecuritySeverity.CRITICAL,
        "title": "Simulated navigation spoofing detected",
        "description": (
            "A simulated spoofing event is causing a UAV to report a position "
            "inconsistent with its dead-reckoned track. Software simulation "
            "only; no navigation receiver is involved."
        ),
        "source": "SIMULATION/NAV",
    },
    "intrusion": {
        "event_type": SecurityEventType.SIMULATED_INTRUSION,
        "severity": SecuritySeverity.HIGH,
        "title": "Simulated unauthorised access attempt",
        "description": (
            "A simulated intrusion attempt against the command API, injected "
            "for demonstration. No real credential or endpoint was involved."
        ),
        "source": "SIMULATION/API",
    },
    "suspicious_api": {
        "event_type": SecurityEventType.SUSPICIOUS_API_ACTIVITY,
        "severity": SecuritySeverity.WARNING,
        "title": "Simulated anomalous API access pattern",
        "description": (
            "A simulated burst of unusual API traffic, injected to exercise the monitoring view."
        ),
        "source": "SIMULATION/API",
    },
}


class SecurityService:
    """Records security events and publishes them to the live feed."""

    @staticmethod
    async def record(
        session: AsyncSession,
        *,
        event_type: SecurityEventType,
        origin: SecurityEventOrigin,
        source: str,
        title: str,
        description: str = "",
        severity: SecuritySeverity | None = None,
        actor_user_id: UUID | None = None,
        subject_email: str | None = None,
        drone_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        response_action: str | None = None,
        payload: dict[str, Any] | None = None,
        publish: bool = True,
    ) -> SecurityEvent:
        severity = severity or REAL_EVENT_SEVERITY.get(event_type, SecuritySeverity.INFO)
        event = SecurityEvent(
            event_type=event_type.value,
            severity=severity.value,
            origin=origin.value,
            source=source[:96],
            title=title[:160],
            description=description,
            status=SecurityEventStatus.NEW.value,
            response_action=response_action or AUTOMATIC_RESPONSE.get(event_type),
            actor_user_id=actor_user_id,
            subject_email=subject_email,
            drone_id=drone_id,
            ip=ip,
            user_agent=user_agent,
            request_id=request_id,
            payload={
                **(payload or {}),
                "simulated": origin is SecurityEventOrigin.SIMULATED,
            },
            created_at=datetime.now(timezone.utc),
        )
        session.add(event)
        await session.flush()
        if publish:
            await get_event_bus().publish(
                Topic.SECURITY.value,
                "security.event",
                SecurityService.serialise(event),
            )
        return event

    @staticmethod
    async def record_isolated(
        *,
        event_type: SecurityEventType,
        origin: SecurityEventOrigin,
        source: str,
        title: str,
        **kwargs: Any,
    ) -> None:
        """Record on an independent session.

        Needed for auth failures, where the request's transaction may be rolled
        back but the security record must still survive.
        """
        from app.core.database import SessionLocal

        try:
            async with SessionLocal() as session:
                await SecurityService.record(
                    session,
                    event_type=event_type,
                    origin=origin,
                    source=source,
                    title=title,
                    **kwargs,
                )
                await session.commit()
        except Exception:
            logger.exception("security_event_write_failed", extra={"event_type": event_type.value})

    @staticmethod
    def serialise(event: SecurityEvent) -> dict[str, Any]:
        return {
            "id": str(event.id),
            "event_type": event.event_type,
            "severity": event.severity,
            "origin": event.origin,
            "source": event.source,
            "title": event.title,
            "description": event.description,
            "status": event.status,
            "response_action": event.response_action,
            "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
            "subject_email": event.subject_email,
            "drone_id": str(event.drone_id) if event.drone_id else None,
            "ip": event.ip,
            "request_id": event.request_id,
            "payload": event.payload,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "handled_at": event.handled_at.isoformat() if event.handled_at else None,
        }

    @staticmethod
    async def inject_simulated(
        session: AsyncSession,
        kind: str,
        *,
        actor_user_id: UUID | None = None,
        drone_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        ip: str | None = None,
        request_id: str | None = None,
    ) -> SecurityEvent:
        """Inject a catalogued demonstration event."""
        spec = SIMULATED_EVENT_CATALOGUE.get(kind.lower())
        if spec is None:
            raise KeyError(
                f"Unknown simulated event {kind!r}. Available: {sorted(SIMULATED_EVENT_CATALOGUE)}"
            )
        return await SecurityService.record(
            session,
            event_type=spec["event_type"],
            origin=SecurityEventOrigin.SIMULATED,
            source=spec["source"],
            title=spec["title"],
            description=spec["description"],
            severity=spec["severity"],
            actor_user_id=actor_user_id,
            drone_id=drone_id,
            ip=ip,
            request_id=request_id,
            payload={"injected_by_operator": True, **(payload or {})},
        )
