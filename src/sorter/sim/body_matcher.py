from __future__ import annotations

from dataclasses import dataclass

from sorter.core.types import BBox, Detection


@dataclass
class BodyProjection:
    body_id: int
    cx: float
    cy: float
    world_x: float


def match_detections_to_bodies(
    detections: list[Detection],
    projections: list[BodyProjection],
    max_distance_px: float = 80.0,
) -> list[Detection]:
    """
    Привязка YOLO bbox к физическим body_id PyBullet по ближайшему центру в кадре.
    track_id заменяется на body_id для WCS/ПЛК-логики.
    """
    if not projections:
        return detections

    used_bodies: set[int] = set()
    matched: list[Detection] = []

    for det in sorted(detections, key=lambda d: d.confidence, reverse=True):
        best: BodyProjection | None = None
        best_dist = max_distance_px
        dcx, dcy = det.bbox.cx, det.bbox.cy
        for proj in projections:
            if proj.body_id in used_bodies:
                continue
            dist = ((proj.cx - dcx) ** 2 + (proj.cy - dcy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best = proj
        if best is None:
            continue
        used_bodies.add(best.body_id)
        matched.append(
            Detection(
                track_id=best.body_id,
                class_id=det.class_id,
                class_name=det.class_name,
                confidence=det.confidence,
                bbox=det.bbox,
                barcode=det.barcode,
            )
        )
    return matched
