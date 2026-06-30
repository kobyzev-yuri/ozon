# Ozon Sorter — Digital Twin (задача 3)

Интеллектуальная сортировка на конвейере: CV + трекинг + Mock WMS + ПЛК-тайминг + симуляция актуатора.

## Документация

| Файл | Содержание |
|------|------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Слои Field / WCS / WMS, модули, события |
| [PRESENTATION.md](PRESENTATION.md) | Набросок слайдов (~7–10 мин) |
| [DEFENSE.md](DEFENSE.md) | **Питч 3 мин + Q&A жюри + пояснительная записка** |
| [PLAN.md](PLAN.md) | Детальный план подготовки до/после ТЗ |

## Быстрый старт

```bash
cd /home/cnn/ozon

# Рекомендуется: conda env py12 (torch + ultralytics уже есть)
# python main.py --demo
```

```bash
# Синтетическое демо без весов YOLO (color fallback)
python main.py --demo

# Видео с лентой (после добавления в data/)
python main.py --video data/conveyor.mp4

# Без GUI (headless smoke test)
python main.py --demo --no-show --max-frames 100
```

## Структура

```
src/sorter/
  core/         — типы, EventBus, JSONL
  field/        — FrameSource (video / будущий PyBullet)
  perception/   — YOLO, ScanStation
  planning/     — трекинг, ETA, CommandQueue
  wms/          — routes.yaml
  wcs/          — SimActuator
  arbitrage/    — LLM Arbitrator (опционально)
  sim/          — PyBullet stub
```

## Конфигурация

- `config/pipeline.yaml` — геометрия линий, YOLO, arbitrator
- `config/routes.yaml` — Mock WMS: класс → зона

## LLM Arbitrator

```bash
export GEMINI_API_KEY=your_key
# config/pipeline.yaml → arbitrator.enabled: true
```

Спорные случаи (низкий confidence) → LLM выбирает зону → `logs/arbitrator.jsonl`.

## Зависимости

```bash
pip install -r requirements.txt
pip install -r requirements-sim.txt   # pybullet для 3D twin

python main.py --pybullet              # 3D + YOLO + спавнер + метрики
python main.py --demo                  # 2D без pybullet
```

## Статус

Скелет v0.1 — до постановки 2 июля 2026. PyBullet, обучение YOLO и Gradio — следующие фазы.
