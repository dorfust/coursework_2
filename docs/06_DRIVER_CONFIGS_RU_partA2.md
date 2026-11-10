# docs/06. Драйвер: driver/run_cell.py, часть A2 (из A1-A4)

В этом документе — раздел «Основные классы и функции», первая половина: два класса, обработка сигналов, проверки аргументов и вспомогательные функции работы с ячейкой (`CellRefused`, `TerminationSignal`, `terminate_as_exception`, `check_cap_minutes`, `exit_code_of`, `one_line`, `refuse_with`, `_glr_records`, `resume_verifier`, `cell_paths`, `classify`, `discard_cell`, `kill_tree`). Запуск процесса, `_judge`, `run_cell`, `_params`, `unknown_params`, `wall_option_problem` — в A3; `main` — в A4. Нумерация продолжает A1 (разделы 1-3). Все утверждения получены чтением кода; ничего не запускалось.

## 4. Основные классы и функции (часть 1)

### 4.1. `CellRefused(RuntimeError)`

Исключение без собственного кода. Docstring: «A cell directory/log set exists in an incomplete or inconsistent state (use discard)». Бросается только в `run_cell`, когда у ячейки есть неполные артефакты, а `discard=False`. Перехватывается в `main` вместе с `traces.TraceError` и `train_unit.TrainRefused` (отказ, код 4).

### 4.2. `TerminationSignal(SystemExit)`

- `__init__(self, signum)`: вызывает `super().__init__(128 + int(signum))`, сохраняет `self.signum = int(signum)`. Так как класс — подкласс `SystemExit`, необработанное исключение завершает процесс с кодом `128 + signum` (вывод из чтения).
- `__str__`: `"driver received <ИМЯ>"`, где имя берётся из `signal.Signals(self.signum).name`; при `ValueError` подставляется `str(self.signum)`.

Это текст, который попадает в поле `exception` записи статуса (`f"{type(exc).__name__}: {exc}"`, то есть `TerminationSignal: driver received SIGTERM`; вывод из чтения).

### 4.3. `terminate_as_exception(signals=None)` (контекстный менеджер)

Декоратор `@contextlib.contextmanager`. Назначение (docstring): на время блока превратить `SIGTERM` и `SIGHUP` в `TerminationSignal`, чтобы обычный путь `BaseException` в `_spawn_and_wait` убил группу процессов дочернего процесса и записал статус.

Поведение по тексту кода:
1. `signals is None`: список `[getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name)]`.
2. Не главный поток (`threading.current_thread() is not threading.main_thread()`): ничего не ставится, выдаётся `False`, выход. Иначе при нормальной установке выдаётся `True`.
3. Для каждого сигнала: если текущий обработчик равен `signal.SIG_IGN` (например, `SIGHUP` под `nohup`), сигнал пропускается и остаётся игнорируемым (в этом случае драйвер на него не реагирует, а дочерний процесс продолжает работу; об этом сказано в docstring модуля, пункт (c)). Иначе `previous[signum] = signal.signal(signum, handler)`.
4. Вложенный `handler(signum, frame)`: сначала ставит `signal.SIG_IGN` на все сигналы, установленные ЭТИМ вызовом (`for installed in list(previous)`), затем `raise TerminationSignal(signum)`. Смысл (в коде написано, пометка A-3): второй сигнал во время очистки (killpg, запись статуса, запись события журнала) игнорируется и не прерывает её.
5. `finally`: для каждого сохранённого сигнала восстанавливается прежний обработчик (`old if old is not None else signal.SIG_DFL`).

`SIGINT` не затрагивается: `KeyboardInterrupt` обрабатывается стандартно, и от второго Ctrl-C очистка не защищена (в коде написано, docstring). Функция при импорте не вызывается; вызывается только `main` (в `main` обёрнут весь блок исполнения; также её вызывает `train_unit.main`, см. часть B).

Остаточное окно (в коде написано, docstring): сигнал, пришедший до того, как объект `Popen` присвоен переменной `proc` в `_spawn_and_wait`, поднимается при `proc is None`; дочерний процесс тогда не убивается и остаётся сиротой в своей сессии. Не покрыты (docstring): `SIGKILL` драйвера, потеря питания, OOM-kill, жёсткий сбой.

### 4.4. `check_cap_minutes(**named)`

Перебирает именованные аргументы в порядке передачи; для первого не-`None` значения, для которого не выполнено `0 < value < math.inf`, возвращает строку `--<имя с дефисами> must be a positive finite number of minutes (got <значение>); omit the option for no cap`. Иначе `None`. Для `nan` сравнение `0 < nan` ложно, поэтому `nan` отклоняется (вывод из чтения). Вызывается из `main` с тремя аргументами (`cap_minutes`, `train_cap_minutes`, `wall_minutes`) и из `train_unit.main` (с одним).

### 4.5. `exit_code_of(result)`

По `result["outcome"]`:
- `"capped"`, `"wall_reached"` -> `EXIT_CAPPED` (3);
- `"ok"`, `"skipped_verified"`, `"ok_unverified_by_request"` -> `EXIT_OK` (0);
- любой другой, включая неизвестный -> `EXIT_FAILED` (2). Docstring: «аn unknown outcome is never green».

Значит, `failed`, `invalid_completion` и `unverified` дают 2. Ключ `outcome` обязателен: при его отсутствии `KeyError` (вывод из чтения).

### 4.6. `one_line(exc)` и `refuse_with(exc)`

