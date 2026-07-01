# События и состояния: понятное описание

> Для кого: жюри, разработчики команды, демо.  
> Файл лога: `logs/events.jsonl` (по одной JSON-строке на событие).

---

## 1. Словарь терминов (по-русски)

| Термин | Что это простыми словами |
|--------|--------------------------|
| **Посылка / объект** | Одна коробка или предмет на ленте |
| **Кадр** | Один снимок с камеры (номер `frame` в логе) |
| **bbox** | Прямоугольник вокруг объекта на кадре (где YOLO его «увидел») |
| **track_id** | Номер посылки в трекере (как временный паспорт, пока едет по ленте) |
| **YOLO** | Нейросеть: находит объекты и их класс (коробка, сфера…) |
| **ByteTrack** | Алгоритм: следит, чтобы один и тот же объект сохранял один `track_id` между кадрами |
| **Индукция** | Проверка: объект реальный, а не случайный «миг» детектора (≥5 кадров подряд) |
| **SCAN LINE** | Виртуальная линия на кадре (~45% ширины): «скан-портал», здесь читают код и назначают маршрут |
| **Штрихкод** | EAN/Code128 на наклейке; читается библиотекой **pyzbar** в области bbox |
| **WMS** | Система «куда везти»: у нас — файл `routes.yaml` + класс `RoutingTable` |
| **Маршрут / zone** | Целевой рукав: `chute_a`, `chute_b`, `zone_reject` (выбраковка) |
| **WCS / ПЛК** | Логика «когда толкнуть»: очередь команд и расчёт времени до актуатора |
| **ACTUATION LINE** | Линия срабатывания пушера (~72% ширины кадра) |
| **Актуатор** | Толкатель / cross-belt: в симуляторе — `applyExternalForce` в PyBullet |
| **Арбитр (LLM)** | Gemini по фото crop — только для спорных случаев (низкая уверенность YOLO) |
| **Событие (event)** | Запись в журнал: что и когда произошло (для аудита и KPI) |
| **Состояние (state)** | Внутренний этап жизни посылки в памяти программы (`NEW` → … → `DIVERTED`) |

---

## 2. Два слоя: состояние и событие

Путать их не нужно:

| | **Состояние (TrackState)** | **Событие (Event)** |
|--|---------------------------|---------------------|
| **Где** | В оперативной памяти (`TrackSnapshot`) | В файле `logs/events.jsonl` |
| **Зачем** | Программа решает, что делать дальше | Журнал для человека, жюри, отладки |
| **Пример** | `state = SCANNED` | `{"event": "scanned", ...}` |

**Важно:** программа **не читает** свой же `events.jsonl` для управления лентой.  
Сначала выполняется логика (YOLO → scan → очередь → актуатор), **параллельно** в журнал пишется событие.

```
  Управление (прямые вызовы функций)     Журнал (побочный эффект)
  ─────────────────────────────────      ──────────────────────────
  detector.detect()                      
  tracker.update()          ──────────►  inducted (если готов)
  scan.process()            ──────────►  scanned, no_read
  timing.schedule_divert()  ──────────►  scheduled
  actuator.execute()        ──────────►  diverted
```

---

## 3. Кто генерирует события и где в коде

| Событие | Кто создаёт | Файл | Когда срабатывает |
|---------|-------------|------|-------------------|
| **`inducted`** | `PositionTracker` | `planning/position_tracker.py` | Трек прожил ≥ `min_track_length` кадров → `NEW` → `INDUCTED` |
| **`scanned`** | `ScanStation` | `perception/scan_station.py` | Центр bbox пересёк SCAN LINE; маршрут назначен |
| **`no_read`** | `ScanStation` | `perception/scan_station.py` | После scan: нет штрихкода и зона = `zone_reject` |
| **`scheduled`** | `main_loop` / `sim/runner.py` | `main_loop.py` | После scan: команда попала в `CommandQueue` |
| **`diverted`** | `SimActuator` | `wcs/actuator.py` | Наступил кадр `execute_frame` — пушер сработал |
| **`arbitrator_decision`** | `LLMArbitrator` | `arbitrage/llm_arbitrator.py` | Внутри scan: спорный кейс, ответ Gemini |

Все они вызывают **`event_bus.publish(Event(...))`**.

### Как устроена шина событий

```python
# core/events.py

EventBus.publish(event):
    1. EventLogger.emit(event)  →  строка в logs/events.jsonl
    2. опционально: подписчики subscribe()  (сейчас не используются)
```

То есть **обработка ленты** идёт обыным кодом Python, а **события** — это аудит-WCS «что мы сделали».

---

## 4. Главный цикл: что происходит каждый кадр

Файл: `main_loop.py` (то же в `sim/runner.py` для PyBullet).

