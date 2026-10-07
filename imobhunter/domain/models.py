from dataclasses import dataclass, field
from datetime import UTC, datetime
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

    def validate(self) -> None:
        if not any((self.address, self.block, self.lot)):
            raise ValueError("search request cannot be empty")
        if self.number and not self.address:
            raise ValueError("number requires address")
        if bool(self.block) != bool(self.lot):
            raise ValueError("block and lot must be provided together")
        if not self.address and not (self.block and self.lot):
            raise ValueError("address or block+lot is required")

@dataclass(frozen=True)
class Provenance:
    source_id: str
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    confidence: float = 0.0
    reference: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

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
