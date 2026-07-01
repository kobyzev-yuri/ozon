# Архитектура: Ozon Sorter (Digital Twin)

> Задача 3 хакатона Ozon Tech — интеллектуальная сортировка на конвейере.  
> Статус: **скелет v0.1** (до полной постановки 2 июля 2026).

---

## 1. Идея в одном абзаце

Мы строим **переносимый контур сортировки** в стиле реального хаба Ozon: камера → идентификация (штрихкод + CV) → **WMS-маршрут по коду** → ПЛК-тайминг → актуатор. Источник кадра сменный: RTSP, `.mp4`, **PyBullet**. CV-пайплайн и бизнес-логика **не зависят** от среды.

**Бизнес-правила (тип vs рукав):** [docs/BUSINESS_RULES.md](docs/BUSINESS_RULES.md)

---

## 2. Слои системы (как на проде)

```mermaid
flowchart TB
    subgraph FIELD["FIELD — Digital Twin / RTSP"]
        FS[FrameSource]
        PB[PyBullet / Video / MJPEG]
        ACT_PH[PyBullet divert / physics]
        PB --> FS
    end

    subgraph WCS["WCS — Warehouse Control System"]
        DET[YoloDetector + ByteTrack]
        IND[InductionFilter]
        SCAN[ScanStation]
        POS[PositionTracker]
        TIM[TimingController]
        Q[CommandQueue]
        SA[SimActuator]
        FS --> DET --> IND --> POS --> SCAN
        SCAN --> TIM --> Q --> SA
        SA --> ACT_PH
    end

    subgraph CORR_SCAN["Блок коррекции маршрута (внутри ScanStation)"]
        direction TB
        ID["① Идентификация<br/>pyzbar · barcode_sim · class"]
        WMS_P["② WMS preliminary<br/>RoutingTable.resolve"]
        CHK{"③ Спорный кейс?<br/>conf · barcode_cv_conflict"}
        LLM["④ LLM Arbitrator<br/>crop + Gemini"]
        ROUTE["⑤ Финальный маршрут"]
        ID --> WMS_P --> CHK
        CHK -->|да + enabled| LLM --> ROUTE
        CHK -->|нет| ROUTE
    end

    subgraph CORR_EXEC["Блок коррекции исполнения (WCS, частично)"]
        direction TB
        ETA["⑥ ETA / CommandQueue"]
        FAULT["⑦ fault_sim<br/>slip · miss · weak"]
        ETA --> FAULT
    end

    subgraph WMS["WMS — правила (не ML)"]
        RT[routes.yaml / RoutingTable]
    end

    SCAN --- CORR_SCAN
    WMS_P --> RT
    LLM -.->|arbitrator_decision| AJL[arbitrator.jsonl]
    TIM --- CORR_EXEC

    subgraph OBS["Observability"]
        EB[EventBus → events.jsonl]
    end

    WCS --> EB
```

| Слой | Ответственность | Модуль |
|------|-----------------|--------|
| **Field** | Кадры, физика ленты, сила актуатора | `field/`, `sim/` |
| **WCS** | CV, трекинг, тайминг, очередь команд | `perception/`, `planning/`, `wcs/` |
| **WMS** | Правила «куда»: штрихкод → cluster → рукав; CV — fallback | `wms/routing_table.py` |
| **Коррекция маршрута** | Спорный scan → LLM или WMS preliminary | `scan_station.py`, `llm_arbitrator.py` |
| **Коррекция исполнения** | Проскальзывание, сбой пушера (сим) | `fault_simulator.py`, `actuator.py` |

Подробная матрица сбоев и роли арбитра: [docs/FAULT_MATRIX.md](docs/FAULT_MATRIX.md).

### 2a. Блок коррекции маршрута (детально)

Выполняется **синхронно на SCAN LINE** в одном вызове `ScanStation.process()` — отдельного `TrackState` в памяти нет, но в логе видны шаги:

```
INDUCTED @ SCAN LINE
    │
    ├─① pyzbar / barcode_sim  →  snap.barcode
    ├─② RoutingTable            →  preliminary route + barcode_cv_conflict?
    ├─③ should_arbitrate?       →  conf < 0.55 | conflict
    │       └─④ LLMArbitrator   →  arbitrator_decision (arbitrator.jsonl)
    └─⑤ state = SCANNED         →  event scanned (финальный zone, route_source)
```

| Шаг | Реализовано | Событие в логе |
|-----|-------------|----------------|
| ① Идентификация | ✓ | поля `barcode`, `barcode_simulated`, `barcode_misread` в `scanned` |
| ② WMS preliminary | ✓ | `route_source`, `reason` |
| ③–④ LLM-арбитр | ✓ опционально | `arbitrator_decision` |
| ⑤ Фиксация | ✓ | `scanned` / `no_read` |

### 2b. Блок коррекции исполнения (WCS)

