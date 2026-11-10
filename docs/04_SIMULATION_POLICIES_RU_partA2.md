# 04. Симуляция и политики. Часть A2 из A3: simulator.py — тик, запуск передач, итоги

Продолжение части A1 (`04_SIMULATION_POLICIES_RU_partA1.md`), разделы 1.3.4 и далее. Обозначения те же. Имена функций без файла — из `simulator.py`.

#### 1.3.4 Порядок событий внутри тика (`Simulator.run`)
Цикл `for tick in range(cfg.horizon_tick + 1)`. Ручной расчёт при `horizon_tick = 900.0 / 0.1 = 9000`: 9001 тик (0…9000). Порядок:
1. `self.tick = tick`. Завершение: для `(pid, transfer)` из `sorted(list(active.items()))` (по `packet_id`) при `finish_tick <= tick` и `finish_tick <= packet.expiry_tick` вызывается `_complete`. Комментарий: «Complete using the previous cell's geometry before the new sample.» Связь на тике завершения не перепроверяется.
2. `network.snapshot(tick)` → `(adjacency, ranges)`; время — в `topology_seconds`.
3. Проверка снимка (формы `(n, n)`, значения 0/1, нулевая диагональ, симметрия, конечные неотрицательные `ranges`; иначе `ValueError("network must return symmetric binary graph and finite nonnegative km ranges")`) пропускается (`trusted_snapshots`) только для сети, созданной самим `Simulator`: `type(own) is _SELF_BUILT_NETWORK_TYPE` и у экземпляра нет собственного атрибута `snapshot`. Переданная сеть проверяется всегда.
4. TTL: из кучи `expiry_heap` `(expiry_tick, packet_id)` берутся записи с `expiry_tick <= tick`; id сортируются; пакет со статусом `pending` получает `_terminal("failed", "ttl")` (идущая передача отменяется: `transfer_cancelled`). Прочие записи возвращаются в кучу (вывод из чтения: при `ttl_ticks >= 1` эта ветка недостижима).
5. Отмены активных передач (`sorted(list(active.items()))`, уже после TTL): если `not adjacency[sender, receiver]` — `_abort(packet, "link_loss")`; иначе, если `start_tick < tick`, `finish_tick > tick`, `failure_probability != 0` и `failure_sampler(failure_seed, sender, receiver, tick, failure_probability)` истинно, — `_abort(packet, "edge_tick_failure")`. Это `if/elif`: при потере связи испытание не проводится. Ручной расчёт: хоп в 15 тиков даёт испытания на тиках `start+1 … start+14`, их 14. Испытание (`traffic.edge_tick_failure`, `02_ENVIRONMENT_RU_part7.md`) — хэш SHA-256 от `(seed, пара узлов, тик)` без изменяемого состояния.
6. Инъекция: записи с `created_tick == tick` → `_inject`.
7. Если `tick < cfg.horizon_tick` — `_schedule`; на последнем тике передачи не начинаются.
8. Если `cfg.audit_each_tick` (по умолчанию `True`) — `audit()`.
Вывод из чтения: принятый пакет может стартовать на том же тике; отменённая передача — перезапуститься на шаге 7 того же тика; хоп, завершившийся ровно на `expiry_tick`, засчитан (шаг 1 раньше шага 4).

#### 1.3.5 Старт передачи и вызов политики (`Simulator._schedule`)
1. `heads`: для каждого узла с непустой очередью вне `busy` — `(queued_tick головы, packet_id головы, node)`, `sorted` (по `queued_tick`, `packet_id`, узлу). Политика вызывается только в этом цикле; узел входит в `heads` один раз, кандидат — лишь голова очереди: не более одного вызова политики на узел за тик. Это следует из структуры кода, счётчика или `assert` нет. Узел, ставший `busy` по ходу цикла, пропускается.
2. `permitted` — `int(v)` для `v` из `np.flatnonzero(adjacency[node])` вне `busy` и с `used[v] + reserved[v] + size_bytes <= buffer_bytes`. Полный буфер получателя исключает соседа, пакет не теряется; политика вызывается и при пустом `permitted`.
3. `RoutingContext(tick, adjacency, ranges, permitted, cfg)`; `decision = policy.choose(packet, context)` измеряется `perf_counter`; `route_calls += 1`. Политика получает живой `Packet` (TSR пишет `header`) и массив `adjacency` сети.
4. Ответ:
 - `None` → `last_wait = "no_route_or_no_permitted_candidate"`, `route_wait_calls += 1`;
 - `neighbor` не точного типа `int` или вне `[0, n)` → `ValueError("policy returned invalid neighbor")`; `not_before_tick` не `int` или `< tick` → `ValueError("policy returned invalid departure tick")` (целые numpy отвергаются);
 - `not_before_tick > tick` → `last_wait = "scheduled_future_contact"`, `future_contact_wait_calls += 1`;
 - `neighbor not in permitted` → `last_wait = "geometric_or_contention_or_receiver_buffer"`, `blocked_decision_calls += 1`;
 - иначе старт: `duration = service_ticks(size_bytes, rate_bytes_s, float(ranges[node, neighbor]), light_speed_km_s, tick_s)` (расстояние на тике старта); `Transfer(pid, node, neighbor, tick, tick + duration)` в `active`; оба узла в `busy`; `reserved[neighbor] += size_bytes`; `last_wait = None`; `started_transfers += 1`; событие `transfer_started`.
