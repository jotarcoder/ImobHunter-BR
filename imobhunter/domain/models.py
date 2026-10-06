from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

@dataclass(frozen=True)
class NormalizedAddress:
    original: str
    normalized: str
    number: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None

class SourceStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    REQUIRES_AUTH = "requires_auth"
    NOT_CONFIGURED = "not_configured"

@dataclass(frozen=True)
class SearchRequest:
    address: str | None = None
    number: str | None = None
    block: str | None = None
    lot: str | None = None
    city: str | None = None
    state: str | None = None

@dataclass(frozen=True)
class Provenance:
    source_id: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 0.0
    reference: str | None = None

@dataclass
class PropertyRecord:
    property_id: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    block: str | None = None
    lot: str | None = None
    cib: str | None = None
    area_m2: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    provenance: list[Provenance] = field(default_factory=list)
