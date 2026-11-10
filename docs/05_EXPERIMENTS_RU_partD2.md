# 05. Эксперименты: `experiment_plots.py` (часть D2: `_validate_native`)

Продолжение `05_EXPERIMENTS_RU_partD1.md`; модуль `src/ssn_hops/experiment_plots.py`. Метки те же: «в коде написано», «вывод из чтения», «ручной расчёт». Ничего не запускалось.

## 5. Основные функции: `_validate_native(summary)`

### 5.1. Общие сведения

Docstring (в коде написано): «Consistency of the accepted summary shape, not full cell verification. Reuses frozen producer builders and scientific diagnostic guard read-only. A summary lacks the plan's scenario-to-seed mapping; only global evidence coverage and group count/seed consistency can be checked without the plan.»

Аргумент: словарь нативной сводки (схема `NATIVE_SUMMARY_SCHEMA`, 27 ключей в `aggregate_plan`, `05_EXPERIMENTS_RU_partC5.md`). Возврат: `None`. Единственный вид отказа: `ValueError`. Все сообщения ниже начинаются с `"native summary "`; сообщение собственного формата перечислено в каждом пункте. Всё тело обёрнуто в `try`; `KeyError`, `TypeError`, `AttributeError`, `OverflowError` превращаются в `ValueError("malformed native summary metadata")` (с цепочкой `from exc`). Вывод: отсутствующий ключ, значение неверного типа, `None` вместо словаря дают именно это общее сообщение, а не точное; `ValueError` из вложенных проверок проходят без изменения.

Вызывается только из `prepare_plots`, и только для нативной схемы. Проверка не открывает файлов и не вызывает матплотлиб.

### 5.2. Шаги проверки (в порядке выполнения, в коде написано)

**Слой производителя.**

1. `producer_plan_schema` (через `_same`) равно `NATIVE_PLAN_SCHEMA` — `"producer schema mismatch"`.
2. `native = summary["producer_native_reference"]`; он обязан совпасть (по `content_hash`) с `native_options(True, native["max_nodes"], native["max_expansions"])` — `"producer reference mismatch"`. Вывод: в справочнике свободны только два бюджета (положительные целые, `positive_budget`, часть B1, 3.2); все остальные тексты, включая `budget_scope`, должны совпасть с литералами `experiment_io.py` (часть B1, 3.3).
3. `producer_single_run_reference` равно `single_run_native_reference(native)` — `"single-run reference mismatch"`.
4. `scientific_consumer` равно литеральному словарю: `contract = dict(SCIENTIFIC_CONTRACT)`, `aggregation_supported = True`, `plots_supported = False`, `scope` («strict saved-artifact scientific verification and complete planned-policy paired aggregation; plots unsupported»), `counter_evidence` («verified saved native diagnostic types, identities, budgets, algebra and bounds; NOT proof of algorithm execution»), `producer_scope_interpretation` («original single-run and transport declarations retained unchanged as historical layer claims; not retroactively relabeled») — `"scientific layer mismatch"`. Вывод: сводка сохраняет `plots_supported = False` у слоя агрегирования, а поддержку графиков заявляет слой `PLOT_CONSUMER` (`plots_supported = True`); эти два заявления относятся к разным слоям.
5. `field_units` равно `FIELDS` — `"units mismatch"`.

**Идентичность и происхождение.**

6. `plan_sha256` — 64 hex; `declared_checkout_revision` — 40 hex (`_hash`, `"invalid hash/revision"`).
7. `source_sha256`: непустой словарь, содержащий ключи `"experiment_results.py"` и `"experiment_plots.py"` (`"missing source provenance"`); каждый ключ — строка вида `[a-zA-Z0-9_]+\.py` (`"malformed source filename"`); каждое значение — 64 hex.
8. `statistics`, `timing_warning`, `authentication_limit` — непустые строки (`"missing limitations"`).
9. `complete` и `transport_finished` — строго `bool` (`"completeness must be boolean"`).

**Политики и режим.**

10. `mode` из двух значений `"baselines_only"`, `"with_trained_GLR"`; `policy_names` равно списку `(POLICIES[1:] при baselines_only, иначе POLICIES) + [NATIVE_POLICY_NAME]` (`"unknown policy/order/mode"`). Ручной расчёт длины: `POLICIES` — 4 имени; `baselines_only` — 3 + 1 = 4; `with_trained_GLR` — 4 + 1 = 5. Вывод: сводка со срезом политик (`policy_scope`) отвергается этой проверкой (нативный план с `policy_scope` невозможен, часть A3, раздел 9).
11. `reference_policy` входит в `policy_names` (`"reference policy not planned"`).
12. `model_feature_specs` — словарь, при `baselines_only` пустой (`"model metadata mismatch"`).

