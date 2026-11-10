# 03. Обучение: часть 1 — `features.py`, `data.py`

Условные обозначения — как в `02_ENVIRONMENT_RU.md`: «в коде написано» (цитата или пересказ), «вывод из чтения», «ручной расчёт». Ничего не запускалось. Каталог модулей: `src/ssn_hops/`. Конфигурация, геометрия и графы описаны в `02_ENVIRONMENT_RU.md` (config — части 1–2, geometry — часть 4, graph — часть 6) и здесь не повторяются.

## 1. `features.py`

### Назначение
«Pure NumPy physical inputs»: проверки матриц смежности и дальностей и единственный вычисляемый здесь признак — канал задержки распространения D. В коде написано: D относится к необязательному режиму расширения, которого нет в статье, и является «reconstruction assumption».

### Входы и выходы, функции
- `validate_adjacency(adjacency)` → `np.ndarray` bool `[N,N]`. Проверки: `ndim==2`, квадратность, `N>=2`; `dtype.kind` из `"buif"`; все значения конечны и из `{0,1}`; нулевая диагональ; точная симметрия. Иначе `ValueError`.
- `real_array(value, shape, name)` → `float64`. Форма должна совпасть точно; `dtype.kind` из `"uif"` (bool отвергается); значения конечны.
- `validate_ranges(ranges_km, n)` → `float64 [n,n]`; значения `>=0`, матрица точно симметрична (`np.array_equal`).
- `ranges_from_positions(positions_km)` → `float64 [N,3]` в матрицу дальностей `[N,N]`: `sqrt(sum(delta*delta))`, предупреждения переполнения подавлены, результат проходит `validate_ranges`. Единицы — км (комментарий: та же арифметика, что `geometry.graph_from_positions`).
- `delay_features(adjacency, ranges_km, model_config=None)` → `float32 [N,N]`. Формула (в коде): для `A[i,j]=1` значение `D[i,j] = (ranges[i,j] / light_speed_km_s) / delay_scale_s`; для отсутствующих рёбер и диагонали — ровно 0 (маска применяется до преобразования). Если результат во `float32` не конечен — `ValueError`. Если `model_config.uses_delay` ложно — `ValueError`.

### Значения по умолчанию
`model_config=None` заменяется на `ModelConfig()`; по умолчанию это топологический режим, поэтому вызов `delay_features` без явного режима задержки завершится `ValueError` (вывод из чтения). `light_speed_km_s=299792.458` и `delay_scale_s=0.01` — `config.py`, `LIGHT_SPEED_KM_S`, `DELAY_SCALE_S` (`ModelConfig.validate` требует именно эти значения). Следовательно D безразмерна: задержка в единицах 10 мс. Ручной расчёт для длины 3500 км (значение `OrbitConfig.range_km` по умолчанию): `3500/299792.458 ≈ 0.011675 с`, `/0.01 ≈ 1.1675`.

### Связи с другими модулями
Импортирует `config.ModelConfig`. Используется: `graph.py` (`validate_adjacency`, `delay_features`; имя `validate_adjacency` из `graph` реэкспортируется и в `model.py`, `data.py`), `training.py` (`ranges_from_positions`). `ABLATION_FEATURES` в `features.py` не упоминается: константа живёт в `config.py`; здесь используется лишь `ModelConfig.uses_delay`. Матрица `Q` («1 / 0.5 / 0») строится в `graph.preprocessed_structure`, не здесь.

### Побочные эффекты
Нет файлов, случайности и глобального состояния.

### Допущения и реконструкция (цитаты кода)
Docstring: D «is NOT stated in the paper», «not recovered author H0»; он ссылается на пометку «T020 C002» (внутренняя метка, документ не входит в экспорт). Комментарий в docstring: все физические значения должны быть конечными и неотрицательными «even when masked out».

### Не установлено чтением
Какие вызывающие модули вне девяти (политики, эксперименты) используют `features.py` — не проверялось.

## 2. `data.py`

### Назначение
Создание и чтение набора данных: точные метки хопов и разбиение по целым траекториям (docstring: «no random split»).

