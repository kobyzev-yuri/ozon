from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sorter.core.types import RouteDecision


class RoutingTable:
    """
    Маршрутизация ПАК задачи 3: category → zone_b | zone_c | zone_d.

    Приоритет resolve():
      1. category (результат Classifier)
      2. by_class (demo CV-fallback)
      3. extensions.wms (штрихкод / cluster), если enabled
      4. default_zone
    """

    def __init__(self, routes_path: str | Path = "config/routes.yaml") -> None:
        with Path(routes_path).open(encoding="utf-8") as fh:
            self._cfg: dict[str, Any] = yaml.safe_load(fh)

    def classification_rules(self) -> dict[str, Any]:
        return self._cfg.get("classification", {})

    def category_for_zone(self, zone: str) -> str | None:
        for cat_id, meta in self._cfg.get("categories", {}).items():
            if meta.get("zone") == zone:
                return cat_id
        return None

    def resolve(
        self,
        class_name: str | None = None,
        barcode: str | None = None,
        cluster: str | None = None,
        category: str | None = None,
        confidence: float = 1.0,
    ) -> RouteDecision:
        default = self._cfg.get("default_zone", "zone_reject")

        if category and category in self._cfg.get("by_category", {}):
            zone = self._cfg["by_category"][category]
            return RouteDecision(
                zone=zone,
                reason=f"category {category}",
                source="category",
            )

        if class_name and class_name in self._cfg.get("by_class", {}):
            zone = self._cfg["by_class"][class_name]
            return RouteDecision(
                zone=zone,
                reason=f"cv class {class_name} (conf={confidence:.2f})",
                source="cv",
            )

        wms = self._cfg.get("extensions", {}).get("wms", {})
        if wms.get("enabled"):
            if barcode:
                for prefix, zone in wms.get("by_barcode_prefix", {}).items():
                    if barcode.startswith(prefix):
                        return RouteDecision(
                            zone=zone,
                            reason=f"barcode prefix {prefix}",
                            source="barcode",
                        )
            if cluster and cluster in wms.get("by_cluster", {}):
                zone = wms["by_cluster"][cluster]
                return RouteDecision(
                    zone=zone,
                    reason=f"cluster {cluster}",
                    source="wms",
                )

        return RouteDecision(zone=default, reason="no matching rule", source="reject")

    def zone_config(self, zone: str) -> dict[str, Any]:
        return self._cfg.get("zones", {}).get(zone, {})

    def expected_category_for_class(self, class_name: str) -> str | None:
        zone = self._cfg.get("by_class", {}).get(class_name)
        if zone:
            return self.category_for_zone(zone)
        return None

    def test_object(self, model_id: str) -> dict[str, Any] | None:
        return self._cfg.get("test_objects", {}).get(model_id)
