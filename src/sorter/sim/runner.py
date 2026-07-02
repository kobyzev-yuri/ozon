from __future__ import annotations

import time
from pathlib import Path

import cv2
import yaml

from sorter.arbitrage.llm_arbitrator import LLMArbitrator
from sorter.config import gemini_model, load_env_files
from sorter.core.events import Event, EventBus, EventLogger
from sorter.field.induction import InductionFilter
from sorter.main_loop import load_config
from sorter.perception.detector import YoloDetector
from sorter.perception.scan_station import ScanStation
from sorter.planning.command_queue import CommandQueue
from sorter.planning.position_tracker import PositionTracker
from sorter.planning.timing_controller import TimingController
from sorter.core.types import Detection, TrackState
from sorter.sim.barcode_simulator import SimBarcodeReader
from sorter.sim.body_matcher import match_detections_to_bodies
from sorter.sim.metrics import SortMetrics
from sorter.sim.pybullet_env import PyBulletConveyor, load_pybullet_config
from sorter.wcs.actuator import SimActuator, draw_overlay
from sorter.wms.routing_table import RoutingTable


def _world_timing_controller(
    routing: RoutingTable,
    queue: CommandQueue,
    actuation_x: float,
    belt_speed_m_per_s: float,
    physics_hz: int,
    lead_steps: int,
) -> TimingController:
    """ETA в шагах физики (не wall-clock time.sleep)."""
    belt_per_frame = belt_speed_m_per_s / physics_hz

    class WorldTiming(TimingController):
        def schedule_divert(self, snap, route, frame_idx, frame_width):
            distance = max(actuation_x - snap.belt_position, 0.0)
            eta = int(distance / max(belt_per_frame, 1e-6)) + lead_steps
            zone_cfg = self.routing.zone_config(route.zone)
            from sorter.core.types import DivertCommand

            cmd = DivertCommand(
                track_id=snap.track_id,
                zone=route.zone,
                execute_at_frame=frame_idx + eta,
                actuator=zone_cfg.get("actuator", "cross-belt"),
                direction=zone_cfg.get("direction"),
            )
            if self.queue.schedule(cmd):
                return cmd
            return None

    return WorldTiming(
        actuation_line_ratio=0.72,
        belt_speed=belt_per_frame,
        lead_frames=lead_steps,
        routing=routing,
        queue=queue,
    )