**Счётчики ячеек и доказательства.**

13. `planned = count(planned_cells)`, `verified = count(scientifically_verified_cells)`; `planned` не нуль и делится на `len(policy_names)` (`"planned cell count mismatch"`). Вывод: `planned = число сценариев x len(policy_names)`.
14. `missing_or_failed_cells` — список, `artifact_evidence` и `excluded_cells` — словари (`"malformed evidence/exclusions"`). Должны выполняться: в `missing` нет повторов; `missing` и ключи `evidence` не пересекаются; множество ключей `excluded_cells` равно множеству `missing`; `verified == len(evidence)`; `verified + len(missing) == planned` (`"inconsistent evidence cell counts"`). Значения `excluded_cells` — только `"missing job status"`, `"failed job"`, `"missing completion artifact"` (`"unknown exclusion reason"`).
15. Для каждого идентификатора ячейки из `missing` и `evidence`: строка с `"--"`; делится по первому `"--"` на сценарий и политику (`"malformed cell id"`); сценарий — `s-<16 hex>`, политика из `policy_names` (`"unknown evidence policy/scenario"`). Для проверенных ячеек (есть в `evidence`):
   - ключи записи ровно `result_sha256`, `traffic_sha256`, `output_sha256`, `log_sha256`, `native_counters` (`"evidence fields mismatch"`); первые два — 64 hex;
   - `output_sha256` — словарь с ключами ровно `config.json`, `traffic.json`, `provenance.json`, `packets.json`, `events.jsonl`; `log_sha256` — ровно `.stdout.txt`, `.stderr.txt` (`"evidence hash map mismatch"`); все значения — 64 hex;
   - для `NATIVE_POLICY_NAME`: `calls = native_counters["policy_calls"]`, затем `verify_native_counters(native_counters, native, {"route_calls": calls}, {"transfer_and_route_counts": {"route_calls": calls}})` (`experiment_results.py`, часть C2); для остальных политик `native_counters` обязан быть `None` (`"baseline has native counters"`).
   Вывод: два последних аргумента `verify_native_counters` строятся из самих счётчиков, поэтому сверка «число вызовов маршрутизации = `policy_calls`» здесь тривиальна; бюджеты и алгебра счётчиков проверяются так же, как при агрегировании. Сигнатура `verify_native_counters` разобрана в части C2.
16. Каждый сценарий обязан иметь все политики `policy_names` среди `missing` и `evidence` (`"incomplete planned-policy cell coverage"`). `complete_scenarios` — число сценариев, у которых все политики проверены.

**Маркер транспорта и полнота.**

17. `transport_completion_marker_present` равно `(marker is not None)`, где `marker = summary["transport_completion_marker"]` (`"marker presence mismatch"`). При `marker is None`: `transport_finished` обязан быть `False` (`"missing marker finished flag mismatch"`). Иначе: `marker["transport_finished"]` — `bool` (`"marker flag malformed"`), и `marker` равен литеральному словарю `{schema: "ssn-native-experiment-transport-complete-v1", transport_finished, runs = planned, plan_sha256 = summary["plan_sha256"], aggregation_supported: False, plots_supported: False, scope: "all planned child artifacts transported; scientific verification/aggregation NOT performed"}` (`"transport marker mismatch"`); `summary["transport_finished"]` равно флагу маркера.
18. `complete == (not missing and transport_finished)` (`"completeness mismatch"`).

**Группы.** `groups` — непустой список (`"groups missing"`). Для каждой группы:

