from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sorter.perception.stl_geometry import (
    CATEGORY_ZONE,
    MeshAnalysis,
    analyze_stl_file,
    classify_dims,
)


class PacClassifier:
    """
    Классификатор ПАК задачи 3: габариты → круг в сечении → category.

    Порядок (приоритет): oversize → repack_required → sortable.
    """

    def __init__(self, routes_path: str | Path = "config/routes.yaml") -> None:
        with Path(routes_path).open(encoding="utf-8") as fh:
            cfg: dict[str, Any] = yaml.safe_load(fh)
        rules = cfg.get("classification", {})
        self.min_dims = tuple(rules.get("min_dims_mm", [10, 10, 2]))
        self.max_dims = tuple(rules.get("max_dims_mm", [450, 320, 320]))
        self.circle_threshold = float(rules.get("circle_in_section_ratio", 0.7))

    def classify(
        self,
        dims_mm: tuple[float, float, float],
        circle_ratio: float = 0.0,
    ) -> str:
        return classify_dims(
            dims_mm,
            circle_ratio,
            min_dims=self.min_dims,  # type: ignore[arg-type]
            max_dims=self.max_dims,  # type: ignore[arg-type]
            circle_threshold=self.circle_threshold,
        )

    def zone_for_category(self, category: str) -> str:
        return CATEGORY_ZONE.get(category, "zone_reject")

    def analyze_mesh(self, path: Path, model_id: str) -> MeshAnalysis:
        return analyze_stl_file(
            path,
            model_id,
            min_dims=self.min_dims,  # type: ignore[arg-type]
            max_dims=self.max_dims,  # type: ignore[arg-type]
            circle_threshold=self.circle_threshold,
        )
