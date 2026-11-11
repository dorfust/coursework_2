# docs/06, часть C4: driver/traces.py, driver/__init__.py; сводка и поправки к частям C1-C3

Четвёртая часть серии C. Как run_cell.py вызывает ensure_traces и связанные функции, описано в частях A; здесь описан сам traces.py. Условные обозначения: «в коде написано», «вывод из чтения», «ручной расчёт». Ничего не запускалось.

# Раздел 1. driver/traces.py

## 1.1 Назначение

Первая строка docstring: «Trace production for a slice: what execute_suite does in-process, resumable. Written, NOT run.» Модуль создаёт или проверяет файлы трасс трафика (trace documents), которые нужны ячейкам среза. В docstring сказано: для каждого различного scenario['trace_path'], взятого из ПЕРВОГО сценария плана, который его несёт (как это делает множество seen в experiments.execute_suite), выполняется write(inside(root, trace_path), trace_document(make_trace(cfg), cfg)), где cfg = from_sim_dict(scenario['config']). Офлайн-шаг плана 'trace-<scenario>' (команда simulate trace) НЕ используется: в docstring написано, что execute_suite его не запускает. Описание команды trace в simulate.py: docs/04 часть B2; описание make_trace и trace_document: docs/02 часть 7 (traffic.py). Совпадает ли файл, который пишет simulate trace, с файлом этого модуля, в этом документе не сверялось.

Импорты верхнего уровня: argparse, os, sys, time, ssn_hops.experiment_io (eio) и from .ledger import utc_now (относительный импорт: нужен пакетный контекст). Импорты ssn_hops.sim_config и ssn_hops.traffic выполняются лениво внутри default_make.

## 1.2 Входы и выходы, командная строка

Запуск (docstring, «from the m1 directory»): python -m driver.traces --plan <root>/plan.json --revision <sha> --ledger L.jsonl --slices slices.json --slice ID. Охрана точки входа: if __name__ == "__main__": sys.exit(main()).

Аргументы main (описание «produce the traces a slice needs (user-invoked)»), 7 штук (ручной расчёт):
- --plan (required), --revision (required), --ledger (required), --slices (required), --slice (dest slice_id, required): значений по умолчанию нет. Требование --slices: он обязателен, и без него argparse завершает работу ошибкой использования.
- --env-label (необязателен, по умолчанию None): метка среды, передаётся в describe_environment (ledger.py, часть D).
- --discard (флаг, по умолчанию выключен): разрешает удалить и перезаписать существующую трассу, которая отличается от регенерированной.

Положение в экспорте (вывод из чтения, не проверенная команда): рабочий каталог CODE_EXPORT, PYTHONPATH включает src, аргумент --slices configs/slices_m1b_cgr.json (путь по умолчанию в этом файле отсутствует), --revision это 40 строчных hex-символов ревизии, записанной в плане, --plan <root>/plan.json (файла в экспорте нет, см. часть C3).

Коды возврата main: 0 после печати строк результата; 4 при OSError из ensure_traces (печатается одна строка «refused: <тип>: <текст>» в стандартный вывод, не в stderr). Остальные исключения (BindingError, SelectorError, TraceError, KeyError неизвестного id среза) не перехватываются: трассировка, код 1 по умолчанию Python (вывод из чтения).

## 1.3 Основные классы и функции

**TraceError(RuntimeError)**: «An existing trace file does not match the regenerated trace.»

**default_make(config)**: лениво импортирует from_sim_dict (ssn_hops.sim_config) и make_trace, trace_document (ssn_hops.traffic); cfg = from_sim_dict(config); возвращает trace_document(make_trace(cfg), cfg). По traffic.py: make_trace вызывает cfg.validate(), создаёт random.Random(cfg.traffic_seed) и для каждого tick в range(0, stop, step) создаёт запись (packet_id, created_tick, source, destination, size_bytes); trace_document возвращает словарь с ключами schema = "ssn-traffic-v1", trace_key, records, sha256 (content_hash тела). Вывод из чтения: документ определяется только конфигурацией сценария.

