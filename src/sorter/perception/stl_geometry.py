from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class MeshAnalysis:
    model_id: str
    stl_path: str
    dims_mm: tuple[float, float, float]  # sorted L >= W >= H
    circle_ratio: float
    category: str
    zone: str


def _read_stl_vertices(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if data[:5].lower() == b"solid":
        return _read_stl_ascii(data.decode("utf-8", errors="ignore"))
    if len(data) < 84:
        raise ValueError(f"STL too small: {path}")
    tri_count = struct.unpack_from("<I", data, 80)[0]
    expected = 84 + tri_count * 50
    if len(data) < expected:
        raise ValueError(f"STL truncated: {path}")
    verts: list[np.ndarray] = []
    offset = 84
    for _ in range(tri_count):
        offset += 12  # normal
        tri = struct.unpack_from("<9f", data, offset)
        offset += 36
        offset += 2  # attribute
        verts.append(np.array(tri, dtype=np.float64).reshape(3, 3))
    return np.vstack(verts)


def _read_stl_ascii(text: str) -> np.ndarray:
    verts: list[list[float]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("vertex"):
            parts = line.split()
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
    if not verts:
        raise ValueError("No vertices in ASCII STL")
    return np.array(verts, dtype=np.float64)


def aabb_dims_mm(vertices: np.ndarray) -> tuple[float, float, float]:
    ext = vertices.max(axis=0) - vertices.min(axis=0)
    dims = sorted((float(ext[0]), float(ext[1]), float(ext[2])), reverse=True)
    return dims[0], dims[1], dims[2]


def _circle_ratio_2d(points: np.ndarray) -> float:
    """Inscribed / described circle radius ratio on 2D projection."""
    if len(points) < 3:
        return 0.0
    center = points.mean(axis=0)
    dists = np.linalg.norm(points - center, axis=1)
    r_desc = float(dists.max())
    if r_desc <= 1e-9:
        return 1.0
    # Approximate inscribed radius via distance to convex hull edges
    hull = _convex_hull(points)
    if len(hull) < 3:
        return 0.0
    r_insc = float("inf")
    for i in range(len(hull)):
        a, b = hull[i], hull[(i + 1) % len(hull)]
        d = _point_line_dist(center, a, b)
        r_insc = min(r_insc, d)
    if not np.isfinite(r_insc) or r_insc <= 0:
        return 0.0
    return r_insc / r_desc


def _point_line_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    denom = np.dot(ab, ab)
    if denom <= 1e-12:
        return float(np.linalg.norm(p - a))
    t = np.clip(np.dot(p - a, ab) / denom, 0.0, 1.0)
    proj = a + t * ab
    return float(np.linalg.norm(p - proj))


def _convex_hull(points: np.ndarray) -> np.ndarray:
    pts = points[np.lexsort((points[:, 1], points[:, 0]))]
    if len(pts) <= 1:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[np.ndarray] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[np.ndarray] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def circle_in_section_ratio(vertices: np.ndarray) -> float:
    """Max ratio over projections onto XY, XZ, YZ planes."""
    ratios: list[float] = []
    for axes in ((0, 1), (0, 2), (1, 2)):
        pts = vertices[:, axes]
        ratios.append(_circle_ratio_2d(pts))
    return max(ratios)


def classify_dims(
    dims_mm: tuple[float, float, float],
    circle_ratio: float,
    *,
    min_dims: tuple[float, float, float] = (10, 10, 2),
    max_dims: tuple[float, float, float] = (450, 320, 320),
    circle_threshold: float = 0.7,
) -> str:
    """L×W×H после сортировки: min 10×10×2, max 450×320×320 мм."""
    l, w, h = dims_mm  # уже L >= W >= H
    max_l, max_w, max_h = sorted(max_dims, reverse=True)

    too_small = l < 10 or w < 10 or h < 2
    too_large = l > max_l or w > max_w or h > max_h
    if too_small or too_large:
        return "oversize"

    if circle_ratio >= circle_threshold:
        return "repack_required"
    return "sortable"


CATEGORY_ZONE = {
    "sortable": "zone_b",
    "oversize": "zone_c",
    "repack_required": "zone_d",
}


def analyze_stl_file(
    path: Path,
    model_id: str,
    *,
    min_dims: tuple[float, float, float] = (10, 10, 2),
    max_dims: tuple[float, float, float] = (450, 320, 320),
    circle_threshold: float = 0.7,
) -> MeshAnalysis:
    verts = _read_stl_vertices(path)
    dims = aabb_dims_mm(verts)
    ratio = circle_in_section_ratio(verts)
    category = classify_dims(
        dims, ratio, min_dims=min_dims, max_dims=max_dims, circle_threshold=circle_threshold
    )
    return MeshAnalysis(
        model_id=model_id,
        stl_path=str(path),
        dims_mm=dims,
        circle_ratio=round(ratio, 4),
        category=category,
        zone=CATEGORY_ZONE[category],
    )
