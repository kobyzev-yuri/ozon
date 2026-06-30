from __future__ import annotations

from sorter.core.events import Event, EventBus
from sorter.core.types import RouteDecision, TrackSnapshot, TrackState
from sorter.perception.barcode_decoder import decode_barcode
from sorter.wms.routing_table import RoutingTable


class ScanStation:
    """
    Этап 2 — скан-портал на SCAN LINE.

    1. Штрихкод (pyzbar) в crop bbox — приоритет WMS
    2. Класс YOLO — если кода нет или префикс не в routes.yaml
    3. Опционально LLM-арбитр при низком conf или конфликте barcode↔CV
    """

    def __init__(
        self,
        scan_line_ratio: float,
        routing: RoutingTable,
        event_bus: EventBus,
        arbitrator=None,
        barcode_enabled: bool = True,
    ) -> None:
        self.scan_line_ratio = scan_line_ratio
        self.routing = routing
        self.event_bus = event_bus
        self.arbitrator = arbitrator
        self.barcode_enabled = barcode_enabled
        self._scanned: set[int] = set()

    def scan_line_px(self, frame_width: int) -> float:
        return frame_width * self.scan_line_ratio

    def _resolve_route(self, snap: TrackSnapshot) -> RouteDecision:
        """WMS: barcode → cluster → CV → reject."""
        cv_route = self.routing.resolve(
            class_name=snap.class_name,
            confidence=snap.confidence,
        )
        route = self.routing.resolve(
            class_name=snap.class_name,
            barcode=snap.barcode,
            confidence=snap.confidence,
        )

        if snap.barcode and cv_route.zone != route.zone:
            snap.metadata["barcode_cv_conflict"] = True
            snap.metadata["cv_zone"] = cv_route.zone
            snap.metadata["barcode_zone"] = route.zone

        return route

    def process(
        self,
        frame,
        snapshots: list[TrackSnapshot],
        frame_idx: int,
    ) -> list[tuple[TrackSnapshot, RouteDecision]]:
        line_x = self.scan_line_px(frame.shape[1])
        decisions: list[tuple[TrackSnapshot, RouteDecision]] = []

        for snap in snapshots:
            if snap.state != TrackState.INDUCTED:
                continue
            if snap.track_id in self._scanned:
                continue
            if snap.bbox.cx < line_x:
                continue

            # --- Сканирование штрихкода (скан-портал) ---
            barcode_read = None
            if self.barcode_enabled:
                barcode_read = decode_barcode(frame, snap.bbox)
            if barcode_read:
                snap.barcode = barcode_read

            route = self._resolve_route(snap)

            if self.arbitrator is not None and self.arbitrator.should_arbitrate(snap, route):
                route = self.arbitrator.arbitrate(frame, snap, route)

            snap.state = TrackState.SCANNED
            snap.target_zone = route.zone
            snap.scan_frame = frame_idx
            self._scanned.add(snap.track_id)

            payload = {
                "class": snap.class_name,
                "confidence": snap.confidence,
                "barcode": snap.barcode,
                "barcode_read": barcode_read is not None,
                "zone": route.zone,
                "route_source": route.source,
                "reason": route.reason,
            }
            if snap.metadata.get("barcode_cv_conflict"):
                payload["cv_zone"] = snap.metadata.get("cv_zone")
                payload["barcode_zone"] = snap.metadata.get("barcode_zone")

            self.event_bus.publish(
                Event(
                    event="scanned",
                    frame=frame_idx,
                    track_id=snap.track_id,
                    payload=payload,
                )
            )

            if route.zone == "zone_reject" and not snap.barcode:
                self.event_bus.publish(
                    Event(
                        event="no_read",
                        frame=frame_idx,
                        track_id=snap.track_id,
                        payload={"class": snap.class_name, "confidence": snap.confidence},
                    )
                )

            decisions.append((snap, route))

        return decisions
