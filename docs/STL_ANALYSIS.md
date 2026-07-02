# Анализ тестовых STL

> Сгенерировано `scripts/analyze_stl.py`. Единицы: мм (AABB mesh).

| model_id | L×W×H мм | circle | category | zone | vs routes.yaml |
|----------|----------|--------|----------|------|----------------|
| bottle | 305×91×91 | 0.981 | repack_required | zone_d | ✓ |
| cylinder | 435×50×43 | 0.681 | sortable | zone_b | ≠ repack_required |
| box_300 | 301×200×200 | 0.571 | sortable | zone_b | ✓ |
| box_400 | 401×400×300 | 0.716 | oversize | zone_c | ≠ sortable |
| lunchbox | 201×152×62 | 0.629 | sortable | zone_b | ✓ |
| bag | 199×183×175 | 0.850 | repack_required | zone_d | ≠ sortable |
| detergent | 278×259×179 | 0.636 | sortable | zone_b | ≠ repack_required |
| pouf | 489×489×264 | 0.994 | oversize | zone_c | ≠ sortable |
| pen | 148×13×9 | 0.523 | sortable | zone_b | ≠ oversize |
| plate | 210×209×27 | 0.992 | repack_required | zone_d | ✓ |
| helmet | 356×297×280 | 0.776 | repack_required | zone_d | ≠ sortable |

JSON: `assets/stl_analysis.json`
