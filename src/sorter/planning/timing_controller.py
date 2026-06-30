from __future__ import annotations

from sorter.core.types import DivertCommand, RouteDecision, TrackSnapshot
from sorter.planning.command_queue import CommandQueue
from sorter.wms.routing_table import RoutingTable


class TimingController:
    """Этап 3: ETA от SCAN LINE до ACTUATION LINE."""

    def __init__(
        self,
        actuation_line_ratio: float,
        belt_speed: float,
        lead_frames: int,
        routing: RoutingTable,
        queue: CommandQueue,
    ) -> None:
        self.actuation_line_ratio = actuation_line_ratio
        self.belt_speed = belt_speed
        self.lead_frames = lead_frames
        self.routing = routing
        self.queue = queue

    def actuation_line_px(self, frame_width: int) -> float:
        return frame_width * self.actuation_line_ratio

    def schedule_divert(
        self,
        snap: TrackSnapshot,
        route: RouteDecision,
        frame_idx: int,
        frame_width: int,
    ) -> DivertCommand | None:
        act_line = self.actuation_line_px(frame_width)
        distance = max(act_line - snap.belt_position, 0.0)
        eta_frames = int(distance / max(self.belt_speed, 1e-6)) + self.lead_frames
        zone_cfg = self.routing.zone_config(route.zone)

        cmd = DivertCommand(
            track_id=snap.track_id,
            zone=route.zone,
            execute_at_frame=frame_idx + eta_frames,
            actuator=zone_cfg.get("actuator", "cross-belt"),
            direction=zone_cfg.get("direction"),
        )
        if self.queue.schedule(cmd):
            return cmd
        return None
