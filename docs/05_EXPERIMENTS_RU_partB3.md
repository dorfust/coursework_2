# 05. Эксперименты: `experiment_io.py` (часть B3: нативная ячейка, запуск процесса, связи, списки)

Продолжение `05_EXPERIMENTS_RU_partB1.md` и `partB2.md`; модуль `src/ssn_hops/experiment_io.py`. Метки те же: «в коде написано», «вывод», «ручной расчёт». Ничего не запускалось.

## 3. Основные функции (часть 3)

### 3.17. `native_transport_check(plan, cell, scenario)`

Docstring: «Envelope/hash/identity checks ONLY. No scientific counters or aggregation.» Аргументы: план, запись из `body["cells"]`, запись из `body["scenarios"]`. Возврат `None`. `root = Path(body["root"])`, `output = inside(root, cell["out"])`. Проверки по порядку (нарушение — `ValueError`):

1. `complete.json`: `simulation_finished is True` и `result_sha256 == digest(result.json)` -> `"native completion/hash mismatch"`.
2. `result["schema"] == NATIVE_RESULT_SCHEMA`, `result["policy"] == NATIVE_POLICY_NAME` -> `"native result schema/policy mismatch"`.
3. `content_hash(result["native_reference"])` равен `content_hash(single_run_native_reference(body["native_reference"]))` -> `"native result limits/metadata mismatch"`.
4. Пять ключей `result["policy_details"]` (`policy_identity`, `search_identity`, `objective`, `max_nodes`, `max_expansions`) равны эталону по `content_hash` -> `"native policy details identity/limits mismatch"`.
5. `result["declared_checkout_revision"] == body["revision"]` -> `"native result revision mismatch"`.
6. `result["output_sha256"]`: ключи ровно `config.json`, `traffic.json`, `provenance.json`, `packets.json`, `events.jsonl` (`"native result artifact hash map mismatch"`); `digest` каждого файла равен значению (`f"native result artifact hash mismatch: {filename}"`).
7. `content_hash(read(config.json)) == content_hash(scenario["config"])` и `result["config_sha256"] == scenario["config_sha256"]` -> `"native result configuration mismatch"`.
8. `trace = read(inside(root, scenario["trace_path"]))`; `read(traffic.json) == trace`, `result["traffic_sha256"] == trace["sha256"]` -> `"native result paired trace mismatch"`.
9. `provenance.json`: `declared_checkout_revision == body["revision"]`, `source_sha256 == body["source_sha256"]`, `content_hash(native_reference)` = эталон -> `"native provenance identity/source/revision mismatch"`.
10. `input_file_sha256 == {str(root / cell["config_path"]): digest(...), str(root / scenario["trace_path"]): digest(...)}` -> `"native provenance input hashes mismatch"`.

Вывод: не проверяется, что `cell["policy"]` нативная и `cell["scenario"] == scenario["id"]` (делает вызывающий); метрики и содержимое `packets.json`/`events.jsonl` не проверяются (только хеши); `FileNotFoundError`, `KeyError` не оборачиваются; ключи `input_file_sha256` — строки `str(root / ...)` без `resolve` (после `validate_native_plan` `root` каноничен, 3.12 п.6). Вызывают: `experiments.execute_suite` (ячейка нативной политики), `experiment_results._verify_cell`.

### 3.18. `job(root, job_id, command, plan)`

Docstring: «User-invoked subprocess, argv only, no shell; exclusive logs/status.» По порядку:

1. `logs = Path(root) / "logs"`; `logs.mkdir(exist_ok=True)` (без `parents`: нет `root` — `FileNotFoundError`); `prefix = logs / job_id`.
2. `argv = [sys.executable, *command[1:]]`: `command[0]` (в плане `"python"`) отбрасывается, вместо него — интерпретатор текущего процесса; остальное не проверяется.
3. `record = {"id", "argv", "cwd": str(Path.cwd()), "revision", "plan_sha256"}`; `write(prefix + ".started.json", record)` (файл есть — `FileExistsError` до запуска).
4. `try`: `.stdout.txt`, `.stderr.txt` открываются в режиме `"x"`; `subprocess.run(argv, stdout=..., stderr=..., check=False)`: без оболочки, `timeout`, явных `cwd`/`env`/`stdin`; `record.update(exit_code=returncode, exception=None)`.
5. `except Exception`: `exit_code=None`, `exception=f"{type(exc).__name__}: {exc}"`, `write(.status.json)`, `raise`.
6. `record["log_sha256"] = {".stdout.txt": digest(...), ".stderr.txt": digest(...)}`; `write(.status.json, record)` — и при ненулевом коде.
7. `returncode != 0` -> `RuntimeError(f"{job_id} exited {returncode}; preserve {prefix} logs")`; иначе возврат `record`.

Ручной подсчёт: `status.json` после завершения процесса — 8 ключей (`id`, `argv`, `cwd`, `revision`, `plan_sha256`, `exit_code`, `exception`, `log_sha256`); при исключении — 7; `started.json` — 5 (словарь сериализуется до `update`). Вывод: повтор того же `job_id` даёт `FileExistsError`; при обрыве между шагами 3 и 6 остаётся `started.json` без `status.json`; `-m ssn_hops...` требует импорта пакета из наследуемого каталога или среды; `job_id` не проверяется как имя файла (у `make_plan` это `data-n<N>`, `train-n<N>`, `evaluate-n<N>`, `<id сценария>--<политика>`). Вызывают: `train_suite`, `execute_suite`; поля читает `experiment_results._verify_cell`.

## 4. Значения по умолчанию