**_record_interrupted_trace(ledger, item_id, slice_id, counted, stamp, t0, exc)**: пытается записать в леджер событие finish (kind "trace") с started_utc = stamp, finished_utc = utc_now(), elapsed_s = time.monotonic() - t0, exit_code = None, outcome = "interrupted", exception = "<тип>: <текст>". Если запись в леджер не удалась, печатает в stderr предупреждение «warning: the ledger finish event of the interrupted trace <id> could not be written: ...» и ничего не поднимает.

**ensure_traces(view, trace_paths, *, ledger=None, slice_id=None, counted=True, discard=False, make=None)**: возвращает список словарей {'path', 'status': 'written' | 'verified', 'elapsed_s'}. Параметр make (по умолчанию default_make) принимает конфигурацию-словарь и возвращает документ; это точка подмены для тестов (вывод из чтения). Для каждого пути по порядку:
1. owner = view.trace_owner_by_path[trace_path] (KeyError для неизвестного пути); item_id = "trace-" + owner["id"]; target = eio.inside(view.root, trace_path) (ValueError, если путь абсолютный, содержит «..» или выходит за корень).
2. Если target существует: same = (eio.read(target) == make(owner["config"])), любое исключение при этом даёт same = False. Если same: при наличии леджера событие skipped (kind "trace", reason "verified_existing", elapsed_s 0.0, с slice_id и counted), результат status "verified", elapsed_s 0.0, переход к следующему пути. Если не same и discard выключен: TraceError «<путь> exists but differs from the regenerated trace (or is unreadable); refusing to overwrite; pass discard to delete and rewrite». Если discard включён: target.unlink().
3. Событие start (started_utc = метка времени) в леджер, если он задан.
4. Внутри try: document = make(owner["config"]); temp = target.with_name(target.name + f".tmp{os.getpid()}"); eio.write(temp, document) (режим "x", родительские каталоги создаются); os.link(temp, target); в finally temp.unlink(); elapsed = time.monotonic() - t0; событие finish (exit_code 0, outcome "ok"); recorded = True.
5. except (KeyboardInterrupt, SystemExit): если леджер есть и recorded ложно, вызывается _record_interrupted_trace; исключение поднимается дальше. Другие исключения не записываются как события (docstring: «Other exceptions are not recorded as events»).
6. Результат status "written" с измеренным elapsed_s.

**main(argv=None)**: порядок: plan_io.load_for_execution(--plan, --revision) (полная привязка и execution_guard, часть C3); plan_io.mark_started(view) (создаёт execution_started.json, если его нет); selector.resolve_all(view, selector.load_slices(--slices))[--slice] (привязка к набору, часть C2); Ledger(--ledger, plan_sha256=view.sha256, revision=view.revision, source_sha256=view.source_hash, environment=describe_environment(--env-label)); ensure_traces(view, resolved["trace_paths"], ledger=..., slice_id=..., counted=resolved["counted"], discard=--discard). Затем печать каждой строки результата командой print(row) (представление словаря Python, не JSON) и возврат 0. Всего в файле 1 класс и 4 функции (ручной расчёт: default_make, _record_interrupted_trace, ensure_traces, main).

## 1.4 Куда пишется, схемы и имена

Файл трассы пишется по eio.inside(view.root, trace_path), где trace_path это относительный путь из сценария плана; конкретные имена задаёт experiments.py при построении плана (docs/05), в traces.py они не заданы. Временный файл: <имя файла трассы>.tmp<pid> в том же каталоге (ручной пример: x.json и pid 1234 дают x.json.tmp1234). Жёсткая ссылка os.link создаёт окончательное имя; существующий файл не заменяется (os.link не перезаписывает: FileExistsError). Вывод из чтения: недописанный файл под окончательным именем появиться не может, но неудачная запись может оставить временный файл.

