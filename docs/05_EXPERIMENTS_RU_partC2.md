# experiment_results.py: описание, часть C2 из пяти

Продолжение `05_EXPERIMENTS_RU_partC1.md`. В этом документе: `verify_accounting`, `scientific_plan_guard`, `verify_native_counters`. Все ссылки «в коде написано» относятся к `src/ssn_hops/experiment_results.py`.

## verify_accounting(cfg, records, rows, metrics, timing, events)

Назначение (вывод из чтения): независимый пересчёт сохранённых итогов одного запуска из построчной таблицы пакетов и журнала событий; сравнение с итогами, записанными симулятором в `result.json`. Показатели симулятора и состав таблиц описаны в `docs/04` (`simulator.py`), здесь указано только то, что проверяет данная функция.

Аргументы:

- `cfg` — объект конфигурации симуляции (результат `from_sim_dict`); используются атрибуты `ttl_ticks`, `horizon_tick`, `tick_s`, `observation_end_s` (см. `docs/02`, `sim_config.py`).
- `records` — список записей трафика (результат `read_trace`); у каждой атрибуты `packet_id`, `created_tick`, `source`, `destination`, `size_bytes`.
- `rows` — список строк из `packets.json["rows"]` (словари).
- `metrics` — `result["metrics"]`; `timing` — `result["timing"]`; `events` — список словарей из `events.jsonl`.

Возврат: словарь из 8 ключей `generated`, `delivered`, `failed`, `pending`, `delay_sum_s`, `route_calls`, `route_seconds`, `delivered_bytes`. Здесь `delivered = len(delays)`, `delay_sum_s = sum(delays)`, где `delays` — задержки, пересчитанные из тиков (не прочитанные из файла).

Любое нарушение даёт `ValueError` с указанным ниже сообщением. Отсутствие ключа в строке, метрике или событии даёт `KeyError` (в самой функции не перехватывается; для нативных планов перехватывается выше, см. C3).

### Проверки таблицы пакетов (в коде написано)

1. `rows` — список той же длины, что `records`: иначе "packet table/traffic count mismatch".
2. Множество `packet_id` строк совпадает с множеством `packet_id` трафика и без повторов: иначе "packet IDs are not a bijection with traffic".
3. Для каждой строки поля `created_tick`, `source`, `destination`, `size_bytes` равны полям записи трафика: иначе "packet table differs from paired traffic".
4. `expiry_tick == created_tick + cfg.ttl_ticks`: иначе "packet TTL accounting mismatch".
5. `status` из `("delivered", "failed", "pending")` и `type(admitted) is bool`: иначе "invalid packet outcome/admission flag".
6. Если `active_receiver` не `None`, статус обязан быть `pending`: иначе "terminal packet has an active transfer"; такие пакеты считаются в `active`.
7. Статус `pending`: `terminal_tick` и `terminal_reason` равны `None`, `admitted` истинно (иначе "pending packet incorrectly terminal or rejected"), `delay_s` равно `None` (через `close`).
8. Статус не `pending`: `terminal_tick` — неотрицательное целое (`count`), `created_tick <= terminal_tick <= cfg.horizon_tick` (иначе "terminal tick outside packet observation"), `terminal_reason` — строка (иначе "missing terminal reason"); причины накапливаются в счётчик `reasons`.
9. Статус `delivered`: причина равна `"delivered"`, `admitted` истинно, `terminal_tick <= expiry_tick` (иначе "invalid delivered outcome"). Задержка пересчитывается: `delay = (terminal_tick - created_tick) * cfg.tick_s` (секунды), строка `delay_s` должна совпасть (`close`, "packet delay"). Пересчитанная задержка добавляется в `delays`. Задержки считаются только по доставленным пакетам.
10. Статус `failed`: `delay_s` равно `None`. Если при этом `admitted` ложно (пакет отвергнут при вводе), причина должна быть `"packet_oversize"` или `"injection_buffer"` (иначе "invalid rejected injection reason"); такие пакеты считаются в `rejected`.

### Сверка метрик (в коде написано)