Строки схем — `partB1`, 2.3. Из `experiment_io.py`: `native_options`: `max_nodes` = 12, `max_expansions` = 100000 (3.3); `digest`: блок `1024 * 1024` (3.7); `revision`: `[0-9a-f]{40}` (3.8); `write`: `indent=2`, `sort_keys=True`, `allow_nan=False`, режим `"x"` (3.6); `job`: папка `"logs"`, `check=False`, без таймаута (3.18); режимы плана — 3.12.

## 5. Связи с другими модулями

Импортирует (в коде): `hashlib`, `json`, `numbers.Integral`, `pathlib.Path`, `re`, `subprocess`, `sys`; `config` (`content_hash`, `from_dict`, `require_supported_model`), `sim_config` (`from_sim_dict`). Лениво из `experiments` (внутри функций): `validate_native_plan` — `CONTRACT`, `FEATURE_CONTRACT`, `POLICIES`, `merge`, `plan_commands`, `resolve_plan_inputs`, `validate_suite`; `check_scoped_plan` — `POLICIES`.

Вывод: `experiments.py` импортирует `experiment_io` на верхнем уровне, поэтому обратный импорт ленивый (без цикла при загрузке). Верхние импорты `experiments.py` — только `config`, `sim_config`, `experiment_io` и стандартная библиотека; `config.py` импортирует только стандартную библиотеку (прочитано); `sim_config.py` здесь не читался (`02_ENVIRONMENT_RU.md`). Поэтому `validate_native_plan` не должен подгружать `torch`/`numpy` (docstring: «no execution/import ML»).

Импортёры (по чтению): `experiments.py` (имена — `05_EXPERIMENTS_RU_partA3.md`, раздел 10; порядок в `make_plan`: `native_options` -> `revision` -> `source_hashes()` -> `write` конфигов и `digest` в `file_sha256` -> `write(root / "plan.json", {"schema", "body", "sha256": content_hash(body)})`); `experiment_results.py` — `PLAN_SCHEMA`, `NATIVE_PLAN_SCHEMA`, `NATIVE_POLICY_NAME`, `NATIVE_RESULT_SCHEMA`, `digest`, `inside`, `native_transport_check`, `read`, `schema_guard`, `single_run_native_reference`, `source_hashes`, `validate_plan`, `write`; `experiment_plots.py` — `NATIVE_PLAN_SCHEMA`, `NATIVE_POLICY_NAME`, `digest`, `native_options`, `read`, `single_run_native_reference`, `write`. Внутренние (трёмя модулями не импортируются): `positive_budget`, `validate_native_plan`, `check_scoped_plan`. Другие импортёры (например `simulate.py`) не проверялись.

## 6. Побочные эффекты

Файлы: `write` создаёт файлы и папки, не перезаписывает; `job` — `logs/` и четыре файла на задание; остальные функции только читают. Процессы: только `job` (`subprocess.run`, argv из плана, `sys.executable`); сеть и диск — как у дочернего процесса. Случайность, время, глобальное состояние: нет (`random`, `time`, `datetime` не импортируются). При импорте ничего не исполняется (docstring).

## 7. Что в коде названо допущением или реконструкцией

- `budget_scope`: «independent safety controls; NOT author settings»; `authority`: «independently specified bounded exhaustive reference; NOT recovered author traversal/code/performance»; `route_timing_scope`: «whole choose call including adapter, core validation/search and counters; excludes context/masks; NOT pure core cost or author/Fig.5 equivalence».
- `native_options` задаёт `aggregation_supported` и `plots_supported` = `False`, а `experiment_results.py`, `experiment_plots.py` реализуют их для нативных сводок, оставляя прежние заявления как «historical layer claims» (вывод: формулировки заморожены намеренно; части C, D).
- Комментарий `positive_budget` ссылается на ревизию адаптера (`at245aa27`, `blob5a554294`; не входит в экспорт). Метки `T022-S01`, `T057-S01`, `R8`, `P-2` в комментариях и строках — внутренние, расшифровка не входит в экспорт.

## 8. Что не установлено чтением

- Содержание документов из `NATIVE_CONTRACT` и `contract` у `single_run_native_reference` (не входит в экспорт); соответствие строк `*_commit` реальным ревизиям.
- Ключи `result.json`, `provenance.json`, `complete.json` и кто их пишет (`simulate.py`, здесь не читался): известны только читаемые ключи.
- Поведение `resolve_plan_inputs`, `plan_commands`, `validate_suite`, `check_model` (только по вызовам; `partA2`, `partA3`); версия Python (`is_relative_to` — 3.9+, знание о библиотеке); Windows.
- Другие импортёры модуля; работоспособность и время работы: ничего не запускалось.

## 9. Наблюдения о коде (не исправлялись)

1. `write` не атомарна: неполный файл блокирует повтор (3.6).
2. `job`: нет таймаута; `stdin` наследуется; `job_id` не проверяется (3.18).
3. `validate_plan` для `PLAN_SCHEMA` не перевыводит команды; `sha256` — самохеш без секрета; `job` исполняет argv из плана (3.14).
4. `execution_guard` не вызывает `validate_plan` для `PLAN_SCHEMA` (3.16); `validate_plan` оборачивает `KeyError`/`TypeError` только для нативной схемы, `OSError` не оборачивает (3.14).
5. Docstring говорит «Standard-library», но модуль импортирует `config` и `sim_config`.
6. `source_hashes` хеширует все `*.py` рядом: посторонний `*.py` отвергнет `execution_guard` (вывод).
Однозначной логической ошибки чтением не установлено.

## 10. Документы группы 05

`05_EXPERIMENTS_RU_partA1.md`, `partA2.md`, `partA3.md` — `experiments.py`; `05_EXPERIMENTS_RU_partB1.md`, `partB2.md`, `partB3.md` — `experiment_io.py` (этот набор). Планируются: часть C — `experiment_results.py`; часть D — `experiment_plots.py`. Сводного индекса пока нет.
