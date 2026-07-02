from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from sorter.field.frame_source import FrameSource
from sorter.sim.fault_simulator import FaultSimulator
from sorter.sim.mesh_loader import load_stl_body
from sorter.sim.spawner import AutomaticSpawner, SpawnedItem
from sorter.sim.stl_catalog import StlCatalog

try:
    import pybullet as p
    import pybullet_data
except ImportError:  # pragma: no cover
    p = None  # type: ignore
    pybullet_data = None  # type: ignore


def load_pybullet_config(path: str | Path = "config/pybullet.yaml") -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class PyBulletConveyor(FrameSource):
    """
    Digital Twin: лента, автоспавнер, виртуальная камера (замена RTSP).
    """

    def __init__(self, cfg: dict[str, Any] | None = None, gui: bool | None = None) -> None:
        if p is None:
            raise ImportError("pybullet not installed. Run: pip install pybullet")

        self.cfg = cfg or load_pybullet_config()
        self.gui = self.cfg.get("gui", True) if gui is None else gui

        conv = self.cfg["conveyor"]
        self.conveyor_length = float(conv["length"])
        self.conveyor_width = float(conv["width"])
        self.conveyor_height = float(conv["height"])
        self.belt_speed = float(conv["speed_m_per_s"])

        cam = self.cfg["camera"]
        self._cam_eye = cam["eye"]
        self._cam_target = cam["target"]
        self._cam_w = int(cam["width"])
        self._cam_h = int(cam["height"])
        self._cam_fov = float(cam["fov"])

        lines = self.cfg["lines_world"]
        self.scan_x = float(lines["scan_x"])
        self.actuation_x = float(lines["actuation_x"])

        self._physics_hz = int(self.cfg.get("physics_hz", 240))
        self._step = 0
        self._diverted: set[int] = set()
        self.fault_sim = FaultSimulator(self.cfg.get("fault_sim", {}))
        self.stl_catalog: StlCatalog | None = None
        sp = self.cfg["spawner"]
        if sp.get("mode", "primitive") == "stl":
            self.stl_catalog = StlCatalog(
                assets_root=sp.get("assets_root", "assets"),
            )

        mode = p.GUI if self.gui else p.DIRECT
        self._client = p.connect(mode)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        p.setTimeStep(1.0 / self._physics_hz)

        self._plane_id = p.loadURDF("plane.urdf")
        self._conveyor_id = self._build_conveyor()
        self._zone_markers()

        sp = self.cfg["spawner"]
        bs = self.cfg.get("barcode_sim", {})
        barcode_prefixes = (
            list(bs["prefixes"]) if bs.get("enabled", False) else None
        )

        def category_lookup(kind: str) -> tuple[str, str] | None:
            if self.stl_catalog is None:
                return None
            spec = self.stl_catalog.get(kind)
            if spec is None:
                return None
            return spec.category, spec.zone

        kinds = list(sp.get("kinds", ["box", "sphere"]))
        self.spawner = AutomaticSpawner(
            spawn_fn=self._spawn_body,
            remove_fn=self._remove_body,
            position_fn=self._body_position,
            spawn_x=float(lines["spawn_x"]),
            spawn_z=float(sp.get("spawn_z", 0.4)),
            interval_steps=int(sp["interval_steps"]),
            y_offset_range=tuple(sp["y_offset_range"]),
            kinds=kinds,
            cleanup_x=float(lines["cleanup_x"]),
            cleanup_z=float(lines["cleanup_z"]),
            barcode_prefixes=barcode_prefixes,
            fault_sim=self.fault_sim if self.fault_sim.enabled else None,
            category_lookup=category_lookup if self.stl_catalog else None,
        )

    def _build_conveyor(self) -> int:
        cid = p.loadURDF(
            "cube.urdf",
            [0, 0, self.conveyor_height / 2],
            p.getQuaternionFromEuler([0, 0, 0]),
            globalScaling=1.0,
        )
        p.changeVisualShape(
            cid,
            -1,
            rgbaColor=[0.15, 0.15, 0.15, 1],
            shapeVisualSizeXYZ=[self.conveyor_length, self.conveyor_width, 0.1],
        )
        p.changeDynamics(cid, -1, mass=0)
        return cid

    def _zone_markers(self) -> None:
        for x, color in [
            (self.scan_x, [0, 1, 1, 0.5]),
            (self.actuation_x, [0, 0.6, 1, 0.5]),
        ]:
            z = self.conveyor_height + 0.05
            mid = p.loadURDF("cube.urdf", [x, 0, z], globalScaling=0.05)
            p.changeVisualShape(mid, -1, rgbaColor=color)
            p.changeDynamics(mid, -1, mass=0)

        layout = self.cfg.get("layout", {})
        for zone_key, label in [
            ("zone_b", "B"),
            ("zone_c", "C"),
            ("zone_d", "D"),
        ]:
            spec = layout.get(zone_key)
            if not spec:
                continue
            pos = [float(spec["x_m"]), float(spec["y_m"]), self.conveyor_height + 0.08]
            mid = p.loadURDF("cube.urdf", pos, globalScaling=0.08)
            p.changeVisualShape(mid, -1, rgbaColor=spec.get("color", [0.5, 0.5, 0.5, 0.6]))
            p.changeDynamics(mid, -1, mass=0)

    def _spawn_body(self, kind: str, pos: list[float], step: int) -> int:
        sp = self.cfg["spawner"]
        if self.stl_catalog is not None:
            spec = self.stl_catalog.get(kind)
            if spec is not None and spec.stl_path.exists():
                scale = float(sp.get("stl_scale", 0.001))
                mass = float(sp.get("mass", 0.3))
                return load_stl_body(
                    spec.stl_path,
                    pos,
                    scale=scale,
                    mass=mass,
                )

        if kind == "sphere":
            urdf = "sphere2.urdf"
            scale = float(self.cfg["spawner"].get("scale_sphere", 0.25))
            rgba = [0.1, 0.6, 0.2, 1]
        else:
            urdf = "cube.urdf"
            scale = float(self.cfg["spawner"].get("scale_box", 0.2))
            rgba = [0.7, 0.4, 0.2, 1]

        body_id = p.loadURDF(urdf, pos, globalScaling=scale)
        p.changeVisualShape(body_id, -1, rgbaColor=rgba)
        p.changeDynamics(body_id, -1, activationState=p.ACTIVATION_STATE_DISABLE_SLEEPING)
        return body_id

    def _remove_body(self, body_id: int) -> None:
        self._diverted.discard(body_id)
        p.removeBody(body_id)

    def _body_position(self, body_id: int) -> tuple[float, float, float]:
        pos, _ = p.getBasePositionAndOrientation(body_id)
        return float(pos[0]), float(pos[1]), float(pos[2])

    def step(self) -> list:
        p.stepSimulation()
        self.spawner.tick(self._step)
        self._apply_conveyor_physics()
        removed = self.spawner.cleanup(self._step)
        self._step += 1
        return removed

    def _apply_conveyor_physics(self) -> None:
        half = self.conveyor_length / 2
        for body_id in self.spawner.body_ids():
            try:
                pos, _ = p.getBasePositionAndOrientation(body_id)
                if (
                    self.conveyor_height - 0.05 < pos[2] < self.conveyor_height + 0.5
                    and -half < pos[0] < half
                ):
                    slip = self.spawner.slip_factor_for(body_id)
                    vel = [self.belt_speed * slip, 0, 0]
                    p.resetBaseVelocity(body_id, linearVelocity=vel)
            except Exception:
                pass

    def read(self) -> tuple[bool, np.ndarray]:
        view = p.computeViewMatrix(
            cameraEyePosition=self._cam_eye,
            cameraTargetPosition=self._cam_target,
            cameraUpVector=[0, 1, 0],
        )
        proj = p.computeProjectionMatrixFOV(
            fov=self._cam_fov,
            aspect=self._cam_w / self._cam_h,
            nearVal=0.1,
            farVal=5.0,
        )
        _, _, rgb, _, _ = p.getCameraImage(
            width=self._cam_w,
            height=self._cam_h,
            viewMatrix=view,
            projectionMatrix=proj,
        )
        arr = np.array(rgb, dtype=np.uint8).reshape((self._cam_h, self._cam_w, 4))
        return True, cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)

    def world_x_to_pixel(self, world_x: float) -> float:
        return (world_x + self.conveyor_length / 2) / self.conveyor_length * self._cam_w

    def pixel_to_world_x(self, px: float) -> float:
        return (px / self._cam_w) * self.conveyor_length - self.conveyor_length / 2

    def belt_position_for_bbox_center(self, cx: float, cy: float) -> float:
        return self.pixel_to_world_x(cx)

    def scan_line_px(self) -> float:
        return self.world_x_to_pixel(self.scan_x)

    def actuation_line_px(self) -> float:
        return self.world_x_to_pixel(self.actuation_x)

    def get_body_projections(self) -> list:
        from sorter.sim.body_matcher import BodyProjection

        projs: list[BodyProjection] = []
        for body_id in self.spawner.body_ids():
            wx, wy, _ = self._body_position(body_id)
            cx = self.world_x_to_pixel(wx)
            cy = (wy + self.conveyor_width / 2) / self.conveyor_width * self._cam_h
            projs.append(BodyProjection(body_id=body_id, cx=cx, cy=cy, world_x=wx))
        return projs

    def divert(
        self,
        track_id: int,
        direction: str | None = None,
        force_scale: float = 1.0,
    ) -> bool:
        """track_id = PyBullet body_id. Cross-belt импульс по Y."""
        if track_id in self._diverted or force_scale <= 0:
            return False
        if direction in (None, "straight", "null"):
            self._diverted.add(track_id)
            return True
        force_y = float(self.cfg["actuator"].get("force_y", 12.0)) * force_scale
        if direction == "left":
            force_y = abs(force_y)
        elif direction == "right":
            force_y = -abs(force_y)
        else:
            force_y = -abs(force_y)
        try:
            pos, _ = p.getBasePositionAndOrientation(track_id)
            p.applyExternalForce(
                track_id,
                -1,
                forceObj=[0, force_y, 0],
                posObj=pos,
                flags=p.WORLD_FRAME,
            )
            self._diverted.add(track_id)
            return True
        except Exception:
            return False

    def physics_step(self) -> int:
        return self._step

    def close(self) -> None:
        if self._client is not None and p is not None:
            p.disconnect()
            self._client = None
