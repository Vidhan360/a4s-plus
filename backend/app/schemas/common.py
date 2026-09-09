"""Shared response primitives: pagination, envelopes, disclaimers."""

from __future__ import annotations

import re
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.core.defaults import DATA_DISCLAIMER

T = TypeVar("T")

#: Pragmatic address syntax check.
#:
#: ``pydantic[email]``/``email-validator`` rejects special-use TLDs such as
#: ``.local``, which are exactly what an air-gapped deployment and this
#: project's own demo accounts use. Deliverability is not something this
#: application can or should assert, so it validates syntax only.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _validate_email(value: str) -> str:
    cleaned = value.strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise ValueError("Enter a valid email address, for example name@unit.local")
    return cleaned


EmailAddress = Annotated[
    str,
    StringConstraints(min_length=5, max_length=255),
    AfterValidator(_validate_email),
]


class SafeModel(BaseModel):
    """Base that disables Pydantic's ``model_`` protected namespace.

    Several domain fields are legitimately named ``model_name`` /
    ``model_version`` (they describe ML models, not Pydantic models).
    """

    model_config = ConfigDict(protected_namespaces=())


class ORMModel(BaseModel):
    """Base for models read directly from SQLAlchemy rows."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class PageMeta(BaseModel):
    total: int = Field(description="Total matching rows, ignoring pagination.")
    limit: int
    offset: int
    returned: int


class Page(BaseModel, Generic[T]):
    """Uniform list envelope used by every collection endpoint."""

    items: list[T]
    meta: PageMeta


class MessageResponse(BaseModel):
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DisclaimerResponse(BaseModel):
    """Provenance block attached to analytical payloads."""

    data_mode: str = "SOFTWARE PROTOTYPE / SIMULATED DATA"
    validation_status: str = "NOT CLINICALLY VALIDATED"
    notice: str = DATA_DISCLAIMER


def page(items: list[Any], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": items,
        "meta": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "returned": len(items),
        },
    }
