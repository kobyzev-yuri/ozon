from __future__ import annotations

import cv2
import numpy as np

from sorter.core.events import Event, EventBus
from sorter.core.types import DivertCommand, TrackSnapshot, TrackState
from sorter.field.frame_source import FrameSource
from sorter.sim.fault_simulator import ActuatorOutcome, FaultSimulator


class SimActuator:
    """Этап 4: исполнение DivertCommand (лог + физика / overlay)."""

    def __init__(
        self,
        event_bus: EventBus,
        frame_source: FrameSource | None = None,
        fault_sim: FaultSimulator | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.frame_source = frame_source
        self.fault_sim = fault_sim
        self.diverted: set[int] = set()

    def execute(
        self,
        command: DivertCommand,
        frame_idx: int,
        snapshots: dict[int, TrackSnapshot],
    ) -> ActuatorOutcome:
        if command.track_id in self.diverted:
            return ActuatorOutcome("normal", 1.0)

        outcome = (
            self.fault_sim.resolve_actuator()
            if self.fault_sim is not None
            else ActuatorOutcome("normal", 1.0)
        )

        if not outcome.applies_force:
            self.event_bus.publish(
                Event(
                    event="actuator_fault",
                    frame=frame_idx,
                    track_id=command.track_id,
                    payload={
                        "zone": command.zone,
                        "fault": outcome.kind,
                        "actuator": command.actuator,
                    },
                )
            )
            return outcome

        snap = snapshots.get(command.track_id)
        if snap is not None:
            snap.state = TrackState.DIVERTED

        applied = True
        if self.frame_source is not None and command.direction:
            applied = bool(
                self.frame_source.divert(
                    command.track_id,
                    command.direction,
                    outcome.force_scale,
                )
            )

        if not applied:
            return ActuatorOutcome("miss", 0.0)

        self.diverted.add(command.track_id)
        payload = {
            "zone": command.zone,
            "actuator": command.actuator,
            "direction": command.direction,
        }
        if outcome.kind != "normal":
            payload["actuator_fault"] = outcome.kind
            payload["force_scale"] = outcome.force_scale

        self.event_bus.publish(
            Event(
                event="diverted",
                frame=frame_idx,
                track_id=command.track_id,
                payload=payload,
            )
        )
        return outcome


def draw_overlay(
    frame: np.ndarray,
    snapshots: list[TrackSnapshot],
    scan_line_ratio: float,
    actuation_line_ratio: float,
) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    scan_x = int(w * scan_line_ratio)
    act_x = int(w * actuation_line_ratio)
    cv2.line(out, (scan_x, 0), (scan_x, h), (0, 255, 255), 2)
    cv2.line(out, (act_x, 0), (act_x, h), (0, 165, 255), 2)
    cv2.putText(out, "SCAN", (scan_x + 4, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.putText(out, "ACT", (act_x + 4, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

    for snap in snapshots:
        b = snap.bbox
        color = (0, 255, 0) if snap.state == TrackState.DIVERTED else (255, 128, 0)
        cv2.rectangle(out, (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2)), color, 2)
        label = f"#{snap.track_id} {snap.class_name}"
        if snap.target_zone:
            label += f" → {snap.target_zone}"
        cv2.putText(
            out,
            label,
            (int(b.x1), max(int(b.y1) - 6, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
        )
    return out