| Шаг | Реализовано | Событие / метрика |
|-----|-------------|-------------------|
| ⑥ ETA по позиции | ✓ `TimingController` | `scheduled` |
| ⑦ Проскальзывание ленты | ✓ `fault_sim.belt_slip` | объект не у ACT LINE → `divert_wrong` |
| ⑦ Сбой пушера | ✓ `fault_sim.actuator` | `actuator_fault`, `actuator_miss` |
| Пересчёт ETA каждый кадр | план P6 | — |
| Отмена divert при потере трека | план P1 | `divert_cancelled` |
| Триггер по ACTUATION LINE | план P2 | — |

---

## 3. Четыре операционных этапа Ozon

```
[1 Индукция] → [2 Sensing] → [3 Позиционирование] → [4 Диверсия]
```

| Этап | Реальный хаб | Наш код |
|------|--------------|---------|
| 1. Индукция | Сингулятор, зазоры | `InductionFilter` |
| 2. Sensing | Скан-портал, штрихкод → маршрут; ОВХ / тип — CV | `ScanStation` + `YoloDetector` |
| 3. Позиционирование | Энкодер + ETA до рукава | `PositionTracker` + `TimingController` |
| 4. Диверсия | Cross-belt / pop-up / shoe | `SimActuator` + `CommandQueue` |

### Геометрия линии на кадре

```
|--[камера]----[SCAN LINE]----[ACTUATION LINE]----[zone A / B / C]--→
                  ↑                    ↑
            id зафиксирован      DivertCommand (+ lead time)
```

Параметры: `config/pipeline.yaml` → `scan_line_ratio`, `actuation_line_ratio`.

---

## 4. Контракт `FrameSource`

Единая точка замены RTSP ↔ видео ↔ PyBullet:

```python
class FrameSource(ABC):
    def read(self) -> tuple[bool, np.ndarray]: ...      # BGR кадр
    def step(self) -> None: ...                           # шаг симуляции
    def belt_position_for_bbox_center(self, cx, cy) -> float: ...
    def divert(self, track_id, direction) -> None: ...  # опционально 3D
```

**Для жюри:** `get_virtual_camera_frame()` в PyBullet и `cv2.VideoCapture` — две реализации одного интерфейса.

---

## 5. Контракт детекции (точка подмены YOLO)

```python
# perception/detector.py
def detect(frame) -> list[Detection]:
    # демо:  color_fallback_detect(frame)
    # бой:   model.track(frame, persist=True, tracker=bytetrack.yaml)
```

Физика симулятора и WCS **не меняются** при замене заглушки на YOLO.

---

## 6. Поток событий (audit log)

Файл: `logs/events.jsonl` — аналог WCS event stream.

```json
{"event": "scanned", "track_id": 17, "class": "box", "barcode": "461...", "zone": "chute_b", "route_source": "barcode"}
{"event": "scanned", "track_id": 18, "class": "box", "barcode": null, "zone": "chute_a", "route_source": "cv"}
```

Первый — прод-логика: тип `box`, рукав из штрихкода. Второй — demo-fallback без EAN.

При спорном scan (конфликт / низкий conf) — дополнительно `arbitrator_decision` в `logs/arbitrator.jsonl`; финальный `zone` попадает в `scanned`.

**Автомат состояний трека** (память): `NEW → INDUCTED → SCANNED → SCHEDULED → DIVERTED`.  
**Коррекция маршрута** — подпроцесс между `INDUCTED` и `SCANNED` (см. [EVENTS.md](docs/EVENTS.md) §5).  
**Сбой пушера** — событие `actuator_fault` без перехода в `DIVERTED`.

---

## 7. LLM Arbitrator — ветка блока коррекции маршрута

**Место в архитектуре:** шаги ③–④ внутри `ScanStation` (см. §2a). Не отдельный слой WCS — **корректор маршрута** на SCAN LINE.

**Проблема:** на линии бывают *спорные* решения — низкий confidence YOLO, ошибочный штрихкод (`barcode_misread`), конфликт `barcode_cv_conflict`.

**Решение:** не «LLM вместо YOLO», а **арбитр второго уровня**:

```mermaid
flowchart LR
    PRE[WMS preliminary] --> CHK{should_arbitrate?}
    CHK -->|нет| FIX[scanned]
    CHK -->|conf · conflict| LLM[LLMArbitrator]
    LLM --> ADJ[arbitrator_decision]
    ADJ --> FIX
    FIX --> Q[CommandQueue]
```

```
① pyzbar / barcode_sim  →  ② RoutingTable  →  preliminary route
        ↓ (если confidence < 0.55 или barcode_cv_conflict)
④ LLM + crop ROI    →  final zone + reasoning в arbitrator.jsonl
        ↓
⑤ scanned + scheduled → актуатор
```

