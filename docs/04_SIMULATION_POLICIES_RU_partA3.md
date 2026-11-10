# 04. Симуляция и политики. Часть A3 из A3: policies.py

Файл `src/ssn_hops/policies.py` (13112 байт). Обозначения — как в части A1; вызов политик симулятором — в части A2 (1.3.4, 1.3.5). `tbr_policy.py` лишь импортирует `Decision` отсюда; его описание — в частях B.

## 2. policies.py

### 2.1 Назначение
Докстринг: «Independently written reconstruction policies; no upstream source port.» Четыре политики выбора следующего хопа: `HopOracle` (`name = "TBR_style_hop_oracle"`), `GLR`, `SourceDijkstra` (`"TSR_source_dijkstra"`), `ContactRouting` (`"CGR_contact_plan"`). Константа `POLICY_NAMES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan")`.

### 2.2 Входы и выходы
Интерфейс — утиная типизация (базового класса и Protocol нет): атрибут `name`; `choose(packet, context)` → `Decision` или `None`; `stats()` → словарь. `Decision(neighbor, not_before_tick)` и `RoutingContext(tick, adjacency, ranges_km, permitted_neighbors, cfg)` — frozen dataclass; `permitted_neighbors` — кортеж `int`. Поля пакета, которые читают политики: `destination, location, source, visited, hops, header, expiry_tick, size_bytes`. `None` означает ожидание; симулятор требует точный тип `int` у обоих полей `Decision` (часть A2). Файлов политики не читают и не пишут.

### 2.3 Основные классы и функции
**`HopOracle.choose`.** `_bfs` — невзвешенные расстояния в хопах от `packet.destination` по текущей `adjacency` (недостижимо `-1`). Кандидаты — `permitted_neighbors` с расстоянием `>= 0`; пусто → `None`; иначе `min(candidates, key=(distances[v], v))` и `Decision(chosen, context.tick)`. `visited` не используется (вывод: возврат в посещённый узел возможен). Кэш одного последнего графа: `_topology` — копия `adjacency`, `_distances` — по точному `int` назначения; кэш работает, если тип точно `np.ndarray`, 2-D, `dtype.kind` из `biuf`, а форма, dtype и все элементы совпадают (`np.array_equal`); иначе BFS без кэширования. `stats()` — одна строка: «exact unweighted BFS per hop; Fig.5 brute-force timing NON-COMPARABLE» («Fig.5» — рисунок статьи, не входит в экспорт).

**`GLR(predictor, n, model_config=None)`.** `model_config` по умолчанию `ModelConfig()` (`config.py`, `features = TOPOLOGY_FEATURES`), проверяется `validate()`; счётчики `inference_count`, `inference_seconds`, `cache_hits`; кэш из одной записи `_key`/`_scores`. Контракт предиктора (комментарий): без режима задержки (по умолчанию) `predictor(A, None)`, с необязательным расширением `predictor(A, ranges_km)`; результат — оценки `[destination, candidate]` формы `(n, n)`; смена весов требует нового экземпляра. Модель в `policies.py` не создаётся (описана в `03_LEARNING_RU_part2.md`); кто строит `predictor`, не установлено. `choose`:
1. `validate_adjacency` (`features.py`: квадратная, бинарная, симметричная, нулевая диагональ → `bool`); форма не `(n, n)` → `ValueError("GLR fixed-N adjacency mismatch")`.
2. `candidates` = `permitted_neighbors` минус `packet.visited`; пусто → `None` (предиктор не вызывается).
3. Ключ: `(adjacency.tobytes(), canonical_json(asdict(model_config)))`; при `uses_delay` добавляется `ranges.tobytes()` (после `validate_ranges` и проверки `delay_features`, результат не используется). Ручной расчёт: при `n = 132` часть ключа `adjacency.tobytes()` занимает `132 · 132 = 17424` байта.
4. Ключ ≠ `_key`: вызов предиктора с копиями аргументов, `np.asarray(dtype=float)`, время — в `inference_seconds`; не `(n, n)` или не конечные значения → `ValueError("GLR predictor must return finite [destination,candidate] scores")`; затем `inference_count += 1`, сохраняются ключ и копия оценок. Иначе `cache_hits += 1`. Назначения в ключе нет: одна матрица обслуживает все назначения графа; запись заменяется при смене графа.
5. `min(candidates, key=(scores[destination, v], v))`: наименьшая оценка, ничья — меньший номер; `Decision(neighbor, context.tick)`. Допустимы конечные отрицательные оценки, маркера «недостижимо» нет. Смысл оценки в `policies.py` не указан. Запасного хода нет: без непосещённых допустимых соседей — ожидание.
`stats()`: `inference_count`, `inference_seconds`, `inference_seconds_per_call`, `cache_hits`, `feature_spec`, `feature_role`, `cache_boundary`, `unreachable_behavior = "no reachability oracle; no candidate waits, including all-neighbors-visited"`.

