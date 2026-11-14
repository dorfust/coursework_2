# experiment_results.py: описание, часть C5 из пяти

Продолжение `05_EXPERIMENTS_RU_partC4.md`. В этом документе: `aggregate_plan`, выходные документы и их схемы, значения по умолчанию, связи, побочные эффекты, допущения, перечень того, что не установлено чтением. Источник: `src/ssn_hops/experiment_results.py`; вызов из командной строки — `src/ssn_hops/experiments.py` (`parser`, `main`).

## aggregate_plan(plan, output, allow_partial=False, reference="TBR_style_hop_oracle")

Главная функция модуля и единственная, которую вызывает другой модуль. Аргументы: `plan` — словарь плана; `output` — путь нового выходного файла; `allow_partial` — разрешить неполный план; `reference` — эталонная политика. Возврат: `{"summary": str(output), "sha256": digest(output), "complete": complete, "groups": число групп, "missing_or_failed_cells": число}`; `experiments.main` печатает его как JSON.

### Порядок работы (в коде написано)

1. `scientific_plan_guard(plan)` (C2). `native_plan` — схема плана равна `NATIVE_PLAN_SCHEMA`.
2. `reference` должен входить в `body["policies"]`: иначе `ValueError("reference policy was not planned")`. Вывод: например, эталон GLR в плане без GLR (`baselines_only`) отвергается; для плана с `policy_scope` список `body["policies"]` — объединение заявленных политик.
3. `verify_models(plan)` (C3), затем `scoped_declarations(body, scenarios)` (C4), где `scenarios = {s["id"]: s}`.
4. Цикл по `body["cells"]`: `_verify_cell(...)` внутри `try`. Для нативного плана `KeyError`, `TypeError`, `AttributeError`, `OverflowError`, `OSError` превращаются в `ValueError("malformed/missing completed native-plan cell artifact")`; для обычного плана они пробрасываются без изменения.
   - Результат `None`: идентификатор ячейки добавляется в `missing`; для нативного плана в `exclusions[id]` записывается причина: "missing job status" (нет файла статуса), "failed job" (`exit_code != 0` или есть `exception`), иначе "missing completion artifact".
   - Иначе: `verified[scenario][policy] = value`; `evidence[id] = {"result_sha256", "traffic_sha256"}`; для нативного плана добавлены `output_sha256`, `log_sha256`, `native_counters`.
5. Маркер завершения. Нативный план: `native_completion_marker(plan)` (C4). Обычный план: если `execution_complete.json` существует, требуется `marker.get("suite_finished") is True`, `marker["plan_sha256"] == plan["sha256"]`, `marker["runs"] == len(body["cells"])`, иначе `ValueError("suite completion marker differs from plan")`; тогда `finished = True`. Нет файла: `finished = False`.
6. `complete = not missing and finished`. Если `not complete and not allow_partial`: `ValueError(f"suite incomplete: {len(missing)} missing/failed cells; completion marker={finished}")`. Значит, по умолчанию агрегирование возможно только для полностью выполненного плана; с `allow_partial=True` сводка записывается с `complete: false`.

Что считается полным и неполным (вывод из чтения): полный — каждая ячейка плана проверена (а для нативного плана ещё и со статусом успеха) и есть маркер завершения. Отсутствующая ячейка, неуспешное задание, нет маркера — неполнота. Повреждённый или несогласованный артефакт существующей ячейки неполнотой не считается: он вызывает `ValueError` независимо от `allow_partial`.

### Построение групп

