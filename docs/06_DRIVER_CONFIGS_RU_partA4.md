# docs/06. Драйвер: driver/run_cell.py, часть A4 (из A1-A5)

Описание `driver/run_cell.py` состоит из пяти документов: A1, A2, A3, A4 и A5. В A1-A3 названы четыре документа; из-за ограничения на размер одной записи добавлен A5, ни один документ не переписывался. В A4: разделы 6 (ход `main` по шагам), 7 (время), 8 (что записывается), 9 (сбои и коды выхода), 10 (пропуск готовых ячеек), 11 (git-ревизия, случайность, побочные эффекты). В A5: связи с другими модулями, допущения, то, что не установлено чтением, замечания к коду, перечень охваченного и состав следующих документов. Всё получено чтением кода; ничего не запускалось.

## 6. Ход `main` по шагам

1. Первая строка `main`: `from . import train_unit` (комментарий в коде: «lazy: train_unit imports this module»). Импорт выполняется до разбора аргументов, поэтому и `--help` его выполняет (вывод из чтения).
2. `argparse`: 16 аргументов (A1, п. 2.2). Нарушение обязательности или взаимоисключения `--slice`/`--cell`, нечисловое значение `float` — выход argparse с кодом 2.
3. Проверки аргументов (A1, п. 2.4): `check_cap_minutes` -> `_params` -> `--cell` с `--param` -> `wall_option_problem`; каждая — `refused: ...`, код 4. Затем, для `--cell` без `--counted`, строка `note:` в stderr.
4. `wall_t0 = time.monotonic()`; `deadline = None`, если `--wall-minutes` не задан, иначе `wall_t0 + args.wall_minutes * 60`. Комментарий в коде (W-3): стена начинается до загрузки плана и до создания трасс.
5. `plan_io.load_for_execution(args.plan, args.revision, expected_plan_sha256=args.plan_sha256)`. По тексту `plan_io.py` (подробно в части C): `check_binding` (корень из плана равен каталогу `plan.json`; при заданном `--plan-sha256` совпадает поле `sha256`; `revision` равна `body["revision"]`; хеши `*.py` каталога `ssn_hops` равны `body["source_sha256"]`), затем `eio.load_plan` и `eio.execution_guard`. Исключения из `REFUSAL_ERRORS` (в том числе `BindingError`) -> `refused: ...`, код 4. Обычный `ValueError` из `load_plan` и `execution_guard` не перехватывается (вывод из чтения: traceback).
6. `plan_io.mark_started(view)`: пишет `<root>/execution_started.json` с полями `plan_sha256`, `revision` (если файл уже есть — ничего не делает). Шаг выполняется ДО проверки среза и ДО проверки имён `--param`, поэтому файл появляется и при последующем отказе.
7. `Ledger(args.ledger, plan_sha256=view.sha256, revision=view.revision, source_sha256=view.source_hash, environment=describe_environment(args.env_label))`. `view.source_hash` — SHA-256 от JSON-сериализации словаря `body["source_sha256"]` (`plan_io.source_hash_of`: `sort_keys=True`, разделители `(",", ":")`). Файл журнала создаётся при первой записи (конструктор ничего не пишет).
8. `train_minutes = DEFAULT_TRAIN_CAP_MINUTES` (120.0); `cell_cap = args.cap_minutes * 60` или `None`.
9. Режим `--cell`: один шаг `{"kind": "cell", "id": args.cell, "trace_path": view.scenario_of(view.cell(args.cell))["trace_path"], "cap_seconds": cell_cap}`; `label = "ADHOC"`, `counted = args.counted`, `trace_paths = [trace_path]`. Неизвестный идентификатор -> `ValueError` из `view.cell` (не перехватывается).
10. Режим `--slice`: (a) `selector.load_slices(args.slices)`; (b) `unknown_params(overrides, spec)`, при непустом результате `refused: --param name(s) [...] are not defined as parameters in <файл> (defined: [...]; train_cap_minutes is always accepted)`, код 4; (c) `spec["parameters"] = {**spec.get("parameters", {}), **overrides}` (переопределения применяются до `resolve_all`, поэтому действуют и на `cap_minutes_param` в элементах срезов); (d) `train_minutes = spec["parameters"].get("train_cap_minutes", 120.0)`; (e) `selector.resolve_all(view, spec)`; (f) если `args.slice_id` нет среди срезов — `refused: unknown slice '<id>' in <файл> (known: [...])`, код 4; (g) из выбранного среза берутся `steps`, `counted`, `trace_paths`; `label = args.slice_id`.
11. Если задан `--train-cap-minutes`, он заменяет `train_minutes`. Приоритет лимита обучения (вывод из чтения): `--train-cap-minutes`, затем `--param train_cap_minutes=...`, затем параметр `train_cap_minutes` файла срезов, затем 120.0.
12. `wall_kwargs = {}` или `{"deadline": deadline}`; затем `with terminate_as_exception():` (A2, п. 4.3).
13. `traces.ensure_traces(view, trace_paths, ledger=ledger, slice_id=label, counted=counted, discard=args.discard)`: трассы для всех ячеек и trace-шагов среза создаются или проверяются ДО выполнения шагов (даже при `--cells-only`). Что делает функция — часть C.
14. Цикл по `steps` в порядке среза:
   - `kind == "train"`: при `--cells-only` шаг молча пропускается (без вывода); иначе `train_unit.run_train_unit(view, step["n"], ledger=ledger, slice_id=label, counted=counted, cap_seconds=train_minutes * 60, discard=args.discard)`, печать результата в JSON, `bad = train_unit.exit_code_of(result)`, `code = max(code, bad)`; при `bad` и без `--keep-going` — выход из цикла.
   - `kind == "cell"`: `cap = cell_cap if cell_cap is not None else step.get("cap_seconds")` (значит, `--cap-minutes` заменяет лимит из среза для всех ячеек); `run_cell(view, step["id"], ledger=ledger, slice_id=label, counted=counted, cap_seconds=cap, discard=args.discard, **wall_kwargs)`; печать результата; `bad = exit_code_of(result)`; `code = max(code, bad)`; выход из цикла, если `bad` и (нет `--keep-going` или `outcome == "wall_reached"`).
   - прочие `kind` (в частности `trace`) пропускаются (их трассы уже обработаны на шаге 13).
