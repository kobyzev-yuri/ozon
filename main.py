#!/usr/bin/env python3
"""Entry point: Ozon conveyor sorter digital twin."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running without pip install -e .
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from sorter.config import load_env_files  # noqa: E402

load_env_files()

from sorter.main_loop import load_config, run_loop, run_video  # noqa: E402


def _demo_synthetic_frames():
    """Минимальное демо без видео: цветной кадр → color fallback."""
    import numpy as np

    class SyntheticSource:
        def __init__(self):
            self._t = 0

        def read(self):
            frame = np.zeros((320, 320, 3), dtype=np.uint8)
            frame[:, :, 2] = 180 if (self._t // 60) % 2 == 0 else 0
            frame[:, :, 0] = 180 if (self._t // 60) % 2 == 1 else 0
            self._t += 1
            return True, frame

        def step(self):
            pass

        def belt_position_for_bbox_center(self, cx, cy):
            return cx

        def close(self):
            pass

    return SyntheticSource()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ozon Sorter — Digital Twin")
    parser.add_argument("--video", type=str, help="Path to conveyor .mp4")
    parser.add_argument("--config", type=str, default="config/pipeline.yaml")
    parser.add_argument("--no-show", action="store_true")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Synthetic color frames + color fallback (no YOLO weights)",
    )
    parser.add_argument(
        "--pybullet",
        action="store_true",
        help="PyBullet 3D twin + YOLO + auto-spawner + metrics panel",
    )
    parser.add_argument("--pb-config", type=str, default="config/pybullet.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.pybullet:
        from sorter.sim.runner import run_pybullet_demo
        from sorter.sim.pybullet_env import load_pybullet_config

        pb_cfg = load_pybullet_config(args.pb_config)
        metrics = run_pybullet_demo(
            pipeline_cfg=cfg,
            pb_cfg=pb_cfg,
            show=not args.no_show,
            max_physics_steps=args.max_frames,
        )
        print("\n=== Metrics ===")
        for line in metrics.summary_lines():
            print(line)
    elif args.video:
        run_video(args.video, cfg=cfg, show=not args.no_show, max_frames=args.max_frames)
    elif args.demo:
        run_loop(_demo_synthetic_frames(), cfg=cfg, show=not args.no_show, max_frames=args.max_frames or 300)
    else:
        parser.print_help()
        print("\nПример: python main.py --demo")
        print("       python main.py --video data/conveyor.mp4")
        print("       python main.py --pybullet   # 3D + YOLO + спавнер")


if __name__ == "__main__":
    main()
