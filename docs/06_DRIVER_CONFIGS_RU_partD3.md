# docs/06. Конфигурации: n132.json, simulation_n132.json, slices_m1b_cgr.json, часть D3 (из D1-D3)

В этом документе описаны три JSON-файла из `configs/`. Девять обязательных ключей файла серии — в `06_DRIVER_CONFIGS_RU_partD2.md`, раздел 2. Значения даны как в файлах; результатов каких-либо запусков нет. Метки: «в коде написано», «вывод из чтения», «ручной расчёт». Ничего не запускалось.

# Раздел 1. configs/n132.json (шаблон ядра, 1000 байт)

## 1.1 Назначение

Это шаблон конфигурации обучения/данных для серии: в `suite_m1b_cgr.json` его имя стоит в ключе `core_template`. `experiments.resolve_suite` делает `from_dict(merge(<шаблон>, suite["training_overrides"]))` (docs/05 partA2, раздел 4); `config.from_dict` строгий: неизвестные поля на любом уровне дают `ValueError`, пропущенные поля — значения по умолчанию датаклассов, затем `Config.validate()` (docs/02 и docs/03).

## 1.2 Ключи (в коде `config.py` — поля датаклассов; значения — из файла)

Верхний уровень (5 ключей): `schema_version` = 2 (`Config.validate` требует ровно `int` 2), `orbit`, `data`, `model`, `train`.

`orbit` (12 полей, `OrbitConfig`): `n` = 132 (целое ≥ 2); `planes` = 12 (`n % planes == 0`, `planes <= n`; ручной счёт 132 / 12 = 11); `earth_radius_km` = 6371.0; `altitude_km` = 1050.0; `inclination_deg` = 53.0 (допустимо [0, 180]); `eccentricity` = 0.0 (реализованы только круговые орбиты); `mu_km3_s2` = 398600.4418; `walker_f` = 1 (целое ≥ 0 и < `planes`); `phase_mode` = `"independent_plane_offsets"` (допустимы `"walker"` и это); `epoch_s` = 0.0; `range_km` = 3500.0; `earth_los` = true (булево). Смысл полей — docs/02 (`geometry.py`, `contacts.py`).

`data` (7 полей, `DataConfig`): `train_seeds` = [101..108] (8 сидов), `val_seeds` = [201, 202], `test_seeds` = [301, 302]; сиды — целые ≥ 0 и < 2**32, списки непусты, все сиды всех трёх разделов различны; `snapshots_per_trajectory` = 24; `step_s` = 120.0 (положительное); `start_s` = 0.0; `mask_diagonal` = true.

`model` (в файле 7 из 10 полей `ModelConfig`): `gcn_width` = 32, `dense_width` = 64, `gcn_bias` = false, `dense_bias` = true, `features` = `"adjacency_spliced_two_hop"` (константа `TOPOLOGY_FEATURES`; допустимы также `"topology_only_ablation"` и `"adjacency_spliced_two_hop_propagation_delay"`), `feature_version` = 1 (допустимо только 1), `orientation` = `"destination_candidate"` (единственное поддержанное). Поля `delay_kind`, `delay_scale_s`, `light_speed_km_s` не заданы и берутся из умолчаний `"propagation_only"`, 0.01, 299792.458 (`validate` требует именно их).

`train` (12 полей, `TrainConfig`): `seed` = 17 (целое ≥ 0, < 2**32), `epochs` = 100, `batch_size` = 4, `learning_rate` = 0.001, `beta` = 0.00001 (конечное, ≥ 0), `patience` = 15, `device` = `"cpu"` (строка), `deterministic` = true, `threads` = 1, `optimizer` = `"Adam"` (реализован только он), `adam_betas` = [0.9, 0.999] (список из двух, каждый в [0, 1)), `adam_eps` = 1e-8. Смысл полей модели и обучения — docs/03.

Вывод из чтения (полевое сравнение файла с умолчаниями датаклассов `config.py`): все значения файла равны умолчаниям; файл — явная запись этих умолчаний. В серии `m1b_first_run_cgr` `train.epochs` заменяется на 300 (`training_overrides`), для каждого N подставляются `n` и `planes` (из `sizes`). Хеш конфигурации (`Config.sha256`) считается от канонического JSON разобранного словаря, поэтому порядок ключей и пробелы файла его не меняют (вывод из чтения `config.py`). Не установлено чтением: хешируются ли байты самих шаблонов в плане.

# Раздел 2. configs/simulation_n132.json (шаблон симуляции, 723 байта)

## 2.1 Назначение

