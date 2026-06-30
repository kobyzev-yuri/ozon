from __future__ import annotations

from sorter.core.events import Event, EventBus
from sorter.core.types import Detection, TrackSnapshot, TrackState
from sorter.field.induction import InductionFilter


class PositionTracker:
    """Этап 3: трекинг ≈ энкодер ленты."""

    def __init__(self, induction: InductionFilter, event_bus: EventBus | None = None) -> None:
        self.induction = induction
        self.event_bus = event_bus
        self._tracks: dict[int, TrackSnapshot] = {}
        self._prev_pos: dict[int, float] = {}
        self._inducted_logged: set[int] = set()

    def update(
        self,
        detections: list[Detection],
        belt_position_fn,
        frame_idx: int,
    ) -> list[TrackSnapshot]:
        self.induction.update_lengths(detections)
        active_ids: set[int] = set()

        for det in detections:
            if det.track_id is None:
                continue
            tid = det.track_id
            active_ids.add(tid)
            belt_pos = belt_position_fn(det.bbox.cx, det.bbox.cy)
            prev = self._prev_pos.get(tid, belt_pos)
            velocity = belt_pos - prev
            self._prev_pos[tid] = belt_pos

            snap = self._tracks.get(tid)
            if snap is None:
                snap = TrackSnapshot(
                    track_id=tid,
                    class_name=det.class_name,
                    confidence=det.confidence,
                    bbox=det.bbox,
                    belt_position=belt_pos,
                    velocity=velocity,
                    state=TrackState.NEW,
                    barcode=det.barcode,
                )
                self._tracks[tid] = snap
            else:
                snap.class_name = det.class_name
                snap.confidence = det.confidence
                snap.bbox = det.bbox
                snap.belt_position = belt_pos
                snap.velocity = velocity
                if det.barcode:
                    snap.barcode = det.barcode

            if snap.state == TrackState.NEW and self.induction.is_inducted(tid):
                snap.state = TrackState.INDUCTED
                if self.event_bus is not None and tid not in self._inducted_logged:
                    self._inducted_logged.add(tid)
                    self.event_bus.publish(
                        Event(
                            event="inducted",
                            frame=frame_idx,
                            track_id=tid,
                            payload={
                                "class": snap.class_name,
                                "track_length": self.induction.track_length(tid),
                            },
                        )
                    )

        for tid in list(self._tracks):
            if tid not in active_ids:
                del self._tracks[tid]
                self._prev_pos.pop(tid, None)

        snapshots = [s for s in self._tracks.values() if s.state != TrackState.NEW]
        return self.induction.filter_overlapping(snapshots)
