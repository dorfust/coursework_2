# 03. Обучение: часть 2 — `model.py`, `training.py`

Обозначения — как в части 1. `N = cfg.orbit.n` (по умолчанию 132), `w = gcn_width`, `B` — размер батча. Описание `loss.py` (функция `hop_loss`, используемая в `train`) — в части 3, раздел 5.

## 3. `model.py`

### Назначение
Модель фиксированного `N`: оценка числа хопов между всеми парами узлов (docstring: «Fixed-N all-pairs reconstruction», «not author architecture»; ссылка на файл «R3_FEATURES.md» — не входит в экспорт).

### Классы и функции
- `GCNBranch(input_width, width, bias)`: два `torch_geometric.nn.GCNConv` (`first: input_width→width`, `second: width→width`) с `improved=False, cached=False, add_self_loops=True, normalize=True, bias=bias`. `forward(features, edge_index)` = `relu(second(relu(first(x))))`, выход `[N,width]`.
- `HopRegressor(n, config)`: проверяет `n` (`integer(n,"model n",2)`) и `config.validate()`. Две несвязанные ветви `low`, `high`; `predictor = Sequential(Linear(2*w, dense_width, bias=dense_bias), ReLU, Linear(dense_width, n, bias=dense_bias))`.
  `forward(low, high, edge_index)`: проверяет формы `low [N,low_width]`, `high [N,high_width]`, конечность, `edge_index` — `int64 [2,E]`; конкатенирует выходы ветвей по оси 1 (`[N,2w]`) и возвращает `predictor(...)` формы `[N,N]`, без активации на выходе. Смысл (docstring): `S[d,v]` оценивает оставшиеся хопы, а не стоимость пути с задержками; ориентация `[destination, candidate]` (`ModelConfig.orientation`). Вывод из чтения: строка `i` строится из эмбеддинга узла `i`; столбцы — «N ID-specific output coordinates»; веса по узлам общие.
- `predict_hops(model, adjacency, ranges_km=None)` (`torch.no_grad`): проверяет смежность и `shape == (model.n, model.n)`, переводит модель в `eval` (режим восстанавливается в `finally`), строит входы `graph.branch_inputs`, возвращает `numpy [N,N]`; проверяет конечность, затем ставит диагональ `0.0` (только для вывода). Не применяются: оракул достижимости, маска соседей/посещённых, симметризация, обрезка. `ranges_km` нужен только в режиме задержки.

### Ширины входов по режимам (`ModelConfig.features`)
| Режим | `low` | `high` | `low_width` / `high_width` |
|---|---|---|---|
| `adjacency_spliced_two_hop` (по умолчанию), `topology_only_ablation` (синоним) | `[A]` | `[A\|Q]` | `N` / `2N` |
| `adjacency_spliced_two_hop_propagation_delay` | `[A\|D]` | `[A\|Q\|D]` | `2N` / `3N` |

Распространение — по исходной бинарной `A` с нормировкой `A+I` (`edge_index` содержит обе стороны каждого ребра).

### Значения по умолчанию (`config.py`, `ModelConfig`)
`gcn_width=32`, `dense_width=64`, `gcn_bias=False`, `dense_bias=True`.

### Число параметров — ручной расчёт (`N=132`, умолчания)
Допущение вне кода: `GCNConv(in,out,bias=False)` содержит одну матрицу `in×out` без смещения (устройство `torch_geometric` не проверялось). Топологический режим: `low` `132*32+32*32 = 5248`; `high` `264*32+1024 = 9472`; `predictor` `(64*64+64)+(64*132+132) = 4160+8580 = 12740`; итого `27460`. Режим задержки: `low` `264*32+1024 = 9472`, `high` `396*32+1024 = 13696`, итого `9472+13696+12740 = 35908`.

### Связи, побочные эффекты
Импортирует `config.integer`, `graph.branch_inputs`, `graph.validate_adjacency`; используется `training.py`. Файлов не пишет; случайность — инициализация весов в глобальном генераторе `torch`.

### Не установлено чтением
Число параметров по факту; поведение `GCNConv`; точный `dtype` выхода (вывод: `float32`).

## 4. `training.py`

