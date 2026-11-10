# docs/06. Драйвер: driver/train_unit.py, часть B4 (из B1-B4)

Продолжение частей B1-B3. В B4: разделы 6-14: время и ledger, записываемые файлы, сбои, лимит, обрыв и повторный запуск, коды выхода, ревизия, случайность, побочные эффекты, связи, допущения, замечания к коду, то, что не установлено чтением, охват. Пометки «в коде написано», «вывод из чтения», «ручной расчёт» — как в B1.

## 6. Измерение времени и учёт минут в ledger

- Интервалы измеряются `time.monotonic()`; метки времени — `utc_now()` (`ledger.py`: ISO-строка UTC).
- Шаг: `run_cell._spawn_and_wait` измеряет время от перед `Popen` до конца `wait` (или убийства группы); значение попадает в запись `steps` как `elapsed_s` и в `status.json` не пишется отдельным полем.
- Единица: `t0` берётся после записи события `start`; `elapsed_total = time.monotonic() - t0` после цикла шагов. В него входят шаги и накладные расходы между ними (запись журналов, хеширование логов); не входят `classify`, удаление, запись `start`, послеусловие (проверка проекта и чтение `test.json`). В коде написано (docstring): «A normal finish event measures the steps only (not the post-check)». У события `interrupted` интервал считается от `t0` до момента обрыва и включает идущую послепроверку.
- Лимит единицы: `cap_seconds = minutes * 60` (по умолчанию `120.0 * 60 = 7200` с, ручной расчёт); перед каждым шагом остаток `cap_seconds - (monotonic - t0)` передаётся как таймаут шага. Лимит ограничивает время шагов, но не послепроверку (вывод из чтения).
- Учёт минут (`ledger.py`): минуты несут только события `finish` и `capped` (`ELAPSED_EVENTS`); события `start`, `refused`, `skipped`, `discarded` минут не добавляют. `Ledger.record` добавляет поле `cumulative_minutes_environment` = сумма `elapsed_s` предыдущих `finish`/`capped` с той же меткой окружения, делённая на 60, плюс `elapsed_s / 60` текущего события. Флаг `counted` события: из среза (режим `--slice`) или `--counted` (режим `--n`); сводка `python -m driver.ledger sum` делит минуты на учтённые и неучтённые по этому флагу (часть D).
- Верхняя оценка минут для среза из двух единиц (`TRAIN-REST`): `2 × 120 = 240` мин без накладных расходов (ручной расчёт; лимит на единицу, не на срез).

Строка ledger (`ledger.Ledger.record`, схема `LEDGER_SCHEMA = "ssn-m1-ledger-v1"`): ключи `schema, event, kind, id, slice, counted, started_utc, finished_utc, logged_utc, elapsed_s, exit_code, environment, plan_sha256, revision, source_sha256`, затем дополнительные поля события и `cumulative_minutes_environment`; `json.dumps(sort_keys=True, allow_nan=False)`, дозапись, `flush`, `fsync`. Для `train_unit`: `kind = "train"`, `id = train-nN`, `slice` — идентификатор среза или `ADHOC`. События и дополнительные поля: `refused` (`reason`: `supplied_model_check_failed`, `project_check_could_not_run`, `incomplete_training_directory`, `unreadable_evaluation_output`, `incomplete_evaluation_logs`; `present`, `verify_error`); `skipped` (`reason`: `supplied_model_verified`, `verified_complete`; `elapsed_s=0.0`); `discarded` (`removed`, `verify_error` или `scope="evaluation_only"`); `start` (`cap_seconds`, `steps`); `finish`/`capped` (`outcome`, `verified`, `verify_error`, `steps`, `cap_seconds`); `finish` с `outcome="interrupted"` (`exception`, `steps`).

## 7. Что записывается (точные имена)

