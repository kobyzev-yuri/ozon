from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class FrameSource(ABC):
    """
    Единый контракт источника кадра.
    Заменяет RTSP Hikvision / .mp4 / PyBullet getCameraImage.
    """

    @abstractmethod
    def read(self) -> tuple[bool, np.ndarray]:
        """Returns (ok, frame_bgr)."""

    @abstractmethod
    def step(self) -> None:
        """Advance simulation clock (no-op for video)."""

    @abstractmethod
    def belt_position_for_bbox_center(self, cx: float, cy: float) -> float:
        """Map pixel/world center → scalar position along belt axis."""

    def divert(self, track_id: int, direction: str) -> None:
        """Optional: physical actuator in 3D twin."""

    def close(self) -> None:
        pass