```
┌─────────────────────────────────────────────────────────────┐
│  КАЖДЫЙ КАДР (frame_idx)                                    │
├─────────────────────────────────────────────────────────────┤
│  1. frame = источник.read()     # видео или PyBullet-камера │
│  2. detections = YOLO.track()   # bbox, class, track_id      │
│  3. snapshots = tracker.update() # состояния + inducted      │
│  4. scan.process()               # SCAN LINE, штрихкод, WMS │
│       └─► scanned / no_read                                  │
│  5. timing.schedule_divert()     # ETA → CommandQueue        │
│       └─► scheduled                                          │
│  6. queue.pop_due(frame_idx)     # пора ли толкать?           │
│       └─► actuator.execute() → diverted                      │
│  7. overlay на экран + метрики                               │
└─────────────────────────────────────────────────────────────┘
```

Ни один шаг не ждёт записи в файл — запись идёт **в момент** действия.

---

## 5. Автомат состояний посылки

Одна посылка = один `track_id`. Состояния хранятся в `TrackSnapshot.state`.

```
                    ┌──────────┐
                    │   NEW    │  YOLO впервые выдал track_id
                    └────┬─────┘
                         │ ≥5 кадров подряд (индукция)
                         ▼
                    ┌──────────┐     событие: inducted
                    │ INDUCTED │  можно везти к скан-порталу
                    └────┬─────┘
                         │ центр bbox ≥ SCAN LINE
                         │ (штрихкод + WMS + арбитр?)
                         ▼
                    ┌──────────┐     событие: scanned
                    │ SCANNED  │  маршрут зафиксирован навсегда
                    └────┬─────┘     (+ no_read если выбраковка)
                         │ команда в очереди ПЛК
                         ▼
                    ┌──────────┐     событие: scheduled
                    │SCHEDULED │  ждём кадр execute_frame
                    └────┬─────┘
                         │ execute_frame наступил
                         ▼
                    ┌──────────┐     событие: diverted
                    │ DIVERTED │  посылка отведена в зону
                    └──────────┘
```

**Потеря трека** (объект пропал с кадра): состояние исчезает из памяти; команда в очереди может остаться — см. [ERROR_CASES.md](ERROR_CASES.md).

---

## 6. SCAN LINE — сердце маршрутизации

Единственное место, где решается **куда** везти посылку.

### Шаг за шагом (`ScanStation.process`)

1. **Проверки:** состояние = `INDUCTED`, этот `track_id` ещё не сканировали, bbox пересёк линию.
2. **Штрихкод:** вырезаем кусок кадра по bbox → `pyzbar` → строка `"460..."` или пусто (`barcode_decoder.py`).
3. **WMS:** `RoutingTable.resolve()` — приоритет:
   - сначала **штрихкод** (`routes.yaml` → `by_barcode_prefix`);
   - иначе **класс YOLO** (`by_class`);
   - иначе **zone_reject**.
4. **Конфликт:** если код и CV дают разные зоны → флаг `barcode_cv_conflict`.
5. **Арбитр** (если включён): низкий `confidence` или конфликт → Gemini смотрит фото crop.
6. **Фиксация:** `state = SCANNED`, в журнал `scanned`, `track_id` в список «уже сканировали».

После этого маршрут **не меняется**, даже если YOLO на следующем кадре ошибся.

### Примеры маршрута

| Штрихкод | Класс YOLO | Итоговая зона | Поле `route_source` |
|----------|------------|---------------|---------------------|
| `460…` | sphere | chute_a | `barcode` |
| нет | box | chute_a | `cv` |
| нет | неизвестный | zone_reject | `reject` + событие `no_read` |

---

## 7. Описание каждого события в логе

### `inducted` — «посылка готова к сортировке»

**Генератор:** `PositionTracker.update()`

**Смысл:** трек не мигает, объект считаем реальным.

```json
{"event": "inducted", "frame": 85, "track_id": 17, "class": "box", "track_length": 5}
```

**Что делает код дальше:** ждёт пересечения SCAN LINE.

---

### `scanned` — «на скан-портале определили маршрут»

**Генератор:** `ScanStation.process()`

**Смысл:** штрихкод и/или YOLO + WMS → назначена зона.

```json
{
  "event": "scanned",
  "frame": 245,
  "track_id": 17,
  "class": "box",
  "confidence": 0.91,
  "barcode": "4601234567890",
  "barcode_read": true,
  "zone": "chute_a",
  "route_source": "barcode",
  "reason": "barcode prefix 460"
}
```

**Что делает код дальше:** `main_loop` вызывает `timing.schedule_divert()` → очередь ПЛК.

---

### `no_read` — «не смогли идентифицировать»

**Генератор:** `ScanStation` (вместе со `scanned` на reject)

**Смысл:** нет штрихкода и нет подходящего класса → ручная выбраковка.

```json
{"event": "no_read", "frame": 300, "track_id": 12, "class": "unknown", "confidence": 0.22}
```

---

### `scheduled` — «ПЛК запланировал толчок»

**Генератор:** `main_loop.py` после успешного `schedule_divert()`

**Смысл:** посылка доедет до актуатора примерно через `eta_frames` кадров.

