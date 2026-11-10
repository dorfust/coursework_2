# experiment_results.py: описание, часть C3 из пяти

Продолжение `05_EXPERIMENTS_RU_partC2.md`. В этом документе: `verify_cell`, `_verify_cell`, `verify_models`. Источник утверждений: `src/ssn_hops/experiment_results.py`; функции `read`, `digest`, `inside`, `native_transport_check` определены в `experiment_io.py` (см. `docs/05_EXPERIMENTS_RU_partB*.md`).

## verify_cell(plan, cell, scenario, model_records)

Публичная обёртка над `_verify_cell` для прямых вызывающих. Возвращает то же, что `_verify_cell` (словарь проверенной ячейки или `None`). В коде написано:

1. `scientific_plan_guard(plan)` (см. C2).
2. Нативный план (`plan["schema"] == NATIVE_PLAN_SCHEMA`): внутри `try` проверяется, что `content_hash(cell)` совпадает с хэшем одной из ячеек `plan["body"]["cells"]`, `content_hash(scenario)` — с хэшем одного из сценариев `plan["body"]["scenarios"]`, и `cell["scenario"] == scenario["id"]`; иначе `ValueError("cell/scenario not in the native plan")`. Затем вызывается `_verify_cell`. Исключения `KeyError`, `TypeError`, `AttributeError`, `OverflowError`, `OSError` превращаются в `ValueError("malformed/missing completed native-plan cell artifact")` (с цепочкой `from exc`); `ValueError` проходит без изменения.
3. Обычный план: прямой вызов `_verify_cell` без проверки принадлежности ячейки плану и без обёртки исключений.

Вывод из чтения: в `aggregate_plan` сама `verify_cell` не вызывается (там вызывается `_verify_cell`, см. C5); для нативного плана каждый вызов `verify_cell` заново выполняет `validate_plan`, который перечитывает файлы плана, что дорого при многих ячейках.

## _verify_cell(plan, cell, scenario, model_records)

Внутренняя функция полной проверки одной ячейки. Возвращает `None` (ячейка отсутствует, не завершена или завершилась неуспешно) либо словарь проверенной ячейки; при несоответствии артефактов поднимает `ValueError`. Для обычных и нативных планов поведение различается. Ниже: `native_plan = plan["schema"] == NATIVE_PLAN_SCHEMA`, `native_cell = native_plan and cell["policy"] == NATIVE_POLICY_NAME`.

### Шаг 1. Пути и наличие файлов

`root = Path(plan["body"]["root"])`; `output = inside(root, cell["out"])` (отвергает абсолютные пути и `..`); `status_path = root / "logs" / (cell["id"] + ".status.json")`; `has_complete` — существует `output/complete.json`; `has_status` — существует `status_path`.

Для обычного плана: если нет `complete.json` или нет статуса, возврат `None` (поведение «missing» оставлено прежним; комментарий в коде: «Preserve legacy missing/failed behavior»). Для нативного плана завершённые артефакты проверяются, даже если статус отсутствует или неуспешен («never hidden by partial»).

### Шаг 2. Статус задания

`status = read(status_path)` при наличии. Для нативного плана со статусом: множество ключей должно содержать `{id, argv, cwd, revision, plan_sha256, exit_code, exception}` (иначе "missing native-plan job status fields"); `argv` — непустой список непустых строк, `cwd` — непустая строка (иначе "invalid native-plan job argv/cwd"); `exit_code` — `None` или `int` ровно типа `int` (иначе "invalid native-plan job exit code"); `exception` — `None` или строка (иначе "invalid native-plan job exception").

`successful` истинно, если статус есть, `exit_code == 0` и `exception is None`. Для обычного плана при `not successful` возврат `None`.

Если статус есть: `status["plan_sha256"] == plan["sha256"]` и `status["revision"] == plan["body"]["revision"]` (иначе "cell status belongs to another plan/revision"); `status["id"] == cell["id"]` и `status["argv"][1:] == cell["command"][1:]` (иначе "status command differs from planned cell"; нулевой элемент пропущен, потому что `job` в `experiment_io.py` подставляет `sys.executable`). При `successful`: для каждого `(suffix, hash)` из `status["log_sha256"]` суффикс должен быть `".stdout.txt"` или `".stderr.txt"`, а `digest(root/logs/<id><suffix>)` равен `hash` (иначе "cell stdout/stderr hash mismatch"), и набор суффиксов равен ровно этим двум (иначе "missing execution log hashes"). Для неуспешного нативного статуса хэши логов не проверяются (вывод из чтения).