- `generated = len(records)`. Каждое из значений `metrics[key]` (неотрицательное целое по `count`) должно быть равно: `generated`; `admitted` (число строк с `admitted`); `injection_rejected` (`rejected`); `delivered`, `failed`, `pending` (счётчики статусов); `delivered_delay_denominator` (`len(delays)`). Иначе "metric count mismatch: <key>".
- `admitted + rejected == generated` и `metrics["conservation_checked"] is True`: иначе "injection/conservation assertion mismatch". Вывод: при выполненных проверках строк первое равенство следует из них автоматически.
- Доли через `close`, знаменатель `generated`; при `generated == 0` ожидается `None`: `failure_fraction = failed / generated`; `pending_fraction = pending / generated`; `nondelivery_fraction = (failed + pending) / generated`; `delivered_fraction = delivered / generated`.
- `delivered_mean_delay_s` равно `statistics.mean(delays)`, `delivered_median_delay_s` равно `statistics.median(delays)`; при пустом `delays` ожидается `None`.
- `delivered_bytes` равно сумме `size_bytes` доставленных строк (точное целое равенство).
- `observation_duration_s` равно `cfg.observation_end_s`; `goodput_bits_s` равно `8 * delivered_bytes / cfg.observation_end_s` (бит/с; деление на `observation_end_s` в функции не защищено, допустимость нулевого значения здесь не устанавливается).
- `metrics["terminal_reason_counts"] == dict(reasons)`.

Ручной расчёт (иллюстрация формул): 3 пакета; 1 доставлен с `terminal_tick − created_tick = 20`, `tick_s = 0.5`; 1 failed; 1 pending. Тогда `delay = 20 × 0.5 = 10.0` с, `delivered_mean_delay_s = 10.0`, `failure_fraction = 1/3`, `pending_fraction = 1/3`, `nondelivery_fraction = (1 + 1)/3 = 2/3`, `delivered_fraction = 1/3`; пакет `pending` в задержках не участвует.

### Проверки журнала событий (в коде написано)

Для каждого события:

- `packet_id` присутствует в таблице (иначе "event refers to unknown traffic ID");
- `tick` — неотрицательное целое, `tick <= cfg.horizon_tick` (иначе "event outside observation");
- `time_s` равно `tick * cfg.tick_s` (`close`, "event seconds");
- `kind` учитывается в счётчике `event_counts` и в списке идентификаторов `event_ids[kind]`;
- `kind == "terminal"`: `tick`, `status`, `reason` события равны `terminal_tick`, `status`, `terminal_reason` строки (иначе "terminal event differs from table");
- `kind == "transfer_aborted"`: счётчик `abort_reasons[event["reason"]]` растёт;
- `kind == "hop_completed"`: `completed_bytes += size_bytes` строки пакета.

Другие виды событий считаются в `event_counts`, но отдельно не проверяются (вывод из чтения).

Книга событий (ledger): для видов `generated`, `terminal`, `admitted` список идентификаторов не содержит повторов и равен: `generated` — всем идентификаторам трафика; `terminal` — идентификаторам строк со статусом не `pending`; `admitted` — идентификаторам строк с `admitted`. Иначе "<kind> event ledger mismatch".

Счётчики `counters = metrics["transfer_and_route_counts"]` должны равняться: `admitted`, `injection_rejected` — найденным ранее; `started_transfers` — числу событий `transfer_started`; `aborted_transfers` — `transfer_aborted`; `cancelled_transfers` — `transfer_cancelled`; `completed_hops` — `hop_completed`; `completed_hop_bytes` — `completed_bytes`. Иначе "event/counter mismatch: <key>".

Закон сохранения передач: `started_transfers == aborted_transfers + cancelled_transfers + completed_hops + active`, где `active` — число `pending`-пакетов с непустым `active_receiver`; иначе "transfer conservation mismatch".

`metrics["abort_reason_counts"] == dict(abort_reasons)`, иначе "abort reason count mismatch".

### Проверка таймингов (в коде написано)

- `calls = count(timing["route_calls"])` должно равняться `count(counters["route_calls"])`, и `timing["supported_device"] == "cpu"`: иначе "CPU route timing count mismatch".
- `route_seconds`, `simulation_seconds`, `topology_snapshot_seconds`: не `bool`, `int` или `float`, конечные, не меньше нуля; иначе "invalid saved CPU timing". Между собой эти три числа не сравниваются.
- `timing["route_seconds_per_call"]` равно `route_seconds / calls`, при `calls == 0` ожидается `None` (`close`, "per-call CPU time").

Рандомизация в функции отсутствует; файлы не читаются и не пишутся (все входы переданы аргументами).

## scientific_plan_guard(plan)

Назначение: общая входная проверка плана для прямых вызывающих (строка документации: «Native direct callers share the accepted structural/hash/path guards»). Возвращает `None`.