### Константа и функции
`CHECKPOINT_FORMAT = "ssn-hops-fixed-n-v2"`.
- `resolve_device(name)`: `cpu` (без индекса) или `cuda[:i]` (доступна и индекс в диапазоне), иначе `ValueError`.
- `seed_training(config)`: `random.seed`, `np.random.seed`, `torch.manual_seed`, `cuda.manual_seed_all`, `set_num_threads(threads)`, `use_deterministic_algorithms(deterministic)`, `cudnn.benchmark=False`, `cudnn.deterministic=deterministic` (глобальное состояние).
- `tensors_for_snapshot(arrays, index, device, model_config=None)` → `(inputs, target, mask)`: в режиме задержки считает `ranges_from_positions`; входы — `branch_inputs`; `target` — `float32` (метки `-1` остаются, но маскируются), `mask` — bool.
- `static_metrics(model, arrays, device)`: `eval`, `no_grad`, сырые выходы (диагональ не перезаписывается). Микро-среднее по достижимым парам: `mse_hops2`, `rmse_hops`, `mae_hops`, `signed_error_hops`, `max_absolute_error_hops`, `rounded_exact_accuracy` (`torch.round`, к чётному, без обрезки), `supervised_pairs`, `unreachable_offdiagonal_pairs`, `unreachable_offdiagonal_fraction` (делитель `snapshots*N*(N-1)`), `masked_pairs`, `snapshots`, `snapshots_without_supervised_pairs`, `metric_scope`. `count==0` → `ValueError`. Пакетных метрик нет.
- `feature_provenance(cfg, manifest)` → словарь `spec`, `training_source`, `dataset_manifest_schema`, `dataset_array_schema`, `scale_origin` (текст зависит от режима). Комментарий кода: тексты помечены как побайтно совпадающие с прежними значениями (метка не входит в экспорт).
- `train(cfg, dataset_dir, run_dir, revision)` → `summary`. Порядок: `cfg.validate`; `resolve_device(cfg.train.device)`; `load_dataset(dataset_dir, cfg)`; непустые маски во всех трёх split; `seed_training`; `run.mkdir(parents=True, exist_ok=False)`; запись `config.json`, `dataset_manifest.json`, `provenance.json` (+ `input_features`); `HopRegressor` (инициализация после `seed_training`); `Adam(lr, betas, eps, weight_decay=0.0)`. Эпоха: `rng.permutation` индексов train; батчи по `batch_size` (последний может быть меньше); каждый снимок идёт через модель отдельно, результаты `stack` → `[B,N,N]`; батч без пар пропускается (`skipped_empty_batches`); `hop_loss(..., cfg.train.beta)`; проверки конечности потерь и градиентов (`ValueError`); `optimizer.step()`. После эпохи: `static_metrics` на val, `parameter_l2`, строка в `history.jsonl`: `epoch`, `online_train_mse_hops2` (накоплено по ходу эпохи до каждого шага), `train_pairs`, `optimizer_steps`, `skipped_empty_batches`, `parameter_l2`, `validation`, `validation_regularized_objective = val_mse + beta*norm`.
- Выбор и остановка: критерий — только `validation["mse_hops2"]`; улучшение — строго `<` лучшего (при равенстве побеждает ранняя эпоха); при улучшении пишется `best.pt` (через `best.pt.tmp` и `replace`), `stale=0`, иначе `stale+=1`; при `stale >= patience` цикл прерывается. Test в `train` не оценивается (только проверка непустоты). Модель не возвращается, лучшие веса в памяти не восстанавливаются (вывод).
- Payload `best.pt`: `format`, `config`, `config_sha256`, `data_key`, `feature_provenance`, `dataset_manifest_sha256`, `epoch`, `validation_mse_hops2`, `revision`, `model_state`, `optimizer_state`, `selection`.
- Файлы прогона: `config.json`, `dataset_manifest.json`, `provenance.json`, `history.jsonl` (режим `"x"`), `best.pt`, затем `best.json` (`best_epoch`, `best_validation_mse_hops2`, `epochs_run`, `best_checkpoint_sha256`, хэши, `selection`, `runtime_result_origin`) и `complete.json` (`training_finished`, `epochs_run`). Прерванный прогон остаётся без `complete.json`.
- `validate_checkpoint_metadata(payload, expected_model_config=None)` → `Config`: формат, `config_sha256`/`data_key`, `feature_provenance["spec"]`; при `expected_model_config` — полное равенство `ModelConfig` (включая строку режима).
- `load_trained_model(run_dir, device_name="cpu", expected_model_config=None)` → `(model, metadata)`: `complete.json`, формат, sha256 `best.pt`, `torch.load(..., weights_only=True)`, согласованность `config.json`, `best.json`, `dataset_manifest.json`, `provenance.json` и payload, `load_state_dict(strict=True)`, `eval`. Возобновление обучения не поддерживается (комментарий «No resume claim»).
- `evaluate(run_dir, dataset_dir, split, output, revision, device_name="cpu")`: split — `train|val|test`; sha256 манифеста набора данных должен совпасть с записанным в чекпойнте (вывод: заново сгенерированный набор отвергается); результат (`split`, `checkpoint_epoch`, хэши, `metrics`, `provenance`, …) пишется в `output` (родитель создаётся, режим `"x"`) и возвращается.

### Значения по умолчанию (`config.py`, `TrainConfig`)
`seed=17`, `epochs=100`, `batch_size=4`, `learning_rate=0.001`, `beta=0.00001`, `patience=15`, `device="cpu"`, `deterministic=True`, `threads=1`, `optimizer="Adam"`, `adam_betas=[0.9,0.999]`, `adam_eps=1e-8`. Ручной расчёт: при 192 снимках train и `B=4` — `192/4 = 48` шагов за эпоху (без пропусков).

### Случайность
Порядок снимков — `np.random.default_rng(cfg.train.seed)` (комментарий: поток независим от потоков фаз и инициализации); веса — `torch.manual_seed(cfg.train.seed)`; фазы траекторий — seed данных.

### Связи
Импортирует `config`, `data`, `features`, `graph`, `loss`, `model`, `provenance`; `canonical_json` импортируется внутри блока `with`. Используется `cli.py`; прочие импортёры не проверялись.

### Не установлено чтением
`deterministic=True` на CUDA (переменные окружения в коде не заданы); совместимость `optimizer_state` с `weights_only=True`; время, память, значения метрик.
