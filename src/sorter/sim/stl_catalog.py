from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sorter.perception.classifier import PacClassifier


@dataclass(frozen=True)
class StlModelSpec:
    model_id: str
    stl_path: Path
    category: str
    zone: str
    dims_mm: tuple[float, float, float]
    circle_ratio: float


class StlCatalog:
    """Каталог тестовых STL из config/routes.yaml + assets/stl_analysis.json."""

    def __init__(
        self,
        routes_path: str | Path = "config/routes.yaml",
        assets_root: str | Path = "assets",
        analysis_path: str | Path | None = "assets/stl_analysis.json",
    ) -> None:
        self.assets_root = Path(assets_root)
        with Path(routes_path).open(encoding="utf-8") as fh:
            self._routes: dict[str, Any] = yaml.safe_load(fh)
        self._by_id: dict[str, StlModelSpec] = {}
        analysis_file = Path(analysis_path) if analysis_path else None
        if analysis_file and analysis_file.exists():
            self._load_from_analysis(analysis_file)
        else:
            self._load_from_mesh(PacClassifier(routes_path))

    def _load_from_analysis(self, path: Path) -> None:
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            mid = row["model_id"]
            self._by_id[mid] = StlModelSpec(
                model_id=mid,
                stl_path=self.assets_root / row["stl"],
                category=row["category"],
                zone=row["zone"],
                dims_mm=tuple(row["dims_mm"]),
                circle_ratio=float(row["circle_ratio"]),
            )

    def _load_from_mesh(self, classifier: PacClassifier) -> None:
        for mid, meta in self._routes.get("test_objects", {}).items():
            stl_path = self.assets_root / meta["stl"]
            if not stl_path.exists():
                continue
            a = classifier.analyze_mesh(stl_path, mid)
            self._by_id[mid] = StlModelSpec(
                model_id=mid,
                stl_path=stl_path,
                category=a.category,
                zone=a.zone,
                dims_mm=a.dims_mm,
                circle_ratio=a.circle_ratio,
            )

    def model_ids(self) -> list[str]:
        return list(self._by_id.keys())

    def get(self, model_id: str) -> StlModelSpec | None:
        return self._by_id.get(model_id)

    def spec_for_kind(self, kind: str) -> StlModelSpec | None:
        return self.get(kind)