В коде написано:

1. `schema_guard(plan)` (из `experiment_io.py`): допустимы только `PLAN_SCHEMA` и `NATIVE_PLAN_SCHEMA`; обычный план с признаками нативного отвергается.
2. Только для нативного плана: `validate_plan(plan)` (полная проверка хэшей, путей, реконструкция ячеек и команд, см. `docs/05_EXPERIMENTS_RU_partB*.md`), затем `source_hashes() != plan["body"]["source_sha256"]` даёт `ValueError("source files changed since planning; create a fresh plan")`.

Вывод из чтения: для обычного плана (`PLAN_SCHEMA`) функция выполняет только `schema_guard`; хэш самого плана и хэши файлов здесь не пересчитываются (это делает `load_plan` в `experiments.py` на пути командной строки), а сравнение хэшей исходных файлов с планом для обычных планов делается позднее через `provenance.json` каждой ячейки (см. C3). Если `plan` не словарь, `plan.get` в `schema_guard` поднимет `AttributeError`.

## verify_native_counters(details, native, timing, metrics)

Строка документации (в коде написано): проверка сохранённой диагностики, а не доказательство выполнения заявленного алгоритма; ссылка на определения в `tbr_policy.py` (в тексте указаны строки "at245aa27, blob5a554294" — идентификаторы ревизий вне экспорта). Каждый завершённый поиск включает корневой префикс; каждый «путь к назначению» — входной префикс; завершение с маршрутом или нулём шагов даёт не менее одного такого пути; точные числа расширений и путей, зависящие от графа, не проверяются.

Аргументы: `details` — `result["policy_details"]` нативной ячейки; `native` — `plan["body"]["native_reference"]`; `timing`, `metrics` — как выше. Возвращает `deepcopy(details)`; ошибки — `ValueError`.

Порядок проверок (в коде написано):

1. Эталон идентичности: из `native` берутся 5 ключей `policy_identity`, `search_identity`, `objective`, `max_nodes`, `max_expansions`; добавляются два ключа: `algorithm` = "exhaustive admissible simple paths per policy call; independently specified, not author code or timing" и `budget_scope` = "independent safety controls; not author settings". Итого 5 + 2 = 7 ключей идентичности; вместе с 13 счётчиками `NATIVE_COUNTERS` ожидается ровно 20 ключей (ручной расчёт: 7 + 13 = 20).
2. `details` — словарь, множество его ключей равно объединению идентичности и `NATIVE_COUNTERS`: иначе "native diagnostic fields mismatch".
3. Для каждого ключа идентичности `content_hash(details[key]) == content_hash(expected)`: иначе "native diagnostic identity/limits mismatch: <key>".
4. Все 13 счётчиков — неотрицательные целые (`count`).
5. Алгебра (все с `ValueError`):
   - `completed_searches == complete_route_searches + complete_no_route_searches + complete_zero_hop_searches`;
   - `policy_calls == completed_searches + incomplete_searches + invalid_input_calls`;
   - `incomplete_searches == incomplete_max_nodes_searches + incomplete_max_expansions_searches`;
   - `total_prefix_entries == completed_prefix_entries + incomplete_prefix_entries`;
   - `policy_calls` равно `timing["route_calls"]` и равно `metrics["transfer_and_route_counts"]["route_calls"]`.
6. Успешный результат не должен содержать неполной или недопустимой работы: любое из `incomplete_searches`, `incomplete_max_nodes_searches`, `incomplete_max_expansions_searches`, `invalid_input_calls`, `incomplete_prefix_entries` отлично от нуля даёт "successful native result contains incomplete/invalid search work".
7. Границы: `completed_searches <= completed_prefix_entries <= completed_searches * native["max_expansions"]` и `complete_route_searches + complete_zero_hop_searches <= completed_destination_paths <= completed_prefix_entries`.

Ручной расчёт (иллюстрация, числа не из запуска): `max_expansions = 100000` (значение по умолчанию в `experiment_io.py`, `native_options`), `complete_route_searches = 2`, `complete_zero_hop_searches = 1`, `complete_no_route_searches = 0`. Тогда `completed_searches = 3`; `completed_prefix_entries` должно лежать в `[3, 3 × 100000 = 300000]`; `completed_destination_paths` — в `[2 + 1 = 3, completed_prefix_entries]`.

Тем, что проверка не доказывает выполнение алгоритма, код сам оговаривается в строке документации и в сводке (`counter_evidence`, см. C5).
