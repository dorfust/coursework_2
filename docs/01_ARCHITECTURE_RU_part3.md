# 01. Архитектура. Часть 3 из 3: модель времени, случайность, политики, связующие строки схем

Метки — как в `01_ARCHITECTURE_RU_part1.md`. Ничего не запускалось; результатов экспериментов нет. Числа ниже взяты из `sim_config.py` (`SimulationConfig`) и `simulator.py` (оба файла прочитаны целиком при подготовке этого документа) либо помечены «ручной расчёт»; значения — умолчания классов, а `configs/*.json` могут их переопределять (шаблон `simulation_n132.json` в этом документе не разбирался).

## 9. Модель времени в одном месте

### 9.1. Тик и горизонты

| Величина | Значение | Где в коде | Ручной расчёт |
|---|---|---|---|
| Длина тика | `tick_s = 0.1` с | `SimulationConfig.tick_s` | — |
| Перевод секунд в тики | `ticks(seconds, dt)`: `seconds / dt` обязано быть целым с допуском `1e-7`, иначе `ValueError` | `sim_config.ticks` | — |
| Конец трафика | `traffic_end_s = 600.0` | `SimulationConfig` | 600 / 0.1 = 6000 тиков |
| Интервал прихода | `arrival_interval_s = 1.0` | `SimulationConfig` | 1.0 / 0.1 = 10 тиков |
| Число пакетов | `range(0, 6000, 10)` в `traffic.make_trace` | `traffic.make_trace` | 600 пакетов, `created_tick` = 0, 10, …, 5990 |
| Горизонт | `observation_end_s = 900.0` → `horizon_tick` | `SimulationConfig.horizon_tick` | 900 / 0.1 = 9000 |
| Число итераций цикла | `for tick in range(self.cfg.horizon_tick + 1)` | `Simulator.run` | 9001 (тики 0 … 9000); планирование передач — только при `tick < horizon_tick` |
| TTL | `ttl_s = 300.0` → `ttl_ticks`; `expiry_tick = created_tick + ttl_ticks` | `SimulationConfig.ttl_ticks`; `Simulator.__init__` | 300 / 0.1 = 3000; последний пакет: 5990 + 3000 = 8990 ≤ 9000 |
| Буфер узла | `buffer_bytes = 16000000` | `SimulationConfig` | 16000000 / 18000 ≈ 888,9, то есть до 888 пакетов по 18000 байт |

`validate` требует, чтобы `traffic_end_s`, `observation_end_s`, `arrival_interval_s`, `ttl_s` занимали не меньше одного тика и чтобы `observation_end_s >= traffic_end_s`.

### 9.2. Хоп (передача по ребру)

В коде написано (docstring `service_ticks`): «Serialization + start-distance propagation; completion rounded UP to grid». Формула: `raw = (size_bytes / rate_bytes_s + distance_km / light_speed_km_s) / dt`, результат `max(1, ceil(raw − 1e-12))`. Дальность берётся на момент старта передачи (`ranges[node, neighbor]` в `Simulator._schedule`). Умолчания: `packet_bytes = 18000`, `rate_bytes_s = 12500.0`, `light_speed_km_s = 299792.458`; предел дальности ребра `3500.0` км (`OrbitConfig.range_km`, `docs/02`).

Ручной расчёт при умолчаниях: сериализация 18000 / 12500 = 1,44 с; распространение при 3500 км: 3500 / 299792,458 ≈ 0,011675 с; `raw` лежит между 14,4 (дальность 0) и (1,44 + 0,011675) / 0,1 ≈ 14,517; округление вверх даёт 15 тиков = 1,5 с для любой дальности от 0 до 3500 км. То же число (15) приведено в `docs/02`, часть 8. Передача хранится как `Transfer(packet_id, sender, receiver, start_tick, finish_tick = start_tick + duration)`.

### 9.3. Порядок событий внутри одного тика (`Simulator.run`)

1. Завершаются передачи с `finish_tick <= tick` и `finish_tick <= expiry_tick` пакета (в порядке `packet_id`); получатель добавляет пакет в свою очередь с `queued_tick = tick`. Если получатель — назначение, пакет «delivered»; если `hops >= 2 * n`, пакет «failed» с причиной `hop_limit` (для `n = 132` порог 264, ручной расчёт; поля конфигурации для него нет).
2. `network.snapshot(tick)` даёт `(adjacency, ranges)`; для сети, построенной самим `Simulator`, проверки формы пропускаются (константа `_SELF_BUILT_NETWORK_TYPE`).
3. Пакеты в состоянии `pending` с `expiry_tick <= tick` завершаются как `failed`, причина `ttl` (активная передача при этом отменяется).
4. Активные передачи: если ребра `sender–receiver` нет в текущей смежности — отмена `link_loss`; иначе при `start_tick < tick < finish_tick` и `failure_probability != 0` вызывается `failure_sampler`, и при отказе — отмена `edge_tick_failure`. Испытаний отказа за одну передачу в 15 тиков: тики `start + 1 … finish − 1`, то есть 14 (ручной расчёт).
5. Вводятся пакеты с `created_tick == tick` (отказ `packet_oversize` или `injection_buffer`, если не помещаются).
6. При `tick < horizon_tick`: `_schedule` — строгий FIFO по приёму: только голова очереди узла может попытаться отправить; узел и получатель должны быть свободны (одна передача на узел), в буфере получателя должно хватать места с учётом резерва.
7. При `audit_each_tick = True` (умолчание) вызывается `audit()`: проверка инвариантов (байты, FIFO, единственность копии, резервы).