15. `except (CellRefused, traces.TraceError, train_unit.TrainRefused) as exc`: `refused: <текст>`, возврат 4. Возврат происходит немедленно, также при `--keep-going`, и накопленный `code` не возвращается.
16. Иначе `return code` (максимум по шагам; `max(2, 3)` = 3: ручной расчёт по правилу `max`).

Дочерний процесс одной ячейки запускается только функцией `run_cell` через `_spawn_and_wait` (A3): команда плана с заменой первого слова на `sys.executable`, без оболочки, с унаследованными `env`, `cwd`, `stdin`, в новой сессии.

## 7. Измерение времени и учитываемые минуты

- Часы: `time.monotonic()` для интервалов; `utc_now()` (`ledger.py`, `datetime.now(timezone.utc).isoformat()`) для меток `started_utc`, `finished_utc`, `logged_utc`.
- Время ячейки (`elapsed_s` событий `finish` и `capped`): от момента перед `Popen` до возврата `wait` (для ячейки с лимитом — включая ожидание `kill_tree`). Не входят: создание файлов журнала, хеширование логов, `_judge` и проверка результата (A3, п. 5.1).
- `elapsed_s` прерванной ячейки: `time.monotonic() - t0`, где `t0` берётся в `run_cell` сразу после записи события `start`; он включает всё до исключения, в том числе возможное хеширование и проверку.
- Минуты суммирует `ledger_sum` только по событиям `finish` и `capped` (`ELAPSED_EVENTS`); признак `counted` берётся из среза (`resolved["counted"]`) или из `--counted` (`ADHOC`, по умолчанию `False`). События `skipped`, `refused`, `discarded`, `start` минут не добавляют (у `skipped` `elapsed_s = 0.0`).
- Поле `cumulative_minutes_environment` записи: прежняя сумма `elapsed_s` для той же метки среды плюс минуты текущего события, если оно `finish` или `capped` (`Ledger.record`, `_env_minutes`).
- Пересчёт: `--cap-minutes 30` -> `cap_seconds` 1800.0; лимит обучения по умолчанию 120 мин -> 7200.0 с (ручной расчёт). Ячейка при `--wall-minutes W` стартует, только если `W * 60 - (прошедшее с wall_t0) >= cap_seconds`; время создания трасс и загрузки плана входит в прошедшее.
- Стена не ограничивает уже начатую ячейку: превышение возможно на время ячейки, не более её лимита, плюс запись в журнал (docstring: «Remaining overshoot»).

## 8. Что записывается

