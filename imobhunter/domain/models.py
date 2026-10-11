from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class NormalizedAddress:
    original: str
    normalized: str
    number: str | None = None
    city: str | None = None
    state: str | None = None
    street_type: str | None = None
    street_title: str | None = None
    street_name: str | None = None


@dataclass(frozen=True)
class SourceStatus:
    source_id: str
    name: str
    status: str
    message: str | None = None


class SearchRequest:
    def __init__(
        self,
        address: str | None = None,
        number: str | None = None,
        city: str | None = None,
        state: str | None = None,
        block: str | None = None,
        lot: str | None = None,
        cib: str | None = None,
        car_code: str | None = None,
    ) -> None:
        self.address = address
        self.number = number
        self.city = city
        self.state = state
        self.block = block
        self.lot = lot
        self.cib = cib
        self.car_code = car_code

    def validate(self) -> None:
        if not any((self.address, self.block, self.lot, self.cib, self.car_code)):
            raise ValueError("search request cannot be empty")
        if self.number and not self.address:
            raise ValueError("number requires an address")
        if (self.block and not self.lot) or (self.lot and not self.block):
            raise ValueError("block and lot must be provided together")
        if not self.address and not (self.block and self.lot) and not self.cib and not self.car_code:
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


@dataclass(frozen=True)
class TaxDebt:
    status: str
    tax_type: str = "IPTU"
    year: int | None = None
    amount: float | None = None
    due_date: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class PropertyRecord:
    property_id: str | None = None
    registry_number: str | None = None
    cib: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    block: str | None = None
    lot: str | None = None
    area_m2: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    owner_name: str | None = None
    owner_document: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    tax_debts: tuple[TaxDebt, ...] = ()
    provenance: tuple[Provenance, ...] = ()


@dataclass(frozen=True)
class CoverageProject:
    ddd: str
    states: tuple[str, ...]
    label: str
    municipalities: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.ddd) != 2 or not self.ddd.isdigit():
            raise ValueError("DDD must contain exactly two digits")
        if not self.states:
            raise ValueError("coverage project requires at least one state")
