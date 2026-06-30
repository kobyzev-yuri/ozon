from __future__ import annotations

from sorter.core.events import Event, EventBus
from sorter.core.types import Detection, RouteDecision, TrackSnapshot, TrackState
from sorter.wms.routing_table import RoutingTable


class ScanStation:
    """Этап 2: фиксация ID на SCAN LINE → запрос маршрута в WMS."""

    def __init__(
        self,
        scan_line_ratio: float,
        routing: RoutingTable,
        event_bus: EventBus,
        arbitrator=None,
    ) -> None:
        self.scan_line_ratio = scan_line_ratio
        self.routing = routing
        self.event_bus = event_bus
        self.arbitrator = arbitrator
        self._scanned: set[int] = set()

    def scan_line_px(self, frame_width: int) -> float:
        return frame_width * self.scan_line_ratio

    def process(
        self,
        frame,
        snapshots: list[TrackSnapshot],
        frame_idx: int,
    ) -> list[tuple[TrackSnapshot, RouteDecision]]:
        line_x = self.scan_line_px(frame.shape[1])
        decisions: list[tuple[TrackSnapshot, RouteDecision]] = []

        for snap in snapshots:
            if snap.track_id in self._scanned:
                continue
            if snap.bbox.cx < line_x:
                continue

            route = self.routing.resolve(
                class_name=snap.class_name,
                barcode=snap.barcode,
                confidence=snap.confidence,
            )

            if self.arbitrator is not None and self.arbitrator.should_arbitrate(snap, route):
                route = self.arbitrator.arbitrate(frame, snap, route)

            snap.state = TrackState.SCANNED
            snap.target_zone = route.zone
            snap.scan_frame = frame_idx
            self._scanned.add(snap.track_id)

            self.event_bus.publish(
                Event(
                    event="scanned",
                    frame=frame_idx,
                    track_id=snap.track_id,
                    payload={
                        "class": snap.class_name,
                        "confidence": snap.confidence,
                        "zone": route.zone,
                        "route_source": route.source,
                        "reason": route.reason,
                    },
                )
            )
            decisions.append((snap, route))

        return decisions
