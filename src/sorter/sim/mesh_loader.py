from __future__ import annotations

from pathlib import Path

try:
    import pybullet as p
except ImportError:  # pragma: no cover
    p = None  # type: ignore


def load_stl_body(
    stl_path: Path,
    position: list[float],
    *,
    scale: float = 0.001,
    mass: float = 0.5,
    rgba: list[float] | None = None,
) -> int:
    """
    Загрузка STL в PyBullet. STL в мм → scale 0.001 для метров.
    Использует convex hull для стабильной коллизии.
    """
    if p is None:
        raise ImportError("pybullet not installed")

    mesh_scale = [scale, scale, scale]
    visual = p.createVisualShape(
        p.GEOM_MESH,
        fileName=str(stl_path),
        meshScale=mesh_scale,
        rgbaColor=rgba or [0.7, 0.5, 0.3, 1.0],
    )
    collision = p.createCollisionShape(
        p.GEOM_MESH,
        fileName=str(stl_path),
        meshScale=mesh_scale,
    )
    body_id = p.createMultiBody(
        baseMass=mass,
        baseCollisionShapeIndex=collision,
        baseVisualShapeIndex=visual,
        basePosition=position,
    )
    p.changeDynamics(body_id, -1, activationState=p.ACTIVATION_STATE_DISABLE_SLEEPING)
    return body_id