**`source_dijkstra` и `SourceDijkstra` (TSR).** `source_dijkstra(source, destination, size_bytes, context)`: куча `(стоимость, узел)`; вес ребра `size_bytes / cfg.rate_bytes_s + ranges_km[node, neighbor] / cfg.light_speed_km_s` (секунды) по графу и дальностям тика вызова; очереди, занятость и `permitted_neighbors` не учитываются; результат — список узлов `[source, …, destination]` или `[]`. Предшественник меняется только при строгом улучшении; соседи — по возрастанию номеров (вывод: ничья решается порядком обхода).
Ручной расчёт (умолчания): сериализация `18000 / 12500 = 1.44 с` на хоп; распространение `<= 3500 / 299792.458 ≈ 0.01167 с`; путь из `k` хопов стоит `1.44·k` плюс сумма распространений `<= 0.01167·k`. Вывод: он дешевле любого пути из `k+1` хопов при `k <= 123` (`0.01167 · 123 ≈ 1.435 < 1.44`).
`choose`:
1. `header is None`: `location != source` → `ValueError("source header missing after forwarding")`; иначе `header = source_dijkstra(...)`, `source_searches += 1`. Поиск выполняется один раз, при первом вызове на источнике; заголовок хранится в пакете и не пересчитывается.
2. `header == []` → `None` (источник недостижим при первом поиске: пустой заголовок остаётся, перепланировки нет, пакет ждёт до TTL).
3. `hops >= len(header)` или `header[hops] != location` → `ValueError("source header/location mismatch")`; `hops + 1 >= len(header)` → `None`.
4. `neighbor = header[hops + 1]`; не в `permitted_neighbors` → `None` (комментарий: отсутствующее, занятое или заблокированное буфером ребро ждёт до TTL); иначе `Decision(neighbor, context.tick)`.
`stats()`: `source_searches`, `repair = "none"`, `source_search_time`.

**`ContactRouting(plan)` (CGR).** `plan` — `ContactPlan` (`02_ENVIRONMENT_RU_part5.md`, раздел 3: `earliest_hop` — зависящий от времени алгоритм Дейкстры с ожиданием на рёбрах). `choose`:
1. `plan_queries += 1` на каждый вызов, в том числе при попадании в память.
2. Память отрицательных ответов `_none_memo`: `id(packet)` → `[packet, cfg, plan, {ключ: первый тик с None}]`, ключ `(location, destination, expiry_tick, size_bytes)`; запись сбрасывается, если пакет, `cfg` или `plan` — другие объекты. При `context.tick >= known` сразу `None` (тик проверяется `integer(..., "now_tick", 0)`). Обоснование (комментарий): `None` в тике t означает `None` во всех t' >= t; положительные ответы не переиспользуются. Вытеснения записей нет (вывод: память растёт с числом пакетов).
3. `plan.earliest_hop(location, destination, context.tick, expiry_tick, size_bytes, context.cfg)`: поиск от текущего узла, дедлайн — TTL пакета (внутри ограничен `horizon_tick`).
4. `None` → запоминается тик, возврат `None`. Иначе `Decision(route.neighbor, route.departure_tick)` — первый хоп плана; отправление может быть позже текущего тика (тогда симулятор ждёт: `scheduled_future_contact`). Комментарий: очереди и случайные отказы план не прогнозирует. `permitted_neighbors` и `visited` не используются; допустимость проверяет симулятор при `departure_tick == tick`. Перепланирование — при каждом вызове.
`stats()`: `plan_queries`, `contact_plan = plan.metadata()`, `replanning`, `knowledge`.

### 2.4 Значения по умолчанию
Собственных чисел нет. `GLR(model_config=None)` → `ModelConfig()` (`config.py`: `features = TOPOLOGY_FEATURES`, `gcn_width 32`, `dense_width 64`). Остальное — из `SimulationConfig`: `rate_bytes_s 12500.0`, `light_speed_km_s 299792.458`.

### 2.5 Связи с другими модулями
Импортирует: `config` (`ModelConfig, canonical_json, integer`), `features` (`delay_features, validate_adjacency, validate_ranges`), `numpy`, стандартные `collections, dataclasses, heapq, math, time`. Используется: `simulator.py` (`RoutingContext`), `tbr_policy.py` (`Decision`); прочие импортёры не установлены.

### 2.6 Побочные эффекты
Файлов нет; случайности в самих политиках нет. Состояние: кэши и счётчики `HopOracle`, `GLR`, `ContactRouting`; запись `packet.header` в TSR; `perf_counter` в `GLR`.

### 2.7 Что в коде названо допущением или реконструкцией
Докстринг модуля (см. 2.1). Комментарии `GLR`: режим без задержки назван «paper-faithful», режим с `ranges` — «OPTIONAL delay extension (not in the paper)»; в `HopOracle.stats` — «NON-COMPARABLE».

### 2.8 Что не установлено чтением
Как строится `predictor` и что означает оценка; где используется `POLICY_NAMES` и кто создаёт политики (`simulate.py`, части B); соответствие первоисточникам (в коде заявлено лишь «independently written»); эквивалентность кэшей прежней версии (тесты не в экспорте); работоспособность (ничего не запускалось). Наблюдения без исправлений: `HopOracle` и `ContactRouting` не учитывают `visited`; `TBR_bounded_exhaustive_reference` (`tbr_policy.py`) отсутствует в `POLICY_NAMES`; в `_none_memo` нет вытеснения.

## Состав набора 04
Описаны: `simulator.py` (части A1, A2), `policies.py` (часть A3). Не описаны здесь: `tbr_policy.py`, `tbr_reference.py`, `simulate.py` — части B1, B2 (`04_SIMULATION_POLICIES_RU_partB1.md`, `04_SIMULATION_POLICIES_RU_partB2.md`) и индекс `04_SIMULATION_POLICIES_RU.md`.