### Основные функции
- `SPLITS = ("train","val","test")`.
- `adjacency_hash(array)` → hex sha256 от `uint8`-байтов массива (форма в хэш не входит — вывод).
- `generate_dataset(cfg, output, revision)` → manifest (`dict`). `cfg.validate()`; `Path(output).mkdir(parents=True, exist_ok=False)` — существующий путь вызывает ошибку. Для каждого split и каждого seed из `cfg.data.<split>_seeds`: `trajectory = make_trajectory(cfg.orbit, seed)`; моменты `times_s[i] = start_s + i*step_s`, `i=0..snapshots_per_trajectory-1`; для каждого момента `xyz = trajectory.positions_km(t)`, `adjacency = graph_from_positions(xyz, cfg.orbit)[0]`, `target, mask = shortest_hops(adjacency, cfg.data.mask_diagonal)`. Снимки идут в порядке: seed из списка, затем время. Файл `<split>.npz` (`np.savez_compressed`) с массивами `positions_km [S,N,3]`, `adjacency [S,N,N]`, `target [S,N,N]` (int32 из `shortest_hops`; `-1` — недостижимо, диагональ 0, оси `[destination, candidate]`), `mask [S,N,N]` bool; `S = число seed × snapshots_per_trajectory`. Dtype `positions_km` и `adjacency` определяются `geometry.py` — не установлено.
- `validate_manifest(manifest)` → `Config`. Проверяет: `schema_version` — `int` из `(1,2)`; `config_sha256 == content_hash(config)`; схема в `config` совпадает; `dataset_config(...)` (миграция v1 — `02_ENVIRONMENT_RU.md`, часть 2); `data_key`; для v2 — `feature_provenance == cfg.model.feature_spec`; для каждого split: имя файла `<split>.npz`, список seed равен конфигурации, `snapshot_count == len(trajectories)*snapshots_per_trajectory`, `trajectory_id` и `parameters` совпадают с пересчитанной `make_trajectory`, `times_s` совпадают с формулой; уникальность seed, `trajectory_id` и пары (`raan_rad`, `plane_phase_rad`) по всем split.
- `load_dataset(directory, expected_config=None)` → `(data, manifest)`; `data[split]` — словарь четырёх массивов (копии, `allow_pickle=False`). Проверяет: `data_key` ожидаемой конфигурации равен архивному (модельная секция не сравнивается — вывод); sha256 каждого `.npz`; множество имён массивов; формы `(count,n,n)` и `(count,n,3)`; конечность координат; `mask` bool, `target` целочисленный; затем для каждого снимка пересчитывает координаты (`np.allclose`, `rtol=1e-12`, `atol=1e-9`), смежность из геометрии, метки и маску через BFS и сверяет с массивами; число пар и уникальных смежностей; матрицу пересечений. Вывод: загрузка заново вычисляет BFS для всех снимков (стоимость не оценивалась).

### Формат manifest.json
Поля: `schema_version=2`, `config`, `config_sha256`, `data_key`, `feature_provenance`, `provenance` (см. `provenance.py`), `splits{split:{file, sha256, snapshot_count, trajectories[{seed, trajectory_id, parameters, times_s}], supervised_pairs, unique_adjacencies}}`, `cross_split_exact_adjacency_overlap` (ключи `"train:val"`, `"train:test"`, `"val:test"` — число общих точных смежностей), `split_protocol` = «whole independent phase trajectories; adjacent times never split». JSON пишется через `write_json` (`indent=2`, `sort_keys`, без NaN, режим `"x"`).

### Значения по умолчанию (`config.py`, `DataConfig`)
`train_seeds=[101..108]` (8), `val_seeds=[201,202]`, `test_seeds=[301,302]`, `snapshots_per_trajectory=24`, `step_s=120.0`, `start_s=0.0`, `mask_diagonal=True`. Ручной расчёт: снимков `8*24=192` (train), `2*24=48` (val), `48` (test), всего 288; времена `0,120,…,23*120=2760` с; пар на снимок не более `132*131=17292` (при `n=132` по умолчанию, диагональ исключена; достижимых может быть меньше).

### Связи с другими модулями
Импортирует `config`, `geometry` (`make_trajectory`, `graph_from_positions`), `graph` (`shortest_hops`, `validate_adjacency`), `provenance`. Используется `training.py` (`load_dataset`, `validate_manifest`), `cli.py` (`generate_dataset`). Прочие импортёры не проверялись.

### Побочные эффекты и случайность
Создаёт каталог с `train.npz`, `val.npz`, `test.npz`, `manifest.json`. Случайность входит только через seed в `make_trajectory` (геометрия, `02_ENVIRONMENT_RU.md`, часть 4); в `data.py` нет собственного генератора и случайного разбиения. Если `validate_manifest` упадёт после записи `.npz`, каталог останется без `manifest.json` (вывод из порядка вызовов).

### Допущения в коде
Нет пометок «assumption»; docstring и `split_protocol` заявляют отсутствие случайного разбиения.

### Не установлено чтением
Dtype `positions_km`/`adjacency` в архиве; фактический размер файлов и время загрузки; содержимое `trajectory.metadata()` (геометрия).
