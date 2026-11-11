# docs/06. Драйвер: driver/finish.py, часть D1 (из D1-D3)

В этом документе описан `driver/finish.py` (13591 байт) целиком. Продолжение: `06_DRIVER_CONFIGS_RU_partD2.md` (`ledger.py`, `suite_m1b_cgr.json`) и `06_DRIVER_CONFIGS_RU_partD3.md` (`n132.json`, `simulation_n132.json`, `slices_m1b_cgr.json`); указатель всего раздела — `06_DRIVER_CONFIGS_RU.md`. Метки: «в коде написано» — содержимое кода; «вывод из чтения» — следствие чтения; «ручной расчёт» — арифметика с показом. Ничего не запускалось: утверждений о работоспособности и результатах нет.

## 1. Назначение

В коде написано (первая строка docstring): «finish: model_preflight.json and the completion marker execution_complete.json, plus a read-only check. Written, NOT run.» Модуль завершает корень плана, который выполнялся по частям драйвером (`run_cell.py`, `train_unit.py`), и пишет два файла: `model_preflight.json` и `execution_complete.json`. Третий режим, `check`, ничего не пишет. Вывод из чтения: эти два файла в обычном потоке создаёт `experiments.execute_suite` (по описанию `experiments.py` в docs/05, часть A1, раздел 2.3, команда `execute` пишет `model_preflight.json` и `execution_complete.json`); `finish.py` воспроизводит их для корня, выполненного драйвером по срезам. В docstring названы зеркалируемые функции: `experiments.execute_suite`, `experiments.preflight_models`, `experiment_results.verify_models`, `verify_cell`, `aggregate_plan` (метки «blob 72b6fa02» и «blob ba5576ef» — документы и сборки вне экспорта).

Частичный и полный план. В коде написано: маркер пишется «ТОЛЬКО когда каждая ОБЪЯВЛЕННАЯ ячейка проверена `experiment_results.verify_cell`, никогда для частичного набора» (docstring; числа 147 для `suite_m1` и 135 для `suite_m1_nocgr` относятся к наборам, которых в экспорте нет). В `do_marker` для этого есть отказ: «no marker for a partial set». Для экспортированной серии объявленных ячеек, по ручному расчёту (описание в `partD2`, раздел о `suite_m1b_cgr.json`), 162; код сам берёт `len(body["cells"])`. Что агрегатор делает без маркера, видно только из docstring (маркер имеет «the form aggregate_plan checks») и из заметки `configs/slices_m1b_cgr.json` (без маркера агрегирование требует `allow_partial=yes`); сам `aggregate_plan` в этом документе не перечитывался (см. docs/05, часть C).

## 2. Входы и выходы, командная строка

Команды (docstring; рабочий каталог в нём назван «the m1 directory», в экспорте ему соответствует `CODE_EXPORT`, вывод из чтения):

```
python -m driver.finish preflight --plan <root>/plan.json --revision <sha>
python -m driver.finish marker    --plan <root>/plan.json --revision <sha>
python -m driver.finish check     --plan <root>/plan.json [--revision <sha>] [--deep]
```

Охрана точки входа: `if __name__ == "__main__": sys.exit(main())`. Аргументы `main` (5, ручной счёт): позиционный `mode` (`choices` = `preflight`, `marker`, `check`); `--plan` (обязателен); `--revision` (по умолчанию нет); `--plan-sha256` (по умолчанию нет); `--deep` (флаг, по умолчанию выключен; справка: «check: also load the models (needs torch)»).

Коды выхода (константы): `EXIT_OK = 0`, `EXIT_NOT_READY = 3`, `EXIT_REFUSED = 4`, `EXIT_POSTCHECK = 5`. Docstring: 0 — успех, «already done» или печать отчёта; 3 — предусловие не выполнено; 4 — конфликт, проблема файловой системы или использование; 5 — не прошла послепроверка. Имена файлов: `PREFLIGHT = "model_preflight.json"`, `MARKER = "execution_complete.json"` (оба пишутся в `view.root`, корень плана).

