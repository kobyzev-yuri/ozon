from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ActuatorOutcome:
    """Исход срабатывания пушера в симуляторе."""

    kind: str  # normal | miss | weak | overshoot
    force_scale: float

    @property
    def applies_force(self) -> bool:
        return self.kind != "miss" and self.force_scale > 0


class FaultSimulator:
    """
    Случайные отказы линии в PyBullet-демо (только симулятор, не видео/прод).

    - belt_slip: посылка едет быстрее/медленнее номинала → ПЛК стреляет «в мимо»
    - actuator miss: импульс не подан
    - weak / overshoot: слабый или чрезмерный толчок cross-belt
    """

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", False))

        bs = cfg.get("belt_slip", {})
        self.slip_assign_prob = float(bs.get("assign_probability", 0.25))
        slip_range = bs.get("speed_factor_range", [0.82, 1.12])
        self.slip_range = (float(slip_range[0]), float(slip_range[1]))

        act = cfg.get("actuator", {})
        self.miss_prob = float(act.get("miss_probability", 0.06))
        self.weak_prob = float(act.get("weak_push_probability", 0.05))
        self.weak_factor = float(act.get("weak_force_factor", 0.35))
        self.overshoot_prob = float(act.get("overshoot_probability", 0.04))
        self.overshoot_factor = float(act.get("overshoot_force_factor", 1.75))

    def roll_belt_slip_factor(self) -> float:
        if not self.enabled:
            return 1.0
        if random.random() >= self.slip_assign_prob:
            return 1.0
        return random.uniform(self.slip_range[0], self.slip_range[1])

    def resolve_actuator(self) -> ActuatorOutcome:
        if not self.enabled:
            return ActuatorOutcome("normal", 1.0)
        if random.random() < self.miss_prob:
            return ActuatorOutcome("miss", 0.0)
        if random.random() < self.weak_prob:
            return ActuatorOutcome("weak", self.weak_factor)
        if random.random() < self.overshoot_prob:
            return ActuatorOutcome("overshoot", self.overshoot_factor)
        return ActuatorOutcome("normal", 1.0)
