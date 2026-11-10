# 05. Эксперименты: `experiments.py` (часть A1: назначение, команды, файлы, константы)

В этом документе описан один модуль: `src/ssn_hops/experiments.py` (29810 байт). Продолжение: `05_EXPERIMENTS_RU_partA2.md` (серия, сценарии, обучающие единицы, ячейки, план) и `05_EXPERIMENTS_RU_partA3.md` (проверка моделей, обучение, выполнение, ошибки, связи, списки). Модули `experiment_io.py`, `experiment_results.py`, `experiment_plots.py` описываются в отдельных документах группы 05 (части B, C, D); здесь указано лишь, как `experiments.py` их вызывает. Конфигурация, симулятор, политики и обучение описаны в `02_ENVIRONMENT_RU.md`, `03_LEARNING_RU.md`, `04_SIMULATION_POLICIES_RU.md` и не повторяются.

Метки: «в коде написано» — содержимое кода; «вывод из чтения» — следствие чтения; «ручной расчёт» — арифметика с показом. Ничего не запускалось: утверждений о работоспособности и результатах нет.

## 1. Назначение

В коде написано (docstring модуля): «Offline plans and USER-invoked sequential execution. Runtime status: not_run.»; описание парсера (`parser`): «RECONSTRUCTION sweeps; never authors' results».

Вывод из чтения: модуль — оркестратор серии симуляций. Он читает файл серии (suite), офлайн строит ПЛАН (`plan.json`: конфигурации и точные команды дочерних процессов), по вызову пользователя последовательно запускает обучение и симуляции дочерними процессами и передаёт сохранённые прогоны на агрегирование и построение графиков. Сам `experiments.py` метрик не считает, не рисует и не обучает.

Термины (по именам и структурам кода, вывод из чтения):
- ПЛАН — документ `plan.json`: `{schema, body, sha256}`; связывает серию, ревизию, хеши исходников и конфигураций, размеры N, тройки сидов, политики, вероятности отказа, команды (подробно в A2, раздел 7).
- СЦЕНАРИЙ — одна разрешённая `SimulationConfig` (N, вероятность отказа, вариант чувствительности, тройка сидов); id `s-<16 hex>`.
- ЯЧЕЙКА (cell) — один сценарий для одной политики: один вызов `python -m ssn_hops.simulate run ...`; id `<id сценария>--<политика>`.
- ОБУЧАЮЩАЯ ЕДИНИЦА — запись `body["models"][str(N)]`: на каждый N серии конфигурация обучения и три шага `data-n<N>`, `train-n<N>`, `evaluate-n<N>`.

## 2. Входы и выходы

### 2.1. Команды

Запуск (в коде `main` и блок `if __name__ == "__main__"`): `python -m ssn_hops.experiments <команда> ...`; подкоманда обязательна (`add_subparsers(dest="command", required=True)`). `ssn_hops/__init__.py` содержит только docstring и `__version__ = "0.1.0"`: импорт пакета ничего не подгружает.

| Команда | Аргументы | Вызов |
|---|---|---|
| `plan` | `--suite`, `--out`, `--revision` (все обязательны); `--models`; `--baselines-only`; `--include-native-tbr`; `--tbr-max-nodes`; `--tbr-max-expansions` | `make_plan` |
| `train` | `--plan`, `--revision` (обязательны) | `train_suite(load_plan(...), revision)` |
| `execute` | `--plan`, `--revision` (обязательны) | `execute_suite(load_plan(...), revision)` |
| `aggregate` | `--plan`, `--out` (обязательны); `--allow-partial`; `--reference` | `experiment_results.aggregate_plan(load_plan(...), out, allow_partial, reference)` |
| `plot` | `--summary`, `--out` (обязательны); `--allow-partial` | `experiment_plots.plot_summary(summary, out, allow_partial)` |

Подробности аргументов:
- `--revision`: ровно 40 строчных шестнадцатеричных символов (`experiment_io.revision`); для `train`/`execute` обязано совпасть с ревизией в плане.
- `--models`: JSON «строка N -> путь к готовому запуску обучения»; читается `experiment_io.read`.
- `--tbr-max-nodes`, `--tbr-max-expansions`: тип `positive_cli_budget` (ASCII-цифры, значение > 0, иначе `argparse.ArgumentTypeError`), по умолчанию `None`; справка называет значения 12 и 100000, применяются они в `experiment_io.native_options` (`12 if max_nodes is None`, `100000 if max_expansions is None`). Без `--include-native-tbr` любой из них — `ValueError` («TBR budgets require explicit native opt-in»).
- `--baselines-only`: из плана исключается `GLR`, обученные модели не проверяются.
- `--include-native-tbr`: добавляет политику `TBR_bounded_exhaustive_reference` (справка: «opt-in bounded exhaustive transport ONLY»); сама политика — `04_SIMULATION_POLICIES_RU_partB1.md`.
- `--reference` (`aggregate`): `choices = POLICIES + (NATIVE_POLICY_NAME,)`, по умолчанию `"TBR_style_hop_oracle"`; `--allow-partial` (`aggregate`, `plot`) передаётся флагом; смысл — части C и D.

