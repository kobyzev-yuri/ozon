# План импорта STL в PyBullet

> Архив: `docs/doc-1782987733.zip` · STEP (CAD): `docs/doc-1782987706.zip`  
> Ожидаемые категории: `config/routes.yaml` → `test_objects`

## Цель

Заменить примитивы `box` / `sphere` в симуляторе на **тестовые модели организаторов** и проверять классификацию + маршрутизацию B/C/D на реальной геометрии.

---

## Этап 0 — Подготовка ассетов

| Шаг | Статус |
|-----|--------|
| 0.1 Распаковать STL в `assets/Stl/` | ✓ |
| 0.2 Alias / каталог `test_objects` в routes.yaml | ✓ |
| 0.3 Замер AABB → `docs/STL_ANALYSIS.md` | ✓ |
| 0.4 Обновить `expected_category` в routes.yaml | ✓ |

**Зависимости:** `trimesh` или `numpy-stl` для офлайн-анализа; PyBullet `createCollisionShape` / `createVisualShape` из mesh.

---

## Этап 1 — Офлайн-анализ геометрии

**Статус:** ✓ `scripts/analyze_stl.py` → `assets/stl_analysis.json`, `docs/STL_ANALYSIS.md`

Скрипт `scripts/analyze_stl.py` (создать):

1. Загрузить mesh, выровнять по осям (principal axes).
2. Вычислить габариты L×W×H (мм).
3. Для «круг в сечении»: срез по max-площади, fit окружностей → ratio вписанная/описанная.
4. Вывести таблицу: `object → dims → circle_ratio → category`.

Это даст ground truth для метрик **без** CV.

---

## Этап 2 — Загрузчик mesh в PyBullet

**Статус:** ✓ `src/sorter/sim/mesh_loader.py`, интеграция в `pybullet_env.py`

Файл: `src/sorter/sim/mesh_loader.py`

```python
def load_stl_body(
    stl_path: Path,
    position: list[float],
    scale: float = 1.0,
    mass: float = 0.5,
) -> int:
    ...
```

| Подзадача | Подход |
|-----------|--------|
| Единицы STL | Проверить: чаще **мм** → `scale=0.001` для PyBullet (метры) |
| Collision | `GEOM_MESH` + `meshScale` или convex hull (`createConvexHull`) для стабильности |
| Тяжёлые mesh (Мешок ~5.6MB) | Упростить: `vhacd` или decimate в Blender |
| Ориентация | Случайный yaw на спавне; фиксированный roll/pitch |

Интеграция в `pybullet_env.py`:

- `_spawn_body(kind)` → `_spawn_stl(model_id)` при `kind` из каталога `test_objects`.
- `spawner.kinds`: список id (`bottle`, `cylinder`, `box_300`, …).

---

## Этап 3 — Спавнер и ground truth

`AutomaticSpawner`:

```yaml
# config/pybullet.yaml (целевое)
spawner:
  mode: stl          # primitive | stl | mixed
  kinds: [bottle, cylinder, box_300, box_400, plate]
  stl_scale: 0.001
  interval_steps: 800
```

При спавне сохранять в `SpawnedItem`:

- `model_id: str`
- `expected_category: str` — из `routes.yaml` → `test_objects`
- `expected_zone: str` — через `by_category`

Метрики `SortMetrics.expected_zone_for_kind` → `expected_zone_for_model(model_id)`.

---

## Этап 4 — Геометрия сцены (накопитель + B/C/D)

Обновить `config/pybullet.yaml`:

```yaml
layout:
  point_a:
    conveyor_length_m: 0.5
    conveyor_width_m: 0.7
    belt_speed_m_s: 1.0
  accumulator:
    x_m: 0.0          # конец ленты
    width_m: 0.7
  zones:
    zone_b: { x_m: 1.5, y_m: 0.0 }   # вперёд
    zone_c: { x_m: 0.5, y_m: -1.0 }  # влево
    zone_d: { x_m: 0.5, y_m: 1.0 }   # вправо
```

`pybullet_env._zone_markers()` — цветные маркеры B (зелёный), C (красный), D (жёлтый).

Исполнительная часть (фаза 2):

- Упрощённо: «вакуумный захват» = kinematic constraint + teleport в зону.
- Реалистичнее: 3 DOF cartesian + gripper URDF.

---

## Этап 5 — Связка с Classifier

```
STL spawn → mesh AABB (sim ground truth)
         → CV: bbox + depth/heuristic → dims + circle
         → category → RoutingTable.resolve(category=...)
         → actuator → zone_b/c/d
```

До готовности Classifier: `by_class` / `model_id → expected_category` в демо.

---

## Этап 6 — Проверка и метрики

| Метрика | Источник |
|---------|----------|
| Category accuracy | `expected_category` vs `route.category` |
| Zone accuracy | `expected_zone` vs `diverted zone` |
| Cycle time | spawn → divert timestamps |

Чеклист перед демо:

- [ ] Все 11 STL загружаются без падения физики
- [ ] AABB согласованы с правилами ТЗ
- [ ] Минимум 3 объекта на категорию в ротации спавнера
- [ ] Видео: объект → классификация → отвод в B/C/D

---

## Риски

| Риск | Митигация |
|------|-----------|
| STL в мм, PyBullet в м | Единый `scale` в конфиге + assert на разумный AABB |
| Невыпуклые mesh | Convex decomposition |
| Мешок / Шлем — тяжёлые mesh | LOD / convex hull |
| «Круг в сечении» на сложных формах | Сначала цилиндр, бутылка, тарелка; потом пограничные |

---

## Порядок работ (рекомендуемый)

1. `scripts/analyze_stl.py` + таблица категорий  
2. `mesh_loader.py` + один объект (`Цилиндр.stl`)  
3. Спавнер `mode: stl`  
4. Маркеры B/C/D + три направления актуатора  
5. Остальные 10 моделей  
6. Classifier по габаритам/сечению поверх mesh ground truth