- Для каждого сценария и каждого элемента `scenario["memberships"]` сценарий помещается в корзину `(member["grid"], scenario["variant"], member["axis"], member["x"])`. Группы перебираются в порядке `sorted(buckets.items())`.
- Для каждого сценария группы: копия `scenario["config"]` без ключей `phase_seed`, `traffic_seed`, `failure_seed` (при отсутствии любого — `KeyError`); хэш `content_hash` этой копии добавляется в множество `controls`. Если `len(controls) != 1`: `ValueError("unmatched tick/rate/load/orbit/control variants in group")`. Смысл: повторения группы различаются только зёрнами. Вывод из чтения: так как `resolve_plan_inputs` (`experiments.py`) отвергает несколько конфигураций на одну пару (сетка, вариант, x, зёрна), сетка с осью `n` фактически содержит одну вероятность, с осью `failure_probability` — один размер.
- Обычный план: `needed = body["policies"]`; сценарий входит в `matched`, если множество проверенных политик равно `needed`; иначе его зёрна идут в `excluded`. Так при неполной ячейке одной политики сценарий выпадает у всех политик. Оценки: `summarize_group(matched, body["policies"], reference)`.
- План с `policy_scope` (`declared is not None`): `needed = declared[scenario id]`; `present` содержит записи всех сценариев группы; оценки: `summarize_scoped_group(present, body["policies"], reference)`.

### Запись группы (12 ключей, 13 при policy_scope; ручной расчёт)

`grid`, `variant`, `axis`, `x`, `control_sha256`, `planned_repetitions` (= число сценариев группы), `matched_repetitions` (= `len(matched)`), `included_seed_tuples`, `excluded_seed_tuples` (списки троек `[phase, traffic, failure]`), `controls`, `policies`, `paired_policy_minus_reference`. Для плана с `policy_scope` добавляется `policy_cells = {policy: {"planned": число сценариев, где политика заявлена, "verified": число сценариев, где она проверена}}`.

`controls` — 8 ключей из конфигурации первого сценария группы: `tick_s`, `rate_bytes_s`, `arrival_rate_packets_s = 1 / arrival_interval_s` (деление не защищено), `traffic_end_s`, `observation_end_s`, `n`, `planes`, `failure_probability`.

## Выходные документы

Файл один, имя задаётся аргументом `output` (в командной строке `--out`); имя по умолчанию в модуле не задано. Запись выполняет `write` из `experiment_io.py`: открытие в режиме `"x"` (существующий файл даёт `FileExistsError`), создание родительских каталогов, `json.dump(..., indent=2, sort_keys=True, allow_nan=False)`, затем перевод строки.

### Обычная сводка, схема `"ssn-experiment-summary-v2"` (18 ключей верхнего уровня)

`schema`; `label` = "RECONSTRUCTION / NOT AUTHORS' RESULTS"; `complete`; `mode` (из `body["mode"]`); `plan_sha256`; `declared_checkout_revision`; `source_sha256`; `model_feature_specs` (`{n: feature_spec}` из `verify_models`); `reference_policy`; `policy_names`; `field_units` (`FIELDS`); `missing_or_failed_cells`; `suite_completion_marker_present`; `artifact_evidence`; `groups`; `statistics`; `timing_warning`; `authentication_limit`. Тексты `statistics`, `timing_warning`, `authentication_limit` — константные строки кода. Первая сообщает: средние с равным весом повторений, выборочное SD (ddof=1), SE = SD / sqrt(число не-null n), без доверительного интервала, парные разности только для одинаковых сценария и зёрен, задержка без доставок равна null, цензурированные ожидающие пакеты не считаются доставкой с нулевой задержкой. Вторая: время CPU на вызов маршрутизации и время прогона разделены; `TBR_style_hop_oracle` — обход в ширину, несопоставим с перебором оригинальной работы. Третья: хэши и ревизии выявляют случайные несоответствия, но не подделку.

### Добавка при policy_scope (ключ `policy_scope`, 10 ключей)

`suite_policy_scope` (копия или `None`), `scenario_policies_sha256` (`content_hash` списка пар `[id, список]`), `declared_cells_by_policy`, `planned_cells` (= число ячеек плана), `verified_cells` (= `len(evidence)`), `absent_by_design_cells = число сценариев × число политик плана − число ячеек` (ручной расчёт на примере: 4 сценария, 4 политики, 10 ячеек: 4 × 4 − 10 = 6), `absent_by_design_note`, `completeness_note`, `matched_repetitions_meaning`, `statistics_note`. Заявленное кодом: ячейки незаявленных политик отсутствуют намеренно и не попадают в `missing_or_failed_cells`; сводка плана, где не все заявленные ячейки выполнены, неполная «by decision».