Что читается: `plan.json` (через `plan_io`), для каждой модели `<run>/complete.json` и `<run>/best.pt`, модели целиком (только `preflight` и `check --deep`, нужен `torch`), записи ячеек `runs/<id>/...` (через `verify_cell` или `run_cell.resume_verifier`). Что пишется: только два файла выше; на stdout — одна строка JSON (`preflight`, `marker`) или отчёт JSON с отступом 1 (`check`).

## 3. Классы

Все четыре — подклассы `RuntimeError`:
- `FinishRefused`: предусловие не выполнено, ничего не записано (код 3, строка `not ready: ...`).
- `FinishConflict`: целевой файл существует с другим содержимым или нечитаем; никогда не перезаписывается (код 4, `refused: ...`).
- `FinishIOError(FinishConflict)`: проблема файловой системы при создании файла (остаточный временный файл, ошибка записи, нет жёстких ссылок); код 4.
- `PostCheckFailed`: собственная проверка агрегатора отвергла только что созданное (код 5, `post-check failed: ...`).

## 4. Функции (13, ручной счёт)

**`create_exact(path, content)`** возвращает `"written"` или `"already_done"`. `wanted = json.loads(json.dumps(content, sort_keys=True, allow_nan=False))` (NaN запрещён). Если файл есть: `eio.read(path)`; исключение чтения даёт `FinishConflict("... exists and is unreadable ...; not touching it")`; равенство значений — `already_done`; иначе `FinishConflict("... exists with different content; refusing to overwrite")`. Если файла нет: временный файл `<имя>.tmp<pid>` в том же каталоге, `eio.write(temp, wanted)`; `FileExistsError` — `FinishIOError` («stale temp file ...»; удалить вручную, убедиться, что другой вызов `finish` не идёт); другая `OSError` — временный файл удаляется (`missing_ok=True`) и `FinishIOError`. Затем `os.link(temp, path)`: `FileExistsError` (гонка) — рекурсивный вызов `create_exact` для сравнения с победившим файлом; другая `OSError` — `FinishIOError` («the work directory must be on a file system that supports hard links»); в `finally` временный файл удаляется. Устаревший временный файл этим инструментом не удаляется (docstring). Вывод из чтения: окончательное имя не получает недописанного файла и не заменяется (жёсткая ссылка не перезаписывает).