Строки схем: документ трассы "ssn-traffic-v1" (traffic.trace_document); строки леджера содержат "ssn-m1-ledger-v1" (ledger.LEDGER_SCHEMA, добавляется Ledger.record; часть D). События леджера этого файла: start, finish, skipped, все kind "trace" с id "trace-<id сценария-владельца>". Вывод из чтения: finish входит в ELAPSED_EVENTS леджера и потому учитывается в минутах, skipped нет.

Повторное использование: существующая трасса принимается, только если разобранный JSON равен регенерированному документу (включая sha256). Это сравнение значений, а не текста файла.

## 1.5 Побочные эффекты, связи

Пишет файлы трасс, временные файлы, строки леджера, execution_started.json (через mark_started в main); случайность только внутри make_trace (random.Random(cfg.traffic_seed)). Вызывается из run_cell.py (ensure_traces, часть A) и из собственного main. Использует plan_io, selector, ledger, experiment_io, sim_config, traffic.

## 1.6 light_state

В traces.py, selector.py, plan_io.py, __init__.py и finish.py имя light_state не определено и не используется (все пять файлов прочитаны полностью; в finish.py есть функция models_light и ключ preflight_check_level со значением 'light': это другие имена). В ledger.py оно тоже не встречается (прочитан). Определение light_state есть в train_unit.py (часть B2). Поиск по репозиторию вернул неполные результаты, поэтому отсутствие вызовов в run_cell.py этим документом не установлено.

## 1.7 Допущения, не установлено, наблюдения

В коде как «mirror» названо отношение к experiments.execute_suite (docstring). Внутренние метки docstring (T063 A-2, T065-A01-S02 и blob 72b6fa02) и ссылка на execute_suite не входят в экспорт как документы. Не установлено: совпадение с файлом simulate trace; имена файлов трасс. Наблюдения (не исправлялись): (1) проверка существующей трассы регенерирует её целиком, а отчёт даёт elapsed_s 0.0; (2) TraceError в main не перехватывается; (3) mark_started выполняется до проверки среза; (4) при --discard старый файл удаляется до события start, и при отказе make он теряется; (5) при ошибке записи (не FileExistsError) временный файл остаётся; (6) «refused» печатается в stdout. Определённой логической ошибки чтением не установлено.

# Раздел 2. driver/__init__.py

В коде написано: единственная строка docstring «M1 execution driver (T058 W1a). Written, NOT run. Imports project interfaces only.» (метка T058 W1a не входит в экспорт). Кода, констант и импортов нет (ручной расчёт: 88 символов строки плюс перевод строки дают 89 B). Роль (вывод из чтения): обозначает каталог driver как пакет, поэтому работают запуск python -m driver.<модуль> и относительные импорты вида from . import plan_io. Не установлено чтением: ничего, кроме сказанного.

# Раздел 3. Сводка серии C и поправки

Описано полностью: selector.py (1 класс, 11 функций, 3 аргумента командной строки, 3 константы); plan_io.py (2 класса, 5 функций модуля, у PlanView __init__, 7 методов и 1 свойство; командной строки нет); traces.py (1 класс, 4 функции, 7 аргументов); __init__.py. Поправки к части C3: (а) в разделе 3 фраза «8 методов и 1 свойство» ошибочна, верно: 7 методов, 1 свойство и __init__; (б) в разделе 8 вызывающие функций plan_io уточняются: traces.py использует load_for_execution и mark_started; finish.py использует load_for_execution и load_readonly и не вызывает mark_started; selector.main использует load_readonly.

Планируемая часть D: finish.py, ledger.py, четыре JSON-конфигурации и указатель docs/06 (A1-A5, B1-B4, C1-C4, D).

## Не установлено чтением (сводка серии C)
Точные имена файлов трасс; использование cap_seconds вызывающими файлами; вызовы check_partition вне selector.py; вызовы light_state из run_cell.py; совпадение трассы с simulate trace; содержимое настоящего plan.json.