| Свойство | Значение |
|----------|----------|
| Hot path | Нет — только спорные кейсы |
| Rate limit | `max_calls_per_minute` в config |
| Fallback | При ошибке API → WMS preliminary |
| Демо без API | `arbitrator.enabled: false` |
| **ProxyAPI** | `GEMINI_BASE_URL=https://api.proxyapi.ru/google`, модель по умолчанию **`gemini-3.5-flash`** ([список моделей](https://proxyapi.ru/docs/google-models)) |
| Vision | crop JPEG → `inline_data` в `generateContent`; ключ `OPENAI_API_KEY` или `GEMINI_API_KEY` |
| Конфиг | `config.env` (как в scinikel), см. `config.env.example` |

**Фраза для защиты:** «Нейросеть видит объект, WMS знает правила, LLM — *диспетчер* на пограничных случаях: отправляем crop в Gemini 3.5 Flash через ProxyAPI, reasoning в `arbitrator.jsonl`».

---

## 8. Структура репозитория

```
ozon/
├── main.py                 # CLI entry
├── config/
│   ├── pipeline.yaml       # геометрия, YOLO, arbitrator
│   ├── routes.yaml         # Mock WMS
│   └── bytetrack.yaml
├── src/sorter/
│   ├── main_loop.py        # главный цикл
│   ├── core/               # типы, EventBus, JSONL
│   ├── field/              # FrameSource, induction
│   ├── perception/         # YOLO, ScanStation
│   ├── planning/           # tracker, timing, queue
│   ├── wms/                # RoutingTable
│   ├── wcs/                # SimActuator, overlay
│   ├── arbitrage/          # LLMArbitrator
│   ├── sim/                # PyBullet (после ТЗ)
│   └── ui/                 # Gradio
├── data/                   # видео, датасет
├── models/                 # веса YOLO
├── logs/                   # events.jsonl
├── ARCHITECTURE.md
├── PRESENTATION.md
└── PLAN.md
```

---

## 9. Запуск

```bash
# conda py12 (рекомендуется)
cd /home/cnn/ozon
pip install pybullet   # один раз для 3D twin
python main.py --demo
python main.py --pybullet              # 3D + YOLO + спавнер + панель метрик
python main.py --video data/belt.mp4

# LLM arbitrator
export GEMINI_API_KEY=...
# в config/pipeline.yaml: arbitrator.enabled: true
```

---

## 9a. Автоспавнер PyBullet

Модуль `sim/spawner.py` — вызывается **каждый шаг физики** из `PyBulletConveyor.step()`:

| Задача | Реализация |
|--------|------------|
| Генерация | `tick(step)`: каждые `interval_steps` → cube/sphere со случайным `y_offset` |
| Очистка памяти | `cleanup(step)`: `removeBody` если `z < cleanup_z` или `x > cleanup_x` |
| Метаданные | `kind_for(body_id)` → ground-truth для WMS и метрик точности |

```python
# Упрощённо:
env.step()  # внутри: spawner.tick → conveyor velocity → spawner.cleanup
```

Конфиг: `config/pybullet.yaml` → `spawner.interval_steps`, `lines_world.spawn_x`.

**Отличие от шаблона с `time.time()`:** ETA и актуатор через `CommandQueue` в **кадрах CV**, расстояние в **метрах** (`actuation_x - world_x`).

---

## 9b. Панель метрик

`sim/metrics.py` — overlay на окне CV:

- Spawned / Removed (утечки памяти нет)
- Scanned / Scheduled / Diverted
- **Divert accuracy %** — в PyBullet: сверка с demo-fallback (`box→chute_a`); не KPI городов WMS
- Счётчики Boxes/Spheres — **тип упаковки** в демо, не рукава A/B
- YOLO frames / detections

После остановки (`q`) — сводка в консоль.

---

## 10. Roadmap после ТЗ (2 июля)

| Приоритет | Задача |
|-----------|--------|
| P0 | Классы из ТЗ → `routes.yaml` + dataset |
| P0 | `PyBulletConveyor`: спавнер, камера, `applyExternalForce` | **готово** |
| P1 | Train YOLO11, `use_color_fallback: false` |
| P1 | Gradio: видео + лог событий + метрики |
| P2 | `pyzbar` на SCAN LINE |
| P2 | LLM arbitrator на live-демо (1–2 кейса) |
| P3 | Synthetic data export из PyBullet для дообучения |

---

## 11. Что не входит в scope (но упоминаем на защите)

- Полная WMS (батчинг, слоттинг)
- Реальный ПЛК / Modbus (опционально Factory I/O)
- Магистральная погрузка после накопителя

---

## Ссылки

- [Ozon Tech: ОВХ + YOLO на складе](https://www.pvsm.ru/machine-learning/391187)
- [docs/BUSINESS_RULES.md](docs/BUSINESS_RULES.md) — бизнес-правила маршрутизации
- Внутренний план: `PLAN.md`
- Набросок презентации: `PRESENTATION.md`