Самим `train_unit.py`: строки ledger (выше); `<root>/execution_started.json` = `{"plan_sha256", "revision"}` (`plan_io.mark_started`); удаления `shutil.rmtree`/`unlink` в `discard_unit`. Файлы шагов (`run_cell._spawn_and_wait`): `<root>/logs/<id шага>.started.json`, `.stdout.txt`, `.stderr.txt`, `.status.json` для `id` = `data-nN`, `train-nN`, `evaluate-nN`. Имя `logs/train-nN.*` совпадает по написанию с идентификатором единицы в ledger (`train-nN`); это разные сущности.

Дочерними процессами (чтение `training.py` и `experiments.plan_commands`): `<root>/training/nN/data/` (команда `generate`, состав — docs/03); каталог запуска `<root>/training/nN/run/` с файлами `config.json`, `dataset_manifest.json`, `provenance.json`, `history.jsonl`, `best.pt` (через временный `best.pt.tmp`), `best.json`, `complete.json` = `{"training_finished": true, "epochs_run": <число>}` (пишется последним); формат чекпойнта `CHECKPOINT_FORMAT = "ssn-hops-fixed-n-v2"`; `<root>/training/nN/test.json` (команда `evaluate`, запись через `write_json` из `provenance.py`, режим записи которого здесь не проверялся). Строка схемы плана: `ssn-experiment-plan-v2` (`experiment_io.PLAN_SCHEMA`), файла срезов: `ssn-m1-slices-v1` (`selector.SLICES_SCHEMA`).

Не пишутся: `training_started.json`, `training_complete.json`, `complete.json` драйвером, `model_preflight.json`.

## 8. Сбои, лимит, обрыв, повторный запуск, коды выхода

- Исход `failed` (код шага не 0): остальные шаги не запускаются; артефакты остаются. Вывод из чтения: при сбое `train-nN` каталог `run` без `complete.json` даёт при повторе `incomplete` (проверка проекта бросает `FileNotFoundError`), отказ 4 до `--discard`; при сбое `evaluate-nN` запуск проходит проверку, остаются журналы `evaluate-nN` (и, возможно, `test.json`), отказ до `--discard`, который удалит только их и повторит оценку; при сбое `data-nN` каталога `run` нет, состояние `incomplete`.
- Исход `capped`: группа процессов убита `SIGKILL`; ledger-событие `capped`; код 3; каталоги остаются, повторный запуск отказывается (docstring: «its directories stay and are refused on rerun until discard»). Обучение, остановленное лимитом, НЕ продолжается: с `--discard` единица удаляется целиком и обучается заново (в коде написано: «no resume»).
- Законченная единица (проверка проекта прошла, `test.json` читается): пропускается (`skipped_complete`, код 0). Единица с готовым обучением без оценки: выполняется только `evaluate` (B3, п. 4.14).
- Исход `invalid_postcondition` (код 2): шаги вернули 0, но послепроверка не прошла.
- Обрыв (`KeyboardInterrupt`, `TerminationSignal` и любое `BaseException`): `_spawn_and_wait` убивает группу процессов шага и пишет `status.json` с `exit_code: null`; затем одно событие `finish`/`interrupted` и повторный бросок. Выход при SIGTERM/SIGHUP: `128 + номер` (на Linux 143 и 129, ручной расчёт при внешнем знании номеров 15 и 1). Незаписанный `finish` при сбое самого ledger: попытка записать `interrupted` с предупреждением (docstring). Остаточное окно (docstring): сигнал между возвратом записи и присвоением `recorded` может дать второе событие `finish` (завышение, «fail-safe»). SIGKILL драйвера или потеря питания оставляют дочерний процесс-сироту и неполную единицу: перед `--discard` проверить `ps` (docstring ссылается на `run_cell`, пункт (c)).
- Отказы (код 4, строка `refused: ...`): ошибки аргументов; `REFUSAL_ERRORS` при загрузке плана и срезов; неизвестный срез; срез без шага обучения; `TrainRefused`.

