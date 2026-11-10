# docs/06. Драйвер: driver/run_cell.py, часть A5 (из A1-A5)

В этом документе завершено описание `driver/run_cell.py`: разделы 12 (связи с другими модулями), 13 (что в коде названо допущением или реконструкцией), 14 (что не установлено чтением; замечания к коду), 15 (охват и состав следующих документов). Нумерация продолжает A4. Всё получено чтением кода; ничего не запускалось.

## 12. Связи с другими модулями

**Импорты `run_cell.py`.** Верхний уровень: стандартная библиотека (`argparse`, `contextlib`, `json`, `math`, `os`, `pathlib.Path`, `shutil`, `signal`, `subprocess`, `sys`, `threading`, `time`); `from ssn_hops import experiment_io as eio`; `from . import plan_io, selector, traces`; `from .ledger import Ledger, describe_environment, utc_now`. Лениво: `ssn_hops.experiment_results` (в `resume_verifier`) и `driver.train_unit` (первая строка `main`). Сторонних пакетов нет (вывод из чтения: нет ни одного импорта вне стандартной библиотеки и `ssn_hops`).

**Цикл.** `train_unit.py` импортирует `run_cell` на верхнем уровне (прочитано в `train_unit.py`), поэтому в `run_cell.main` импорт `train_unit` отложен. Следствие (вывод из чтения, не проверялось запуском): при запуске `python -m driver.run_cell` выполняемый модуль называется `__main__`, а `train_unit` импортирует тот же файл ещё раз как `driver.run_cell`; в памяти оказываются две копии модуля с отдельными классами (`CellRefused`, `TerminationSignal`) и константами. Функции `main` используют классы своей копии, `train_unit` — классы второй; пересечений исключений между копиями в прочитанном коде не видно.

**Что `run_cell.py` берёт у других модулей** (описание самих модулей — в указанных частях):
- `plan_io.py` (часть C): `load_for_execution`, `mark_started`, `BindingError`; у объекта `PlanView` — `root`, `sha256`, `revision`, `body`, `plan`, `source_hash`, методы `cell(id)` и `scenario_of(cell)`.
- `selector.py` (часть C): `load_slices`, `resolve_all`, `SelectorError`; из результата `resolve_all` — `steps`, `counted`, `trace_paths`; из шага — `kind`, `id`, `n`, `trace_path`, `cap_seconds`.
- `traces.py` (часть C): `ensure_traces`, `TraceError`.
- `ledger.py` (часть D): `Ledger` (метод `record`), `describe_environment`, `utc_now`.
- `train_unit.py` (часть B): `run_train_unit`, `exit_code_of`, `TrainRefused`. Обратно `train_unit.py` берёт из `run_cell`: `STATUS_SUFFIXES`, `_spawn_and_wait`, `check_cap_minutes`, `_params`, `unknown_params`, `refuse_with`, `REFUSAL_ERRORS`, `terminate_as_exception` (прочитано в `train_unit.py`).
- `finish.py` (часть D): `run_cell.py` его не импортирует и не вызывает. В комментарии `_glr_records` сказано, что файл `model_preflight.json` пишет команда `finish preflight`. Импортирует ли `finish.py` модуль `run_cell`, в этом документе не проверялось.
- `ssn_hops` (docs/05, docs/04): `experiment_io` — `read`, `write`, `digest`, `inside` (и через `plan_io` — `load_plan`, `execution_guard`, `source_hashes`); `experiment_results.verify_cell` (проверка ячейки, docs/05); команды ячеек строит `experiments.py`, а `execute_suite` в docstring указан как образец поведения; сама симуляция выполняется дочерним процессом по команде плана (`simulate.py`, docs/04). Прямых импортов `experiments` и `simulate` в `run_cell.py` нет.

**Сравнение с `experiment_io.job()`** (оба текста прочитаны): те же файлы `logs/<id>.started.json`, `.stdout.txt`, `.stderr.txt`, `.status.json` (режим `"x"`), тот же `argv = [sys.executable, *command[1:]]`, те же поля записи. Отличия: `job` использует `subprocess.run` без лимита и новой сессии, ловит `Exception`, при ненулевом коде бросает `RuntimeError`; `_spawn_and_wait` использует `Popen` с `start_new_session=True`, лимит `wait(timeout=...)`, ловит `BaseException`, ненулевой код не бросает, а возвращает; добавлены поля `capped`, `cap_seconds`.

## 13. Что в коде названо допущением или реконструкцией

- Docstring: «Written, NOT run» (код написан и не запускался) и «Mirrors job()» (зеркало `job`, отличия перечислены под буквами (a)-(d)).
- «Windows-native is out of scope» (сообщение `OSError` в `run_cell`); «POSIX only (Linux, WSL2)».
- «Single worker; the child environment is inherited unchanged».
- Режим возобновления `_glr_records` (resume mode): личность модели восстанавливается из блока checkpoint в `result.json` самой ячейки, затем полная проверка откладывается агрегатору (комментарий в коде).
- Признанные остаточные окна: «Remaining window (milliseconds)» (сигнал до присвоения `proc`), «Remaining overshoot» (превышение стены); процессы-потомки с собственным `setsid` не обрабатываются.
- Метки, не входящие в экспорт (в коде они только как строки docstring и комментариев): `T058-S02`, `T063` (`A-3`, `A-5/A-6`), `S02c-1`, `D8`, `NB-1`, `W-2`, `W-3`, «W1b», «from the m1 directory», `slices.json`, «360-minute sum», префикс блоба `0119dfc5` (он совпадает с блобом экспортированного `experiment_io.py`). Документов с такими названиями в экспорте нет.

