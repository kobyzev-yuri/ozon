from __future__ import annotations

from pathlib import Path

import numpy as np

from sorter.core.types import BBox, Detection
from sorter.perception.color_fallback import color_fallback_detect


class YoloDetector:
    """
    YOLO + ByteTrack. Одна точка подмены для жюри:
    color_fallback_detect → model.track(frame, persist=True).
    """

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        conf: float = 0.35,
        tracker_yaml: str = "config/bytetrack.yaml",
        use_color_fallback: bool = False,
    ) -> None:
        self.model_path = model_path
        self.conf = conf
        self.tracker_yaml = tracker_yaml
        self.use_color_fallback = use_color_fallback
        self._model = None

    def _load_model(self):
        if self._model is None:
            from ultralytics import YOLO

            path = Path(self.model_path)
            weights = str(path) if path.exists() else self.model_path
            self._model = YOLO(weights)
        return self._model

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self.use_color_fallback:
            return color_fallback_detect(frame)

        model = self._load_model()
        results = model.track(
            frame,
            persist=True,
            conf=self.conf,
            tracker=self.tracker_yaml,
            verbose=False,
        )[0]

        if results.boxes is None or len(results.boxes) == 0:
            return []

        names = results.names
        out: list[Detection] = []
        for box in results.boxes:
            tid = int(box.id.item()) if box.id is not None else None
            cls_id = int(box.cls.item())
            conf = float(box.conf.item())
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            out.append(
                Detection(
                    track_id=tid,
                    class_id=cls_id,
                    class_name=str(names.get(cls_id, cls_id)),
                    confidence=conf,
                    bbox=BBox(x1, y1, x2, y2),
                )
            )
        return out