Решение политики — `Decision(neighbor, not_before_tick)`: при `not_before_tick > tick` симулятор ждёт («scheduled_future_contact»); `None` — ожидание; решение вне `permitted` — «blocked» (счётчики `route_wait_calls`, `future_contact_wait_calls`, `blocked_decision_calls`).

### 9.4. Правило повтора

`additional_retries = 3` (`SimulationConfig`). В `Simulator._abort`: счётчик `hop_failures` пакета растёт на 1 при любом аборте передачи (`link_loss` или `edge_tick_failure`); если `hop_failures > additional_retries`, пакет завершается как `failed` с причиной `retry_exhaustion`; иначе та же копия может начать передачу заново «с нулевого байта» на том же тике (комментарий кода), при этом политика выбирает соседа заново. Счётчик обнуляется только в `_complete`, то есть при завершённом хопе, а не при смене соседа (вывод из чтения). Ручной расчёт: отказы 1, 2, 3 допустимы, четвёртый подряд на одном хопе (4 > 3) завершает пакет; значит, на хоп приходится не более 1 + 3 = 4 попыток.

### 9.5. Вероятность отказа

`failure_probability = 0.04` на тик внутри передачи. Функция `traffic.edge_tick_failure(seed, u, v, tick, probability)` — точное бернуллиевское испытание на хешах SHA-256 с ключом `ssn-edge-tick-v1:{seed}:{min(u,v)}:{max(u,v)}:{tick}:`; состояния и общего генератора нет, ребро симметрично по `(u, v)`.

## 10. Где входит случайность

| Источник | Механизм | Сид |
|---|---|---|
| Фаза и ориентация созвездия | `numpy.random.default_rng(seed)` в `geometry.make_trajectory` (`docs/02`, часть 8) | `SimulationConfig.phase_seed = 401` (у сценариев серии — первый элемент тройки) |
| Трасса трафика | `random.Random(traffic_seed)`: на пакет `source = randrange(n)`, затем `destination = randrange(n − 1)` со сдвигом на 1, если `destination >= source` (`traffic.make_trace`) | `traffic_seed = 501` |
| Отказы передач | SHA-256 по `(seed, min, max, tick)`, без состояния | `failure_seed = 601` |
| Наборы данных | сиды `DataConfig`: 101-108, 201-202, 301-302 (по `docs/02`); порядок `train_seeds + val_seeds + test_seeds` в `simulate.run_single` (вывод: это сиды обучения, проверки, теста) | `config.py` |
| Обучение | `TrainConfig.seed = 17` (применение в `training.py` — `docs/03`) | — |

Тройки сидов серии: `[401,501,601]` … `[405,505,605]` (`suite_m1b_cgr.json`, `seed_tuples`); у сценария они заменяют `(phase_seed, traffic_seed, failure_seed)`. Политики детерминированы: выбор минимума с разрешением равенства по номеру узла (`HopOracle`, `GLR`), Дейкстра (`TSR`, `CGR`). В `simulate.run_single` для GLR вызывается `torch.set_num_threads(cfg.torch_threads)` (умолчание 1) и `torch.use_deterministic_algorithms(True)`.

## 11. Четыре политики и опциональная пятая (по `policies.py`, `tbr_policy.py`)

Имена из `POLICY_NAMES`; общий вход — `RoutingContext(tick, adjacency, ranges_km, permitted_neighbors, cfg)` и пакет. Все возвращают `Decision` или `None`.

