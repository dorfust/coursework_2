# experiment_results.py: описание, часть C1 из пяти

Файл: `src/ssn_hops/experiment_results.py` (39072 байт). Описание разбито на файлы `05_EXPERIMENTS_RU_partC1.md` ... `partC5.md`. Состав:

- C1 (этот файл): назначение, входы и выходы, константы модуля, вспомогательные функции `close`, `count`, `describe`.
- C2: `verify_accounting`, `scientific_plan_guard`, `verify_native_counters`.
- C3: `verify_cell`, `_verify_cell`, `verify_models`.
- C4: `summarize_group`, `summarize_scoped_group`, `native_completion_marker`, `scoped_declarations`.
- C5: `aggregate_plan`, схемы выходных документов, значения по умолчанию, связи, побочные эффекты, допущения, что не установлено чтением.

Отношения с соседними модулями описаны в других документах: `experiments.py` в `docs/05_EXPERIMENTS_RU_partA1..A3.md`, `experiment_io.py` в `docs/05_EXPERIMENTS_RU_partB1..B3.md`, симулятор и политики в `docs/04`, конфигурации, трассы трафика в `docs/02`. Здесь они не повторяются.

Обозначения: «в коде написано» означает прямую цитату или пересказ строки кода; «вывод из чтения» означает следствие, которое в коде явно не заявлено. Ничего не запускалось; описание получено только чтением.

## Назначение

Модуль `experiment_results.py` начинается со строки документации: «Aggregate saved user-run evidence, never manufacture simulation measurements» (в коде написано). Он ничего не моделирует: он читает уже сохранённые на диске артефакты набора запусков («плана»), проверяет каждый артефакт против плана и собирает один сводный JSON-документ.

Единица агрегирования (вывод из чтения `aggregate_plan`):

- Ячейка (cell) — один запуск одной политики на одном сценарии. Идентификатор ячейки в плане: `<scenario id>--<policy>` (см. `experiments.py`, `plan_commands`, `cell_id = scenario["id"] + "--" + policy`).
- Сценарий (scenario) — один разрешённый набор параметров симуляции с тройкой зёрен `seeds = [phase, traffic, failure]`.
- Группа (group) — ключ-кортеж `(grid, variant, axis, x)`, где `grid` — имя сетки, `variant` — имя варианта чувствительности, `axis` — `"n"` или `"failure_probability"`, `x` — значение по оси. Ключ собирается из `scenario["memberships"]` и `scenario["variant"]` в `aggregate_plan`. Сценарий может входить в несколько групп. В группе находятся повторения (repetitions) — сценарии, различающиеся только тройкой зёрен.

Вычисляемые показатели — оценки по повторениям внутри группы для каждой политики и парные разности «политика минус эталон» (reference). Формулы даны в C1 (`describe`), C2 (проверка учёта по пакетам) и C4 (`summarize_group`).

Модуль различает два вида планов (см. также `experiment_io.py`):

- Обычный план: `PLAN_SCHEMA = "ssn-experiment-plan-v2"`, итоговая схема сводки `SUMMARY_SCHEMA = "ssn-experiment-summary-v2"`.
- Нативный план: `NATIVE_PLAN_SCHEMA = "ssn-native-exhaustive-experiment-plan-v1"`, сводка со схемой `NATIVE_SUMMARY_SCHEMA = "ssn-native-exhaustive-experiment-summary-v1"`, политика `NATIVE_POLICY_NAME = "TBR_bounded_exhaustive_reference"` (константы определены в `experiment_io.py`, импортируются сюда).

Классов в модуле нет. Функций 14: 13 без префикса подчёркивания (`close`, `count`, `describe`, `verify_accounting`, `scientific_plan_guard`, `verify_native_counters`, `verify_cell`, `verify_models`, `summarize_group`, `summarize_scoped_group`, `native_completion_marker`, `scoped_declarations`, `aggregate_plan`) и одна внутренняя `_verify_cell` (ручной расчёт: 13 + 1 = 14). `__all__` в модуле не определён. Другим модулем используется только `aggregate_plan` (см. C5).

## Входы и выходы (общая картина)

Вход: словарь плана `plan` с ключами `schema`, `body`, `sha256` (обычно получен `load_plan` из `experiment_io.py`); путь выходного файла `output`; флаги `allow_partial`, `reference`. Читаемые файлы под `body["root"]`: `plan.json` не читается этим модулем; читаются `logs/<cell id>.status.json`, логи `logs/<cell id>.stdout.txt` и `.stderr.txt` (только хэш), `runs/<cell id>/{complete.json, result.json, config.json, traffic.json, provenance.json, packets.json, events.jsonl}`, трасса `scenario["trace_path"]`, файл конфигурации `cell["config_path"]`, `model_preflight.json` (если в плане есть GLR), `execution_complete.json`; для GLR также `<run>/best.pt` и `<run>/config.json`.

Выход: один новый JSON-файл `output` (см. C5) и возвращаемый словарь `{"summary", "sha256", "complete", "groups", "missing_or_failed_cells"}`.

## Импорты (в коде написано)

- Стандартная библиотека: `Counter`, `defaultdict` (collections), `deepcopy` (copy), `math`, `Path` (pathlib), `mean`, `median`, `stdev` (statistics).
- `.config`: `content_hash`, `from_dict`.
- `.experiment_io`: `PLAN_SCHEMA`, `NATIVE_PLAN_SCHEMA`, `NATIVE_POLICY_NAME`, `NATIVE_RESULT_SCHEMA`, `digest`, `inside`, `native_transport_check`, `read`, `schema_guard`, `single_run_native_reference`, `source_hashes`, `validate_plan`, `write`.
- `.sim_config`: `from_sim_dict`; `.traffic`: `read_trace`.
- Отложенные импорты внутри функций: `from .experiments import check_model` (в `verify_models`) и `import json` (внутри блока `with` в `_verify_cell`).
- Вывод из чтения: имя `PLAN_SCHEMA` импортируется, но в теле модуля не используется (в тексте встречаются только `NATIVE_PLAN_SCHEMA` и `schema_guard`). Импорт torch в самом модуле отсутствует; импортируют ли torch `config.py`, `sim_config.py`, `traffic.py`, этим файлом не устанавливается (см. `docs/02`).

