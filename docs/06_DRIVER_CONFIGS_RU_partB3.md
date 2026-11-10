# docs/06. Драйвер: driver/train_unit.py, часть B3 (из B1-B4)

Продолжение частей B1 и B2. В B3: раздел 4, подразделы 4.14-4.16 (`run_train_unit`, `_record_interrupted_unit`, `exit_code_of`) и раздел 5 (`main` по шагам, включая запуск дочерних процессов). Нумерация разделов сквозная для частей B1-B4. Имена полей и событий ledger приведены здесь по ходу изложения; сводка и время — в B4 (раздел 6).

## 4. Основные классы и функции (часть 2)

### 4.14. `run_train_unit(view, n, *, ledger, slice_id=None, counted=True, cap_seconds=None, discard=False, check=None)`

Docstring: «Train (or skip) ONE N.» Возвращает словарь с ключом `outcome`: `skipped_complete`, `supplied_verified`, `ok`, `failed`, `capped`, `invalid_postcondition`. Аргументы после `n` только именованные. Значения по умолчанию в сигнатуре: `slice_id=None`, `counted=True`, `cap_seconds=None` (нет лимита), `discard=False`, `check=None` (затем `project_check`). Командная строка всегда передаёт `cap_seconds = minutes * 60`.

Предусловия (в коде написано):
- `cap_seconds` не `None` и не положительное число (включая `nan`) — `ValueError("cap_seconds must be positive")`;
- `os.name != "posix"` — `OSError("capped runs need POSIX process groups (Linux/WSL2); Windows-native is out of scope")`.