Коды выхода (в коде написано): 0 — `ok`, `skipped_complete`, `supplied_verified`; 2 — `failed`, `invalid_postcondition`, неизвестный исход, а также ошибка использования argparse; 3 — `capped`; 4 — отказ; `128 + сигнал` — `TerminationSignal`. Необработанное исключение завершает процесс стандартным кодом Python (1; общее свойство интерпретатора, не код этого файла).

## 9. Ревизия, случайность, побочные эффекты

- Ревизия: `--revision` должен совпасть со строкой `body["revision"]` (`check_binding`, иначе `BindingError`, код 4), а `experiment_io.revision` требует `re.fullmatch(r"[0-9a-f]{40}", value)` («revision must be the actual lowercase 40-character checkout SHA»). Git драйвер не читает. Ревизия попадает в `started.json`, в строки ledger и (через план) в аргумент `--revision` дочерних команд.
- Случайность: в `train_unit.py` нет. Сиды задаёт дочерний процесс `train`: `training.seed_training` (`random`, `numpy`, `torch` от `cfg.train.seed`), `np.random.default_rng(cfg.train.seed)` для порядка выборок; значения берутся из `configs/training-nN.json` плана. Совпадение результатов повторного обучения после `--discard` не установлено.
- Побочные эффекты: запись файлов раздела 7; удаление каталогов под корнем плана; дочерние процессы (в новых сессиях) и `SIGKILL`; установка на время блока обработчиков SIGTERM/SIGHUP (`terminate_as_exception`); ленивый импорт `torch` в самом процессе драйвера (`project_check` после обучения и при классификации); печать в stdout/stderr; запись `execution_started.json`, после которой `experiments execute` отказывается (docstring, метка F-6).

## 10. Связи с другими модулями

Импорты: `experiment_io` (только `read`), `plan_io` (`load_for_execution`, `mark_started`), `run_cell` (`STATUS_SUFFIXES`, `_spawn_and_wait`, `check_cap_minutes`, `_params`, `unknown_params`, `REFUSAL_ERRORS`, `refuse_with`, `terminate_as_exception`), `selector` (`load_slices`, `resolve_all`), `ledger` (`Ledger`, `describe_environment`, `utc_now`); лениво `ssn_hops.experiments` (`preflight_models`). Импортируется: `run_cell.main` (лениво: `run_train_unit`, `exit_code_of`, `TrainRefused`). Прочие потребители (`finish.py`, `traces.py`) чтением в этом документе не рассматривались.

Отношение к `ssn_hops`. `training.train(cfg, dataset_dir, run_dir, revision)` создаёт каталог запуска с `mkdir(exist_ok=False)` и `history.jsonl` в режиме `"x"`: возобновления нет. `experiments.train_suite(plan, rev)`: `execution_guard`; `FileExistsError`, если `run` или `data` неподаваемой модели уже существуют; пишет `training_started.json`; выполняет шаги всех не поставленных N через `experiment_io.job()` (`subprocess.run` без лимита, `RuntimeError` при ненулевом коде); пишет `training_complete.json`. `train_unit` повторяет шаги и их порядок, но: одна единица N за вызов; лимит и убийство группы; журналы шагов те же (`logs/<id>.*`); проверка полноты `preflight_models` для одного N; пропуск готовых и перезапуск только оценки; исходы в ledger; без `training_*.json`. Раскладка чекпойнта — docs/03, часть 2 (`best.pt`, `best.json`, `complete.json`).

## 11. Что в коде названо допущением или реконструкцией

Модуль назван «Written, NOT run.» Метки в docstring и сообщениях (цитаты строк кода; документы, на которые они указывают, в экспорт не входят): `A-1`, `A-2`, `A-4`, `A-7` с пометкой `T063`; `S02c-1`, `D8`, `NB-1`; `F-5` (нечитаемый `test.json`); `F-6` (`mark_started`); «blob 72b6fa02» (по метаданным совпадает с экспортированным `experiments.py`, вывод из чтения); «360-minute sum» и метка `ADHOC`. Явное отступление в docstring: `FileNotFoundError`, `NotADirectoryError`, `IsADirectoryError` не считаются «проверка недоступна» (п. 4.10, B2).

