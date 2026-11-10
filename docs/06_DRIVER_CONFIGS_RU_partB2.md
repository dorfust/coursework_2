# docs/06. Драйвер: driver/train_unit.py, часть B2 (из B1-B4)

Продолжение части B1 (`docs/06_DRIVER_CONFIGS_RU_partB1.md`). В B2: раздел 4, подразделы 4.1-4.13: исключение `TrainRefused` и вспомогательные функции файла `driver/train_unit.py` (пути единицы, проверка проекта, классификация состояния, удаление). Подразделы 4.14-4.16 (`run_train_unit`, `_record_interrupted_unit`, `exit_code_of`) и раздел 5 (`main`) находятся в B3.

Условные обозначения: `view` — объект `plan_io.PlanView` (прочитанный план: `view.body`, `view.root`, `view.sha256`, `view.revision`); `n` — размер N, десятичная строка; `item` — словарь `view.body["models"][N]`. Ключи `item` по `experiments.resolve_plan_inputs` и `plan_commands`: `config`, `config_sha256`, `feature_spec`, `config_path`, `supplied`, `run`, `data`, `steps` (шаги `data-nN`, `train-nN`, `evaluate-nN`, см. B1, раздел 1).

## 4. Основные классы и функции (часть 1)

### 4.1. Класс `TrainRefused(RuntimeError)`

Docstring: «Unit artifacts exist in an incomplete state (use discard), or the unit does not exist in the plan.» Исключение отказа: его бросают `model_item`, `evaluation_output`, `discard_unit` и `run_train_unit`; перехватывает `main` (печать `refused: <текст>`, код 4). В режиме `--slice` из `run_cell.main` (там он также входит в перехватываемый кортеж) — см. часть A4. Не входит в `run_cell.REFUSAL_ERRORS`: этот кортеж относится к загрузке плана и файла срезов.

### 4.2. `model_item(view, n)`

Возвращает `view.body["models"][str(n)]`. Бросает `TrainRefused`:
- если `"GLR"` нет в `view.body["policies"]`: «the plan has no GLR policy: no training is planned»;
- если `str(n)` не ключ `view.body["models"]`: «N={n} is not a planned model (planned: [...])», список — `sorted(view.body['models'])`, то есть сортировка строк.
Вывод из чтения: проверка GLR нужна потому, что `experiments.resolve_plan_inputs` строит словарь моделей `training` независимо от режима, а в режиме плана `baselines_only` политика GLR из `body["policies"]` исключена (`active = POLICIES[1:]`).

### 4.3. `evaluation_output(item)`

Возвращает `Path` значения, следующего за `--out` в команде первого шага, у которого `id` начинается с `evaluate-` и в `command` есть `--out`. Если такого шага нет: `TrainRefused("the plan has no evaluate step with --out")`. Docstring: путь `training/nN/test.json` в планах `make_plan`; в плане он абсолютный (`str(root / f"training/n{n}/test.json")`, `experiments.plan_commands`). Проверка на принадлежность корню здесь не делается (она есть в `discard_unit`).

### 4.4. `step_logs(view, step)`

Возвращает список из четырёх `Path`: `str(view.root / "logs" / step["id"])` плюс каждый суффикс из `run_cell.STATUS_SUFFIXES` = `(".started.json", ".stdout.txt", ".stderr.txt", ".status.json")`. Это файлы, которые создаёт `run_cell._spawn_and_wait` для шага (часть A3).

### 4.5. `evaluation_logs(view, item)`

Конкатенация `step_logs` для всех шагов, у которых `id` начинается с `evaluate-` (для плана `make_plan` это один шаг `evaluate-nN`, четыре файла: ручной расчёт 1 × 4 = 4).

### 4.6. `unit_paths(view, item)`

Возвращает кортеж из четырёх элементов: `Path(item["data"])`, `Path(item["run"])`, `evaluation_output(item)` и список всех файлов журнала всех шагов единицы (для трёх шагов плана — 12 путей, ручной расчёт 3 × 4). Это полный набор артефактов единицы, на котором основаны `classify`, `discard_unit` и `light_state`.

### 4.7. `project_check(view, n)`

«The project's own check for ONE model» (docstring): ленивый `from ssn_hops import experiments`, затем копия `body = dict(view.body)` (поверхностная), `body["models"]` заменяется словарём из единственного N, вызывается `experiments.preflight_models({"body": body})[str(n)]`. Нужен `torch` (в коде написано, docstring: «needs torch»; импорт `torch` происходит внутри `preflight_models` через `from .training import load_trained_model`).

Что делает `experiments.preflight_models` для одного N (чтение `experiments.py` и `training.py`; подробности docs/03 и docs/05): ожидаемая конфигурация модели берётся из `item["config"]`; `training.load_trained_model(item["run"], "cpu", expected)` проверяет в каталоге запуска: `complete.json` с `training_finished` равным `True`; `best.json` и формат чекпойнта; равенство sha256 файла `best.pt` значению `best_checkpoint_sha256`; загрузку `torch.load(..., weights_only=True)`; согласие конфигурации, манифеста данных, происхождения признаков и метаданных отбора; строгую загрузку весов (`strict=True`). Затем `check_model` сверяет орбиту/N/число плоскостей и фазовые сиды с конфигурациями сценариев плана этого N, а `item["feature_spec"]` сверяется со спецификацией признаков чекпойнта. Результат — запись `{run, checkpoint_sha256, training_config_sha256, training_revision, epoch, feature_spec}`; драйвер сам эту запись не использует, значим факт отсутствия исключения. При любой неполноте или несовпадении бросается исключение (ValueError, KeyError, FileNotFoundError и т. п.).

