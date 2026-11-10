# 05. Эксперименты: `experiments.py` (часть A2: серия, сценарии, обучающие единицы, ячейки, план)

Продолжение `05_EXPERIMENTS_RU_partA1.md`. Числа и имена — из `experiments.py`, если не назван другой файл. Классов в модуле нет: только функции и константы.

## 4. Основные функции: файл серии (suite)

`merge(base, changes)`: глубокая копия `base`; вложенные словари сливаются рекурсивно, остальное (в том числе списки) заменяется копией целиком (вывод из чтения).

`resolve_suite(suite_path)`: (1) читает suite; (2) `suite_keys_valid` и `schema == SUITE_SCHEMA`, иначе `ValueError("invalid suite fields/schema")` — до чтения шаблонов; (3) `core = from_dict(merge(<core_template>, suite["training_overrides"]))`, `sim = from_sim_dict(merge(<simulation_template>, suite["simulation_overrides"]))`; шаблоны читаются из папки файла suite (`suite_path.parent / ...`), недостающие поля берутся из умолчаний `config.py`/`sim_config.py` (`02_ENVIRONMENT_RU.md`); (4) `validate_suite`. Возвращает `(suite, core, sim)`.

`validate_suite(suite, core, sim)` (docstring: «Validate saved resolved inputs too, without importing any ML modules»), по порядку, все ошибки — `ValueError`:
- ключи и схема; `name(suite["name"])`;
- `seed_tuples`: список не короче 5; тройка — список из 3 элементов `[phase, traffic, failure]`; сид — `int` (не `bool`), `0 <= seed < 2**32`; все числа всех троек различны («disjoint, including streams»); пересечение с `core.data.train_seeds + val_seeds + test_seeds + [core.train.seed]` запрещено;
- `grids` и `sensitivities` непусты; имена — по `name()`, без повторов;
- вариант чувствительности — ровно ключи `name`, `overrides`; `overrides` только из `tick_s`, `rate_bytes_s`, `arrival_interval_s`;
- `core.validate()`, `sim.validate()`; при наличии ключа — `validate_policy_scope`.
Вывод из чтения: `name(g["name"])` вызывается раньше проверки структуры сетки, поэтому сетка без `name` или не словарь даст `KeyError`/`TypeError`, а не `ValueError`.

## 5. Сиды, сценарии, обучающие единицы

### 5.1. Сиды
В коде сид сценария не вычисляется по формуле. Вывод из чтения: `resolve_plan_inputs` берёт тройку `suite["seed_tuples"][index]` как есть: `phase_seed = triple[0]`, `traffic_seed = triple[1]`, `failure_seed = triple[2]` (`index` из `enumerate`). Роли — по именам полей `SimulationConfig` (фаза орбит, трафик, отказы; `02_ENVIRONMENT_RU.md`, `04_SIMULATION_POLICIES_RU.md`). Умолчания 401/501/601 (`sim_config.py`) перезаписываются.
Ручной расчёт: по умолчанию зарезервировано 8 + 2 + 2 + 1 = 13 чисел (101–108, 201, 202, 301, 302 и `train.seed` = 17, `config.py`); серия содержит не менее 5 · 3 = 15 различных чисел.

### 5.2. Перебор: `resolve_plan_inputs(suite, core, sim, root, models, baselines_only, native=None)`
Сетка — ровно поля `name`, `axis`, `sizes`, `probabilities`; `axis` равно `n` или `failure_probability`; `sizes`, `probabilities` непусты; вероятности без повторов (через `set`: `0` и `0.0` — повтор). Элемент `sizes` — ровно `{n, planes}`; N не повторяется в сетке, а один N во всех сетках имеет одно `planes`.
Циклы: сетка → размер → вероятность → вариант чувствительности → тройка сидов. Вывод из чтения: `axis` перебор не ограничивает (берётся всё произведение `sizes × probabilities`), он лишь задаёт поле `x` членства (`n` либо вероятность).
Конфигурация сценария: `from_sim_dict(merge(sim.to_dict(), {"orbit": size, "failure_probability": p, "phase_seed", "traffic_seed", "failure_seed", **variant["overrides"]}))`; в орбиту шаблона подставляются только `n` и `planes`.
Идентичность: `key = content_hash({"config": cfg.to_dict(), "variant": variant["name"]})` (SHA-256 канонического JSON, `config.content_hash`), `id = "s-" + key[:16]` (16 hex = 16 · 4 = 64 бита, ручной расчёт). Равные `id` при разных `key` — `ValueError("short scenario ID hash collision")`. Сценарий с той же конфигурацией и именем варианта из другой сетки не дублируется: в его `memberships` добавляется `{grid, axis, x}`.
Поля сценария: `id`, `key`, `config`, `config_sha256`, `config_path = "configs/<id>.json"`, `trace_path = "traces/t-<cfg.trace_key>.json"`, `variant`, `seeds`, `memberships`, `policies` (только при `policy_scope`). `trace_key` (`sim_config.py`) — хеш от N, `traffic_seed`, `tick_s`, `traffic_end_s`, `arrival_interval_s`, `packet_bytes`; вывод из чтения: сценарии, различающиеся только вероятностью отказа, фазой, сидом отказов или скоростью канала, делят один файл трассы.
После циклов: ключи `models` входят в набор N серии; ключ `(grid, variant, x, tuple(seeds))` уникален среди членств, иначе «ambiguous grid: multiple controls per seed/x» (вывод: в сетке `axis="n"` допустима одна вероятность, в сетке `axis="failure_probability"` — один размер).
Ручной расчёт-иллюстрация (числа вымышлены, не из конфигураций экспорта): сетка A (`axis=n`) 3 размера × 1 вероятность, сетка B (`axis=failure_probability`) 1 размер × 4 вероятности, 3 варианта, 5 троек: A = 3·1·3·5 = 45, B = 1·4·3·5 = 60, до слияния 105. Ячеек без `policy_scope`: сценариев × политик (4; 3 при `--baselines-only`; +1 с нативной), здесь не более 105·4 = 420.
Нативная предпроверка: при `native` сценарий с `cfg.orbit.n > native["max_nodes"]` — `ValueError` до создания папки. Ручной расчёт: умолчание N = 132 > 12.
Без `--baselines-only` для каждого сценария вызывается `check_model(train_cfg.to_dict(), [cfg.to_dict()])` (A3, 8.1).

