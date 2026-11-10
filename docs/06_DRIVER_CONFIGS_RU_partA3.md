# docs/06. Драйвер: driver/run_cell.py, часть A3 (из A1-A4)

В этом документе — вторая половина раздела «Основные классы и функции»: запуск дочернего процесса (`_spawn_and_wait`), оценка результата (`_judge`), запись прерванного события (`_record_interrupted`), исполнение одной ячейки (`run_cell`) и три вспомогательные функции аргументов (`_params`, `unknown_params`, `wall_option_problem`). Первая половина — в A2, `main` — в A4. Нумерация продолжает A2. Всё получено чтением кода; ничего не запускалось.

## 5. Основные классы и функции (часть 2)

### 5.1. `_spawn_and_wait(view, cell, cap_seconds)`

Возвращает `(record, capped, elapsed_s)`. Docstring: «job() mirror with a cap»; от ячейки нужны только ключи `id` и `command` (поэтому функцию используют и для шагов обучения, `train_unit.py`). Порядок действий:

1. `logs = view.root / "logs"`; `logs.mkdir(exist_ok=True)` (родительские каталоги не создаются: корень плана должен существовать).
2. `prefix = logs / cell["id"]`; `argv = [sys.executable, *cell["command"][1:]]`.
3. `record = {"id", "argv", "cwd": str(Path.cwd()), "revision": view.revision, "plan_sha256": view.sha256}`; запись `eio.write(prefix + ".started.json", record)`. Режим записи `"x"`: если файл есть, `FileExistsError`.
4. Файлы `<prefix>.stdout.txt` и `<prefix>.stderr.txt` открываются в режиме `"x"` (текст, `utf-8`); существующий файл даёт `FileExistsError`.
5. `t0 = time.monotonic()`; `proc = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True)`. Аргументы `env`, `cwd`, `stdin`, `shell` не заданы, то есть среда, рабочий каталог и стандартный ввод наследуются, оболочка не используется (вывод из чтения). Дочерний процесс — лидер новой сессии и группы процессов (в docstring: `setsid`).
6. `returncode = proc.wait(timeout=cap_seconds)`. При `subprocess.TimeoutExpired`: `capped = True`, `returncode = kill_tree(proc)`.
7. `elapsed = time.monotonic() - t0` (вычисляется после блока `except`, поэтому для ячейки с лимитом включает ожидание `kill_tree`; не включает создание файлов, хеширование логов и проверку результата).
8. `record.update({"exit_code": returncode, "exception": None})`. Если `capped`: `exception = f"CellCapExceeded: killed after {cap_seconds} s wall clock"`, `capped = True`, `cap_seconds = cap_seconds`.
9. Любое `BaseException` (в том числе `KeyboardInterrupt`, `TerminationSignal`): если `proc is not None and proc.poll() is None`, `kill_tree(proc)`; затем `record.update({"exit_code": None, "exception": f"{type(exc).__name__}: {exc}"})`, запись `status.json`, повторный `raise`. Хеши логов в этом случае не записываются.
10. В нормальном случае: `record["log_sha256"] = {".stdout.txt": sha256, ".stderr.txt": sha256}` (через `eio.digest`, SHA-256 по блокам 1 MiB), запись `<prefix>.status.json`, возврат.

Схема-строки у файлов `started.json` и `status.json` в коде нет (поля задаются прямо в словаре). Ключи `status.json`: `id`, `argv`, `cwd`, `revision`, `plan_sha256`, `exit_code`, `exception`, `log_sha256`; при превышении лимита добавляются `capped` и `cap_seconds`. JSON пишет `eio.write` (отступ 2, ключи отсортированы, NaN запрещён).

Замечания по чтению. Если исключение возникает после того, как `status.json` уже записан (в блоке `try` этого нет), повторной записи нет. Если `status.json` уже существует при обработке `BaseException`, `eio.write` бросит `FileExistsError` и скроет исходное исключение (вывод из чтения; в обычном потоке `classify` перед запуском такой случай исключает). Docstring (a): процесс-потомок, сам вызвавший `setsid`, убийством группы не затрагивается (не обработано); работает только на POSIX.

### 5.2. `_judge(view, cell, record, verifier, verify_after)`

Возвращает `(outcome, verified, verify_error)` для дочернего процесса, который НЕ был остановлен по лимиту:

1. `record["exit_code"] != 0` -> `("failed", None, None)`.
2. `output = eio.inside(view.root, cell["out"])`. Читается `output/"complete.json"`; признак валидности: `complete.get("simulation_finished") is True` и `complete["result_sha256"] == eio.digest(output/"result.json")`. Любое `Exception` при чтении или сравнении даёт `valid = False`.
3. Не валидно -> `("invalid_completion", None, None)`. Комментарий в коде: `execute_suite` в этом месте бросает исключение «child exited zero without a valid completion record» (сверка с текстом `experiments.py` в этом документе не выполнялась; описание `execute_suite` — docs/05).
4. `verify_after` ложно -> `("ok_unverified_by_request", None, None)`.
5. Иначе `verified = verifier(view, cell) is not None`; при `None`: `verify_error = "the verifier returned None: the cell is missing, failed or not successful"`; при исключении: `verified = False`, `verify_error = f"{type(exc).__name__}: {exc}"`. Результат: `("ok" if verified else "unverified", verified, verify_error)`.

### 5.3. `_record_interrupted(ledger, cell_id, stamp, t0, exc, common)`

Пишет событие журнала `ledger.record("finish", "cell", cell_id, started_utc=stamp, finished_utc=utc_now(), elapsed_s=time.monotonic() - t0, exit_code=None, outcome="interrupted", exception=f"{type(exc).__name__}: {exc}", **common)`. Любое исключение записи перехватывается: в stderr печатается `warning: the ledger finish event of the interrupted cell <id> could not be written: ...`, исходное исключение не подменяется.

