from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import asdict

import cv2
import httpx
import numpy as np

from sorter.config import gemini_api_key, gemini_base_url, gemini_model
from sorter.core.events import Event, EventLogger
from sorter.core.types import RouteDecision, TrackSnapshot

GEMINI_FALLBACK_MODELS = (
    # https://proxyapi.ru/docs/google-models — vision-capable, по убыванию приоритета
    "gemini-3.1-flash-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)


class LLMArbitrator:
    """
    «Умный диспетчер» для спорных случаев: crop с ленты → Gemini Vision (ProxyAPI).

    Не в hot path каждого кадра — только при низком confidence YOLO или конфликте barcode↔CV.
    API: POST {GEMINI_BASE_URL}/v1beta/models/{model}:generateContent (ProxyAPI).
    Модели: https://proxyapi.ru/docs/google-models
    """

    def __init__(
        self,
        min_confidence: float = 0.55,
        provider: str = "gemini",
        model: str | None = None,
        log_path: str = "logs/arbitrator.jsonl",
        max_calls_per_minute: int = 10,
        barcode_cv_mismatch: bool = True,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.min_confidence = min_confidence
        self.provider = provider
        self.model = model or gemini_model()
        self.base_url = (base_url or gemini_base_url()).rstrip("/")
        self.timeout = float(os.environ.get("GEMINI_TIMEOUT", timeout))
        self.logger = EventLogger(log_path)
        self.max_calls_per_minute = max_calls_per_minute
        self.barcode_cv_mismatch = barcode_cv_mismatch
        self._call_times: list[float] = []

    def should_arbitrate(self, snap: TrackSnapshot, route: RouteDecision) -> bool:
        if snap.confidence < self.min_confidence:
            return True
        if self.barcode_cv_mismatch and snap.metadata.get("barcode_cv_conflict"):
            return True
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
        used_model = self.model

        try:
            if self.provider == "gemini":
                answer, used_model = self._call_gemini_vision(prompt, crop)
            elif self.provider == "openai":
                answer = self._call_openai_vision(prompt, crop)
            else:
                raise ValueError(f"Unknown provider: {self.provider}")

            zone = answer.get("zone", preliminary.zone)
            reason = answer.get("reasoning", "llm arbitration")
            decision = RouteDecision(zone=zone, reason=reason, source="llm_arbitrator")
        except Exception as exc:  # noqa: BLE001 — fallback на WMS
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
                    "llm_model": used_model,
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
        if x2 <= x1 or y2 <= y1:
            return frame
        return frame[y1:y2, x1:x2]

    def _build_prompt(self, snap: TrackSnapshot, route: RouteDecision) -> str:
        return (
            "Ты — арбитр сортировки на конвейере распределительного хаба (стиль Ozon).\n"
            "На изображении — crop посылки с ленты. YOLO дал неуверенный или спорный результат.\n"
            "Выбери целевой рукав и кратко объясни решение.\n\n"
            "Ответь ТОЛЬКО JSON:\n"
            '{"zone": "chute_a|chute_b|chute_c|zone_reject", "reasoning": "..."}\n\n'
            f"track_id: {snap.track_id}\n"
            f"cv_class: {snap.class_name}\n"
            f"confidence: {snap.confidence:.2f}\n"
            f"barcode: {snap.barcode or 'нет'}\n"
            f"wms_preliminary: {route.zone} ({route.reason})\n"
            "chute_a — коробки/тип A; chute_b — сферы/тип B; chute_c — прочее; zone_reject — no read.\n"
        )

    def _encode_image_b64(self, crop_bgr: np.ndarray) -> str:
        ok, buf = cv2.imencode(".jpg", crop_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            raise RuntimeError("Failed to encode crop")
        return base64.b64encode(buf.tobytes()).decode("ascii")

    def _parse_json_text(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return json.loads(text)

    def _gemini_models_to_try(self) -> list[str]:
        seen: set[str] = set()
        models: list[str] = []
        for name in (self.model, *GEMINI_FALLBACK_MODELS):
            if name and name not in seen:
                seen.add(name)
                models.append(name)
        return models

    def _call_gemini_vision(self, prompt: str, crop_bgr: np.ndarray) -> tuple[dict, str]:
        api_key = gemini_api_key()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY или OPENAI_API_KEY не задан — см. config.env (ProxyAPI)"
            )

        image_b64 = self._encode_image_b64(crop_bgr)
        last_error = "unknown"

        for model in self._gemini_models_to_try():
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 512,
                },
            }
            try:
                response = httpx.post(
                    f"{self.base_url}/v1beta/models/{model}:generateContent",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code != 200:
                    body = response.text[:300]
                    last_error = f"{model}: HTTP {response.status_code} {body}"
                    if response.status_code in (400, 403, 404):
                        continue
                    raise RuntimeError(last_error)

                result = response.json()
                candidates = result.get("candidates") or []
                if not candidates:
                    last_error = f"{model}: empty candidates"
                    continue
                parts = candidates[0].get("content", {}).get("parts", [])
                text = parts[0].get("text", "") if parts else ""
                if not text.strip():
                    last_error = f"{model}: empty text"
                    continue
                return self._parse_json_text(text), model
            except json.JSONDecodeError as exc:
                last_error = f"{model}: invalid JSON ({exc})"
                continue
            except httpx.HTTPError as exc:
                last_error = f"{model}: {exc}"
                continue

        raise RuntimeError(last_error)

    def _call_openai_vision(self, prompt: str, crop_bgr: np.ndarray) -> dict:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in config.env")

        from openai import OpenAI

        base = os.environ.get("OPENAI_BASE_URL", "https://api.proxyapi.ru/openai/v1")
        client = OpenAI(api_key=api_key, base_url=base)
        b64 = self._encode_image_b64(crop_bgr)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        response = client.chat.completions.create(
            model=model,
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
