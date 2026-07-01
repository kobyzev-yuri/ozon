from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class SimBarcodeRead:
    """Результат «чтения» скан-портала в симуляторе (не pyzbar)."""

    value: str
    truth: str
    misread: bool


def generate_barcode(prefixes: list[str]) -> str:
    prefix = random.choice(prefixes)
    suffix = random.randint(1_000_000_000, 9_999_999_999)
    return f"{prefix}{suffix}"


def flip_prefix(barcode: str, prefixes: list[str]) -> str:
    """Ошибочное чтение: смена префикса маршрута (460 ↔ 461)."""
    if len(prefixes) < 2:
        return barcode
    current = next((p for p in prefixes if barcode.startswith(p)), None)
    if current is None:
        return barcode
    other = random.choice([p for p in prefixes if p != current])
    return other + barcode[len(current) :]


class SimBarcodeReader:
    """
    Эмуляция скан-портала в PyBullet: на объекте «висит» EAN (truth),
    на SCAN LINE возвращаем чтение — иногда с misread.
    """

    def __init__(
        self,
        truth_lookup,
        prefixes: list[str] | None = None,
        misread_probability: float = 0.08,
    ) -> None:
        self._truth_lookup = truth_lookup
        self.prefixes = prefixes or ["460", "461"]
        self.misread_probability = misread_probability

    def read(self, body_id: int) -> SimBarcodeRead | None:
        truth = self._truth_lookup(body_id)
        if not truth:
            return None
        misread = random.random() < self.misread_probability
        value = flip_prefix(truth, self.prefixes) if misread else truth
        return SimBarcodeRead(value=value, truth=truth, misread=misread)