## 12. Замечания к коду (не исправлялись; ни одной определённой логической ошибки не установлено)

1. `light_state` в этом файле не вызывается.
2. `mark_started` выполняется до проверки среза и параметров: отказ из-за отсутствующего файла срезов, неизвестного среза или `--n` с неизвестным N уже оставляет `execution_started.json`.
3. Не перехватываются: простой `ValueError` из `load_plan`/`execution_guard`, `OSError` на не-POSIX, `KeyError` при плане без ключа `steps`, `FileExistsError` при существующих журналах шага.
4. Любое исключение внутри `try` называется в ledger `interrupted` (в том числе `FileExistsError`).
5. `TrainRefused` возвращает 4 сразу и отбрасывает накопленный код, даже при `--keep-going`.
6. `discard_unit` проверяет корень по мере удаления: ранние цели могут быть удалены до отказа на поздней.
7. `--slice ""` (пустая строка) ложен в условии `if args.slice_id`, поэтому идёт ветка `--n` с `ns = [None]`; итог: `refused: N=None is not a planned model` после `mark_started`.
8. `run_complete_no_evaluation` не требует каталога `data`; повтор `evaluate` без него завершится сбоем шага (вывод из чтения по `training.evaluate`, `load_dataset`).
9. `cap_seconds` в `status.json` убитого шага — остаток лимита, а не лимит единицы.
10. Текст `check_cap_minutes` «omit the option for no cap» здесь неточен: отсутствие опции даёт значение по умолчанию 120 мин.
11. Послепроверка не ограничена лимитом.

Поправки к B2 и B3 (не переписывались): в B2, п. 4.1, фраза о `run_cell.main` означает, что `run_cell.main` тоже перехватывает `TrainRefused`; в B3, п. 4.14, последняя фраза «Вывод из чтения...» означает лишь следующее: результат пропуска содержит только `outcome` и `id`, а событие `skipped` в ledger несёт `elapsed_s=0.0`.

## 13. Что не установлено чтением

- Работа любой команды: ничего не запускалось; раскладка экспорта (`PYTHONPATH`, `--slices configs/slices_m1b_cgr.json`) — вывод из чтения, не проверенная команда.
- Вызовы `light_state` из других файлов (`finish.py`, `traces.py`).
- Состав каталога `data` и содержимое `test.json` (docs/03); режим записи `write_json`.
- Фактические длительности шагов и достаточность лимита 120 мин.
- Коды возврата при `SIGKILL` на конкретной ОС (в коде не заданы).
- Поведение `selector.resolve_all` и `ledger_sum` сверх использованного здесь (части C и D).

## 14. Охват и планируемые части

Описано всё содержимое `driver/train_unit.py`: класс `TrainRefused` (B2); 16 функций: `model_item`, `evaluation_output`, `step_logs`, `evaluation_logs`, `unit_paths`, `project_check`, `_readable`, `light_state`, `check_could_not_run`, `classify`, `_inside_root`, `discard_unit` (B2), `run_train_unit`, `_record_interrupted_unit`, `exit_code_of` (B3), `main` (B3, раздел 5); 13 аргументов командной строки (B1, п. 2.2); константы `EXIT_*`, `DEFAULT_TRAIN_CAP_MINUTES`, `OK_OUTCOMES` (B1, раздел 3); охрана `if __name__ == "__main__"` (B1, п. 2.5). Планируются: часть C — `selector.py`, `plan_io.py`, `traces.py`, `__init__.py`; часть D — `finish.py`, `ledger.py`, четыре JSON-конфигурации и индекс `docs/06`.