```json
{
  "event": "scheduled",
  "frame": 245,
  "track_id": 17,
  "zone": "chute_a",
  "execute_frame": 312,
  "eta_frames": 67
}
```

**Что делает код дальше:** каждый кадр `CommandQueue.pop_due(frame_idx)` проверяет, не пора ли.

---

### `diverted` — «актуатор сработал»

**Генератор:** `SimActuator.execute()`

**Смысл:** посылку отвели в зону (в PyBullet — сила на объект).

```json
{
  "event": "diverted",
  "frame": 312,
  "track_id": 17,
  "zone": "chute_a",
  "actuator": "cross-belt",
  "direction": "left"
}
```

**Что делает код дальше:** для этого `track_id` повторный divert не выполняется (`diverted` set).

---

### `arbitrator_decision` — «LLM пересмотрел спорный случай»

**Генератор:** `LLMArbitrator.arbitrate()`

**Файл:** `logs/arbitrator.jsonl` (отдельно от основного лога)

**Смысл:** было предварительное решение WMS/CV, арбитр дал финал с объяснением.

---

## 8. Полный пример: от появления до сброса

Коробка, `track_id=17`, штрихкод `460…`, YOLO стабилен.

| Кадр | Состояние | Модуль | Событие |
|------|-----------|--------|---------|
| 80 | NEW | `YoloDetector` | — |
| 85 | INDUCTED | `PositionTracker` | `inducted` |
| 245 | SCANNED | `ScanStation` | `scanned` |
| 245 | SCHEDULED | `TimingController` + `main_loop` | `scheduled` |
| 312 | DIVERTED | `SimActuator` | `diverted` |

```jsonl
{"event":"inducted","track_id":17,"frame":85,"class":"box","track_length":5}
{"event":"scanned","track_id":17,"frame":245,"barcode":"4601234567890","barcode_read":true,"zone":"chute_a","route_source":"barcode","confidence":0.91,"class":"box"}
{"event":"scheduled","track_id":17,"frame":245,"execute_frame":312,"eta_frames":67,"zone":"chute_a"}
{"event":"diverted","track_id":17,"frame":312,"zone":"chute_a","actuator":"cross-belt","direction":"left"}
```

---

## 9. Схема модулей и событий

```
  FrameSource          YoloDetector
  (видео/PyBullet)          │
       │                    ▼
       └────────────► PositionTracker ──► inducted
                              │
                              ▼
                        ScanStation ──► scanned, no_read
                         │      │
                    RoutingTable  LLMArbitrator ──► arbitrator.jsonl
                         │
                         ▼
                  TimingController
                         │
                         ▼
                   CommandQueue ◄── scheduled (main_loop)
                         │
                         ▼
                    SimActuator ──► diverted
                         │
                         ▼
              logs/events.jsonl  (EventLogger)
```

| Модуль | Роль | События |
|--------|------|---------|
| `field/frame_source.py` | Картинка с ленты | — |
| `perception/detector.py` | YOLO + ByteTrack | — |
| `field/induction.py` | Фильтр зазоров | — |
| `planning/position_tracker.py` | Позиция, состояния | `inducted` |
| `perception/barcode_decoder.py` | pyzbar | — |
| `perception/scan_station.py` | SCAN LINE | `scanned`, `no_read` |
| `wms/routing_table.py` | Правила маршрута | — |
| `arbitrage/llm_arbitrator.py` | Спорные кейсы | `arbitrator_decision` |
| `planning/timing_controller.py` | ETA до пушера | — |
| `planning/command_queue.py` | Очередь ПЛК | — |
| `main_loop.py` | Связка всего | `scheduled` |
| `wcs/actuator.py` | Толкатель | `diverted` |
| `core/events.py` | Запись в JSONL | все |

---

## 10. Конфигурация

```yaml
# config/pipeline.yaml
induction:
  min_track_length: 5      # кадров до inducted

lines:
  scan_line_ratio: 0.45     # SCAN LINE
  actuation_line_ratio: 0.72 # ACTUATION LINE

scan:
  barcode_enabled: true      # pyzbar на SCAN LINE
```

```bash
pip install pyzbar
# Linux: sudo apt install libzbar0
```

Штрихкоды и зоны: `config/routes.yaml`

---

## 11. Частые вопросы

**Почему в `scheduled` нет bbox и confidence?**  
Они нужны только в момент `scanned`. ПЛК знает только *когда* и *куда* — не пиксели.

**Читает ли программа events.jsonl?**  
Нет. Журнал для аудита и демо. Управление — прямые вызовы в `main_loop`.

**Где штрихкод в PyBullet-демо?**  
На кубах кодов нет → маршрут по классу YOLO. На видео с наклейками pyzbar работает на SCAN LINE.

**Что если сменился track_id?**  
См. [ERROR_CASES.md](ERROR_CASES.md), сценарий ID-switch.

---

## 12. Одна строка

```
Кадр → YOLO → inducted → [SCAN: штрихкод → WMS] → scanned → scheduled → diverted
         ↑ управление кодом          ↑ события пишутся в events.jsonl параллельно
```
