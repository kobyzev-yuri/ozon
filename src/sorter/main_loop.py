from __future__ import annotations

import time
from pathlib import Path

import cv2
import yaml

from sorter.arbitrage.llm_arbitrator import LLMArbitrator
from sorter.config import gemini_model, load_env_files
from sorter.core.events import Event, EventBus, EventLogger
from sorter.field.frame_source import FrameSource
from sorter.field.induction import InductionFilter
from sorter.field.video_source import VideoFileSource
from sorter.perception.detector import YoloDetector
from sorter.perception.scan_station import ScanStation
from sorter.planning.command_queue import CommandQueue
from sorter.planning.position_tracker import PositionTracker
from sorter.planning.timing_controller import TimingController
from sorter.core.types import TrackState
from sorter.wcs.actuator import SimActuator, draw_overlay
from sorter.wms.routing_table import RoutingTable


def load_config(path: str | Path = "config/pipeline.yaml") -> dict:
    load_env_files()
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_pipeline(cfg: dict, source: FrameSource) -> tuple:
    logger = EventLogger(cfg["logging"]["events_path"])
    bus = EventBus(logger=logger)

    routing = RoutingTable()
    induction = InductionFilter(
        min_track_length=cfg["induction"]["min_track_length"],
        min_bbox_gap_px=cfg["induction"]["min_bbox_gap_px"],
    )
    tracker = PositionTracker(induction, event_bus=bus)
    queue = CommandQueue()
    timing = TimingController(
        actuation_line_ratio=cfg["lines"]["actuation_line_ratio"],
        belt_speed=cfg["belt"]["speed_px_per_frame"],
        lead_frames=cfg["lines"]["actuator_lead_frames"],
        routing=routing,
        queue=queue,
    )

    arbitrator = None
    arb_cfg = cfg.get("arbitrator", {})
    if arb_cfg.get("enabled"):
        arbitrator = LLMArbitrator(
            min_confidence=arb_cfg["trigger"]["min_confidence"],
            provider=arb_cfg.get("provider", "gemini"),
            model=arb_cfg.get("model") or gemini_model(),
            log_path=cfg["logging"]["arbitrator_path"],
            max_calls_per_minute=arb_cfg.get("max_calls_per_minute", 10),
            barcode_cv_mismatch=arb_cfg["trigger"].get("barcode_cv_mismatch", True),
        )

    scan_cfg = cfg.get("scan", {})
    scan = ScanStation(
        scan_line_ratio=cfg["lines"]["scan_line_ratio"],
        routing=routing,
        event_bus=bus,
        arbitrator=arbitrator,
        barcode_enabled=scan_cfg.get("barcode_enabled", True),
    )
    detector = YoloDetector(
        model_path=cfg["perception"]["model_path"],
        conf=cfg["perception"]["conf_threshold"],
        tracker_yaml=cfg["perception"]["tracker"],
        use_color_fallback=cfg["perception"]["use_color_fallback"],
    )
    actuator = SimActuator(bus, frame_source=source)

    return detector, tracker, scan, timing, queue, actuator, bus, logger


def run_loop(
    source: FrameSource,
    cfg: dict | None = None,
    show: bool = True,
    max_frames: int | None = None,
) -> None:
    cfg = cfg or load_config()
    detector, tracker, scan, timing, queue, actuator, bus, logger = build_pipeline(cfg, source)

    frame_idx = 0
    snapshots_by_id: dict = {}

    try:
        while max_frames is None or frame_idx < max_frames:
            source.step()
            ok, frame = source.read()
            if not ok:
                break

            detections = detector.detect(frame)
            snapshots = tracker.update(
                detections,
                lambda cx, cy: source.belt_position_for_bbox_center(cx, cy),
                frame_idx,
            )
            snapshots_by_id = {s.track_id: s for s in snapshots}

            for snap, route in scan.process(frame, snapshots, frame_idx):
                cmd = timing.schedule_divert(snap, route, frame_idx, frame.shape[1])
                if cmd:
                    snap.state = TrackState.SCHEDULED
                    bus.publish(
                        Event(
                            event="scheduled",
                            frame=frame_idx,
                            track_id=snap.track_id,
                            payload={
                                "zone": cmd.zone,
                                "execute_frame": cmd.execute_at_frame,
                                "eta_frames": cmd.execute_at_frame - frame_idx,
                            },
                        )
                    )

            for cmd in queue.pop_due(frame_idx):
                actuator.execute(cmd, frame_idx, snapshots_by_id)

            if show:
                vis = draw_overlay(
                    frame,
                    snapshots,
                    cfg["lines"]["scan_line_ratio"],
                    cfg["lines"]["actuation_line_ratio"],
                )
                cv2.imshow("Ozon Sorter — CV View", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            frame_idx += 1
            time.sleep(1.0 / 60.0)
    finally:
        source.close()
        logger.close()
        if show:
            cv2.destroyAllWindows()


def run_video(path: str, **kwargs) -> None:
    run_loop(VideoFileSource(path), **kwargs)