### 5.4. `run_cell(view, cell_id, *, ledger, slice_id=None, counted=True, cap_seconds=None, discard=False, verifier=None, verify_after=True, deadline=None)`

Публичная функция: исполняет или пропускает ОДНУ ячейку. Порядок (по тексту кода):

1. Проверки: `cap_seconds` не `None` и не `> 0` -> `ValueError("cap_seconds must be positive")` (значение `nan` тоже отвергается); `deadline` без `cap_seconds` -> `ValueError`; `os.name != "posix"` -> `OSError("capped runs need POSIX process groups (Linux/WSL2); Windows-native is out of scope")`.
2. `verifier = verifier or resume_verifier`; `cell = view.cell(cell_id)` (`ValueError`, если идентификатор не принадлежит плану); `common = {"slice_id": slice_id, "counted": counted}`.
3. `state, present, error = classify(view, cell, verifier)`.
4. `state == "verified"`: `ledger.record("skipped", "cell", cell_id, reason="verified_complete", elapsed_s=0.0, **common)`; возврат `{"outcome": "skipped_verified", "id": cell_id}`. Это пропуск уже готовой ячейки (идемпотентность): процесс не запускается.
5. Если `deadline` задан: `remaining = deadline - time.monotonic()`; при `remaining < cap_seconds` возврат `{"outcome": "wall_reached", "id", "remaining_s", "cap_seconds"}` без записей в журнал и без вмешательства в артефакты (даже при `discard=True`). Проверка стоит ПОСЛЕ пропуска готовых и ДО обработки неполных.
6. `state == "incomplete"`: `names` — пути артефактов относительно `view.root.resolve()`. Без `discard`: `ledger.record("refused", "cell", cell_id, reason="incomplete_cell_directory", present=names, verify_error=error, **common)` и `raise CellRefused(...)`. С `discard`: `ledger.record("discarded", "cell", cell_id, removed=discard_cell(view, cell), verify_error=error, **common)` (удаление выполняется до записи события).
7. `stamp = utc_now()`; `ledger.record("start", "cell", cell_id, started_utc=stamp, cap_seconds=cap_seconds, **common)`; `t0 = time.monotonic()`.
8. В `try`: `_spawn_and_wait(view, cell, cap_seconds)`; если не `capped`, `_judge(...)`. `except BaseException`: `_record_interrupted(...)`, повторный `raise`. Любое исключение внутри этого блока (не только сигнал) записывается как `outcome="interrupted"` (вывод из чтения: так будет и при обычной ошибке ввода-вывода внутри `_spawn_and_wait`).
9. `capped`: `ledger.record("capped", "cell", cell_id, started_utc, finished_utc, elapsed_s=elapsed, exit_code=record["exit_code"], cap_seconds, outcome="capped", **common)`; возврат `{"outcome": "capped", "id", "elapsed_s", "exit_code"}`.
10. Иначе `ledger.record("finish", "cell", cell_id, started_utc, finished_utc, elapsed_s, exit_code, outcome, verified, verify_error, **common)`; возврат `{"outcome", "id", "elapsed_s", "exit_code", "verified", "verify_error"}`.

Возможные `outcome` (docstring): `skipped_verified`, `ok`, `unverified`, `ok_unverified_by_request`, `failed`, `invalid_completion`, `capped`, `wall_reached`; прерванная ячейка исключение пробрасывает. Через `main` параметр `verify_after` всегда `True` (в `main` он не передаётся, значение по умолчанию); `verifier` тоже не передаётся.

Что видно в записи журнала (`ledger.py`, `Ledger.record`; подробное описание — в части D): поля `schema` (= `"ssn-m1-ledger-v1"`, `LEDGER_SCHEMA`), `event`, `kind` (здесь `"cell"`), `id`, `slice` (из `slice_id`), `counted`, `started_utc`, `finished_utc`, `logged_utc`, `elapsed_s`, `exit_code`, `environment`, `plan_sha256`, `revision`, `source_sha256`, дополнительные ключи вызова и `cumulative_minutes_environment`. В сумму минут идут только события `finish` и `capped` (`ELAPSED_EVENTS`).

### 5.5. `_params(pairs)`

Для каждой строки из `--param`: `name, sep, value = pair.partition("=")`. Ошибки (`ValueError`): нет `=` или пустое имя — `--param needs NAME=VALUE, got '...'`; значение не `float` — `--param <name>: '<value>' is not a number`; значение не в `(0, inf)` — `--param <name>=<value>: must be a positive finite number`. Результат: словарь имя -> `float`; при повторе имени побеждает последнее значение.

### 5.6. `unknown_params(overrides, spec)`

Отсортированный список имён из `overrides`, которых нет среди `spec.get("parameters", {})`; имя `train_cap_minutes` принимается всегда: `sorted(set(overrides) - set(spec.get("parameters", {})) - {"train_cap_minutes"})`. Используется также в `train_unit.main`.

### 5.7. `wall_option_problem(args)`

Проверяется до загрузки плана. При `args.wall_minutes is None` возвращает `None`. Иначе по порядку:
1. `args.cell`: `--wall-minutes has no effect with --cell (a single cell has no wall); use it with --slice`;
2. `args.cap_minutes is None`: `--wall-minutes requires --cap-minutes (a cell without a cap could run past the wall)`;
3. не `args.cells_only`: `--wall-minutes requires --cells-only (a training step has no wall in this option; run slices that contain train steps with --cells-only)`;
иначе `None`.
