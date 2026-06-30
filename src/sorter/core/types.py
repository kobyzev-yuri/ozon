from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TrackState(str, Enum):
    NEW = "new"
    INDUCTED = "inducted"
    SCANNED = "scanned"
    SCHEDULED = "scheduled"
    DIVERTED = "diverted"
    REJECTED = "rejected"


@dataclass
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2


@dataclass
class Detection:
    track_id: int | None
    class_id: int
    class_name: str
    confidence: float
    bbox: BBox
    barcode: str | None = None


@dataclass
class TrackSnapshot:
    track_id: int
    class_name: str
    confidence: float
    bbox: BBox
    belt_position: float
    velocity: float = 0.0
    state: TrackState = TrackState.NEW
    barcode: str | None = None
    target_zone: str | None = None
    scan_frame: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DivertCommand:
    track_id: int
    zone: str
    execute_at_frame: int
    actuator: str
    direction: str | None = None


@dataclass
class RouteDecision:
    zone: str
    reason: str
    source: str  # wms | cv | barcode | llm_arbitrator | reject