## 14. Что не установлено чтением

- Поведение при запуске: ничего не запускалось; ни одна команда, ни один тест не проверены.
- Что именно проверяет `experiment_results.verify_cell` и возвращает ли он `None` для ячейки, убитой по лимиту: docstring утверждает это про «_verify_cell», в этом документе с кодом `experiment_results.py` не сверялось (см. docs/05).
- Какую именно команду и какие выходные файлы задаёт план для ячейки (`experiments.py`, docs/05) и создаёт ли дочерний процесс `complete.json` так, как ожидает `_judge`.
- Совпадение с текстом `experiments.execute_suite` (цитата в комментарии `_judge`).
- Код завершения интерпретатора при необработанном исключении и при `KeyboardInterrupt`.
- Поведение `proc.wait(timeout=inf)` для библиотечных вызовов `run_cell` с бесконечным `cap_seconds` (CLI такие значения отвергает).
- Блокировка дочернего процесса на стандартном вводе (stdin наследуется).
- Поведение на системах без `/proc` и без POSIX-групп процессов (кроме явного отказа `OSError`).

**Замечания к коду (не исправлялись; определённой логической ошибки не установлено):**
1. Двойная загрузка модуля при `python -m driver.run_cell` (раздел 12).
2. `plan_io.mark_started` вызывается до проверки среза и имён `--param`: `execution_started.json` появляется и при последующем отказе (в docstring `train_unit.py` сказано, что после него `experiments execute` отвергается).
3. Не перехватываются в `main` (будет traceback): обычный `ValueError` из `load_plan`, `execution_guard`, `view.cell`; `OSError` из `ensure_traces` (в `traces.main` он перехватывается и даёт код 4); `OSError` непосикс-ветки `run_cell`.
4. Любой отказ (`CellRefused`, `TraceError`, `TrainRefused`) возвращает 4 сразу, даже с `--keep-going`, а накопленный `code` теряется.
5. `except BaseException` в `run_cell` записывает любое исключение внутри блока как `outcome="interrupted"`, не только сигнал.
6. `--cap-minutes` перекрывает лимиты ячеек из файла срезов для всех ячеек среза.
7. Список `names` для `incomplete` строится через `relative_to(view.root.resolve())`, а пути логов — от `view.root` без `resolve`: код полагается на каноничность `body["root"]` (для `discard_cell` есть защита `is_relative_to`).
8. Время создания трасс не ограничено `--cap-minutes`, но входит в стену и в журнал (`kind="trace"`).
9. Если исключение возникает при хешировании логов или записи `status.json` в нормальной ветке `_spawn_and_wait`, блок `except BaseException` его не ловит (эти действия стоят после `try`), и `status.json` может отсутствовать.

Расхождений между docstring и кодом в проверенных местах (коды выхода, порядок проверок `--wall-minutes`, `wall_reached`, `verify_after`) не найдено.

## 15. Охват и состав следующих документов

Описаны все: 2 класса (`CellRefused`, `TerminationSignal`); 19 функций уровня модуля (`terminate_as_exception`, `check_cap_minutes`, `exit_code_of`, `one_line`, `refuse_with`, `_glr_records`, `resume_verifier`, `cell_paths`, `classify`, `discard_cell`, `kill_tree`, `_spawn_and_wait`, `_judge`, `_record_interrupted`, `run_cell`, `_params`, `unknown_params`, `wall_option_problem`, `main`) и вложенная `handler`; 16 аргументов командной строки; константы `STATUS_SUFFIXES`, `EXIT_OK`, `EXIT_FAILED`, `EXIT_CAPPED`, `EXIT_REFUSED`, `DEFAULT_TRAIN_CAP_MINUTES`, `REFUSAL_ERRORS`; защита `if __name__ == "__main__"` (ручной подсчёт по тексту файла).

Поправки к A1-A4: A1-A3 называют четыре документа, фактически пять (A1-A5); в A1 (п. 2.4, пункт 5) «п. A4» означает раздел 6, шаг 10 документа A4; в A1 (раздел 1) порядок шагов «трассы, обучение, ячейки» уточнён в A4, раздел 6, шаги 13-14 (трассы, затем шаги среза в его порядке).

Остальные файлы драйвера описываются в следующих документах раздела docs/06: часть B — `train_unit.py`; часть C — `selector.py`, `plan_io.py`, `traces.py`, `__init__.py`; часть D — `finish.py`, `ledger.py`, четыре JSON-конфигурации и индекс docs/06 (он должен перечислить документы A1-A5).
