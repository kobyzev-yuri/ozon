from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sorter.core.types import RouteDecision


class RoutingTable:
    """Mock WMS: правила маршрутизации, не нейросеть."""

    def __init__(self, routes_path: str | Path = "config/routes.yaml") -> None:
        with Path(routes_path).open(encoding="utf-8") as fh:
            self._cfg: dict[str, Any] = yaml.safe_load(fh)

    def resolve(
        self,
        class_name: str | None = None,
        barcode: str | None = None,
        cluster: str | None = None,
        confidence: float = 1.0,
    ) -> RouteDecision:
        default = self._cfg.get("default_zone", "zone_reject")

        if barcode:
            for prefix, zone in self._cfg.get("by_barcode_prefix", {}).items():
                if barcode.startswith(prefix):
                    return RouteDecision(zone=zone, reason=f"barcode prefix {prefix}", source="barcode")

        if cluster and cluster in self._cfg.get("by_cluster", {}):
            zone = self._cfg["by_cluster"][cluster]
            return RouteDecision(zone=zone, reason=f"cluster {cluster}", source="wms")

        if class_name and class_name in self._cfg.get("by_class", {}):
            zone = self._cfg["by_class"][class_name]
            return RouteDecision(
                zone=zone,
                reason=f"cv class {class_name} (conf={confidence:.2f})",
                source="cv",
            )

        return RouteDecision(zone=default, reason="no matching rule", source="reject")

    def zone_config(self, zone: str) -> dict[str, Any]:
        return self._cfg.get("zones", {}).get(zone, {})
