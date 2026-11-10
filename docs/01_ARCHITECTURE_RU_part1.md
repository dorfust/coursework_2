# 01. Архитектура. Часть 1 из 3: слои и зависимости модулей

Документ описывает систему целиком. Часть 1: слои и таблица зависимостей; часть 2 (`01_ARCHITECTURE_RU_part2.md`): сквозной поток данных, диаграмма, расписание срезов драйвера; часть 3 (`01_ARCHITECTURE_RU_part3.md`): модель времени, случайность, таблица политик, связующие файлы и строки схем. Подробности по модулям — в группах 02-06 (`docs/02_ENVIRONMENT_RU.md` … `docs/06_DRIVER_CONFIGS_RU.md`).

Метки: «в коде написано» — пересказ или цитата кода; «вывод из чтения» — заключение без запуска; «ручной расчёт» — арифметика, показанная в тексте. Ничего не запускалось: нет утверждений, что код работает, прошёл тесты или даёт результаты; результатов экспериментов здесь нет. Документы, которые код называет в строках (пути `Repo_Orchestrator_2/tasks/...`, `SIMULATION_PROTOCOL.md` и др.), в экспорт не входят.

## 1. Слои системы

Пять слоёв кода плюс конфигурации. Слой выше использует слой ниже по списку импортов (раздел 2); обратных зависимостей на уровне модулей нет, кроме ленивых импортов внутри функций (раздел 3).

### 1.1. Среда (`src/ssn_hops/`: `config`, `sim_config`, `geometry`, `contacts`, `graph`, `traffic`)

- `config.py`: неизменяемые dataclass-конфигурации орбиты, данных, модели и обучения, проверка значений, `canonical_json`, `content_hash` (SHA-256 канонического JSON). В нём нет внутренних импортов (по индексу `docs/02`).
- `sim_config.py`: `SimulationConfig` (схема `ssn-simulation-config-v1`), `ticks()` (секунды → целое число тиков, кратность `tick_s` обязательна), `service_ticks()` (длительность передачи пакета по ребру в тиках), свойства `horizon_tick`, `ttl_ticks`, `trace_key`.
- `geometry.py`: положения спутников на круговых орбитах, видимость и смежность по дальности и по прямой видимости (Земля не должна закрывать отрезок).
- `contacts.py`: `GeometryNetwork.snapshot(tick)` (смежность и дальности на тик), план контактов (интервалы существования рёбер), `earliest_hop` (поиск по плану для CGR), `build_geometric_plan`.
- `graph.py`: точные метки числа хопов (поиск в ширину), структура `Q` (1.0 — соседи, 0.5 — пары только через общего соседа, 0 — прочие), входы двух ветвей модели.
- `traffic.py`: трасса пакетов (`make_trace`), документ трассы со схемой `ssn-traffic-v1` и хешем, `edge_tick_failure` (испытание отказа передачи без состояния).

### 1.2. Обучение (`features`, `data`, `model`, `loss`, `training`, `provenance`, `cli`, `__main__`, `__init__`)

- `features.py`: проверка смежности и дальностей, признаки задержки (необязательное расширение).
- `data.py`: генерация набора данных в каталог (`train.npz`, `val.npz`, `test.npz`, `manifest.json`).
- `model.py`: модель регрессии числа хопов на `torch_geometric`; `predict_hops` используется политикой GLR.
- `loss.py`, `training.py`: функция потерь, `train`, `evaluate`, `load_trained_model`; каталог прогона содержит `config.json`, `dataset_manifest.json`, `provenance.json`, `history.jsonl`, `best.pt`, `best.json`, `complete.json` (по `docs/03`, вывод из чтения).
- `provenance.py`: хеши `*.py` пакета, описание среды (версии пакетов, `torch.version.cuda`), запись JSON в режиме `"x"` (перезапись запрещена). В коде написано: «No shell calls, credentials, external datasets or fabricated result evidence.»
- `cli.py`, `__main__.py`: `python -m ssn_hops <environment|generate|train|evaluate>`. `__init__.py`: docstring и `__version__ = "0.1.0"`.

### 1.3. Симуляция и политики (`simulator`, `policies`, `tbr_policy`, `tbr_reference`, `simulate`)