### Нативная сводка, схема `"ssn-native-exhaustive-experiment-summary-v1"` (27 ключей; ручной расчёт: 18 − 1 удалён + 10 добавлено)

Удаляется `suite_completion_marker_present`; `schema` заменяется; добавляются `producer_plan_schema`, `producer_native_reference`, `producer_single_run_reference` (`single_run_native_reference`), `transport_completion_marker`, `transport_completion_marker_present`, `transport_finished`, `scientifically_verified_cells`, `planned_cells`, `excluded_cells`, `scientific_consumer` (`contract` = копия `SCIENTIFIC_CONTRACT`, `aggregation_supported: true`, `plots_supported: false`, `scope`, `counter_evidence`, `producer_scope_interpretation`); `timing_warning` заменяется собственным текстом (время нативного вызова включает адаптер, проверки, поиск и счётчики, но не контекст и маски; сравнимость с оригиналом не заявляется). Вывод: `policy_scope` и нативный план не сочетаются, так как `validate_plan` отвергает такое сочетание.

## Значения по умолчанию

- `aggregate_plan`: `allow_partial=False`, `reference="TBR_style_hop_oracle"` (experiment_results.py).
- Командная строка `aggregate` (experiments.py, `parser`): `--plan` и `--out` обязательны; `--allow-partial` — флаг, по умолчанию ложь; `--reference` с `choices=POLICIES + (NATIVE_POLICY_NAME,)`, по умолчанию `"TBR_style_hop_oracle"`.
- Допуски `close`: `rel_tol=1e-10`, `abs_tol=1e-10`; устройство тайминга `"cpu"` (оба — литералы в функциях).
- Бюджеты нативного поиска здесь не задаются; границы в `verify_native_counters` используют `native["max_expansions"]` из плана (значения по умолчанию 12 и 100000 заданы в `experiment_io.py`, `native_options`).

## Связи с другими модулями

- Импортирует `config`, `sim_config`, `traffic`, `experiment_io` (вверху) и отложенно `experiments` (`check_model`).
- Вызывается из `experiments.py`, `main`, команда `aggregate`: `from .experiment_results import aggregate_plan` (отложенный импорт), после `load_plan`. Другие импортёры в прочитанных файлах не найдены; остальные модули не просматривались.
- Читает артефакты, записанные `simulate.py` (`run`, `trace`; см. `docs/04`), `experiments.py` (`execute_suite`, `preflight_models`) и `job` из `experiment_io.py`.
- Выходной файл — вход `experiment_plots.py` (описание: части D, `05_EXPERIMENTS_RU_partD1.md`-`partD4.md`).

## Побочные эффекты

Чтение файлов под корнем плана; запись одного выходного файла; хэширование файлов. Случайность не используется (модуля `random` и генераторов нет). Сеть, подпроцессы и глобальное состояние не задействованы. Входной словарь плана не изменяется (вывод из чтения; копии через `deepcopy`).

## Что в коде названо допущением или реконструкцией

- `label`: "RECONSTRUCTION / NOT AUTHORS' RESULTS".
- `authentication_limit`: хэши выявляют только случайные несоответствия; эмпирические утверждения допустимы лишь при подлинном доверенном запуске пользователем.
- Нативная политика названа в коде независимо заданным эталоном, «NOT author» (не код и не время авторов); историческая оговорка `producer_scope_interpretation` сохраняет прежние заявления слоя-производителя без пересмотра.

## Что не установлено чтением

- Содержимое `result.json`, `packets.json`, `events.jsonl` как записей симулятора и точный состав `policy_details` нативной политики (`simulator.py`, `tbr_policy.py`, `simulate.py` не перечитывались; `docs/04`). В частности, совпадение строки `budget_scope` в идентичности (написана со строчным "not") с фактически записываемой адаптером не проверено.
- Допустимость `observation_end_s == 0` и `arrival_interval_s == 0` (деления без защиты; проверки в `sim_config.py` не перечитывались).
- Другие импортёры модуля, кроме `experiments.py`; импортирует ли torch цепочка `config` / `sim_config` / `traffic`.
- Поведение `experiment_plots.py` над нативной сводкой (`plots_supported: false` в сводке).
- Любые числовые результаты: ничего не запускалось.