**`models_light(view)`** — дешёвый просмотр без `torch`: для каждого элемента `view.body["models"]` (включая подданные `--models`, чтение) читает `<run>/complete.json`, значение `training_finished is True` (любое исключение — ложь) и наличие `best.pt`. Возвращает `(список N-строк с полным обучением, {N: "run is not complete (complete.json/best.pt missing)"})`. Это не проверка проекта (docstring: «NOT the project's check»).

**`diagnose_models(view)`** (лениво импортирует `ssn_hops.experiments`): для каждой модели вызывает `experiments.preflight_models` на копии тела с одной моделью; результат `{N: "ok"}` или `{N: "<Тип>: <текст>"}`. Нужна только для сообщения об ошибке.

**`compute_preflight(view)`**: `experiments.preflight_models(view.plan)` — функция проекта вызывается, не копируется; любое исключение превращается в `FinishRefused("preflight_models failed (...); per model: {diagnose_models(view)}")`.

**`preflight_document(view, models)`** = `{"plan_sha256": view.plan["sha256"], "models": models}`. **`marker_document(view)`** = `{"suite_finished": True, "runs": len(view.body["cells"]), "plan_sha256": view.plan["sha256"]}`.

**`_legacy_only(view)`**: если `view.plan["schema"] != eio.PLAN_SCHEMA` (строка `ssn-experiment-plan-v2`, docs/05, часть A1, раздел 3), то `FinishRefused("only legacy ssn-experiment-plan-v2 suite plans are supported (native plans refused)")`.

**`do_preflight(view)`**: (1) `_legacy_only`; (2) `models_light`: если есть неполные, `FinishRefused("preflight needs ALL trained models of the plan; not complete: {...}")`; (3) `compute_preflight`; (4) `create_exact(root/PREFLIGHT, preflight_document(...))`; (5) послепроверка `experiment_results.verify_models(view.plan)`: при исключении файл, записанный ЭТИМ вызовом (`status == "written"`), удаляется (`target.unlink()`), затем `PostCheckFailed("verify_models rejected the preflight (...)" + "; the file written by this call was removed")`. Результат: `{"mode": "preflight", "status": ..., "path": ..., "models": sorted(models)}` (сортируются ключи; строки, лексикографически, вывод из чтения).

Продолжение (`verify_cells`, `do_marker`, `_file_state`, `check_report`, `main`), значения по умолчанию, связи, побочные эффекты и непроверенное — в разделах 5-10 этого же файла ниже.

## 5. `verify_cells(view, strict)`

Возвращает `(проверенные id, отсутствующие id, {id: текст ошибки})`. `strict=True`: сначала `records = experiment_results.verify_models(view.plan)` (вне цикла, исключение не перехватывается здесь), затем для каждой ячейки `experiment_results.verify_cell(view.plan, cell, view.scenario_of(cell), records)` — проверка самого агрегатора. `strict=False` (нет годного `model_preflight.json`): `run_cell.resume_verifier(view, cell)` (в docstring: «W1a, weaker for GLR cells»; для GLR личность модели восстанавливается из `result.json` ячейки, см. docs/06 partA2). Исключение на одной ячейке даёт её id в списке отсутствующих и текст `<Тип>: <текст>` в словаре ошибок; результат `None` — тоже «отсутствует».

## 6. `do_marker(view)`

(1) `_legacy_only`; (2) если `"GLR"` входит в `view.body["policies"]` и файла `model_preflight.json` нет — `FinishRefused("model_preflight.json is missing: run `finish preflight` first")` (проверяется только наличие; годность проверяет `verify_models` ниже); (3) `verify_cells(view, strict=True)`; исключение (то есть сбой `verify_models`) — `FinishRefused("verify_models failed (...)")`; (4) если есть непроверенные ячейки — `FinishRefused` с числом `<k> of <N> declared cells are not verified (no marker for a partial set); first: {первые 5 id: ошибка}`; (5) `create_exact(root/MARKER, marker_document(view))`. Результат: `{"mode": "marker", "status", "path", "runs": len(view.cells)}`.

## 7. `_file_state` и `check_report`

`_file_state(path, expected)`: нет файла — `{"present": False, "matches": None}`; иначе `{"present": True, "matches": <чтение == expected>}`; при исключении чтения `matches` ложно и добавлено поле `error`.

`check_report(view, deep=False, cell_result=None)` — только чтение. Ключи отчёта: `plan_sha256` (`view.sha256`), `declared_cells`, `models_complete_light`, `models_missing`, `preflight_check_level` (`"deep"` при `--deep`, иначе `"light"`), `model_preflight` (`present`, `valid`; при ошибке `error`; при `--deep` и существующем файле `matches_recomputed` — совпадение с заново вычисленным), `preflight_deep_error` (только если глубокий расчёт не удался), `preflight_would_succeed`, `cells_verified`, `cells_missing`, `cells_verification` (`"strict (verify_cell)"` или `"resume (no valid model_preflight.json)"`), `first_missing` (первые 5), `first_errors` (первые 3), `marker` (`_file_state`), `marker_would_succeed`.

Правила (в коде написано): глубокий расчёт `compute_preflight` выполняется, только если нет неполных моделей и задан `--deep`; `valid` вычисляется через `verify_models`, если файл есть; `preflight_would_succeed = (нет неполных моделей и нет preflight_deep_error) или valid`; `strict = valid или GLR нет в политиках`; `marker_would_succeed = strict и нет отсутствующих ячеек и схема == PLAN_SCHEMA`. Вывод из чтения: на лёгком уровне `preflight_would_succeed` лишь говорит, что у каждой модели есть `complete.json` и `best.pt`; в нём не учитывается проверка схемы (`_legacy_only`), а в `marker_would_succeed` она учитывается.

## 8. `main(argv=None)`

Порядок: разбор аргументов; для `preflight` и `marker` без `--revision` печать `refused: --revision is required for preflight and marker` и код 4 (до загрузки плана); загрузка плана: с `--revision` — `plan_io.load_for_execution(plan, revision, expected_plan_sha256=--plan-sha256)` (привязка корня, ревизии, хешей исходников и `execution_guard`, docs/06 partC3), без него — `plan_io.load_readonly(plan)`; любое исключение — `refused: <Тип>: <текст>` на stdout, код 4. Затем `check` печатает `json.dumps(check_report(view, deep), indent=1, sort_keys=True)` и возвращает 0; иначе вызывается `do_preflight` или `do_marker`, результат печатается `json.dumps(result, sort_keys=True)`. Перехватываются `FinishRefused` (3), `FinishConflict` (4, включая `FinishIOError`), `PostCheckFailed` (5); прочие исключения не перехватываются.

## 9. Значения по умолчанию, связи, побочные эффекты

Значений по умолчанию, кроме `--deep=False`, нет; `--revision` нужна для записывающих режимов, её формат (40 строчных hex) проверяет `experiment_io.revision` позже, в `load_for_execution`. Импорты верхнего уровня: `argparse`, `json`, `os`, `pathlib.Path`, `sys`, `from ssn_hops import experiment_io as eio`, `from . import plan_io, run_cell`. Лениво: `ssn_hops.experiments` (`diagnose_models`, `compute_preflight`), `ssn_hops.experiment_results` (`do_preflight`, `verify_cells`, `check_report`). `finish.py` использует `plan_io.load_for_execution` и `load_readonly`, не вызывает `mark_started` (ни одна из команд не создаёт `execution_started.json`), и берёт из `run_cell` только `resume_verifier`. Обратно `run_cell.py` и `train_unit.py` модуль `finish` не импортируют; `run_cell._glr_records` лишь называет в комментарии команду `finish preflight`. Побочные эффекты: временные файлы и жёсткие ссылки, два файла маркеров, удаление `model_preflight.json` при неудачной послепроверке (только созданного этим вызовом), загрузка моделей через `torch` (`preflight`, `check --deep`), чтение всех объявленных ячеек. Случайности нет.

`light_state`: в `finish.py` имя не определено и не используется (файл прочитан целиком); есть только `models_light` и значение `"light"` ключа `preflight_check_level` — другие имена. В `ledger.py` имя тоже не встречается.

## 10. Допущения, непроверенное, замечания

Названо в коде: «Written, NOT run.»; «Legacy plan schema only (native plans refused)»; метки «W1a» и «blob ...» — вне экспорта. Не установлено чтением: что именно проверяют `preflight_models`, `verify_models`, `verify_cell` и `aggregate_plan` (docs/05, части A3, C); поведение `os.link` на конкретных файловых системах; фактический вид `plan.json`; запуск любой команды.

Замечания (не исправлялись, определённой логической ошибки не установлено): (1) в docstring код 4 назван и для «usage», но ошибки `argparse` завершают процесс стандартным кодом 2 (общее свойство библиотеки); (2) при `check` без `--revision` значение `--plan-sha256` не используется; (3) `verify_models` в `verify_cells` стоит вне `try`: в `check_report` его исключение не перехватывается (в `do_marker` перехватывается); (4) `do_preflight` и `models_light` учитывают все записи `body["models"]`, включая подставленные через `--models`; (5) `check` с `--revision` выполняет полную привязку (корень, хеши исходников), без него — только `load_readonly`.