- `simulator.py`: тиковый симулятор одной копии пакета с хранением и пересылкой; буферы узлов, одна передача на узел, строгий FIFO по приёму, повторы, аудит инвариантов на каждом тике.
- `policies.py`: `Decision`, `RoutingContext`, `POLICY_NAMES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan")` и классы `GLR`, `HopOracle`, `SourceDijkstra`, `ContactRouting`.
- `tbr_reference.py`, `tbr_policy.py`: опциональная политика `TBR_bounded_exhaustive_reference` (исчерпывающий поиск простых путей с границами `max_nodes`, `max_expansions`); в `POLICY_NAMES` она не входит.
- `simulate.py`: команды `trace` и `run`; `run_single` собирает политику, запускает `simulate` и пишет каталог прогона (`config.json`, `traffic.json`, `provenance.json`, `packets.json`, `events.jsonl`, `result.json`, `complete.json`).

### 1.4. Эксперименты (`experiments`, `experiment_io`, `experiment_results`, `experiment_plots`)

`experiments.py` строит план (`plan.json`) и запускает дочерние процессы `python -m ssn_hops` и `python -m ssn_hops.simulate`; `experiment_io.py` — форматы, хеши, проверка плана, охрана запуска, `job`; `experiment_results.py` — проверка сохранённых ячеек и сводка; `experiment_plots.py` — проверка сводки и рисунки. Сам `experiments.py` метрик не считает (`docs/05`, часть A1).

### 1.5. Драйвер (`driver/`: `plan_io`, `selector`, `run_cell`, `train_unit`, `traces`, `finish`, `ledger`, `__init__`)

Запускает уже созданный план по срезам с лимитами времени и журналом: `plan_io` проверяет привязку плана (корень, ревизия, хеши исходников), `selector` превращает файл срезов в шаги, `run_cell` и `train_unit` исполняют ячейки и обучение, `traces` создаёт файлы трасс, `finish` пишет предпроверку и маркер завершения и проверяет корень, `ledger` ведёт журнал времени. Драйвер не импортирует `finish` ни из одного модуля (`docs/06`, раздел 5).

### 1.6. Конфигурации (`configs/`)

`suite_m1b_cgr.json` (схема `ssn-experiment-suite-v1`, имя серии `m1b_first_run_cgr`), шаблоны `n132.json` и `simulation_n132.json` (читаются рядом с файлом серии), `slices_m1b_cgr.json` (схема `ssn-m1-slices-v1`, ключ `"suite": "m1b_first_run_cgr"` связывает файл со серией по имени).

## 2. Таблица зависимостей по строкам `import`

Столбец «Проверка»: «код» — строки `import` модуля прочитаны в самом файле при подготовке этого документа; «индекс» — взято из индексов `docs/02`-`docs/06` и не перечитывалось в коде. Проверены по коду 11 модулей: `sim_config`, `traffic`, `graph`, `provenance`, `cli`, `policies`, `simulator`, `tbr_policy`, `simulate`, `plan_io`, `ledger`. Расхождений с индексами не обнаружено (вывод из чтения).

