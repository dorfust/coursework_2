# 04. Симуляция и политики. Часть B2 из B2: simulate.py

Файл `src/ssn_hops/simulate.py` (12944 байта). Обозначения — как в части B1. Политики — части A3 и B1, симулятор — A1 и A2, конфигурация, контакты, трафик — `02_ENVIRONMENT_RU.md`, модель и обучение — `03_LEARNING_RU.md`.

## 3. simulate.py

### 3.1 Назначение
Докстринг: «User-run single simulation CLI; sweep entry point is ssn_hops.experiments». Две команды: `trace` (файл трафика) и `run` (один прогон одной политики). Модуль связывает конфигурацию, трафик, политику и `simulator.simulate`.

### 3.2 Входы и выходы
`main(argv=None)`: `parser()`, затем `load_sim_config(args.config)`.
- `trace --config --out` (оба обязательны): `trace_document(make_trace(cfg), cfg)` → `write_json(out)`; `write_json` открывает файл режимом `"x"` (существующий файл → `FileExistsError`, вывод из чтения); родительский каталог создаётся. На stdout — `{"traffic_file", "sha256", "packets"}`.
- `run`: обязательны `--config`, `--trace`, `--policy` (`choices = SINGLE_POLICY_NAMES`), `--out`, `--revision`. Необязательны: `--checkpoint-run` (только GLR); `--tbr-max-nodes`, `--tbr-max-expansions` (только родная политика; `positive_cli_budget` принимает лишь десятичные цифры, значение `> 0`); `--p` (float → `failure_probability`); `--rate-bytes-s` (float → `rate_bytes_s`); после замены — `replace(cfg, …).validate()`. `read_trace(read_json(args.trace), cfg)` проверяет схему, `trace_key`, хеш и порядок записей.
- `--revision`: функция `revision` принимает строку, целиком совпадающую с `[0-9a-fA-F]{40}`, и возвращает её в нижнем регистре; иначе `ArgumentTypeError("record the actual 40-character checkout SHA")`. Соответствие реальному checkout не проверяется (вывод из чтения; `provenance.py` помечает значение `revision_is_user_supplied`).
- Выход `run`: новый каталог `--out` (`mkdir(exist_ok=False)`), 7 файлов: `config.json`, `traffic.json`, `provenance.json`, `packets.json` (`{"schema": "ssn-packet-table-v1", "rows": …}`), `events.jsonl` (событие на строку), `result.json`, `complete.json` (`{"simulation_finished": True, "result_sha256": …}`). На stdout — весь `summary` (`sort_keys=True`, `allow_nan=False`).

### 3.3 Основные классы и функции
`run_single(cfg, records, policy_name, output, checkout_revision, checkpoint_run=None, input_paths=None, *, tbr_max_nodes=None, tbr_max_expansions=None)`:
1. Проверки (`ValueError`): имя из `SINGLE_POLICY_NAMES`; бюджеты TBR — только для родной политики; `checkpoint_run` обязателен для GLR и запрещён для остальных.
2. Родная политика: `TBR_bounded_exhaustive_reference(max_nodes, max_expansions)`; до создания каталога `cfg.orbit.n > policy.max_nodes` → `TBRSearchIncomplete(reason="max_nodes", expansions=0)` (комментарий: «NOT a choose call»); словарь `native_reference` из 13 ключей (идентичность, границы, области применимости, `contract`, два хеша коммитов).
3. `output.mkdir`; `config.json` (`cfg.to_dict()`), `traffic.json`, `provenance.json`: `provenance(revision)` плюс `simulation_contract`, `feature_contract`, `input_file_sha256` для `[--config, --trace]` и (родная) `native_reference`.
4. Политика (ниже); `simulate(cfg, records, policy)` без `network`: симулятор строит свой `GeometryNetwork(cfg)`.
5. `packets.json`, `events.jsonl`; в `summary` добавляются `schema` (`RESULT_SCHEMA` или `NATIVE_RESULT_SCHEMA`; заменяет значение `-v1` из `simulator.py`), хеши `config_sha256`, `traffic_sha256`, `declared_checkout_revision`, `assumptions`, `failure_protocol`, `runtime_origin`, `native_reference` (родная), в `timing` — `model_load_seconds`, `contact_plan_build_seconds`, `torch_threads`, `checkpoint`, `command_seconds_before_summary_write`, `command_scope`; `output_sha256` — для пяти первых файлов; затем `result.json`, `complete.json`.
Исключения не перехватываются: после шага 3 каталог остаётся без `complete.json` (вывод из чтения); при `TBRSearchIncomplete` из `simulate` нет `packets.json` и `result.json` (комментарий: «BEFORE tables/result/complete writes»).

**Сборка политики.** `TBR_style_hop_oracle` → `HopOracle()`; `TSR_source_dijkstra` → `SourceDijkstra()`; `CGR_contact_plan` → `build_geometric_plan(cfg)` (время — `contact_plan_build_seconds`) и `ContactRouting(plan)`; план и сеть симулятора строятся независимо из одного `cfg`.