| Имя | Что использует | Что игнорирует |
|---|---|---|
| `GLR` | предсказанное моделью число хопов: матрица `[destination, candidate]` для текущей двоичной `A` (кэш по байтам `A` и конфигурации модели; вывод модели — только при смене `A`); кандидаты — допустимые соседи, ещё не посещённые пакетом; выбор минимума оценки, равенство — по номеру узла | дальности (в режиме «только топология»), очереди и буферы вне `permitted`, план контактов, будущие отказы; нет оракула достижимости: без кандидата ждёт |
| `TBR_style_hop_oracle` (`HopOracle`) | точный поиск в ширину от назначения по текущей `A` (кэш для последней топологии); допустимые достижимые соседи, минимум `(расстояние, номер)` | дальности, множество посещённых, очереди, план контактов, отказы |
| `TSR_source_dijkstra` (`SourceDijkstra`) | при первом вызове в источнике — Дейкстра с весом ребра `size / rate + range / c` по текущей топологии; путь сохраняется в `packet.header` и далее выполняется | изменения топологии после старта, очереди, отказы; путь не чинится (`repair: none`); недоступный следующий хоп — ожидание до TTL |
| `CGR_contact_plan` (`ContactRouting`) | `ContactPlan.earliest_hop(...)` — зависящий от времени поиск пути по плану контактов от текущего тика до `expiry_tick`; допускает будущий контакт (`not_before_tick` > тика); пересчёт на каждом вызове; память отрицательных ответов | текущие очереди и резервы буферов, случайные отказы («scheduled geometry only») |
| `TBR_bounded_exhaustive_reference` (опция, не в `POLICY_NAMES`) | исчерпывающий поиск простых путей по текущей `A` с допустимыми первыми хопами и множеством посещённых, границы `max_nodes`, `max_expansions` (по умолчанию 12 и 100000 по `docs/05`) | дальности, очереди, план; при превышении границ бросает `TBRSearchIncomplete`, а не выбирает маршрут |

Вывод из чтения: `simulate.run_single` отказывает для нативной политики до записи файлов, если `cfg.orbit.n > max_nodes`; при умолчании 12 и `n = 132` запуск потребует явного `--tbr-max-nodes` (проверка `cfg.orbit.n > policy.max_nodes` в коде есть; работоспособность не проверялась). Соответствие политик источникам не установлено: код заявляет «independently written reconstruction» (`docs/04`, индекс).

## 12. Файлы и строки схем, связывающие слои

| Строка / файл | Определена в | Связывает |
|---|---|---|
| `ssn-simulation-config-v1` | `sim_config.SimulationConfig.schema` | конфигурация симуляции: `simulate`, план, сводка |
| `ssn-traffic-v1` | `traffic.trace_document` | трасса: `trace`, `run`, `execute`, `driver.traces` |
| `ssn-packet-table-v1` | `simulate.run_single` | `packets.json` ячейки |
| `ssn-simulation-result-v1` | `simulator.Simulator.result` | значение до записи; в `run_single` заменяется |
| `ssn-simulation-result-v2` | `simulate.RESULT_SCHEMA` | `result.json` ячейки; читает `experiment_results` |
| `ssn-native-exhaustive-simulation-result-v1` | `simulate.NATIVE_RESULT_SCHEMA` | результат нативной политики |
| `ssn-experiment-suite-v1` | `experiments.SUITE_SCHEMA` | `configs/suite_m1b_cgr.json` |
| `ssn-experiment-plan-v2`, `ssn-native-exhaustive-experiment-plan-v1` | `experiment_io` | `plan.json` |
| `ssn-experiment-summary-v2`, `ssn-native-exhaustive-experiment-summary-v1` | `experiment_results` | сводка `aggregate` → `plot` |
| `ssn-m1-slices-v1` | в файле `configs/slices_m1b_cgr.json` | расписание срезов для `selector` |
| `ssn-m1-ledger-v1` | `ledger.LEDGER_SCHEMA` | строки журнала времени |

Привязки по хешам: `plan.json["sha256"]` = SHA-256 канонического JSON тела; `body["source_sha256"]` = SHA-256 каждого `*.py` рядом с `experiment_io.py`; `body["file_sha256"]` — хеши конфигураций; `result.json` хранит `config_sha256`, `traffic_sha256`, `output_sha256` (пять файлов), `complete.json` — `result_sha256`; `provenance.json` — `declared_checkout_revision` (`revision_is_user_supplied: True`) и `source_sha256`. Файлы корня плана: `plan.json`, `configs/`, `traces/`, `runs/`, `logs/`, `training/`, `training_started.json`, `training_complete.json`, `model_preflight.json`, `execution_started.json`, `execution_complete.json`; журнал `--ledger` лежит где укажет пользователь.

## 13. Поправки и не установлено чтением

- Поправка к части 2, стадия 3: фраза о том, что положения берутся «на моментах времени выборок», не проверена по `data.py` (файл при подготовке этого документа не перечитывался); использование полей `step_s`, `start_s` не установлено (`docs/02`, часть 8, п. 9.3).
- В `simulator.py` схема результата `ssn-simulation-result-v1`, а файл `result.json` получает `v2` из `simulate.run_single`; результат прямого вызова `simulate()` помечен `v1` (вывод из чтения).
- Не установлено: работа любого модуля; значения `configs/n132.json` и `simulation_n132.json` в этом документе не сверялись; поведение `data.py`, `training.py`, `model.py`, `loss.py`, `geometry.py`, `contacts.py` проверялось только по индексам групп 02 и 03; точное размещение функций в `experiments.py`, `experiment_*.py`; совпадение утверждений таблиц 11-12 с реальными записями файлов — только чтением.
