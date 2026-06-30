# Ошибки на линии: кейсы, диагностика, решения

> Привязка к текущему коду: `ScanStation`, `RoutingTable`, `CommandQueue`, `LLMArbitrator`, метрики `ai_missed`.  
> См. также: [EVENTS.md](EVENTS.md) — автомат состояний.

---

## Как читать таблицу

| Колонка | Смысл |
|---------|--------|
| **Симптом** | Что видит оператор / жюри |
| **Причина** | Почему так в нашей модели |
| **В логе** | События / метрики |
| **Решение сейчас** | Уже в коде |
| **Решение дальше** | Улучшение / как на проде Ozon |

---

## 1. No Read — нет идентификации

**Симптом:** посылка уезжает в `zone_reject` или в конец ленты без сортировки.

**Причина:**
- `pyzbar` не прочитал штрихкод (нет кода, блик, низкое разрешение)
- YOLO не знает класс или conf ниже порога маршрута
- `RoutingTable` → `default_zone: zone_reject`

**В логе:**
```jsonl
{"event":"scanned","zone":"zone_reject","route_source":"reject","barcode":null,"barcode_read":false}
{"event":"no_read","track_id":12,...}
```
Метрика: `ai_missed++` если объект ушёл с ленты без успешного divert.

| Решение | Детали |
|---------|--------|
| **Сейчас** | Явный `no_read`, reject-рукав в `routes.yaml` |
| **CV** | Дообучить YOLO на классах ТЗ; YOLO-seg как у Ozon Tech |
| **Штрихкод** | Скан-портал 5 сторон на проде; у нас — крупнее crop, `equalizeHist`, несколько попыток decode |
| **Арбитр** | При низком conf — Gemini по crop (не заменяет No Read без картинки) |
| **Операции** | Ручная выбраковка — нормальная ветка NBS, не баг |

---

## 2. ID-switch — ByteTrack сменил `track_id`

**Симптом:** команда `scheduled` на #17, физически уехала другая посылка; или `ai_missed` при «нормальном» видео.

**Причина:** окклюзия, слипшиеся bbox, потеря трека → новый `track_id`; очередь ПЛК привязана к **старому** id.

**В логе:**
```jsonl
{"event":"scheduled","track_id":17,...}
# track 17 пропал из кадра, появился track 23 — без scanned
{"event":"diverted","track_id":17,...}   # может толкнуть не тот объект / пусто
```

| Решение | Детали |
|---------|--------|
| **Сейчас** | `MIN_TRACK_LENGTH`, `min_bbox_gap`, ByteTrack yaml |
| **PyBullet** | `track_id` ≈ `body_id` — стабильнее для демо |
| **После scan** | На проде маршрут хранят по **barcode**, не по track_id |
| **Дальше** | DeepSORT + Re-ID; энкодер ленты + фотодатчик на scan |
| **Жюри** | «До SCAN — трекинг; после SCAN — штрихкод как истина» |

---

## 3. Низкий confidence YOLO

**Симптом:** неверный класс или колебания `box` ↔ `bag`; KPI accuracy падает.

**Причина:** мятая упаковка, нестандартный SKU, домен не в train.

**В логе:**
```jsonl
{"event":"scanned","confidence":0.41,"route_source":"cv",...}
{"event":"arbitrator_decision","preliminary":{...},"final":{...}}  # если enabled
```

| Решение | Детали |
|---------|--------|
| **Сейчас** | `should_arbitrate` при conf < 0.55 → Gemini + crop (ProxyAPI) |
| **Сейчас** | Rate limit `max_calls_per_minute` — не перегружать API |
| **Fallback** | При ошибке API — маршрут WMS preliminary без изменения |
| **Дальше** | Fine-tune YOLO11 на данных ленты; аугментации rotate/lighting |
| **Штрихкод** | Если код читается — CV ошибка не влияет на zone |

---

## 4. Конфликт штрихкод ↔ CV

**Симптом:** YOLO говорит «сфера», штрихкод ведёт в другой кластер.

**Причина:** разные источники истины; типично при ошибке CV или смешанной этикетке.

**В логе:**
```jsonl
{"event":"scanned","route_source":"barcode","cv_zone":"chute_b","barcode_zone":"chute_a",...}
```