Если `complete.json` нет, возврат `None`.

### Шаг 3. Завершение и результат

- `complete = read(output/"complete.json")`: `simulation_finished is True` и `complete["result_sha256"] == digest(output/"result.json")`, иначе "simulation completion/hash mismatch".
- Для нативной ячейки вызывается `native_transport_check(plan, cell, scenario)` (конверт, хэши, идентичность; не научные счётчики).
- `result = read(output/"result.json")`. Ожидаемая схема: `NATIVE_RESULT_SCHEMA` для нативной ячейки, иначе `"ssn-simulation-result-v2"`. `result["schema"]` должен совпасть и `result["policy"] == cell["policy"]`, иначе "result schema/policy mismatch; v1 results are not corrected R3 evidence" (формулировка из кода). `result["declared_checkout_revision"] == plan["body"]["revision"]`, иначе "result revision differs from suite".
- Набор ключей `result["output_sha256"]` равен `{"config.json", "traffic.json", "provenance.json", "packets.json", "events.jsonl"}` (5 файлов, иначе "incomplete result artifact hash map"); `digest` каждого файла в `output` равен записанному (иначе "result artifact hash mismatch: <file>").

### Шаг 4. Конфигурация, происхождение, трафик

- `cfg = from_sim_dict(read(output/"config.json"))`; требуется `cfg.to_dict() == scenario["config"]`, `cfg.sha256 == scenario["config_sha256"]`, `result["config_sha256"] == cfg.sha256` (иначе "result configuration differs from planned cell").
- `origin = read(output/"provenance.json")`: `declared_checkout_revision` равен ревизии плана и `source_sha256` равен `plan["body"]["source_sha256"]` (иначе "result source/revision provenance mismatch"). Вывод: именно здесь обычный план связывается с хэшами исходных файлов, зафиксированными при планировании.
- `trace = read(inside(root, scenario["trace_path"]))`; `read(output/"traffic.json") == trace` и `result["traffic_sha256"] == trace["sha256"]` (иначе "result did not use the paired suite traffic"). Это обеспечивает парность: все политики одного сценария используют один файл трассы.
- `records = read_trace(trace, cfg)` (проверки трассы, см. `docs/02`, `traffic.py`).
- `origin["input_file_sha256"]` должен быть словарём ровно из двух записей: `str(root / cell["config_path"])` и `str(root / scenario["trace_path"])` с `digest` этих файлов (иначе "original config/trace input hashes differ").

### Шаг 5. Контрольная точка GLR

`checkpoint = result["timing"]["checkpoint"]`. Для политики `"GLR"`: `model = model_records[str(cfg.orbit.n)]`; ожидается словарь из 5 ключей `sha256` (из `checkpoint_sha256`), `training_config_sha256`, `training_revision`, `epoch`, `feature_spec`; `checkpoint` должен быть равен ему, и `result["policy_details"].get("feature_spec") == model["feature_spec"]` (иначе "GLR checkpoint/input identity differs from preflight"). Для остальных политик `checkpoint` обязан быть `None` (иначе "baseline claims a GLR checkpoint"). Вывод: если в обычном плане есть GLR-ячейка, но `model_records` пуст, получится `KeyError`; для корректно построенного плана это не происходит.

### Шаг 6. Таблица пакетов, события, учёт

- `packets = read(output/"packets.json")`: ключи ровно `{"schema", "rows"}` и `packets["schema"] == "ssn-packet-table-v1"` (иначе "packet table schema mismatch").
- События читаются построчно из `events.jsonl` (`import json` выполняется внутри блока `with`): `events = [json.loads(line) for line in handle]`. Вывод: пустая строка в файле вызвала бы `json.JSONDecodeError` (подкласс `ValueError`).
- `totals = verify_accounting(cfg, records, packets["rows"], result["metrics"], result["timing"], events)` (C2).
- Для нативной ячейки `diagnostics = verify_native_counters(result["policy_details"], plan["body"]["native_reference"], result["timing"], result["metrics"])`, иначе `None`.

