from __future__ import annotations

import logging

import cv2
import numpy as np

from sorter.core.types import BBox

logger = logging.getLogger(__name__)

_pyzbar_available: bool | None = None


def pyzbar_available() -> bool:
    global _pyzbar_available
    if _pyzbar_available is None:
        try:
            from pyzbar import pyzbar  # noqa: F401
        except ImportError:
            _pyzbar_available = False
        else:
            _pyzbar_available = True
    return _pyzbar_available


def crop_bbox(frame: np.ndarray, bbox: BBox, pad: int = 8) -> np.ndarray:
    h, w = frame.shape[:2]
    x1 = max(int(bbox.x1) - pad, 0)
    y1 = max(int(bbox.y1) - pad, 0)
    x2 = min(int(bbox.x2) + pad, w)
    y2 = min(int(bbox.y2) + pad, h)
    if x2 <= x1 or y2 <= y1:
        return frame
    return frame[y1:y2, x1:x2]


def decode_barcode(frame: np.ndarray, bbox: BBox) -> str | None:
    """
    Скан-портал: декод штрихкода в ROI объекта (EAN/Code128 и т.д.).
    Требует: pip install pyzbar (+ libzbar в системе).
    """
    if not pyzbar_available():
        return None

    from pyzbar.pyzbar import decode as zbar_decode

    crop = crop_bbox(frame, bbox)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Контраст для мелких кодов на симуляторе / видео
    gray = cv2.equalizeHist(gray)

    for sym in zbar_decode(gray):
        try:
            text = sym.data.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = sym.data.decode("latin-1", errors="ignore").strip()
        if text:
            return text
    return None