Это шаблон конфигурации симуляции (`simulation_template` серии). `resolve_suite` делает `from_sim_dict(merge(<шаблон>, suite["simulation_overrides"]))`; строгий разбор — `sim_config.from_sim_dict` (неизвестные поля — `ValueError`; вложенный `orbit` разбирается тем же `OrbitConfig`), затем `SimulationConfig.validate()`. Каждый сценарий плана получается из этого шаблона подстановкой `orbit` (только `n`, `planes`), `failure_probability` и трёх сидов тройки (docs/05 partA2, раздел 5.2). Вывод из чтения: в серии `m1b_first_run_cgr` между 50 сценариями меняются только эти поля (`sensitivities` без переопределений, `simulation_overrides` пуст).

## 2.2 Ключи (18 ключей верхнего уровня, ручной счёт; проверки — `SimulationConfig.validate`)

`schema` = `"ssn-simulation-config-v1"` (должна быть такой); `orbit` — те же 12 полей и те же значения, что в `n132.json` (полевое сравнение); `phase_seed` = 401, `traffic_seed` = 501, `failure_seed` = 601 (целые ≥ 0, < 2**32; в серии заменяются тройками `seed_tuples`; значения шаблона равны тройке с индексом 0 — наблюдение); `tick_s` = 0.1; `traffic_end_s` = 600.0; `observation_end_s` = 900.0 (не меньше `traffic_end_s`); `arrival_interval_s` = 1.0; `packet_bytes` = 18000; `ttl_s` = 300.0; `buffer_bytes` = 16000000; `rate_bytes_s` = 12500.0; `light_speed_km_s` = 299792.458; `failure_probability` = 0.04 (допустимо [0, 1]); `additional_retries` = 3 (целое ≥ 0); `torch_threads` = 1; `audit_each_tick` = true (булево). Времена `traffic_end_s`, `observation_end_s`, `arrival_interval_s`, `ttl_s` должны быть кратны `tick_s` (`ticks()` с допуском 1e-7). Смысл полей — docs/02 (`sim_config.py`) и docs/04 (`simulator.py`).

Ручной расчёт по значениям файла: 600.0 / 0.1 = 6000 тиков окончания трафика; 900.0 / 0.1 = 9000 (`horizon_tick`); 300.0 / 0.1 = 3000 (`ttl_ticks`); 1.0 / 0.1 = 10 тиков между прибытиями; 18000 / 12500 = 1.44 с сериализации пакета, то есть 14.4 тика до учёта распространения; по `service_ticks` (округление вверх) не менее 15 тиков. Все значения файла равны умолчаниям `SimulationConfig` (полевое сравнение, вывод из чтения). Ключ `trace_key` включает N, `traffic_seed`, `tick_s`, `traffic_end_s`, `arrival_interval_s`, `packet_bytes` (docs/05 partA2): сценарии с одним N и одной тройкой делят файл трассы (вывод из чтения). Не установлено: что именно получается в трассе (число пакетов) — см. docs/02, `traffic.py`.

# Раздел 3. configs/slices_m1b_cgr.json (файл срезов, 3128 байт)

## 3.1 Назначение и верхний уровень

Файл разбивает план на срезы (шаги обучения и ячейки); читается `selector.load_slices` (docs/06 partC1, C2) по аргументу `--slices` у `selector`, `traces`, `run_cell`, `train_unit`. Ключи верхнего уровня (5):
- `schema` = `"ssn-m1-slices-v1"` (должна равняться `SLICES_SCHEMA`, иначе `SelectorError("unsupported slices schema")`).
- `suite` = `"m1b_first_run_cgr"` — ключ привязки: `check_suite_binding` отказывает, если имя серии плана (`body["suite"]["name"]`) — строка и отличается; в файле серии `name` тоже `"m1b_first_run_cgr"` (совпадает). Привязка по имени, без сравнения содержимого (docs/06 partC2).
- `note` — строка-комментарий; `load_slices` её не читает (неизвестные ключи верхнего уровня не проверяются, вывод из чтения). В нём изложены состав срезов, числа ячеек (3 + 117 + 15 + 15 + 1 + 2 + 6 + 3 = 162), порог обучения 120 минут на единицу и правило, что незавершённый CGR-срез оставляет план «частичным» (без маркера завершения, агрегат требует `allow_partial`). Текст называет «R8 addenda 23-29» и «plan m1b_cgr» — документы вне экспорта.
- `parameters` = `{}` (словарь имён → положительные числа; пустой допустим). Вывод из чтения: параметры не определены, поэтому `--param` принимает только имя `train_cap_minutes` (отказ для любого другого, `run_cell.unknown_params`), а `cap_minutes_param` в элементах не может на них ссылаться; лимит обучения — `DEFAULT_TRAIN_CAP_MINUTES = 120.0` (`run_cell.py`, `train_unit.py`), меняется `--param train_cap_minutes=NN` или `--train-cap-minutes`.
- `slices` — список из 11 срезов (ручной счёт).