### Шаг 7. Возврат

Для нативного плана при `not successful` (нет статуса или он неуспешен) возврат `None` после всех проверок. Вывод: ячейка нативного плана входит в оценки только при успешном статусе, даже если артефакты прошли проверку.

Иначе формируются:

- `values` — словарь 7 показателей по ключам `FIELDS`: пять из `result["metrics"]` (`delivered_mean_delay_s`, `failure_fraction`, `pending_fraction`, `nondelivery_fraction`, `goodput_bits_s`) и два из `result["timing"]` (`route_seconds_per_call`, `simulation_seconds`) (ручной расчёт: 7 − 2 = 5, 5 + 2 = 7);
- итоговый словарь `{"values", "totals", "result_sha256", "traffic_sha256", "cell"}`, где `totals` — результат `verify_accounting`, `result_sha256` из `complete.json`, `traffic_sha256` из трассы, `cell` — `cell["id"]`. Для нативного плана добавлены `output_sha256` (копия), `log_sha256` (копия `status["log_sha256"]`), `native_counters` (результат `verify_native_counters`).

Различие обычного и нативного режимов: в обычном плане ячейка без успешного статуса или без `complete.json` просто пропускается (`None`); любая несогласованность артефактов у существующей завершённой ячейки даёт `ValueError` и прерывает агрегирование (вывод из чтения). Поэтому `allow_partial` (C5) допускает отсутствие или неуспех ячеек, но не повреждённые данные.

Рандомизация отсутствует. Побочные эффекты — только чтение файлов; из-за `defaultdict` в вызывающем коде (C5) пустые записи создаются только в памяти.

## verify_models(plan)

Аргумент: словарь плана. Возврат: `{}` если `"GLR"` не входит в `plan["body"]["policies"]`; иначе словарь `preflight["models"]` из `model_preflight.json`: ключ — строка N, значение — запись с `run`, `checkpoint_sha256`, `training_config_sha256`, `training_revision`, `epoch`, `feature_spec` (набор полей определяется записью в `experiments.py`, `preflight_models`; здесь они только читаются).

Проверки (в коде написано):

1. `preflight = read(root/"model_preflight.json")`. Если файла нет, чтение поднимает `FileNotFoundError` (вывод: даже при `allow_partial` агрегирование плана с GLR требует этого файла).
2. `preflight["plan_sha256"] == plan["sha256"]` и множество ключей `preflight["models"]` равно множеству ключей `plan["body"]["models"]`; иначе "model preflight plan/mapping mismatch".
3. Отложенный импорт `from .experiments import check_model` (импорт отложен, чтобы не создавать цикл `experiments` ↔ `experiment_results`; вывод).
4. Для каждого `n`: `model["run"] == item["run"]` и `digest(Path(item["run"]) / "best.pt") == model["checkpoint_sha256"]`, иначе "checkpoint missing/changed since preflight" (при отсутствии `best.pt` `digest` поднимает `FileNotFoundError`, а не `ValueError`; вывод из чтения).
5. `cfg = check_model(read(Path(item["run"]) / "config.json"), [конфигурации сценариев с orbit.n == n], from_dict(item["config"]).model)`. Функция `check_model` (`experiments.py`) проверяет совместимость метаданных: орбита, скорость света при расширении с задержкой, непересечение зёрен обучения и эксперимента, равенство конфигурации модели ожидаемой. Подробности в `docs/05_EXPERIMENTS_RU_partA*.md`.
6. `cfg.sha256 == model["training_config_sha256"]`, иначе "training config hash differs from preflight".
7. `model.get("feature_spec") == cfg.model.feature_spec` и `item["feature_spec"] == cfg.model.feature_spec`, иначе "model feature identity differs from plan/preflight".

Тензоры и torch здесь не загружаются: используются только конфигурации и хэши (вывод из чтения; импорты верхнего уровня `experiments.py` — стандартные модули, `.config`, `.experiment_io`, `.sim_config`).