**GLR: как строится предиктор (ответ на вопрос части A3).** В ветке `GLR` лениво импортируются `torch`, `model.predict_hops`, `training.load_trained_model` (`model.py` тянет `torch_geometric`):
1. `torch.set_num_threads(cfg.torch_threads)`, `torch.use_deterministic_algorithms(True)` — глобальное состояние процесса.
2. `load_trained_model(checkpoint_run, "cpu")` читает из каталога обучения `complete.json`, `best.json`, `best.pt`, `config.json`, `dataset_manifest.json`, `provenance.json`, сверяет хеши и формат `ssn-hops-fixed-n-v2`, загружает `torch.load(..., weights_only=True)`, строит `HopRegressor(cfg.orbit.n, cfg.model)` и загружает веса с `strict=True` (`expected_model_config` не передаётся).
3. Проверки (`ValueError`): `require_supported_model`; при `uses_delay` равенство `light_speed_km_s`; `asdict(training_config.orbit) == asdict(cfg.orbit)`; `cfg.phase_seed` не входит в затравки обучения, проверки, теста. Ручной расчёт для умолчаний: `401 ∉ {101..108, 201, 202, 301, 302}`.
4. `GLR(lambda adjacency, ranges: predict_hops(model, adjacency, ranges), cfg.orbit.n, training_config.model)`.
Смысл оценки (в коде написано): `HopRegressor` — «S[d,v] estimates remaining hops, NOT delay-weighted path cost»; `predict_hops` возвращает конечную матрицу `[destination, candidate]` с нулевой диагональю, без оракула достижимости, маски соседей и посещённых, симметрии и обрезки; `GLR.choose` берёт непосещённого допустимого `v` с минимальным `scores[destination, v]`. Вывод из чтения: оценка — предсказанное число хопов от кандидата до назначения; в `training.py` ошибка считается только на `mask` (достижимые пары), поэтому для недостижимых пар значение обучением не задано.

### 3.4 Значения по умолчанию
`RESULT_SCHEMA = "ssn-simulation-result-v2"`, `NATIVE_RESULT_SCHEMA = "ssn-native-exhaustive-simulation-result-v1"`, `NATIVE_POLICY_NAME = "TBR_bounded_exhaustive_reference"`, `SINGLE_POLICY_NAMES = POLICY_NAMES + (NATIVE_POLICY_NAME,)` (5 имён); бюджеты 12 и 100000 (`tbr_reference.py`); `checkpoint_run=None`, `input_paths=None`; остальное — `sim_config.SimulationConfig`. Ручной расчёт для умолчаний: `trace` — `range(0, 6000, 10)` (`600 / 0.1 = 6000` тиков, шаг `1.0 / 0.1 = 10`) → 600 записей; `Simulator.run` — `900 / 0.1 = 9000`, `range(9000 + 1)` → 9001 тик.

### 3.5 Связи с другими модулями
Импортирует `argparse, dataclasses, json, pathlib, re, time` и `config, contacts, policies, provenance, sim_config, simulator, tbr_policy, tbr_reference, traffic`. Уточнение к прежней инвентаризации: `torch` загружается при импорте, потому что `provenance.py` содержит `import torch` на уровне модуля (в коде написано), в том числе для `trace` и политик без GLR; `torch_geometric` при импорте `simulate.py` не нужен: `model.py` и `training.py` подключаются только в ветке GLR (вывод из чтения по импортам перечисленных модулей, `geometry.py`, `features.py`). Импортёры `simulate.py` не установлены.

### 3.6 Побочные эффекты
Файлы нового каталога; родительский каталог `trace`; настройки `torch` в ветке GLR; `perf_counter`. Случайности в самом модуле нет.

### 3.7 Что в коде названо допущением или реконструкцией
Строки кода: «independent safety controls; NOT author settings»; «independently specified bounded exhaustive reference; NOT recovered author traversal/code/performance»; `route_timing_scope`: «NOT pure core cost or author/Fig.5 equivalence»; `failure_protocol`: «ssn-edge-tick-v1; exact rational p; unordered edge/tick; not persistent outages»; `runtime_origin`: «only created when user executes; no precomputed paper results».
Строки с названиями документов, которые не входят в экспорт: `"SIMULATION_PROTOCOL.md; R3_FEATURES.md"`, `"; TBR_NATIVE_SINGLE_RUN.md"`; словари `CONTRACT`, `FEATURE_CONTRACT`, `NATIVE_CONTRACT` (пути вида `Repo_Orchestrator_2/tasks/….md`, хеши коммитов и блобов, метки шагов); `core_source_commit`, `adapter_source_commit`.

### 3.8 Что не установлено чтением
Кто вызывает `run_single`; точность предсказаний GLR; допускают ли операции `GCNConv` режим `use_deterministic_algorithms(True)` на CPU; содержимое документов не из экспорта; работоспособность (ничего не запускалось).