Файлы самого `run_cell.py` (корень `<root>` = `view.root`, из плана):
- `<root>/logs/<id>.started.json`: `id`, `argv`, `cwd`, `revision`, `plan_sha256` (до запуска процесса).
- `<root>/logs/<id>.stdout.txt`, `<root>/logs/<id>.stderr.txt`: вывод дочернего процесса.
- `<root>/logs/<id>.status.json`: поля из A3, п. 5.1.
- Каталог `<root>/<cell["out"]>` и `complete.json`, `result.json` в нём создаёт только дочерний процесс (команда плана; `simulate.py`, docs/04). Драйвер их читает (`_judge`, `_glr_records`, `resume_verifier`).
- Журнал `--ledger` (JSONL, схема `ssn-m1-ledger-v1`, строка на событие). События ячейки: `skipped` (причина `verified_complete`), `refused` (`incomplete_cell_directory`), `discarded` (`removed`), `start`, `capped`, `finish` (`outcome` одно из `ok`, `unverified`, `ok_unverified_by_request`, `failed`, `invalid_completion`, `interrupted`). События `wall_reached` в журнал не пишутся.
- Через вызываемые модули: `<root>/execution_started.json` (`plan_io.mark_started`), файлы трасс по `trace_path` и события `kind="trace"` (`traces.ensure_traces`, часть C), артефакты и события `kind="train"` (`train_unit`, часть B).
- Своих файлов вне корня плана и журнала `run_cell.py` не создаёт (вывод из чтения; логи пишутся с абсолютным корнем плана, не с `cwd`).

## 9. Сбои, коды выхода, остановка

- Ненулевой код ребёнка: `outcome="failed"`, код 2. Нулевой код без корректного `complete.json`: `invalid_completion`, код 2. Корректное завершение, но верификатор вернул `None` или бросил исключение: `unverified`, код 2.
- Лимит исчерпан: `SIGKILL` группе, статус с `exception="CellCapExceeded: killed after <cap_seconds> s wall clock"`, `capped=True`; `outcome="capped"`, код 3. Стена исчерпана: `wall_reached`, код 3, цикл прерывается всегда. В коде нет ограничения на число ячеек: лимиты только по времени (`cell_cap`, `deadline`).
- Без `--keep-going` цикл прерывается на первом ненулевом коде. С `--keep-going` продолжает, кроме `wall_reached` и отказов (п. 6.15).
- Отказ (`CellRefused`, `TraceError`, `TrainRefused`) и ошибки привязки: `refused: ...`, код 4. Неперехватываемые исключения дают traceback и ненулевой код интерпретатора (значение не установлено чтением).
- Прерывание: `KeyboardInterrupt` или `TerminationSignal` — группа ребёнка убивается, пишется `status.json` (`exit_code=None`), событие `finish` с `outcome="interrupted"`, исключение пробрасывается. Для `TerminationSignal` процесс завершается с кодом 128 + номер сигнала.
- После лимита и после прерывания остаются каталог ячейки и логи без валидной записи: при следующем запуске это `incomplete`, отказ до `--discard` (вывод из чтения: классификация `classify` + docstring (b), (c)).

## 10. Пропуск готовых ячеек (идемпотентность)

`run_cell` вызывает `classify`: если верификатор вернул запись, ячейка пропускается (`skipped_verified`, событие `skipped`, процесс не запускается, код 0). Следовательно, повторный запуск того же среза не повторяет готовые ячейки (вывод из чтения). Остатки без верификации — отказ либо, с `--discard`, удаление (`runs`-каталог ячейки и четыре лога) и новая попытка; удаление записывается как `discarded`. Проверка стены не трогает ничего.

## 11. Git-ревизия, случайность, побочные эффекты

- Ревизия: `--revision` — строка от пользователя; `run_cell.py` git не вызывает. Значение сравнивается с `body["revision"]` (`plan_io.check_binding`), затем проверяется `eio.revision` (нижний регистр, ровно 40 hex) в `execution_guard`; пишется в `started.json`, `status.json` и каждую запись журнала. Если значение отличается от плановой (а та проверена как 40-hex при `validate_plan`), `check_binding` даёт `BindingError` раньше (вывод из чтения).
- Случайность: в `run_cell.py` нет; сиды лежат в конфигурациях плана и использует ребёнок.
- Побочные эффекты: запуск процессов и `os.killpg`; создание и удаление файлов (при `--discard`); запись и `os.fsync` журнала (`Ledger.record`); установка и восстановление обработчиков `SIGTERM`/`SIGHUP`; чтение `/proc/meminfo`, `/proc/cpuinfo` и переменных `RUNNER_NAME`, `GITHUB_ACTIONS` (`describe_environment`); сети нет.
