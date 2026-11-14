# 05. Эксперименты: `experiments.py` (часть A3: проверки, обучение, выполнение, ошибки, связи, списки)

Продолжение `05_EXPERIMENTS_RU_partA2.md`.

## 8. Основные функции: проверки, обучение, выполнение

### 8.1. `check_model(training_cfg, scenario_configs, expected_model_config=None)`
Проверка метаданных без тензоров. По порядку: `from_dict(training_cfg)`; `require_supported_model` (`02_ENVIRONMENT_RU.md`); при заданном `expected_model_config` и `cfg.model != expected` — `ValueError` (строгое равенство: чекпойнт одного режима признаков не подходит плану другого). Для каждого сценария: `asdict(cfg.orbit) == asdict(simulation.orbit)` (все поля орбиты, не только N и planes); при `cfg.model.uses_delay` — равенство `light_speed_km_s`; `phase_seed` не входит в сиды `train+val+test` чекпойнта. Возвращает `cfg`. Вывод из чтения: различие любого поля орбиты между шаблонами обучения и симуляции (высота, дальность и т. д.) отвергнет план без `--baselines-only`.

### 8.2. `preflight_models(plan)`
Если `"GLR"` нет в `body["policies"]` — возврат `{}`. Иначе (ленивый импорт `training.load_trained_model`) для каждого N из `body["models"]`: `load_trained_model(run, "cpu", expected)` (затем `del model`), `check_model(metadata["config"], конфигурации сценариев этого N, expected)`, сравнение `feature_spec`; запись `{run, checkpoint_sha256 (SHA-256 файла <run>/best.pt), training_config_sha256, training_revision, epoch, feature_spec}`. Вывод из чтения: проверяются все N серии, даже если `policy_scope` исключает `GLR` для части N.

### 8.3. `train_suite(plan, checkout_revision)`
1. `execution_guard`: ревизия равна `body["revision"]`, хеши всех `*.py` пакета равны `source_sha256`, иначе `ValueError` (часть B).
2. Выбор единиц с `supplied == False`.
3. Существует `run` или `data` любой из них — `FileExistsError` («partial runs cannot be resumed»).
4. Запись `training_started.json` (`plan_sha256`, `revision`; режим `"x"`, повторный запуск упадёт).
5. Для каждой единицы и шага — `job(root, id, command, plan)` (подпроцесс; ненулевой код — `RuntimeError`; журналы — часть B).
6. `training_complete.json` (`steps_finished`, `new_models`, `supplied_models_skipped`).
Возврат: `{"training_finished": True, "new_models": k}`. Возобновления нет; при сбое остаётся `training_started.json` без `training_complete.json`. Результат обучения проверяется только по коду выхода.

### 8.4. `execute_suite(plan, checkout_revision)`
1. `execution_guard`.
2. Любой из `execution_started.json`, `runs`, `traces`, `model_preflight.json` уже существует — `FileExistsError` («create a fresh plan»).
3. `preflight_models` → `model_preflight.json` → `execution_started.json`.
4. Ленивый импорт `traffic.make_trace`, `trace_document`; для каждого различного `trace_path` пишется `trace_document(make_trace(cfg), cfg)` самим процессом (`cfg` — по первому сценарию с этим путём).
5. Для каждой ячейки по порядку `body["cells"]`: `job(...)`; затем чтение `<out>/complete.json`: `simulation_finished is True` и `result_sha256 == digest(result.json)`, иначе `ValueError`; для нативной политики — `native_transport_check`.
6. Для нативной схемы — `execution_complete.json` (`schema = "ssn-native-experiment-transport-complete-v1"`, `transport_finished`, `runs`, `plan_sha256`, `aggregation_supported: False`, `plots_supported: False`, `scope`), возврат `{"transport_finished": True, "runs", "aggregation_supported": False}`. Иначе `execution_complete.json` = `{suite_finished: True, runs, plan_sha256}`, возврат `{"suite_finished": True, "runs": n}`.
Первая ошибка прерывает серию (исключения не ловятся), маркера завершения нет. Таймаута в `experiments.py` нет (`subprocess.run` — внутри `job`, часть B).

### 8.5. `aggregate` и `plot` в `main`
Обе ветки импортируют модуль лениво: `from .experiment_results import aggregate_plan`, `from .experiment_plots import plot_summary`. `aggregate` получает `load_plan(args.plan)` без `execution_guard` и ревизии. Содержание — части C и D.

## 9. Условия отказа (все — исключения, в `main` не перехватываются)
- Планирование: неверный suite/схема/сиды/сетки/варианты/`policy_scope` (раздел 4–5); `revision` не 40 hex; существующая `--out`; неверный `--models`; нативный план с `policy_scope`; нативный N больше `max_nodes`; `check_model` (8.1).
- `train`/`execute`: ревизия или хеши исходников не совпали (`execution_guard`); существующие пути (8.3, 8.4); неверный план (`load_plan`: хеш плана, перемещённый корень, хеши конфигураций); ненулевой код дочернего процесса; недействительная запись `complete.json`.
- Аргументы: `--tbr-*` без `--include-native-tbr`; не положительное целое.