`one_line` возвращает `" ".join(str(exc).split())`: все серии пробельных символов (включая переводы строк) сжимаются в один пробел. `refuse_with` печатает в stdout `refused: <одна строка>` и возвращает `EXIT_REFUSED` (4). Используется для `REFUSAL_ERRORS` в `main` и в `train_unit.main`.

### 4.7. `_glr_records(view, cell, scenario)`

Строит для ячейки с политикой GLR словарь «записей моделей», который требует проверка ячейки (`model_records`). Две ветки:

1. Если существует файл `<root>/model_preflight.json` (`view.root / "model_preflight.json"`): читается через `eio.read`; если `record["plan_sha256"] != view.sha256`, `ValueError("model_preflight.json belongs to another plan")`; возвращается `record["models"]`. Файл записывает команда `finish preflight` (в docstring функции: «`finish preflight` writes it»; см. часть D).
2. Иначе — «режим возобновления» (resume mode): читается `<out>/result.json` ячейки (`out = eio.inside(view.root, cell["out"])`), берётся блок `["timing"]["checkpoint"]` (`ckpt`); `n = str(scenario["config"]["orbit"]["n"])`; `best = Path(view.body["models"][n]["run"]) / "best.pt"`. Если `best.pt` нет или `eio.digest(best) != ckpt["sha256"]`, `ValueError("GLR checkpoint of the cell differs from the planned model best.pt")`. Возвращается `{n: {"checkpoint_sha256", "training_config_sha256", "training_revision", "epoch", "feature_spec"}}`, где все значения (кроме ключа `n`) взяты из `ckpt` ячейки (`sha256` -> `checkpoint_sha256`).

Вывод из чтения: в ветке 2 ожидаемая идентичность модели строится из самого `result.json` проверяемой ячейки; независимым остаётся только требование, чтобы хеш запланированного `best.pt` равнялся хешу чекпойнта в этом `result.json`. Комментарий в коде: «The aggregator's verify_models re-checks everything later» (полная проверка выполняется позже агрегатором; описание — docs/05). Если у GLR-ячейки нет `result.json`, `eio.read` бросает `FileNotFoundError`; в `classify` это превращается в состояние `incomplete` с текстом ошибки.

### 4.8. `resume_verifier(view, cell)`

Ленивый импорт `from ssn_hops import experiment_results as results`. Затем `scenario = view.scenario_of(cell)`; `records = _glr_records(view, cell, scenario)` для `cell["policy"] == "GLR"`, иначе `{}`; результат: `results.verify_cell(view.plan, cell, scenario, records)`. Docstring: возвращает проверенную запись, либо `None` (ячейка отсутствует, завершилась сбоем или была ограничена по времени), либо бросает `ValueError` при несогласованности. Что именно проверяет `verify_cell` — в docs/05 (описание `experiment_results.py`); в этом документе не воспроизводится. Это верификатор по умолчанию (`run_cell(..., verifier=None)` заменяет `None` на `resume_verifier`).

### 4.9. `cell_paths(view, cell)`

Возвращает пару: каталог результата `out = eio.inside(view.root, cell["out"])` (относительный путь внутри корня плана; абсолютный путь и `..` отвергаются функцией `inside`) и список из четырёх путей `Path(str(view.root / "logs" / cell["id"]) + suffix)` для суффиксов `STATUS_SUFFIXES`. То есть набор артефактов ячейки: каталог `out` и файлы `logs/<id>.started.json`, `.stdout.txt`, `.stderr.txt`, `.status.json`.

### 4.10. `classify(view, cell, verifier)`

Возвращает `(состояние, существующие_пути, текст_ошибки_или_None)`.
1. Из пяти путей (`out` и четыре лога) выбираются существующие. Если их нет: `("absent", [], None)`; верификатор не вызывается.
2. Иначе вызывается `verifier(view, cell)`; любое `Exception` превращается в `error = f"{type(exc).__name__}: {exc}"`, `value = None`.
3. `"verified"`, если `value is not None`; иначе `"incomplete"`.

Состояние `verified` не требует наличия `status.json`: достаточно, чтобы верификатор вернул запись (вывод из чтения). Состояние `incomplete` покрывает и «осталась пара логов без каталога», и «каталог есть, но проверка не прошла».

### 4.11. `discard_cell(view, cell)`

Удаляет артефакты ячейки в порядке: `out`, затем четыре лога. Каталог: `shutil.rmtree`; существующий файл: `unlink`; отсутствующий — пропуск. Возвращает список удалённых путей, относительно `view.root.resolve()` (если путь лежит внутри корня; иначе абсолютный). Сама функция не пишет в журнал и не проверяет наличие работающего дочернего процесса; предупреждение о проверке `ps` перед `--discard` есть только в docstring модуля (пункт (c)). Для `out`, являющегося символической ссылкой на каталог, `shutil.rmtree` бросит ошибку (поведение стандартной библиотеки; в коде не обрабатывается; вывод из чтения).

### 4.12. `kill_tree(proc)`

`os.killpg(proc.pid, signal.SIGKILL)`; `ProcessLookupError` игнорируется; затем `return proc.wait()` (ожидание без таймаута). Идентификатор группы равен `pid` потому, что дочерний процесс запущен через `start_new_session=True` и стал лидером новой группы (docstring: он ещё не «пожат» к моменту истечения `wait(timeout)`, поэтому группа валидна). Потомок, сам вызвавший `setsid`, ускользает (в коде написано, docstring (a); не обрабатывается). Возвращаемый код: для убитого сигналом процесса `subprocess` даёт отрицательное число — номер сигнала (docstring: «negative signal number»; для SIGKILL это -9, вывод из знания стандартной библиотеки, не проверялось).
