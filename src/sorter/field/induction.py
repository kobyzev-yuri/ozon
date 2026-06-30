from __future__ import annotations

from sorter.core.types import Detection, TrackSnapshot


class InductionFilter:
    """Этап 1: сингуляция — отсекаем короткие треки и слипшиеся bbox."""

    def __init__(self, min_track_length: int = 5, min_bbox_gap_px: float = 40) -> None:
        self.min_track_length = min_track_length
        self.min_bbox_gap_px = min_bbox_gap_px
        self._track_lengths: dict[int, int] = {}

    def update_lengths(self, detections: list[Detection]) -> None:
        seen: set[int] = set()
        for det in detections:
            if det.track_id is None:
                continue
            seen.add(det.track_id)
            self._track_lengths[det.track_id] = self._track_lengths.get(det.track_id, 0) + 1
        for tid in list(self._track_lengths):
            if tid not in seen:
                del self._track_lengths[tid]

    def is_inducted(self, track_id: int) -> bool:
        return self._track_lengths.get(track_id, 0) >= self.min_track_length

    def filter_overlapping(self, snapshots: list[TrackSnapshot]) -> list[TrackSnapshot]:
        if len(snapshots) < 2:
            return snapshots
        kept: list[TrackSnapshot] = []
        for snap in sorted(snapshots, key=lambda s: s.confidence, reverse=True):
            if any(
                abs(snap.bbox.cx - other.bbox.cx) < self.min_bbox_gap_px
                and abs(snap.bbox.cy - other.bbox.cy) < self.min_bbox_gap_px
                for other in kept
            ):
                continue
            kept.append(snap)
        return kept
