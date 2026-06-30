from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from sorter.field.frame_source import FrameSource


class VideoFileSource(FrameSource):
  def __init__(self, path: str | Path, loop: bool = True) -> None:
    self.path = Path(path)
    self.loop = loop
    self._cap = cv2.VideoCapture(str(self.path))
    self._frame_idx = 0
    if not self._cap.isOpened():
      raise FileNotFoundError(f"Cannot open video: {self.path}")

  def read(self) -> tuple[bool, np.ndarray]:
    ok, frame = self._cap.read()
    if not ok and self.loop:
      self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
      ok, frame = self._cap.read()
    if ok:
      self._frame_idx += 1
    return ok, frame

  def step(self) -> None:
    pass

  def belt_position_for_bbox_center(self, cx: float, cy: float) -> float:
    return cx

  def close(self) -> None:
    self._cap.release()
