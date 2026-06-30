from __future__ import annotations

import numpy as np

from sorter.core.types import BBox, Detection


def color_fallback_detect(frame: np.ndarray) -> list[Detection]:
    """
    Быстрый прототип без весов YOLO (демо / CI без GPU).
    Заменяется YoloDetector без смены контракта detect(frame).
    """
    h, w, _ = frame.shape
    roi = frame[h // 3 : 2 * h // 3, w // 3 : 2 * w // 3]
    avg = np.mean(roi, axis=(0, 1))
    detections: list[Detection] = []
    if avg[2] > 150:
        detections.append(
            Detection(
                track_id=1,
                class_id=0,
                class_name="box",
                confidence=0.9,
                bbox=BBox(w * 0.35, h * 0.35, w * 0.65, h * 0.65),
            )
        )
    elif avg[0] > 150:
        detections.append(
            Detection(
                track_id=1,
                class_id=1,
                class_name="sphere",
                confidence=0.9,
                bbox=BBox(w * 0.35, h * 0.35, w * 0.65, h * 0.65),
            )
        )
    return detections