## 3.2 Ключи среза и элемента (по коду `selector.py`)

Срез: `id` (строка, уникальная), `counted` (строго булево), `items` (непустой список). Элемент: `kind` — `train` или `cell` (вид `trace` в файле не используется); `N` — список целых (членство); `failure_probability` — список чисел, точное `==` без допуска (в файлах серии и срезов значения записаны одинаковыми литералами: 0.0, 0.02, 0.04, 0.06); `seed_tuple_indices` — позиции в `seed_tuples` серии (0-4); `policies` — имена из `POLICY_NAMES`; `exclude_earlier` — исключить ячейки, уже занятые ранее в файле. Не используются в файле: `optional_policy_absent`, `cap_minutes`, `cap_minutes_param`. Элемент `train` принимает только `N`; шаг — `train-n<N>`.

## 3.3 Срезы в порядке файла (все `counted` = true; по одному элементу в срезе)

| id | kind, N | фильтры | ячеек (ручной расчёт) |
|---|---|---|---|
| `TRAIN-132` | train, [132] | — | — |
| `TRAIN-REST` | train, [198, 264] | — | — (две единицы обучения) |
| `TRAIN-330` | train, [330] | — | — |
| `PILOT` | cell, [132] | p [0.04], индекс [0], GLR, TBR_style_hop_oracle, TSR_source_dijkstra | 1 × 3 = 3 |
| `B1B` | cell, [132, 198] | те же 3 политики, `exclude_earlier` | (35 + 5) × 3 − 3 = 117 |
| `B264` | cell, [264] | 3 политики | 5 × 3 = 15 |
| `B330` | cell, [330] | 3 политики | 15 |
| `CGR-PILOT` | cell, [132] | p [0.04], индекс [0], CGR_contact_plan | 1 |
| `CGR-EXT1` | cell, [132] | p [0.04], индексы [1, 2], CGR | 2 |
| `CGR-EXT2` | cell, [132] | p [0.0, 0.06], индексы [0, 1, 2], CGR | 2 × 3 = 6 |
| `CGR-EXT3` | cell, [132] | p [0.02], индексы [0, 1, 2], CGR | 3 |

Расчёт для `B1B`: сценариев при N = 132 — 7 вероятностей × 5 троек = 35, при N = 198 — 5 (p = 0.04); три политики; 3 ячейки `PILOT` уже заняты. Сумма: 3 + 117 + 15 + 15 = 150 не-CGR ячеек; 1 + 2 + 6 + 3 = 12 CGR-ячеек; всего 162 = 50 × 3 + 12 (см. `partD2`, раздел 2.2). Обучения: N = 132, 198, 264, 330 — каждый ровно раз. Вывод из чтения: это то, что требует `check_partition` (объединение ячеек срезов = `body["cells"]`, никакой ячейки дважды, обучения = модели плана); проверка не запускалась. Без `exclude_earlier` срез `B1B` забрал бы ячейки `PILOT`, и `resolve_all` отказался бы («selected by ... and ...»).

## 3.4 Связи, лимиты ячеек, неустановленное

Лимит ячейки в `run_cell.main`: `cap = cell_cap if cell_cap is not None else step.get("cap_seconds")`, где `cell_cap` — `--cap-minutes × 60`. В этом файле у элементов нет ключей лимита, поэтому без `--cap-minutes` ячейки без лимита времени (вывод из чтения). В цикле `main` исход `capped` даёт код 3 и при выключенном `--keep-going` обрывает срез (docs/06 partA4); это соответствует объяснению в `note`, почему каждый CGR-срез выделен отдельно. Порядок запуска срезов задаёт вызывающий: один вызов `run_cell`/`train_unit` — один срез (`--slice`); код, проходящий все срезы, в драйвере не найден. Флаги `counted` все true, поэтому минуты всех этих срезов идут в `counted_minutes` (`ledger_sum`, вывод из чтения). Путь файла по умолчанию в `run_cell`/`train_unit` на этот файл не указывает (см. индекс `06_DRIVER_CONFIGS_RU.md`, раздел «Раскладка экспорта»).

Не установлено чтением: фактический результат `resolve_all` на настоящем `plan.json` (числовые ожидания выше — ручной расчёт по тексту файлов и правилам кода); время выполнения любого среза и достаточность лимита 120 минут.