def run_pybullet_demo(
    pipeline_cfg: dict | None = None,
    pb_cfg: dict | None = None,
    show: bool = True,
    max_physics_steps: int | None = None,
) -> SortMetrics:
    load_env_files()
    pipeline_cfg = pipeline_cfg or load_config()
    pb_cfg = pb_cfg or load_pybullet_config()

    # YOLO для PyBullet — не color fallback
    pipeline_cfg = dict(pipeline_cfg)
    perception = dict(pipeline_cfg.get("perception", {}))
    perception["use_color_fallback"] = False
    if not Path(perception.get("model_path", "models/best.pt")).exists():
        perception["model_path"] = "yolo11n.pt"
    pipeline_cfg["perception"] = perception

    env = PyBulletConveyor(pb_cfg)
    metrics = SortMetrics()

    logger = EventLogger(pipeline_cfg["logging"]["events_path"])
    bus = EventBus(logger=logger)
    routing = RoutingTable()

    physics_hz = int(pb_cfg.get("physics_hz", 240))
    cv_interval = int(pb_cfg.get("cv_interval_steps", 16))
    lead_steps = int(pipeline_cfg["lines"].get("actuator_lead_frames", 18))

    induction = InductionFilter(
        min_track_length=max(1, pipeline_cfg["induction"]["min_track_length"] // 2),
        min_bbox_gap_px=pipeline_cfg["induction"]["min_bbox_gap_px"],
    )
    tracker = PositionTracker(induction, event_bus=bus)
    queue = CommandQueue()
    timing = _world_timing_controller(
        routing,
        queue,
        env.actuation_x,
        env.belt_speed,
        physics_hz,
        lead_steps,
    )

    arbitrator = None
    arb_cfg = pipeline_cfg.get("arbitrator", {})
    if arb_cfg.get("enabled"):
        from sorter.config import gemini_model

        arbitrator = LLMArbitrator(
            min_confidence=arb_cfg["trigger"]["min_confidence"],
            provider=arb_cfg.get("provider", "gemini"),
            model=arb_cfg.get("model") or gemini_model(),
            log_path=pipeline_cfg["logging"]["arbitrator_path"],
            max_calls_per_minute=arb_cfg.get("max_calls_per_minute", 10),
            barcode_cv_mismatch=arb_cfg["trigger"].get("barcode_cv_mismatch", True),
        )

    scan_cfg = pipeline_cfg.get("scan", {})
    bs_cfg = pb_cfg.get("barcode_sim", {})
    sim_barcode_reader = None
    if bs_cfg.get("enabled", False):
        sim_barcode_reader = SimBarcodeReader(
            truth_lookup=env.spawner.barcode_for,
            prefixes=list(bs_cfg.get("prefixes", ["460", "461"])),
            misread_probability=float(bs_cfg.get("misread_probability", 0.08)),
        )
    scan = ScanStation(
        scan_line_ratio=env.scan_line_px() / env._cam_w,
        routing=routing,
        event_bus=bus,
        arbitrator=arbitrator,
        barcode_enabled=scan_cfg.get("barcode_enabled", True),
        sim_barcode_reader=sim_barcode_reader.read if sim_barcode_reader else None,
    )

    detector = YoloDetector(
        model_path=perception["model_path"],
        conf=perception["conf_threshold"],
        tracker_yaml=perception["tracker"],
        use_color_fallback=False,
    )
    actuator = SimActuator(
        bus,
        frame_source=env,
        fault_sim=env.fault_sim if env.fault_sim.enabled else None,
    )

    cv_frame_idx = 0
    snapshots_by_id: dict = {}

    try:
        while max_physics_steps is None or env.physics_step() < max_physics_steps:
            removed_batch = env.step()

            for rem in removed_batch:
                metrics.on_item_removed(rem)
            if removed_batch:
                metrics.record_removed(len(removed_batch))

            if env.physics_step() % cv_interval != 0:
                time.sleep(1.0 / physics_hz)
                continue

            ok, frame = env.read()
            if not ok:
                break

            raw_dets = detector.detect(frame)
            projections = env.get_body_projections()
            detections = match_detections_to_bodies(raw_dets, projections)
            # В симуляторе знаем ground-truth тип с спавнера → WMS lookup
            grounded: list = []
            for det in detections:
                kind = env.spawner.kind_for(det.track_id)
                if kind:
                    grounded.append(
                        Detection(
                            track_id=det.track_id,
                            class_id=det.class_id,
                            class_name=kind,
                            confidence=det.confidence,
                            bbox=det.bbox,
                            barcode=det.barcode,
                        )
                    )
                else:
                    grounded.append(det)
            detections = grounded
            metrics.record_yolo(len(detections))

            snapshots = tracker.update(
                detections,
                lambda cx, cy: env.belt_position_for_bbox_center(cx, cy),
                cv_frame_idx,
            )
            for snap in snapshots:
                cat = env.spawner.category_for(snap.track_id)
                if cat:
                    snap.metadata["category"] = cat
            snapshots_by_id = {s.track_id: s for s in snapshots}

            for snap, route in scan.process(frame, snapshots, cv_frame_idx):
                metrics.record_scan(body_id=snap.track_id)
                if route.zone == "zone_reject":
                    metrics.record_no_read()
                cmd = timing.schedule_divert(snap, route, cv_frame_idx, frame.shape[1])
                if cmd:
                    snap.state = TrackState.SCHEDULED
                    metrics.record_scheduled(body_id=snap.track_id)
                    bus.publish(
                        Event(
                            event="scheduled",
                            frame=cv_frame_idx,
                            track_id=snap.track_id,
                            payload={
                                "zone": cmd.zone,
                                "execute_frame": cmd.execute_at_frame,
                                "eta_frames": cmd.execute_at_frame - cv_frame_idx,
                                "physics_step": env.physics_step(),
                            },
                        )
                    )

            for cmd in queue.pop_due(cv_frame_idx):
                snap = snapshots_by_id.get(cmd.track_id)
                expected = env.spawner.expected_zone_for(cmd.track_id)
                if expected is None and snap and snap.target_zone:
                    expected = snap.target_zone
                outcome = actuator.execute(cmd, cv_frame_idx, snapshots_by_id)
                if not outcome.applies_force:
                    metrics.record_actuator_miss()
                else:
                    metrics.record_divert(cmd.track_id, expected, cmd.zone)
                    if outcome.kind != "normal":
                        metrics.record_actuator_fault()

            spawned = env.spawner.total_spawned
            if spawned > metrics.spawned:
                metrics.record_spawn(spawned - metrics.spawned)

            if show:
                vis = draw_overlay(
                    frame,
                    snapshots,
                    scan.scan_line_ratio,
                    env.actuation_line_px() / frame.shape[1],
                )
                vis = metrics.draw_panel(vis)
                cv2.imshow("Ozon AI Vision (PyBullet + YOLO)", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            cv_frame_idx += 1
            time.sleep(1.0 / physics_hz)
    finally:
        env.close()
        logger.close()
        if show:
            cv2.destroyAllWindows()

    return metrics