Вывод из чтения: проверка использует только каталог `run` (`best.pt`, `best.json`, `complete.json`, `config.json`, `dataset_manifest.json`, `provenance.json`) и конфигурации плана; каталог `data` и файл `test.json` она не читает.

### 4.8. `_readable(path)`

`True`, если `experiment_io.read(path)` (чтение и разбор JSON) завершился без исключения; при любом `Exception` — `False`. Проверяется только то, что файл открывается и разбирается как JSON; схема и содержимое не проверяются. Нужна для обнаружения оборванной записи `test.json` (в docstring метка F-5).

### 4.9. `light_state(view, n)`

«Cheap, torch-free state for status displays» (docstring): `'absent'`, `'complete'` или `'partial'`; docstring: «NOT the project's check».
- `'absent'`: ни один путь из `(data, run, test, *logs)` не существует;
- иначе читается `run/complete.json`, `finished = (поле training_finished is True)`; при любом исключении `finished = False`;
- `'complete'`, если `finished`, существует `run/best.pt` и `test.json` читается как JSON; иначе `'partial'`.
Хешей и конфигураций функция не проверяет. В файле `train_unit.py` функция не вызывается (в коде написано: нет вызова в `run_train_unit`, `main`; в прочитанных `run_cell.py`, `selector.py`, `plan_io.py`, `ledger.py` вызова нет). Вызывает ли её `finish.py` или `traces.py`, не установлено чтением в этом документе (эти файлы описываются в частях C и D).

### 4.10. `check_could_not_run(exc)`

Возвращает `True`, если исключение проверки означает «проверку нельзя выполнить», а не «запуск повреждён» (метка A-4 в docstring):
- `ImportError` (нет `torch` или другой зависимости) — всегда `True`;
- `OSError`, кроме `FileNotFoundError`, `NotADirectoryError`, `IsADirectoryError`, — `True` (проблемы ввода-вывода: `PermissionError`, `EIO`, `ENOSPC`);
- всё остальное — `False`.
В docstring названо отступление от буквальной формулировки «OSError»: три «ошибки раскладки» не считаются «проверка недоступна», потому что запуск, убитый до появления `best.pt`, заставляет загрузчик проекта бросить `FileNotFoundError`; иначе `--discard` был бы бесполезен именно для такого запуска.

### 4.11. `classify(view, n, check)`

Возвращает кортеж `(состояние, список существующих путей, текст ошибки или None)`. Порядок решений:
1. `present` = существующие среди `data, run, test, *logs`. Если пусто: `("absent", [], None)`.
2. Если `run` не существует (но что-то другое есть): `("incomplete", present, "run directory is absent but other artifacts of the unit exist")`.
3. Вызов `check(view, n)`. При исключении `exc`: если `check_could_not_run(exc)`, то `("check_unavailable", present, "<ТипИсключения>: <текст>")`, иначе `("incomplete", present, "<ТипИсключения>: <текст>")`. Ловится `Exception`, не `BaseException`.
4. Проверка прошла. Если `test.json` существует: читается как JSON — `("complete", present, None)`, иначе `("run_complete_bad_evaluation", present, "evaluate output exists but is not readable JSON")`. Если `test.json` нет: `("run_complete_no_evaluation", present, None)`.
Шесть состояний: `absent`, `incomplete`, `check_unavailable`, `complete`, `run_complete_bad_evaluation`, `run_complete_no_evaluation` (ручной расчёт: 6). Вывод из чтения: состояние `complete` не зависит от журнала `status.json` и от наличия каталога `data` (проверка проекта их не читает, п. 4.7). Параметр `check` в `run_train_unit` можно подменить (по умолчанию `project_check`).

### 4.12. `_inside_root(view, path)`

`Path(path).resolve().is_relative_to(view.root.resolve())`: лежит ли путь (после раскрытия ссылок) внутри корня плана. Используется в `discard_unit` и для имён в `run_train_unit`.

### 4.13. `discard_unit(view, n, only_evaluation=False)`

Удаляет артефакты единицы и возвращает список удалённых путей относительно `view.root.resolve()` (строки). Порядок:
1. `item = model_item(view, n)`; если `item.get("supplied")`: `TrainRefused("a supplied model is never discarded")`.
2. Цели: при `only_evaluation=True` — `[test, *evaluation_logs]`; иначе `[data, run, test, *logs]` (в этом порядке).
3. Для каждой цели: если путь вне корня — `TrainRefused("refusing to delete outside the plan root: <путь>")`; каталог удаляется `shutil.rmtree`, файл — `unlink()`; несуществующий путь пропускается.
Проверка корня делается непосредственно перед удалением каждой цели, поэтому при отказе на более поздней цели более ранние уже удалены (вывод из чтения). Для моделей, построенных `make_plan`, все пути лежат под `<root>/training/nN/` и `<root>/logs/` (вывод из чтения по `experiments.resolve_plan_inputs`, `plan_commands`); `load_plan` пути `models[N].data/run` отдельно не проверяет (вывод из чтения по `experiment_io.validate_plan`). Режим «только оценка» не трогает `data`, `run`, а также журналы шагов `data-nN` и `train-nN`.

Продолжение: B3 (4.14-4.16 и раздел 5), B4 (разделы 6-14).
