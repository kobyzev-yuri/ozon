#!/usr/bin/env python3
"""Анализ тестовых STL: габариты, круг в сечении, категория B/C/D."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sorter.perception.classifier import PacClassifier  # noqa: E402


def main() -> int:
    routes_path = ROOT / "config" / "routes.yaml"
    assets_root = ROOT / "assets"
    out_json = ROOT / "assets" / "stl_analysis.json"
    out_md = ROOT / "docs" / "STL_ANALYSIS.md"

    with routes_path.open(encoding="utf-8") as fh:
        routes = yaml.safe_load(fh)

    classifier = PacClassifier(routes_path)
    rows: list[dict] = []

    for model_id, meta in routes.get("test_objects", {}).items():
        stl_rel = meta["stl"]
        stl_path = assets_root / stl_rel
        if not stl_path.exists():
            print(f"SKIP missing: {stl_path}", file=sys.stderr)
            continue
        analysis = classifier.analyze_mesh(stl_path, model_id)
        rows.append(
            {
                "model_id": model_id,
                "stl": stl_rel,
                "dims_mm": list(analysis.dims_mm),
                "circle_ratio": analysis.circle_ratio,
                "category": analysis.category,
                "zone": analysis.zone,
                "expected_category": meta.get("expected_category"),
                "match": analysis.category == meta.get("expected_category"),
            }
        )

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Анализ тестовых STL",
        "",
        "> Сгенерировано `scripts/analyze_stl.py`. Единицы: мм (AABB mesh).",
        "",
        "| model_id | L×W×H мм | circle | category | zone | vs routes.yaml |",
        "|----------|----------|--------|----------|------|----------------|",
    ]
    for r in rows:
        d = r["dims_mm"]
        dim_s = f"{d[0]:.0f}×{d[1]:.0f}×{d[2]:.0f}"
        match = "✓" if r["match"] else f"≠ {r['expected_category']}"
        lines.append(
            f"| {r['model_id']} | {dim_s} | {r['circle_ratio']:.3f} | "
            f"{r['category']} | {r['zone']} | {match} |"
        )
    lines.extend(["", f"JSON: `assets/stl_analysis.json`", ""])
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(out_md)
    for r in rows:
        print(
            f"{r['model_id']:12} {r['dims_mm']} ratio={r['circle_ratio']:.3f} "
            f"→ {r['category']} ({r['zone']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