## Константы модуля

- `SUMMARY_SCHEMA = "ssn-experiment-summary-v2"`.
- `NATIVE_SUMMARY_SCHEMA = "ssn-native-exhaustive-experiment-summary-v1"`.
- `SCIENTIFIC_CONTRACT`: словарь из четырёх строковых ключей `path`, `commit`, `blob`, `step`. Значение `path` в коде: `"Repo_Orchestrator_2/tasks/T011-S02-native-results.md"`; такого документа нет в экспорте (не входит в экспорт). Словарь копируется в сводку нативного плана (`scientific_consumer.contract`) как справочная строка; на логику проверок не влияет (вывод из чтения).
- `NATIVE_COUNTERS` — кортеж из 13 имён счётчиков нативной диагностики: `policy_calls`, `completed_searches`, `complete_route_searches`, `complete_no_route_searches`, `complete_zero_hop_searches`, `incomplete_searches`, `incomplete_max_nodes_searches`, `incomplete_max_expansions_searches`, `invalid_input_calls`, `completed_prefix_entries`, `incomplete_prefix_entries`, `total_prefix_entries`, `completed_destination_paths` (ручной расчёт: 13 имён по порядку).
- `FIELDS` — словарь из 7 показателей и строк единиц (в коде написано):
  - `delivered_mean_delay_s`: "seconds; delivered packets only";
  - `failure_fraction`: "unique terminal failed/generated";
  - `pending_fraction`: "right-censored pending/generated";
  - `nondelivery_fraction`: "(failed+pending)/generated";
  - `goodput_bits_s`: "bits/second over observation window";
  - `route_seconds_per_call`: "CPU wall seconds/choose call; includes inference misses";
  - `simulation_seconds`: "CPU wall seconds for entire simulator.run".

  `FIELDS` задаёт множество показателей, по которым строятся оценки и разности; тот же словарь записывается в сводку как `field_units`.

## Вспомогательные функции

### close(actual, expected, label)

Сравнение сохранённого числа с пересчитанным. Возвращает `None`; при расхождении поднимает `ValueError`. Правила (в коде написано):

- Если `expected is None`: `actual` обязан быть `None`, иначе `ValueError("<label>: expected JSON null")`.
- Иначе `actual` должен быть не `bool`, типа `int` или `float`, конечным (`math.isfinite`) и удовлетворять `math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)`. Нарушение даёт `ValueError("<label>: inconsistent numerical accounting")`. Следствие (вывод): если `expected` число, а `actual` равно `None`, это тоже ошибка.
- Конечность `expected` не проверяется. Допуски `1e-10` заданы литералами внутри функции, не константой.

### count(value, label)

Возвращает `value`, если `type(value) is int` и `value >= 0`; иначе `ValueError("<label>: expected nonnegative integer")`. Проверка `type(...) is int` отвергает `bool` и `float` (вывод: даже `3.0` отвергается).

### describe(values)

Сводная статистика списка чисел с пропусками. Аргумент: список, элементы которого число или `None`. Правила (в коде написано):

1. `present` — элементы, не равные `None`. Если среди них есть `bool`, не `int`/`float` или нечисловое значение (`NaN`, `inf`), поднимается `ValueError("non-finite summary input")`.
2. `n = len(present)`; `sd = statistics.stdev(present)` при `n > 1`, иначе `None`.
3. Возврат словаря из шести ключей: `n_total = len(values)`, `n_nonnull = n`, `n_null = len(values) - n`, `mean = statistics.mean(present)` при `n > 0`, иначе `None`; `sample_sd = sd`; `se_of_mean = sd / math.sqrt(n)` если `sd is not None`, иначе `None`.

Следствия (вывод из чтения):

- Стандартная ошибка: SE = SD / sqrt(n), где SD — выборочное стандартное отклонение с делителем n − 1 (`statistics.stdev`), n = `n_nonnull` (число не-null значений, не `n_total`). Это совпадает со строкой `statistics` итогового документа: "sample SD (ddof=1), SE=SD/sqrt(non-null n); no confidence interval".
- Нуль — обычное значение, не пропуск: ни в `describe`, ни выше нули специально не обрабатываются; пропуском считается только `None`.
- n = 0: `mean`, `sample_sd`, `se_of_mean` равны `None`. n = 1: `mean` равно значению, `sample_sd` и `se_of_mean` равны `None` (SE при единственном значении не вычисляется и не подменяется нулём). Если все не-null значения одинаковы, `sd = 0.0`, а `se_of_mean = 0.0` (0.0 не равно `None`).
- Доверительный интервал не строится.

Ручной расчёт (иллюстрация формул, не результат запуска). Вход `[1.0, 3.0, None]`: `n_total = 3`, `n_nonnull = 2`, `n_null = 1`; mean = (1 + 3) / 2 = 2.0; дисперсия = ((1 − 2)² + (3 − 2)²) / (2 − 1) = 2, SD = √2 ≈ 1.4142; SE = √2 / √2 = 1.0. Вход `[5.0]`: `n_total = 1`, `n_nonnull = 1`, mean = 5.0, `sample_sd = None`, `se_of_mean = None`. Вход `[2.0, 2.0]`: SD = 0.0, SE = 0.0.