| Решение | Детали |
|---------|--------|
| **Сейчас** | WMS: **barcode > CV** (`routing_table.py`) |
| **Сейчас** | `barcode_cv_conflict` → опционально арбитр |
| **Политика** | На проде Ozon: штрихкод WMS обычно главный; CV — ОВХ/тип упаковки |
| **Дальше** | Явное правило в config: `on_conflict: barcode|cv|arbitrator` |

---

## 5. Слипшиеся объекты (cluttering)

**Симптом:** один bbox на две посылки; один divert; вторая уезжает не туда.

**Причина:** два объекта в одном детекте или зазор < `min_bbox_gap_px`.

**В логе:** один `scanned` на один track; второй объект без событий или `ai_missed`.

| Решение | Детали |
|---------|--------|
| **Сейчас** | `InductionFilter.filter_overlapping` — один bbox из пары |
| **Сейчас** | Сингулятор в нарративе (лента разгона) |
| **Дальше** | YOLO-seg + отдельный bbox на экземпляр; линия индукции в симуляторе |
| **ПЛК** | Одна команда на один `track_id` — не двойной импульс |

---

## 6. Поздний scan — объект слишком быстро / короткий трек

**Симптом:** объект проскочил SCAN LINE пока ещё `NEW` (не `INDUCTED`).

**Причина:** `min_track_length` не набран; scan только для `INDUCTED`.

**В логе:** нет `scanned` для этого объекта → `ai_missed` на cleanup.

| Решение | Детали |
|---------|--------|
| **Сейчас** | Уменьшить `min_track_length` (риск шума) |
| **Дальше** | SCAN LINE правее (больше `scan_line_ratio`) |
| **Симулятор** | Увеличить `SPAWN_INTERVAL`, снизить скорость ленты |
| **Прод** | Сингулятор даёт зазор до скан-портала |

---

## 7. Промах актуатора (timing / проскальзывание)

**Симптом:** `diverted` в логе есть, объект не попал в рукав; `divert_wrong` в метриках.

**Причина:** ETA по постоянной скорости; в реальности лента проскальзывает; в симуляторе — нет оптической завесы.

**В логе:**
```jsonl
{"event":"scheduled","eta_frames":67,...}
{"event":"diverted",...}
# metrics: divert_wrong
```

| Решение | Детали |
|---------|--------|
| **Сейчас** | `CommandQueue` по кадрам + `actuator_lead_frames` |
| **Сейчас** | `PositionTracker.velocity` — база для пересчёта ETA |
| **Дальше** | Триггер по **ACTUATION LINE** в world X / пикселях, не только по таймеру |
| **Прод** | Оптическая завеса перед пушером — финальный триггер |
| **Калибровка** | Замер скорости ленты по двум линиям на кадре |

---

## 8. Потеря трека между SCHEDULED и DIVERTED

**Симптом:** `diverted` для track_id, объекта уже нет в кадре.

**Причина:** ByteTrack потерял объект; команда в очереди осталась.

**В логе:** `diverted` без актуального bbox на overlay.

| Решение | Детали |
|---------|--------|
| **Сейчас** | `SimActuator` всё равно шлёт force по `body_id` (PyBullet) |
| **Дальше** | Перед `execute`: проверить `track_id in active_snapshots`; иначе cancel + log `divert_cancelled` |
| **Прод** | ПЛК ждёт фотодатчик «объект у актуатора» |

---

## 9. Двойная сортировка одного объекта

**Симптом:** два `diverted` на один физический объект (редко).

**Причина:** два `track_id` на одну посылку после re-ID; оба прошли scan.

**В логе:** два `scanned` с разными track_id близко по времени.

| Решение | Детали |
|---------|--------|
| **Сейчас** | `_scanned` per track_id (не спасает от двух id) |
| **Дальше** | После scan дедуп по `barcode` в окне N секунд |
| **Дальше** | `crossed_tracks` / флаг «уже diverted» по barcode |

---

## 10. Арбитр недоступен / rate limit

**Симптом:** в логе `arbitrator error` или `arbitrator skipped (rate limit)`.

