from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np

from sorter.core.events import Event, EventLogger
from sorter.core.types import RouteDecision, TrackSnapshot


class LLMArbitrator:
    """
    Оригинальный ход: «умный диспетчер» для спорных случаев.

    Не в hot path каждого кадра — только когда:
    - confidence YOLO ниже порога
    - расхождение штрихкода и CV-класса
    - повторный scan с другим классом (опционально)

    Паттерн из chicken_count (UltralyticsCounterAudit + Gemini), адаптирован
  под маршрутизацию WMS.
    """

    def __init__(
        self,
        min_confidence: float = 0.55,
        provider: str = "gemini",
        model: str = "gemini-2.0-flash",
        log_path: str = "logs/arbitrator.jsonl",
        max_calls_per_minute: int = 10,
        barcode_cv_mismatch: bool = True,
    ) -> None:
        self.min_confidence = min_confidence
        self.provider = provider
        self.model = model
        self.logger = EventLogger(log_path)
        self.max_calls_per_minute = max_calls_per_minute
        self.barcode_cv_mismatch = barcode_cv_mismatch
        self._call_times: list[float] = []

    def should_arbitrate(self, snap: TrackSnapshot, route: RouteDecision) -> bool:
        if snap.confidence < self.min_confidence:
            return True
        if self.barcode_cv_mismatch and snap.barcode and route.source == "cv":
            # WMS по штрихкоду мог бы дать другую зону — флаг для демо
            return snap.metadata.get("barcode_cv_conflict", False)
        return False

    def _rate_limit_ok(self) -> bool:
        now = time.time()
        self._call_times = [t for t in self._call_times if now - t < 60]
        return len(self._call_times) < self.max_calls_per_minute

    def arbitrate(
        self,
        frame: np.ndarray,
        snap: TrackSnapshot,
        preliminary: RouteDecision,
    ) -> RouteDecision:
        if not self._rate_limit_ok():
            preliminary.reason += " | arbitrator skipped (rate limit)"
            return preliminary

        self._call_times.append(time.time())
        crop = self._crop(frame, snap)
        prompt = self._build_prompt(snap, preliminary)

        try:
            answer = self._call_llm(prompt, crop)
            zone = answer.get("zone", preliminary.zone)
            reason = answer.get("reasoning", "llm arbitration")
            decision = RouteDecision(zone=zone, reason=reason, source="llm_arbitrator")
        except Exception as exc:  # noqa: BLE001 — fallback на WMS на демо
            decision = RouteDecision(
                zone=preliminary.zone,
                reason=f"{preliminary.reason} | arbitrator error: {exc}",
                source=preliminary.source,
            )
            answer = {"error": str(exc)}

        self.logger.emit(
            Event(
                event="arbitrator_decision",
                frame=snap.scan_frame or 0,
                track_id=snap.track_id,
                payload={
                    "preliminary": asdict(preliminary),
                    "final": asdict(decision),
                    "llm_response": answer,
                },
            )
        )
        return decision

    def _crop(self, frame: np.ndarray, snap: TrackSnapshot) -> np.ndarray:
        b = snap.bbox
        h, w = frame.shape[:2]
        x1, y1 = max(int(b.x1), 0), max(int(b.y1), 0)
        x2, y2 = min(int(b.x2), w), min(int(b.y2), h)
        return frame[y1:y2, x1:x2]

    def _build_prompt(self, snap: TrackSnapshot, route: RouteDecision) -> str:
        return (
            "You are a warehouse sortation arbitrator for an Ozon-style hub.\n"
            "Given parcel metadata, choose the best chute zone.\n"
            "Reply JSON only: {\"zone\": \"chute_a|chute_b|chute_c|zone_reject\", "
            "\"reasoning\": \"...\"}\n\n"
            f"track_id: {snap.track_id}\n"
            f"cv_class: {snap.class_name}\n"
            f"confidence: {snap.confidence:.2f}\n"
            f"barcode: {snap.barcode or 'none'}\n"
            f"wms_preliminary: {route.zone} ({route.reason})\n"
        )

    def _call_llm(self, prompt: str, crop_bgr: np.ndarray) -> dict:
        if self.provider == "gemini":
            return self._call_gemini(prompt, crop_bgr)
        if self.provider == "openai":
            return self._call_openai(prompt, crop_bgr)
        raise ValueError(f"Unknown provider: {self.provider}")

    def _encode_image(self, crop_bgr: np.ndarray) -> str:
        ok, buf = cv2.imencode(".jpg", crop_bgr)
        if not ok:
            raise RuntimeError("Failed to encode crop")
        return base64.b64encode(buf.tobytes()).decode("ascii")

    def _call_gemini(self, prompt: str, crop_bgr: np.ndarray) -> dict:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")

        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.model)
        b64 = self._encode_image(crop_bgr)
        response = model.generate_content(
            [
                prompt,
                {"mime_type": "image/jpeg", "data": BytesIO(base64.b64decode(b64)).read()},
            ]
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(text)

    def _call_openai(self, prompt: str, crop_bgr: np.ndarray) -> dict:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        b64 = self._encode_image(crop_bgr)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content or "{}")
