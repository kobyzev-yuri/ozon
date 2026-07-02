from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class RemovedItem:
    body_id: int
    kind: str
    reason: str  # end_of_belt | fell_floor | lost
    x: float
    y: float
    z: float


@dataclass
class SortMetrics:
    """KPI Dashboard: пропускная способность, счётчики по типам, AI missed."""

    spawned: int = 0
    removed: int = 0
    scanned: int = 0
    scheduled: int = 0
    diverted: int = 0
    processed_boxes: int = 0
    processed_spheres: int = 0
    ai_missed: int = 0
    divert_correct: int = 0
    divert_wrong: int = 0
    yolo_frames: int = 0
    yolo_detections: int = 0
    no_read: int = 0
    actuator_miss: int = 0
    actuator_faults: int = 0
    start_time: float = field(default_factory=time.time)
    _diverted_bodies: set[int] = field(default_factory=set)
    _scanned_bodies: set[int] = field(default_factory=set)
    _scheduled_bodies: set[int] = field(default_factory=set)
    _counted_processed: set[int] = field(default_factory=set)

    @property
    def total_processed(self) -> int:
        return self.processed_boxes + self.processed_spheres

    @property
    def elapsed_seconds(self) -> float:
        return max(time.time() - self.start_time, 1.0)

    @property
    def throughput_per_min(self) -> float:
        """Пропускная способность: успешно обработанных штук/мин."""
        return self.total_processed / self.elapsed_seconds * 60.0

    @property
    def spawn_rate_per_min(self) -> float:
        return self.spawned / self.elapsed_seconds * 60.0

    @property
    def ai_accuracy(self) -> float:
        decided = self.total_processed + self.ai_missed
        if decided == 0:
            return 100.0
        return 100.0 * self.total_processed / decided

    @property
    def divert_accuracy(self) -> float:
        total = self.divert_correct + self.divert_wrong
        if total == 0:
            return 0.0
        return 100.0 * self.divert_correct / total

    def record_spawn(self, count: int = 1) -> None:
        self.spawned += count

    def record_removed(self, count: int = 1) -> None:
        self.removed += count

    def record_scan(self, body_id: int | None = None) -> None:
        self.scanned += 1
        if body_id is not None:
            self._scanned_bodies.add(body_id)

    def record_scheduled(self, body_id: int | None = None) -> None:
        self.scheduled += 1
        if body_id is not None:
            self._scheduled_bodies.add(body_id)

    def record_divert(self, body_id: int, expected_zone: str | None, actual_zone: str) -> None:
        if body_id in self._diverted_bodies:
            return
        self._diverted_bodies.add(body_id)
        self.diverted += 1
        if expected_zone is None:
            return
        if actual_zone == expected_zone:
            self.divert_correct += 1
        else:
            self.divert_wrong += 1
        self._mark_processed(body_id, actual_zone)

    def _mark_processed(self, body_id: int, zone: str) -> None:
        if body_id in self._counted_processed:
            return
        self._counted_processed.add(body_id)
        if zone in ("zone_b", "chute_a"):
            self.processed_boxes += 1
        elif zone in ("zone_d", "chute_b"):
            self.processed_spheres += 1

    def record_yolo(self, n_detections: int) -> None:
        self.yolo_frames += 1
        self.yolo_detections += n_detections

    def record_no_read(self) -> None:
        self.no_read += 1

    def record_actuator_miss(self) -> None:
        self.actuator_miss += 1

    def record_actuator_fault(self) -> None:
        self.actuator_faults += 1

    def on_item_removed(self, item: RemovedItem) -> None:
        """
        Вызывается при cleanup спавнера.
        ai_missed: объект покинул ленту без скана или без завершённой сортировки.
        """
        bid = item.body_id
        if bid in self._counted_processed:
            return

        kind = item.kind
        scanned = bid in self._scanned_bodies
        diverted = bid in self._diverted_bodies

        if item.reason == "fell_floor" and kind == "box" and diverted:
            self._mark_processed(bid, "zone_b")
            return

        if item.reason == "end_of_belt":
            if not scanned:
                self.ai_missed += 1
                return
            if kind == "sphere":
                # Сфера едет прямо — успех без актуатора
                if bid not in self._counted_processed:
                    self._counted_processed.add(bid)
                    self.processed_spheres += 1
                return
            if kind == "box" and not diverted:
                self.ai_missed += 1

    def expected_zone_for_kind(self, kind: str) -> str:
        mapping = {
            "box": "zone_b",
            "sphere": "zone_d",
            "cylinder": "zone_b",
            "box_300": "zone_b",
            "box_400": "zone_c",
            "lunchbox": "zone_b",
            "bottle": "zone_d",
            "plate": "zone_d",
            "bag": "zone_d",
            "pouf": "zone_c",
            "helmet": "zone_d",
            "detergent": "zone_b",
            "pen": "zone_b",
        }
        return mapping.get(kind, "zone_reject")

    def summary_lines(self) -> list[str]:
        return [
            "=== Ozon Tech Sorting Dashboard ===",
            f"Processed: {self.total_processed} | Spawned: {self.spawned} | Removed: {self.removed}",
            f"Boxes (CV type): {self.processed_boxes} | Spheres (CV type): {self.processed_spheres}",
            f"Throughput: {self.throughput_per_min:.1f} items/min  (spawn: {self.spawn_rate_per_min:.1f}/min)",
            f"AI Accuracy: {self.ai_accuracy:.1f}%  |  AI Missed: {self.ai_missed}",
            f"Scanned: {self.scanned}  Scheduled: {self.scheduled}  Diverted: {self.diverted}",
            f"Divert accuracy: {self.divert_accuracy:.1f}%  |  No-read: {self.no_read}",
            f"Actuator miss: {self.actuator_miss}  |  Faults (weak/overshoot): {self.actuator_faults}",
        ]

    def draw_panel(self, frame: np.ndarray) -> np.ndarray:
        """KPI overlay — как аналитическая панель на видеопотоке."""
        out = frame.copy()
        h, w = out.shape[:2]
        panel_h = 110
        cv2.rectangle(out, (0, 0), (w, panel_h), (20, 20, 20), -1)

        cv2.putText(
            out,
            "Ozon Tech Sorting Dashboard",
            (10, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 165, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            out,
            f"Processed: {self.total_processed} | Spawned: {self.spawned}",
            (10, 48),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            out,
            f"Boxes (CV): {self.processed_boxes} | Spheres (CV): {self.processed_spheres}",
            (10, 68),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            out,
            f"Throughput: {self.throughput_per_min:.1f} items/min",
            (10, 88),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )

        acc_color = (0, 255, 0) if self.ai_accuracy >= 90 else (0, 0, 255)
        right_x = min(w - 180, 280)
        cv2.putText(
            out,
            f"AI Accuracy: {self.ai_accuracy:.1f}%",
            (right_x, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            acc_color,
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            out,
            f"AI Missed: {self.ai_missed}",
            (right_x, 48),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            out,
            f"YOLO dets: {self.yolo_detections}",
            (right_x, 68),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (180, 180, 180),
            1,
            cv2.LINE_AA,
        )
        return out

    def export_snapshot(self) -> dict:
        return {
            "spawned": self.spawned,
            "processed_boxes": self.processed_boxes,
            "processed_spheres": self.processed_spheres,
            "ai_missed": self.ai_missed,
            "ai_accuracy_pct": round(self.ai_accuracy, 2),
            "throughput_per_min": round(self.throughput_per_min, 2),
            "elapsed_sec": round(self.elapsed_seconds, 1),
        }