**Причина:** нет ключа ProxyAPI, таймаут, лимит RPM Gemini.

**В логе:** `arbitrator.jsonl` с `"error": "..."` или reason с `skipped`.

| Решение | Детали |
|---------|--------|
| **Сейчас** | Fallback на WMS preliminary (`scan_station`) |
| **Сейчас** | `config.env` + fallback models в `llm_arbitrator.py` |
| **Демо** | `arbitrator.enabled: false` — только WMS+CV |
| **Прод** | Арбитр только off-line / супервизор, не hot path |

---

## 11. pyzbar не установлен / libzbar нет

**Симптом:** всегда `barcode_read: false`, маршрут только по CV.

**Причина:** `pyzbar_available() == False`.

| Решение | Детали |
|---------|--------|
| **Сейчас** | Тихий fallback на CV (`barcode_decoder.py`) |
| **Fix** | `pip install pyzbar` + `apt install libzbar0` |
| **Конфиг** | `scan.barcode_enabled: false` — явно отключить |

---

## 12. Ошибка match YOLO ↔ PyBullet body

**Симптом:** divert на не тот 3D-объект; странные метрики accuracy.

**Причина:** `body_matcher` привязал bbox не к тому `body_id` (близкие объекты).

**В логе:** `scanned` с корректным class, но визуально другой объект едет.

| Решение | Детали |
|---------|--------|
| **Сейчас** | Match по ближайшему центру в кадре, `max_distance_px` |
| **Дальше** | Ужесточить distance; приоритет body по world X на SCAN LINE |
| **Дальше** | Штрихкод/QR на текстуре куба в симуляторе |

---

## 13. Зона reject, но scheduled всё равно

**Симптом:** No Read, но команда на reject-актуатор.

**Причина:** `zone_reject` — обычная зона в `routes.yaml` с актуатором.

**В логе:**
```jsonl
{"event":"scanned","zone":"zone_reject",...}
{"event":"scheduled","zone":"zone_reject",...}
```

| Решение | Детали |
|---------|--------|
| **Сейчас** | By design — reject это физический рукав |
| **Опция** | Не вызывать `schedule_divert` для reject — только лог + ручной забор |

---

## Матрица: ошибка → что смотреть первым

| Метрика / лог | Вероятная ошибка |
|---------------|------------------|
| `ai_missed` растёт | #1 No Read, #2 ID-switch, #6 поздний scan |
| `divert_wrong` | #7 timing, #12 body match |
| `no_read` | #1, #11 pyzbar |
| `arbitrator_decision` часто | #3, #4 |
| `route_source: reject` | #1 |
| Нет `inducted` | слишком короткий трек / YOLO не стабилен |

---

## Сценарии для демо жюри (контролируемые ошибки)

### A. Показать No Read
- `barcode_enabled: false` + неизвестный класс YOLO → `zone_reject` + `no_read`.

### B. Показать арбитра
- Объект с низким conf или конфликт (когда на видео есть код `461` на box).
- `arbitrator.enabled: true` + `config.env`.

### C. Показать приоритет штрихкода
- Видео/кадр с EAN prefix `460` при ошибочном классе YOLO → `route_source: barcode`.

### D. Честно про ID-switch
- Показать `docs/EVENTS.md` §9 + решение: barcode после scan.

---

## Roadmap исправлений в коде (приоритет)

| P | Задача | Кейсы |
|---|--------|-------|
| P1 | Cancel divert если трек потерян | #8 |
| P2 | Триггер divert по ACTUATION LINE (геометрия) | #7 |
| P3 | Дедуп scan по barcode | #9 |
| P4 | QR/EAN текстура на PyBullet кубах | #11, #12 |
| P5 | `on_conflict` policy в yaml | #4 |
| P6 | Пересчёт ETA по velocity каждый кадр | #7 |

---

## Фраза для защиты

«Мы разделили ошибки на **идентификацию** (No Read, штрихкод, арбитр), **трекинг до scan** (ID-switch, cluttering) и **исполнение** (timing, актуатор). WMS с приоритетом штрихкода, audit в `events.jsonl` и KPI `ai_missed` / `divert_accuracy` — измеримая диагностика, как на реальном WCS.»
