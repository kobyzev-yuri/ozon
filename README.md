# Ozon Sorter — ПАК предсортировки (задача 3)

Программно-аппаратный комплекс: классификация товара (габариты + круг в сечении) → маршрутизация в зоны **B / C / D** + симуляция PyBullet.

**Хакатон:** 2 июля — 13 сентября 2026, онлайн. См. [HACKATHON.md](HACKATHON.md), [task_3.md](task_3.md).

## Документация

| Файл | Содержание |
|------|------------|
| [task_3.md](task_3.md) | **Краткое ТЗ** (категории, A→B/C/D) |
| [HACKATHON.md](HACKATHON.md) | Roadmap, материалы организаторов |
| [docs/STL_ANALYSIS.md](docs/STL_ANALYSIS.md) | **Анализ 11 тестовых STL** (габариты, категории) |
| [docs/LAYOUT_ABCD.md](docs/LAYOUT_ABCD.md) | Схема точек A–D |
| [docs/QUESTIONS_FOR_ORGANIZERS.md](docs/QUESTIONS_FOR_ORGANIZERS.md) | Вопросы организаторам |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Модули, события, пайплайн |
| [DEFENSE.md](DEFENSE.md) | Питч + Q&A |
| [docs/EVENTS.md](docs/EVENTS.md) | FSM и события |

## Быстрый старт

```bash
cd /home/cnn/ozon

# Анализ STL (габариты + категория)
PYTHONPATH=src python3 scripts/analyze_stl.py

# Симуляция PyBullet + YOLO (нужны: conda py12, pybullet, ultralytics)
PYTHONPATH=src python main.py --pybullet
```

## Структура

```
assets/Stl/          — 11 тестовых моделей организаторов (распакованы)
assets/stl_analysis.json
config/
  routes.yaml        — категории → zone_b/c/d, test_objects
  pybullet.yaml      — симулятор (mode: stl)
scripts/analyze_stl.py
src/sorter/
  perception/        — YOLO, PacClassifier, stl_geometry
  sim/               — PyBullet, mesh_loader, stl_catalog
  planning/          — трекинг, ETA, CommandQueue
  wcs/               — SimActuator
```

## Классификация (ядро задачи 3)

```
STL / CV → PacClassifier (габариты 10×10×2…450×320×320, круг ≥0.7)
         → category → zone_b | zone_c | zone_d
```

Демо в PyBullet: спавн STL из `assets/Stl/`, категория из `stl_catalog` → `ScanStation` → актуатор.

## Статус

- ✓ ТЗ, routes B/C/D, 11 STL в `assets/`
- ✓ `PacClassifier`, `analyze_stl.py`, `mesh_loader`
- ✓ PyBullet `spawner.mode: stl`
- ⏳ DEFENSE/PRESENTATION — обновление под ПАК
- ⏳ Накопитель + полноценная перекладка (исполнительная часть)