Порядок действий:
1. `n = str(n)`, `item = model_item(view, n)` (возможный `TrainRefused` до любой записи в ledger), `uid = f"train-n{n}"`, `common = {"slice_id": slice_id, "counted": counted}`.
2. Модель задана извне (`item.get("supplied")`; план с `--models`): `check(view, n)`. При исключении: событие ledger `refused` (`reason="supplied_model_check_failed"`, `verify_error=str(exc)`) и `TrainRefused` («the supplied model fails the project's check»). Иначе событие `skipped` (`reason="supplied_model_verified"`, `elapsed_s=0.0`) и результат `{"outcome": "supplied_verified", "id": uid}`. Обучения нет никогда (docstring: поставленные модели не обучаются; `experiments.train_suite` их пропускает без проверки, здесь она добавлена).
3. `state, present, error = classify(view, n, check)`; `names` — пути из `present` относительно корня (или как есть, если вне корня).
4. Ветвление по состоянию (п. 4.11 в B2):
   - `check_unavailable`: событие `refused` (`reason="project_check_could_not_run"`, `present=names`, `verify_error=error`), `TrainRefused` с текстом «the project's completeness check could not run (...); this says nothing about the state of the run, so nothing is deleted, even with discard»; удаления нет и при `--discard`;
   - `complete`: событие `skipped` (`reason="verified_complete"`, `elapsed_s=0.0`), результат `{"outcome": "skipped_complete", "id": uid}`: законченная единица пропускается;
   - `absent`: выполняются все три шага;
   - `incomplete` без `discard`: событие `refused` (`reason="incomplete_training_directory"`, `present`, `verify_error`), `TrainRefused` («train() has no resume and generate refuses an existing directory; not touching them without discard»); с `discard`: `discard_unit(view, n)` (целиком: `data`, `run`, `test.json`, все журналы шагов), событие `discarded` (`removed=<список>`, `verify_error=<текст>`), затем все три шага;
   - `run_complete_no_evaluation` / `run_complete_bad_evaluation`: `leftovers` = существующие среди `test.json` и журналов шага `evaluate-nN`. Если они есть и нет `discard`: событие `refused` с `reason="unreadable_evaluation_output"` (для `bad_evaluation`) или `"incomplete_evaluation_logs"` и `TrainRefused` («pass discard to remove ONLY the evaluation artifacts and rerun evaluate (the training is kept)»). Если есть и `discard`: `discard_unit(..., only_evaluation=True)`, событие `discarded` (`removed`, `scope="evaluation_only"`). В обоих случаях список шагов сокращается до шагов с `id`, начинающимся с `evaluate-`; обучение не затрагивается.
5. Событие `start` (`kind="train"`, `id=uid`, `started_utc=stamp`, `cap_seconds`, `steps=[id шагов]`, `slice`, `counted`); `t0 = time.monotonic()`.
6. Цикл по шагам внутри `try` (подробно в п. 5.1 ниже): остаток лимита `remaining = cap_seconds - (time.monotonic() - t0)` (или `None`); если `remaining <= 0` — исход `capped`, `exit_code = None`, выход из цикла без запуска; иначе `run_cell._spawn_and_wait(view, step, remaining)`; в список `log` добавляется `{"id", "exit_code", "elapsed_s", "capped"}`; `capped` — исход `capped`; код возврата не 0 — исход `failed`; остальные шаги в обоих случаях не выполняются.
7. `elapsed_total = time.monotonic() - t0` (измерено сразу после цикла, до послепроверки).
8. Послеусловие при исходе `ok`: `check(view, n)` и `_readable(evaluation_output(item))`; при исключении исход `invalid_postcondition`, `verified=False`, `verify_error="<Тип>: <текст>"` (при нечитаемом `test.json` текст «evaluate output is missing or not readable JSON»); иначе `verified=True`. При исходах `failed` и `capped` `verified` и `verify_error` равны `None`.
9. Завершающее событие ledger: `capped` при исходе `capped`, иначе `finish` (в том числе при `failed` и `invalid_postcondition`); поля: `started_utc`, `finished_utc`, `elapsed_s=elapsed_total`, `exit_code`, `outcome`, `verified`, `verify_error`, `steps=log`, `cap_seconds`, `slice`, `counted`. После записи `recorded = True`.
10. `except BaseException`: если `recorded` ложно — `_record_interrupted_unit(...)`; исключение пробрасывается дальше. Блок `try` охватывает цикл, послепроверку и завершающую запись.
11. Возвращает `{"outcome", "id", "elapsed_s", "exit_code", "steps", "verified"}`.

Вывод из чтения: событие `skipped` и результат пропуска не содержат ключей `elapsed_s`/`steps` в результате (результат пропуска — только `outcome` и `id`).

### 4.15. `_record_interrupted_unit(ledger, uid, stamp, t0, exc, log, common)`

Пишет событие `finish` с `outcome="interrupted"`, `exit_code=None`, `elapsed_s = time.monotonic() - t0`, `finished_utc=utc_now()`, `exception="<Тип>: <текст>"`, `steps=log` (шаги, завершённые к моменту обрыва; ключей `verified`, `cap_seconds` у этого события нет), плюс `slice`, `counted`. Ошибка записи (`Exception`) не маскирует исходное исключение: в stderr печатается `warning: the ledger finish event of the interrupted training unit <uid> could not be written: <Тип>: <текст>`. Второй сигнал (`BaseException`) здесь не перехватывается.

### 4.16. `exit_code_of(result)`

«Process exit code of one unit result; an unknown outcome is never green (A-7).»: `capped` → 3 (`EXIT_CAPPED`); исход из `OK_OUTCOMES` (`ok`, `skipped_complete`, `supplied_verified`) → 0; всё остальное (`failed`, `invalid_postcondition`, любой неизвестный) → 2. В отличие от `run_cell.exit_code_of` нет исходов `wall_reached` и `ok_unverified_by_request`.

## 5. Ход `main` по шагам

1. Строится `argparse.ArgumentParser(description="run the training unit of one N (user-invoked; executes training)")`; `parse_args(argv)` (аргументы: B1, п. 2.2).
2. Проверки аргументов до загрузки плана (B1, п. 2.3): `check_cap_minutes`, `_params`, имена `--param` при `--n`, строка `note:`.
3. Загрузка плана: `plan_io.load_for_execution(args.plan, args.revision, expected_plan_sha256=args.plan_sha256)`. По `plan_io.py` и `experiment_io.py`: читается `plan.json`; `check_binding` требует, чтобы `body["root"]` (после `resolve`) совпадал с каталогом файла `plan.json` (иначе «root mismatch ... plan moved»), чтобы при заданном `--plan-sha256` совпал хеш плана, чтобы `--revision` равнялся `body["revision"]` и чтобы `experiment_io.source_hashes()` (sha256 каждого `*.py` в каталоге `ssn_hops`, у экспорта 24 файла) совпали с `body["source_sha256"]` (сообщение называет до 12 несовпавших файлов); затем `experiment_io.load_plan` (поля, схема, хеш содержимого, 40-hex ревизия, хеши файлов конфигураций, пути ячеек внутри корня) и `experiment_io.execution_guard`. Хеш `view.source_hash` (sha256 от канонического JSON карты хешей, `plan_io.source_hash_of`) записывается во все события ledger. Исключения `selector.SelectorError`, `plan_io.BindingError`, `FileNotFoundError`, `json.JSONDecodeError` (`run_cell.REFUSAL_ERRORS`) превращаются в `refused: <одна строка>` и код 4 (`run_cell.refuse_with`); прочие (например `ValueError` из `load_plan`) не перехватываются.
4. `plan_io.mark_started(view)`: запись `<root>/execution_started.json` = `{"plan_sha256", "revision"}` (режим `"x"`; если файл есть, ничего не происходит). Вызывается до проверки среза и параметров файла срезов (docstring: после этого `python -m ssn_hops.experiments execute` отклоняется, метка F-6).
5. `Ledger(args.ledger, plan_sha256=view.sha256, revision=view.revision, source_sha256=view.source_hash, environment=describe_environment(args.env_label))`: файл создаётся при первой записи.
6. Режим `--slice`: `selector.load_slices(args.slices)` (отказы как в п. 3); имена `--param`, не определённые в файле срезов и не равные `train_cap_minutes`, дают `refused: --param name(s) [...] are not defined as parameters in <файл> (defined: [...]; train_cap_minutes is always accepted)` и код 4; `params = {**parameters, **overrides}`, `spec["parameters"] = params`; `selector.resolve_all(view, spec)` (отказы как в п. 3; описание в части C); неизвестный `--slice` даёт `refused: unknown slice '<ID>' in <файл> (known: [...])`; из среза берутся `counted` и `ns = list(resolved["train_ns"])`; пустой `ns` даёт `refused: slice <ID> has no train step` (например, для среза только из ячеек).
7. Режим `--n`: `params = overrides`, `label = "ADHOC"`, `counted = args.counted`, `ns = [args.n]` (значение не проверяется до `model_item`).
8. Лимит: `minutes = args.train_cap_minutes`, иначе `params.get("train_cap_minutes", DEFAULT_TRAIN_CAP_MINUTES)`.
9. `with run_cell.terminate_as_exception():` (SIGTERM и SIGHUP превращаются в `TerminationSignal`, код выхода `128 + номер сигнала`; описание в части A2): для каждого `n` из `ns` по порядку — `run_train_unit(view, n, ledger=ledger, slice_id=label, counted=counted, cap_seconds=minutes * 60, discard=args.discard)`; печать `json.dumps(result, sort_keys=True)`; `bad = exit_code_of(result)`; `code = max(code, bad)`; при `bad` и без `--keep-going` цикл прерывается. Единицы одного запуска выполняются последовательно, лимит применяется к каждой отдельно.
10. `TrainRefused` в цикле: печать `refused: <текст>` и возврат 4 сразу (накопленный `code` отбрасывается, предыдущие единицы остаются выполненными). Иначе возвращается `code` (0, 2 или 3; при `--keep-going` итог — максимум, то есть 3 старше 2).

### 5.1. Как запускается обучение

Каждый шаг выполняет `run_cell._spawn_and_wait(view, step, remaining)` (части A3-A4): создаёт `<root>/logs/` (`mkdir(exist_ok=True)`); пишет `logs/<id шага>.started.json` (`{id, argv, cwd, revision, plan_sha256}`); открывает `logs/<id>.stdout.txt` и `.stderr.txt` в режиме `"x"`; `argv = [sys.executable, *step["command"][1:]]` (первое слово `python` из плана заменяется интерпретатором драйвера); `subprocess.Popen(argv, stdout=..., stderr=..., start_new_session=True)` без оболочки, без `env` и `cwd` (наследуются окружение и рабочий каталог драйвера); `proc.wait(timeout=remaining)`; по истечении лимита `os.killpg(pid, SIGKILL)` на всю группу; пишет `logs/<id>.status.json` (`exit_code`, `exception`, `log_sha256`; при лимите ещё `exception="CellCapExceeded: killed after <remaining> s wall clock"`, `capped: true`, `cap_seconds=<remaining>`). Заметим: `cap_seconds` в этой записи — остаток лимита единицы на момент запуска шага, а не сам лимит единицы (вывод из чтения). Здесь вызывается внутренняя функция `run_cell._spawn_and_wait`; в `experiments.train_suite` те же шаги идут через `experiment_io.job()` без лимита (B4, раздел 10).

Продолжение: B4 (время и ledger, записываемые файлы, сбои и повторный запуск, ревизия, случайность, связи, допущения, не установлено).