### 5.3. Обучающая единица
На каждый N: `train_cfg = from_dict(merge(core.to_dict(), {"orbit": size}))` и запись `training[str(N)]`: `config`, `config_sha256`, `feature_spec`, `config_path = "configs/training-n<N>.json"`, `supplied` (N есть в `--models`), `run` (путь из `--models` либо `<root>/training/n<N>/run`), `data` (`<root>/training/n<N>/data`), позже `steps`. Записи создаются и при `--baselines-only`; существование готового `run` при планировании не проверяется.

### 5.4. `policy_scope` (необязательный ключ suite)
`validate_policy_scope`: непустой словарь «политика → фильтры»; имена из `POLICIES` (нативная не допускается); фильтры только `n`, `failure_probability`, `seed_tuple_indices` (нет ключа = «все», пустой словарь = «везде»); значение — список без повторов (пустой = «нигде»); `n` — `int` из размеров сеток; вероятность — конечное `int`/`float` из вероятностей сеток (точное `==`); индекс — `int` не `bool` из `range(len(seed_tuples))`.
`scope_policies(scope, n, probability, index, active)`: политика без записи работает везде, иначе — если выполняются все заданные фильтры. Итог — `scenario["policies"]`; пустой итог или разный итог для общего сценария — `ValueError`. Обучающие единицы `policy_scope` не убирает.

## 6. Ячейки и команды: `plan_commands(root, training, scenarios, policies, checkout_revision, native=None)`
Возвращает `(commands, cells)`; `commands` идёт в `body["offline_steps"]`. Первый элемент каждой команды — `"python"` (при запуске заменяется, часть B: `job`).
Шаги обучения (на каждый N, и для готовых моделей тоже; везде `--revision <rev>`):
- `data-n<N>`: `python -m ssn_hops generate --config <root>/configs/training-n<N>.json --out <data>`;
- `train-n<N>`: `... train --config <тот же> --data <data> --out <run>`;
- `evaluate-n<N>`: `... evaluate --run <run> --data <data> --split test --device cpu --out <root>/training/n<N>/test.json`.
Детали — `03_LEARNING_RU.md`.
На каждый сценарий в `commands` добавляется `trace-<id>`: `python -m ssn_hops.simulate trace --config <root>/<config_path> --out <root>/<trace_path>`. Вывод из чтения: `execute_suite` эти команды не запускает (трассы пишет сам, A3).
Ячейка (на каждую политику из `scenario["policies"]` или общего списка): `id = <id сценария>--<политика>`, `out = "runs/<id ячейки>"`, поля `id`, `scenario`, `policy`, `config_path`, `out`, `command`: `python -m ssn_hops.simulate run --config <root>/<config_path> --trace <root>/<trace_path> --policy <политика> --out <root>/<out> --revision <rev>`. Для `GLR` добавляется `--checkpoint-run <run для N сценария>`; для нативной — `--tbr-max-nodes`, `--tbr-max-expansions`. Команды `run`/`trace` — `04_SIMULATION_POLICIES_RU_partB2.md`.

## 7. Документ плана: `make_plan(suite_path, output, checkout_revision, models=None, baselines_only=False, *, include_native_tbr=False, tbr_max_nodes=None, tbr_max_expansions=None)`
Порядок (docstring: «Write configurations/commands ONLY; no imports of torch or simulator»):
1. `native_options(...)`; 2. `revision(...)`; 3. `resolve_suite`; 4. нативный план вместе с `policy_scope` — `ValueError` («native schema is frozen»); 5. без `--baselines-only` — `require_supported_model(core.model)`; 6. существующая папка `root` — `FileExistsError("plan output must be a new directory")`; 7. `policies` = `POLICIES` или `POLICIES[1:]`, плюс нативная; 8. `models`: словарь, ключи — строки из цифр, значения — строки, иначе `ValueError`; 9. `resolve_plan_inputs`; 10. при `policy_scope` `policies` = объединение списков сценариев в каноническом порядке; 11. `plan_commands`; 12. сборка `body`; 13. `root.mkdir(parents=True, exist_ok=False)`, запись `configs/*.json` с хешами в `body["file_sha256"]`; 14. запись `plan.json`. Вся нативная и сценарная проверка идёт до первого `mkdir`.
Документ: `{"schema": PLAN_SCHEMA, "body": body, "sha256": content_hash(body)}` (при нативном режиме `NATIVE_PLAN_SCHEMA`). Поля `body`: `suite` (исходный словарь), `revision`, `root` (абсолютный путь), `contract`, `feature_contract`, `mode`, `source_sha256` (имя `*.py` пакета → SHA-256, `experiment_io.source_hashes`), `policies`, `models`, `scenarios`, `cells`, `offline_steps`, `file_sha256` (только записанные конфигурации), `execution`; при нативном плане ещё `native_reference` и `resolved_templates`. Хеш и абсолютный `root` делают план непереносимым (вывод из чтения; проверка — `experiment_io.validate_plan`, часть B).
Возврат: `plan` (путь), `sha256`, `mode`, `models_required` (отсортированные строки N), `scenarios` (число), `runs` (число ячеек).