| Модуль | Внутренние импорты | Сторонние | Проверка |
|---|---|---|---|
| `config` | нет | нет | индекс |
| `sim_config` | `config` (`OrbitConfig`, `_section`, `content_hash`, `integer`, `positive`) | нет | код |
| `geometry` | `config` | numpy | индекс |
| `contacts` | `config`, `geometry`, `sim_config` | numpy | индекс |
| `traffic` | `config` (`content_hash`, `integer`), `sim_config` (`ticks`) | нет | код |
| `features` | `config` | (numpy; не перечитывалось) | индекс |
| `graph` | `config` (`ModelConfig`), `features` (`delay_features`, `validate_adjacency`) | numpy, torch | код |
| `provenance` | нет | torch (на уровне модуля) | код |
| `loss` | нет | torch | индекс |
| `model` | `config`, `graph` | torch, torch_geometric | индекс |
| `data` | `config`, `geometry`, `graph`, `provenance` | numpy, torch | индекс |
| `training` | `config`, `data`, `features`, `graph`, `loss`, `model`, `provenance` | torch | индекс |
| `cli` | `config` (`load_config`), `data` (`generate_dataset`), `provenance` (`environment`), `training` (`train`, `evaluate`) | нет | код |
| `__main__` | `cli` | нет | индекс |
| `policies` | `config` (`ModelConfig`, `canonical_json`, `integer`), `features` (`delay_features`, `validate_adjacency`, `validate_ranges`) | numpy | код |
| `simulator` | `contacts` (`GeometryNetwork`), `policies` (`RoutingContext`), `sim_config` (`service_ticks`), `traffic` (`edge_tick_failure`, `validate_records`) | numpy | код |
| `tbr_reference` | `features` | numpy | индекс |
| `tbr_policy` | `policies` (`Decision`), `tbr_reference` (`DEFAULT_MAX_EXPANSIONS`, `DEFAULT_MAX_NODES`, `OBJECTIVE`, `SEARCH_IDENTITY`, `TBRSearchIncomplete`, `exhaustive_simple_path_reference`) | numpy | код |
| `simulate` | `config`, `contacts`, `policies`, `provenance`, `sim_config`, `simulator`, `tbr_policy`, `tbr_reference`, `traffic`; лениво (только для GLR, внутри `run_single`): `model` (`predict_hops`), `training` (`load_trained_model`) | torch (лениво), провенанс тянет torch | код |
| `experiments` | `config`, `sim_config`, `experiment_io`; лениво: `training`, `traffic`, `experiment_results`, `experiment_plots` | нет на верхнем уровне | индекс |
| `experiment_io` | `config`, `sim_config`; лениво: `experiments` | нет | индекс |
| `experiment_results` | `config`, `sim_config`, `traffic`, `experiment_io`; лениво: `experiments` (`check_model`) | нет | индекс (`docs/05`, C1) |
| `experiment_plots` | `config`, `experiment_io`, `experiment_results`; лениво `matplotlib` | matplotlib (лениво) | индекс |
| `driver/ledger` | нет | нет (версии пакетов через `importlib.metadata`) | код |
| `driver/plan_io` | `ssn_hops.experiment_io` | нет | код |
| `driver/selector` | лениво в `main`: `plan_io` | нет | индекс |
| `driver/traces` | `ssn_hops.experiment_io`, `ledger.utc_now`; лениво: `plan_io`, `selector`, `Ledger`, `sim_config`, `traffic` | нет | индекс |
| `driver/run_cell` | `experiment_io`, `plan_io`, `selector`, `traces`, `ledger`; лениво: `train_unit` (в `main`), `experiment_results` | нет | индекс |
| `driver/train_unit` | `experiment_io`, `plan_io`, `run_cell`, `selector`, `ledger`; лениво: `experiments` | нет | индекс |
| `driver/finish` | `experiment_io`, `plan_io`, `run_cell`; лениво: `experiments`, `experiment_results` | нет | индекс |

## 3. Выводы по графу импортов (вывод из чтения)

1. Цепочка `config` → `sim_config` → `traffic` состоит из стандартной библиотеки (для `sim_config` и `traffic` проверено по коду). Всё, что импортирует `provenance`, тянет `torch` на уровне модуля: `cli`, `data`, `training`, `simulate`. Поэтому `python -m ssn_hops.simulate trace` требует `torch`, хотя трассу строит только `traffic`.
2. Модули `model` и `training` в `simulate` подключаются лениво и только для политики GLR; `torch_geometric` нужен поэтому лишь обучению, оценке и прогону GLR.
3. Циклов на уровне загрузки нет. Обратные ссылки `experiment_io` → `experiments`, `experiment_results` → `experiments` — ленивые. В драйвере цикл `run_cell` ↔ `train_unit` разорван ленивым импортом в `run_cell.main`.
4. Драйвер вызывает пакет только через `experiment_io`, `experiment_results`, `experiments`, `sim_config`, `traffic`; сам дочерние процессы запускает как `python -m ssn_hops ...` и `python -m ssn_hops.simulate ...` с тем же интерпретатором (`docs/06`, часть A3).
5. Не установлено чтением: полный список импортёров каждого модуля (проверялись строки `import` только перечисленных выше модулей) и состав импортов у модулей с пометкой «индекс».
