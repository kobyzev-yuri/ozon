from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from sorter.sim.barcode_simulator import generate_barcode
from sorter.sim.fault_simulator import FaultSimulator
from sorter.sim.metrics import RemovedItem


@dataclass
class SpawnedItem:
    body_id: int
    kind: str
    spawned_step: int
    barcode: str | None = None
    belt_slip_factor: float = 1.0


class AutomaticSpawner:
    """
    Бесконечная генерация объектов на начале ленты + очистка «отработанных» тел.
    Вызывается каждый шаг физики из PyBulletConveyor.step().
    """

    def __init__(
        self,
        spawn_fn: Callable[[str, list[float], int], int],
        remove_fn: Callable[[int], None],
        position_fn: Callable[[int], tuple[float, float, float]],
        spawn_x: float,
        spawn_z: float,
        interval_steps: int = 500,
        y_offset_range: tuple[float, float] = (-0.2, 0.2),
        kinds: list[str] | None = None,
        cleanup_x: float = 3.5,
        cleanup_z: float = 0.05,
        barcode_prefixes: list[str] | None = None,
        fault_sim: FaultSimulator | None = None,
    ) -> None:
        self._spawn_fn = spawn_fn
        self._remove_fn = remove_fn
        self._position_fn = position_fn
        self.spawn_x = spawn_x
        self.spawn_z = spawn_z
        self.interval_steps = interval_steps
        self.y_offset_range = y_offset_range
        self.kinds = kinds or ["box", "sphere"]
        self.cleanup_x = cleanup_x
        self.cleanup_z = cleanup_z
        self.barcode_prefixes = barcode_prefixes or ["460", "461"]
        self._fault_sim = fault_sim
        self.active: list[SpawnedItem] = []
        self.total_spawned = 0
        self.total_removed = 0
        self.last_removed: list[RemovedItem] = []

    def tick(self, step: int) -> list[SpawnedItem]:
        created: list[SpawnedItem] = []
        if step > 0 and step % self.interval_steps == 0:
            kind = random.choice(self.kinds)
            y_off = random.uniform(*self.y_offset_range)
            pos = [self.spawn_x, y_off, self.spawn_z]
            body_id = self._spawn_fn(kind, pos, step)
            barcode = (
                generate_barcode(self.barcode_prefixes) if self.barcode_prefixes else None
            )
            slip = (
                self._fault_sim.roll_belt_slip_factor()
                if self._fault_sim is not None
                else 1.0
            )
            item = SpawnedItem(
                body_id=body_id,
                kind=kind,
                spawned_step=step,
                barcode=barcode,
                belt_slip_factor=slip,
            )
            self.active.append(item)
            self.total_spawned += 1
            created.append(item)
        return created

    def cleanup(self, step: int) -> list[RemovedItem]:
        removed: list[RemovedItem] = []
        remaining: list[SpawnedItem] = []
        for item in self.active:
            try:
                x, y, z = self._position_fn(item.body_id)
            except Exception:
                removed.append(
                    RemovedItem(item.body_id, item.kind, "lost", 0.0, 0.0, 0.0)
                )
                self.total_removed += 1
                continue

            if z < self.cleanup_z:
                try:
                    self._remove_fn(item.body_id)
                except Exception:
                    pass
                removed.append(
                    RemovedItem(item.body_id, item.kind, "fell_floor", x, y, z)
                )
                self.total_removed += 1
            elif x > self.cleanup_x:
                try:
                    self._remove_fn(item.body_id)
                except Exception:
                    pass
                removed.append(
                    RemovedItem(item.body_id, item.kind, "end_of_belt", x, y, z)
                )
                self.total_removed += 1
            else:
                remaining.append(item)

        self.active = remaining
        self.last_removed = removed
        return removed

    def body_ids(self) -> list[int]:
        return [i.body_id for i in self.active]

    def kind_for(self, body_id: int) -> str | None:
        for item in self.active:
            if item.body_id == body_id:
                return item.kind
        return None

    def barcode_for(self, body_id: int) -> str | None:
        for item in self.active:
            if item.body_id == body_id:
                return item.barcode
        return None

    def slip_factor_for(self, body_id: int) -> float:
        for item in self.active:
            if item.body_id == body_id:
                return item.belt_slip_factor
        return 1.0

    def kind_for_removed(self, body_id: int, removed_batch: list[RemovedItem]) -> str | None:
        for r in removed_batch:
            if r.body_id == body_id:
                return r.kind
        return self.kind_for(body_id)
