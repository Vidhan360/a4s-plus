"""``/api/v1/security`` — security monitor, simulated attacks, crypto demo."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession, PageParams, require
from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.permissions import Perm
from app.models.enums import (
    SecurityEventOrigin,
    SecurityEventStatus,
    SecurityEventType,
    SecuritySeverity,
)
from app.repositories import system as system_repo
from app.schemas.common import page
from app.schemas.system import (
    CryptoDemoRequest,
    CryptoDemoResponse,
    SecurityAcknowledgeRequest,
    SecurityEventOut,
    SecurityInjectRequest,
    SecurityPostureOut,
)
from app.services.audit_service import AuditService
from app.services.crypto_service import (
    ALGORITHM,
    DEMO_LABEL,
    DEMO_NOTICE,
    KEY_BYTES,
    NONCE_BYTES,
    CryptoDemoService,
)
from app.services.security_service import (
    AUTOMATIC_RESPONSE,
    SIMULATED_EVENT_CATALOGUE,
    SecurityService,
)

router = APIRouter(prefix="/security", tags=["security"])

#: Controls that are actually implemented in this codebase.
IMPLEMENTED_CONTROLS: list[dict[str, Any]] = [
    {
        "control": "Password hashing",
        "detail": "Argon2id, time_cost=3, memory_cost=64 MiB, parallelism=4.",
        "status": "IMPLEMENTED",
    },
    {
        "control": "Access tokens",
        "detail": "Short-lived HS256 JWTs carrying role and permission claims.",
        "status": "IMPLEMENTED",
    },
    {
        "control": "Refresh-token rotation",
        "detail": (
            "Single-use opaque tokens stored as SHA-256 hashes; replay revokes "
            "the whole token family and raises a security event."
        ),
        "status": "IMPLEMENTED",
    },
    {
        "control": "Account lockout",
        "detail": "Configurable failed-attempt threshold and lockout window.",
        "status": "IMPLEMENTED",
    },
    {
        "control": "Permission-based RBAC",
        "detail": "Every endpoint declares required permissions; denials are logged.",
        "status": "IMPLEMENTED",
    },
    {
        "control": "Rate limiting",
        "detail": "Per-IP limits on authentication endpoints (Redis-backed).",
        "status": "IMPLEMENTED",
    },
    {
        "control": "Append-only audit log",
        "detail": (
            "No UPDATE/DELETE path exists in the application, and the migration "
            "revokes those privileges from the application database role."
        ),
        "status": "IMPLEMENTED",
    },
    {
        "control": "Security headers",
        "detail": "CSP, HSTS (when HTTPS), nosniff, frame-deny, referrer policy.",
        "status": "IMPLEMENTED",
    },
    {
        "control": "Authenticated encryption demo",
        "detail": (
            f"{ALGORITHM} round-trip with tamper detection. Demonstration of a "
            "primitive only — this prototype does not encrypt the database or "
            "transport payloads at rest."
        ),
        "status": "DEMONSTRATION_ONLY",
    },
    {
        "control": "Transport encryption (TLS)",
        "detail": (
            "Terminated by the deployment platform / reverse proxy, not by this "
            "application. Not configured in the development compose stack."
        ),
        "status": "OUT_OF_SCOPE",
    },
    {
        "control": "Multi-factor authentication",
        "detail": "Not implemented in this prototype.",
        "status": "NOT_IMPLEMENTED",
    },
]


@router.get("/events")
async def list_events(
    session: DbSession,
    pagination: PageParams,
    _user: Annotated[Any, require(Perm.SECURITY_READ)],
    severity: SecuritySeverity | None = None,
    origin: SecurityEventOrigin | None = None,
    event_status: Annotated[SecurityEventStatus | None, Query(alias="status")] = None,
    event_type: SecurityEventType | None = None,
) -> dict[str, Any]:
    rows, total = await system_repo.list_security_events(
        session,
        limit=pagination.limit,
        offset=pagination.offset,
        severity=severity.value if severity else None,
        origin=origin.value if origin else None,
        status=event_status.value if event_status else None,
        event_type=event_type.value if event_type else None,
    )
    return page(
        [SecurityEventOut.model_validate(r) for r in rows],
        total,
        pagination.limit,
        pagination.offset,
    )


@router.get("/posture", response_model=SecurityPostureOut)
async def posture(
    session: DbSession,
    _user: Annotated[Any, require(Perm.SECURITY_READ)],
) -> SecurityPostureOut:
    data = await system_repo.security_posture(session)
    rows, _ = await system_repo.list_security_events(session, limit=15, offset=0)
    return SecurityPostureOut.model_validate(
        {
            **data,
            "recent": [SecurityEventOut.model_validate(r) for r in rows],
            "controls": IMPLEMENTED_CONTROLS,
        }
    )


@router.get("/catalogue")
async def catalogue(
    _user: Annotated[Any, require(Perm.SECURITY_READ)],
) -> dict[str, Any]:
    """Which scenarios can be injected, and the automatic responses."""
    return {
        "simulated_events": [
            {
                "kind": kind,
                "event_type": spec["event_type"].value,
                "severity": spec["severity"].value,
                "title": spec["title"],
                "description": spec["description"],
            }
            for kind, spec in SIMULATED_EVENT_CATALOGUE.items()
        ],
        "automatic_responses": {key.value: value for key, value in AUTOMATIC_RESPONSE.items()},
        "origin_semantics": {
            SecurityEventOrigin.REAL.value: (
                "Generated by this application's own security controls "
                "(failed sign-ins, permission denials, token reuse)."
            ),
            SecurityEventOrigin.SIMULATED.value: (
                "Deliberately injected for demonstration. No real attack, radio "
                "or network activity is involved."
            ),
        },
    }


@router.post("/inject", response_model=SecurityEventOut)
async def inject_event(
    request: Request,
    payload: SecurityInjectRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SECURITY_SIMULATE)],
) -> SecurityEventOut:
    from app.services.audit_service import audit_context

    context = audit_context(request)
    event = await SecurityService.inject_simulated(
        session,
        payload.kind,
        actor_user_id=actor.id,
        drone_id=payload.drone_id,
        payload=payload.payload,
        ip=context["ip"],
        request_id=context["request_id"],
    )
    await AuditService.log_from_request(
        session,
        request,
        action="security.inject",
        resource_type="security_event",
        resource_id=str(event.id),
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"kind": payload.kind},
    )
    return SecurityEventOut.model_validate(event)


@router.post("/events/{event_id}/acknowledge", response_model=SecurityEventOut)
async def acknowledge_event(
    request: Request,
    event_id: uuid.UUID,
    payload: SecurityAcknowledgeRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.SECURITY_WRITE)],
) -> SecurityEventOut:
    event = await system_repo.get_security_event(session, event_id)
    if event is None:
        raise NotFoundError("Security event not found.")
    event.status = SecurityEventStatus.MITIGATED.value
    event.handled_by_id = actor.id
    event.handled_at = datetime.now(timezone.utc)
    if payload.note:
        data = dict(event.payload or {})
        data["handler_note"] = payload.note
        event.payload = data
    await session.flush()
    await AuditService.log_from_request(
        session,
        request,
        action="security.acknowledge",
        resource_type="security_event",
        resource_id=str(event_id),
        actor_user_id=actor.id,
        actor_email=actor.email,
    )
    return SecurityEventOut.model_validate(event)


@router.post("/crypto-demo", response_model=CryptoDemoResponse)
async def crypto_demo(
    request: Request,
    payload: CryptoDemoRequest,
    session: DbSession,
    actor: Annotated[Any, require(Perm.CRYPTO_DEMO)],
) -> CryptoDemoResponse:
    """AES-256-GCM round-trip with a deliberate tamper test.

    This is an educational demonstration of an authenticated-encryption
    primitive. It is explicitly **not** a claim that the system encrypts stored
    data, and the term "military-grade" is not used anywhere in this project.
    """
    encrypt_started = time.perf_counter()
    result = CryptoDemoService.encrypt(payload.plaintext, payload.aad)
    encrypt_ms = (time.perf_counter() - encrypt_started) * 1000.0

    decrypt_started = time.perf_counter()
    roundtrip = CryptoDemoService.roundtrip(payload.plaintext, payload.aad)
    decrypt_ms = (time.perf_counter() - decrypt_started) * 1000.0

    await SecurityService.record(
        session,
        event_type=SecurityEventType.ENCRYPTION_DEMO,
        origin=SecurityEventOrigin.SIMULATED,
        source="security.crypto_demo",
        title="Authenticated encryption demonstration run",
        description=(
            f"{ALGORITHM} encrypt/decrypt round-trip executed on "
            f"{len(payload.plaintext)} bytes of operator-supplied text."
        ),
        actor_user_id=actor.id,
        payload={"plaintext_length": len(payload.plaintext)},
    )
    await AuditService.log_from_request(
        session,
        request,
        action="security.crypto_demo",
        resource_type="crypto_demo",
        actor_user_id=actor.id,
        actor_email=actor.email,
        metadata={"bytes": len(payload.plaintext)},
    )
    data = result.as_dict()
    return CryptoDemoResponse(
        algorithm=ALGORITHM,
        label=DEMO_LABEL,
        notice=DEMO_NOTICE,
        key_bits=KEY_BYTES * 8,
        nonce_bits=NONCE_BYTES * 8,
        plaintext_length=len(payload.plaintext),
        ciphertext_b64=data["ciphertext_b64"],
        nonce_b64=data["nonce_b64"],
        key_b64=data["key_b64"],
        ciphertext_length=int(data["ciphertext_length"]),
        tag_bytes=int(data["tag_bytes"]),
        aad=payload.aad,
        decrypted_matches_input=bool(roundtrip["roundtrip_ok"]),
        tamper_test=roundtrip["tamper_test"],
        encrypt_ms=round(encrypt_ms, 3),
        decrypt_ms=round(decrypt_ms, 3),
    )


@router.get("/settings")
async def security_settings(
    _user: Annotated[Any, require(Perm.SECURITY_READ)],
) -> dict[str, Any]:
    """Effective, non-secret security parameters."""
    return {
        "access_token_minutes": settings.access_token_minutes,
        "refresh_token_days": settings.refresh_token_days,
        "max_failed_logins": settings.max_failed_logins,
        "lockout_minutes": settings.lockout_minutes,
        "min_password_length": 12,
        "password_hash": "argon2id",
        "environment": settings.env,
        "controls": IMPLEMENTED_CONTROLS,
    }