19. `grid` и `variant` — строки вида `[a-z][a-z0-9_-]{0,39}` (`"unsafe plot name"`): имя попадает в имя файла PNG (вывод: защита от разделителей пути и прочих символов; максимальная длина имени 40 символов — 1 + 39).
20. `axis` — ключ `METRICS` (иначе `ValueError("unsupported plot axis")` без префикса); `control_sha256` — 64 hex.
21. `planned_repetitions`, `matched_repetitions` — `count`; условие: `repetitions != 0`, `matched <= repetitions`, `matched <= complete_scenarios`, `repetitions <= planned // len(policy_names)` (`"inconsistent group matched counts"`). Ручной расчёт: при `planned = 20`, `len(policy_names) = 5` число сценариев 4, значит, `repetitions <= 4`.
22. `included_seed_tuples`, `excluded_seed_tuples` — через `_seed_list` (раздел 4.5); `len(included) == matched`; `len(excluded) == repetitions - matched`; множества не пересекаются (`"inconsistent group seed counts"`). При `summary["complete"]` обязано быть `matched == repetitions` (`"complete group has exclusions"`).
23. Блок `controls` (`c`): `tick_s`, `rate_bytes_s`, `arrival_rate_packets_s`, `traffic_end_s`, `observation_end_s` — `_number(..., positive=True)`; `n`, `planes` — `count`; `p = failure_probability` — `_number`. Условия (`"invalid controls/safety bound"`): `n >= 2`; `1 <= planes <= n`; `n % planes == 0`; `n <= native["max_nodes"]`; `p <= 1`; `observation_end_s >= traffic_end_s`. Вывод: проверка `n <= max_nodes` повторяет предпроверку планирования (`experiments.resolve_plan_inputs`, «native node preflight»).
24. `x = _number(group["x"], "x")` обязан равняться (точное `==`) `n` при `axis == "n"` и `p` при `axis == "failure_probability"` (`"x/control mismatch"`).
25. Ключи `group["policies"]` равны `set(policy_names)`; ключи `paired_policy_minus_reference` равны `set(policy_names) - {reference_policy}` (`"group policy mismatch"`).

**Оценки и итоги по каждой политике группы.**

26. Элемент политики — словарь с ключами ровно `equal_replicate` и `pooled_packet_and_call`; множество ключей `equal_replicate` равно `set(FIELDS)` (`"policy statistics mismatch"`). Для каждого показателя — `_stats(stats, matched)` (раздел 4.4); при непустом `mean`: `_number(mean)` (то есть `mean >= 0`) и для имён, оканчивающихся на `"fraction"`, `mean <= 1` (`"fraction outside [0,1]"`).
27. `pooled_packet_and_call`: `generated`, `delivered`, `failed`, `pending`, `route_calls`, `delivered_bytes` — `count`; `generated == delivered + failed + pending` (`"pooled conservation mismatch"`); `delay_sum_s`, `route_seconds` — `_number`.
28. Для пар (показатель, знаменатель) `delivered_mean_delay_s`/`delivered`, `route_seconds_per_call`/`route_calls`, `failure_fraction`/`generated`, `pending_fraction`/`generated`, `nondelivery_fraction`/`generated`: при нулевой сумме знаменателя `n_nonnull` показателя обязан быть 0 (`"empty denominator must be a null gap"`). Вывод: нулевая сумма не может стоять рядом с числовой оценкой.
29. Если `matched == 0`, все восемь объединённых величин (`generated`, `delivered`, `failed`, `pending`, `route_calls`, `delivered_bytes`, `delay_sum_s`, `route_seconds`) обязаны быть нулями (`"zero matched group has pooled work"`).
30. Для каждой записи `paired_policy_minus_reference`: множество ключей равно `set(FIELDS)` (`"paired fields mismatch"`), каждый блок — `_stats(stats, matched)`.

### 5.3. Что проверка не делает (вывод из чтения)

- Не сверяет значения `equal_replicate` с объединёнными суммами (кроме правила 28), не пересчитывает среднее по повторениям и не проверяет, что среднее лежит между минимумом и максимумом (минимумов в сводке нет).
- Не открывает файлы: хеши в `artifact_evidence` не сравниваются с содержимым, `plan_sha256` не сверяется с `plan.json` (в документе `statistics`/`authentication_limit` сводки: хеши не доказывают подлинность).
- Не проверяет, что `reference_policy` совпадает с реальным эталоном при построении разностей, и что `mode` соответствует `model_feature_specs`, кроме правила 12.
- Не проверяет значения `included_seed_tuples` против плана (плана нет); проверяются только количество, формат и уникальность.
- Для проверенных ячеек не перепроверяются `result_sha256`, `traffic_sha256` и хеши выходов, кроме формата.
- Пункт 28 использует точное сравнение с нулём для сумм `route_seconds`, но не для `delay_sum_s`: знаменатель — `delivered`, а не сумма задержек.