## 10. Связи с другими модулями
Импортирует (в коде): `config` (`content_hash`, `from_dict`, `require_supported_model`), `sim_config` (`from_sim_dict`), `experiment_io` (`PLAN_SCHEMA`, `NATIVE_PLAN_SCHEMA`, `NATIVE_POLICY_NAME`, `digest`, `execution_guard`, `inside`, `job`, `load_plan`, `native_options`, `native_transport_check`, `read`, `revision`, `source_hashes`, `write`); лениво — `training.load_trained_model`, `traffic.make_trace`, `traffic.trace_document`, `experiment_results.aggregate_plan`, `experiment_plots.plot_summary`. Стандартная библиотека: `argparse`, `copy`, `dataclasses`, `json`, `math`, `pathlib`, `re`.
Его импортируют (по чтению экспортированных файлов): `experiment_io.py` (лениво, в `validate_native_plan`, `check_scoped_plan`: `CONTRACT`, `FEATURE_CONTRACT`, `POLICIES`, `merge`, `plan_commands`, `resolve_plan_inputs`, `validate_suite`) и `experiment_results.py` (лениво `check_model` в `verify_models`). Прочие импортёры не установлены чтением. Дочерние процессы: `python -m ssn_hops` (`cli.py`, `03_LEARNING_RU.md`) и `python -m ssn_hops.simulate` (`04_SIMULATION_POLICIES_RU_partB2.md`).

## 11. Побочные эффекты
- Файлы — по командам (A1, 2.3). Подпроцессы запускает только `train`/`execute` (через `job`, без оболочки; текущий каталог наследуется, значит пакет `ssn_hops` должен импортироваться из него — вывод из чтения).
- Случайность: `experiments.py` генераторов не использует; идентификаторы детерминированы (`content_hash`), меток времени в плане нет. Случайность — в дочерних процессах и `make_trace` по сидам конфигураций (`02_ENVIRONMENT_RU.md`).
- Глобального изменяемого состояния нет (`merge` копирует; `plan_commands` изменяет только записи `training`, добавляя `steps`).
- Ленивые импорты (список в разделе 10): команда `plan` не импортирует `torch` и `traffic` (вывод из чтения: `config`, `sim_config`, `experiment_io` используют только стандартную библиотеку); `execute` подгружает `traffic` и, при `GLR`, `training`.

## 12. Что в коде названо допущением или реконструкцией
- «RECONSTRUCTION sweeps; never authors' results» (`parser`); «Runtime status: not_run» (docstring).
- Комментарий о наборе входов: по умолчанию «topology-only (paper-faithful)», канал задержки — «optional extension» (над `FEATURE_CONTRACT`).
- Нативные пределы: «NOT recovered author settings» (`make_plan`), «independent safety bound» (справка `--tbr-max-*`).
- Комментарии кода содержат внутренние метки правок (номера задач и шагов); их расшифровка не входит в экспорт.

## 13. Что не установлено чтением
- Содержимое документов, названных в `CONTRACT`/`FEATURE_CONTRACT` (не входит в экспорт).
- Формат файла suite на практике (примеры — файлы `configs/` экспорта, вне этого документа).
- Поведение `job`, `load_plan`, `execution_guard`, `native_transport_check` — части B; `aggregate_plan` — часть C; `plot_summary` — часть D.
- Сигнатура и поведение `training.load_trained_model` кроме использованных ключей `config`, `config_sha256`, `revision`, `epoch` (`03_LEARNING_RU.md`).
- Кто, кроме `experiment_io.py`/`experiment_results.py`, импортирует модуль.
- Работоспособность модуля и время выполнения серии: ничего не запускалось.

## 14. Наблюдения о коде (не исправлялись)
1. `validate_suite`: `name(g["name"])` до проверки структуры (`KeyError`/`TypeError` вместо `ValueError`).
2. Обучающие единицы и шаги создаются для всех N даже при `--baselines-only` и для готовых моделей; `train` при `--baselines-only` обучил бы неготовые.
3. Команды `trace-<id>` в `offline_steps` не используются `execute_suite`.
4. `preflight_models` требует чекпойнт каждого N, даже если `policy_scope` убирает `GLR` для части N.
5. `execute_suite`: `complete["result_sha256"]` при отсутствии ключа даст `KeyError`.
6. `aggregate --reference GLR` для плана `--baselines-only` отвергнется только в `aggregate_plan` («reference policy was not planned»).
7. Пути шаблонов `suite_path.parent / ...` не проверяются на выход за папку (входные данные пользователя).

## 15. Документы группы 05
- `05_EXPERIMENTS_RU_partA1.md`, `partA2.md`, `partA3.md` — `experiments.py` (этот набор; сводный индекс — `05_EXPERIMENTS_RU.md`, дополнение — `05_EXPERIMENTS_RU_partE.md`).
- Поставляются: часть B — `partB1`-`partB3` (`experiment_io.py`); часть C — `partC1`-`partC5` (`experiment_results.py`); часть D — `partD1`-`partD4` (`experiment_plots.py`).