Хоп по умолчанию — 15 тиков (`02_ENVIRONMENT_RU_part3.md`, раздел 4); завершение — на шаге 1 тика `start_tick + duration`.

#### 1.3.6 Конец прогона, `audit`, `result`
- После цикла: `audit()`; `RuntimeError`, если не все записи инъецированы, статус пакета вне `delivered/failed/pending`, события `terminal` не соответствуют `terminal_ids` или `admitted + injection_rejected != len(records)`; затем `result`. Повторный `run` → `RuntimeError("a Simulator instance is single-use")`.
- `audit()` (`RuntimeError`): `used` = сумма размеров очереди; `0 <= used + reserved <= buffer_bytes`; пакеты очереди `pending`, `location == node`, `queued_tick` не убывает; единственная копия (хранимые id без повторов = множество `pending`); концы активных передач уникальны и равны `busy`; `reserved` = сумма по активным; терминальные статусы = `terminal_ids`.
- `result` → `{"summary", "packets", "events"}`. `summary`: `schema = "ssn-simulation-result-v1"`, `policy`, `metrics`, `policy_details = policy.stats()`, `timing`. `metrics`: `generated, admitted, injection_rejected, delivered, failed, pending`; `delivered_mean_delay_s`, `delivered_median_delay_s` (`None` без доставленных; задержка = `(terminal_tick - created_tick) * tick_s`); доли `failure_fraction, pending_fraction, nondelivery_fraction, delivered_fraction` (`None` при `generated == 0`); `delivered_bytes`; `goodput_bits_s = 8 * delivered_bytes / observation_end_s`; `terminal_reason_counts` (`delivered, ttl, retry_exhaustion, hop_limit, packet_oversize, injection_buffer`); `abort_reason_counts`; `transfer_and_route_counts` (11 счётчиков, часть A1); `conservation_checked = True`.
- `timing`: `simulation_seconds`, `topology_snapshot_seconds`, `topology_snapshot_builds` (`getattr(network, "snapshot_builds", None)`), `route_calls`, `route_seconds` (время вокруг `policy.choose`), `route_seconds_per_call`, `route_scope = "entire choose call, including GLR inference on misses; excludes context/masks"`. Значения измеряются при выполнении, недетерминированы.
- `packets`: строка на пакет (по `packet_id`): поля `Packet` плюс `delay_s` (только доставленные), `source_header`, `hop_failed_attempts`, `active_receiver`, `active_finish_tick`; `events` — события по порядку.
- Ручной расчёт при умолчаниях: последний `created_tick = 5990`, `expiry_tick = 5990 + 3000 = 8990 <= 9000`; вывод: `pending` к концу нет.

### 1.4 Значения по умолчанию
Собственных параметров нет, кроме `network=None`, `failure_sampler=edge_tick_failure`. Остальное — из `SimulationConfig` (`02_ENVIRONMENT_RU_part3.md`): `tick_s 0.1`, `ttl_s 300.0`, `observation_end_s 900.0`, `buffer_bytes 16000000`, `rate_bytes_s 12500.0`, `failure_probability 0.04`, `failure_seed 601`, `additional_retries 3`, `audit_each_tick True`. Лимит хопов `2 * cfg.orbit.n` задан в `_complete`.

### 1.5 Связи с другими модулями
Импортирует: `Counter`, `dataclasses`, `heapq`, `statistics`, `perf_counter`, `numpy`, `.contacts.GeometryNetwork`, `.policies.RoutingContext`, `.sim_config.service_ticks`, `.traffic.edge_tick_failure`, `.traffic.validate_records`. Кто импортирует `simulator.py` — не установлено.

### 1.6 Побочные эффекты
Файлов нет. Изменяются объекты `Packet`; события копятся в памяти. Генератора случайных чисел нет; отказы — детерминированная функция `failure_sampler` от `(failure_seed, ребро, тик)`. Время — `perf_counter`.

### 1.7 Что в коде названо допущением или реконструкцией
Слов «assumption/reconstruction» в файле нет. Явные соглашения комментариев: «Strict local-receive FIFO», «Complete using the previous cell's geometry before the new sample», повтор «from byte zero». Блоки `OPT-5`, `OPT-6` названы оптимизациями, равными прежней версии («BASELINE»): утверждение комментариев, не проверено.

### 1.8 Что не установлено чтением
Кто импортирует модуль и как `simulate.py` строит `records` и политику (части B); эквивалентность `OPT-5`/`OPT-6` прежней версии (тесты не в экспорте); JSON-совместимость `policy.stats()`; работоспособность (ничего не запускалось). Наблюдения без исправлений: `validate_records` получает `cfg`, а не `self.cfg` (тот же объект); возврат записей в кучу (шаг 4) недостижим по чтению; `events` не ограничены; испытание отказа привязано к ребру и тику, не к пакету.