Результат любой команды — словарь, который `main` печатает как `json.dumps(result, indent=2, sort_keys=True, allow_nan=False)`. Исключения в `main` не перехватываются (вывод из чтения: ошибка проверки даёт трассировку Python и ненулевой код выхода).

### 2.2. Предполагаемый порядок (вывод из чтения)

1. `plan` — офлайн, один раз; создаёт новую папку плана.
2. `train` — нужна, если в плане есть `GLR` и модели для каких-то N не переданы через `--models`.
3. `execute` — строит трассы и запускает все ячейки; при `GLR` сначала проверяет все чекпойнты.
4. `aggregate` — проверяет сохранённые прогоны, пишет сводку.
5. `plot` — рисует по сводке.
Код не требует `train` перед `execute`: `training_complete.json` не проверяется; отсутствие чекпойнта обнаружит `preflight_models`.

### 2.3. Какие файлы читает и пишет каждая команда

Пути относительно корня плана `<root>` (абсолютный путь `--out` команды `plan`).
- `plan` читает: suite; шаблоны, названные в нём (`core_template`, `simulation_template`, пути от папки файла suite); `--models`; `*.py` пакета (для хешей). Пишет: `<root>/plan.json`, `<root>/configs/training-n<N>.json` (по одному на N), `<root>/configs/s-<id>.json` (по одному на сценарий).
- `train` читает `plan.json` через `load_plan` (проверки плана и хешей — часть B). Пишет: `training_started.json`, `training_complete.json`; дочерние процессы — `training/n<N>/data/`, `training/n<N>/run/`, `training/n<N>/test.json`; `job` — журналы в `logs/`.
- `execute` читает `plan.json` и чекпойнты (`<run>/best.pt`, только при `GLR`). Пишет: `model_preflight.json`, `execution_started.json`, `traces/t-<trace_key>.json`, `runs/<ячейка>/...` (дочерними процессами; состав — `04_SIMULATION_POLICIES_RU_partB2.md`), `logs/<ячейка>.*`, `execution_complete.json`.
- `aggregate` читает план и всё, что оставили `train`/`execute`; пишет один файл `--out` (часть C). `plot` читает `--summary`, пишет по `--out` (часть D).
Исходные файлы серии не изменяются (вывод из чтения: записи идут только в `<root>` и `--out`).

## 3. Значения по умолчанию и константы модуля

Из `experiments.py`, если не указан другой файл.
- `POLICIES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan")` — канонический порядок; `POLICIES[1:]` — набор `--baselines-only`.
- `SUITE_SCHEMA = "ssn-experiment-suite-v1"`.
- `SUITE_REQUIRED_KEYS` — девять ключей: `schema`, `name`, `core_template`, `simulation_template`, `training_overrides`, `simulation_overrides`, `seed_tuples`, `grids`, `sensitivities`; `SUITE_OPTIONAL_KEYS = {"policy_scope"}`.
- `POLICY_SCOPE_FILTERS = ("n", "failure_probability", "seed_tuple_indices")`.
- `CONTRACT`, `FEATURE_CONTRACT` — словари со строками `path`, `commit`/`blob`, `step`, называющими документы вне экспорта (не входит в экспорт); их содержание не установлено чтением. Оба записываются в тело плана. Комментарий кода: `FEATURE_CONTRACT` «MUST stay identical to simulate.FEATURE_CONTRACT»; его `commit` равен `None`.
- Из `experiment_io.py`: `PLAN_SCHEMA = "ssn-experiment-plan-v2"`, `NATIVE_PLAN_SCHEMA = "ssn-native-exhaustive-experiment-plan-v1"`, `NATIVE_POLICY_NAME = "TBR_bounded_exhaustive_reference"`.
- Шаблон имён `name()`: `[a-z][a-z0-9_-]{0,39}` (1–40 символов, первый — строчная латинская буква).
- Минимум пять троек сидов; предел сида `2**32` (ручной расчёт: 4294967296, допустимо `0 <= seed < 4294967296`).
- Ключи переопределений чувствительности: `tick_s`, `rate_bytes_s`, `arrival_interval_s` (`allowed` в `validate_suite`).
- `body["mode"]`: `"baselines_only"` или `"with_trained_GLR"`; `body["execution"] = "sequential user invocation only; no resume/overwrite"`.
- Устройство в командах `evaluate` и в `preflight_models`: `"cpu"`.
- Умолчания полей конфигурации (орбита N=132, planes=12; сиды 101–108, 201–202, 301–302, `train.seed=17`; сиды симуляции 401/501/601, вероятность отказа 0.04, шаг 0.1 с) — `config.py`, `sim_config.py` (`02_ENVIRONMENT_RU.md`); в сценариях сиды заменяются тройкой из suite.
