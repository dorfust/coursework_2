# 02. Среда моделирования. Часть 5 из 8: contacts.py

Файл: `src/ssn_hops/contacts.py` (9769 байт). Условные обозначения — в `02_ENVIRONMENT_RU.md`.

## 1. Назначение

Докстринг: «Scheduled geometric contacts on an explicit right-continuous tick grid.» Модуль даёт два независимых механизма работы с динамикой связей:
1. `GeometryNetwork` — поставщик «мгновенного» графа на каждом тике (используется симулятором): матрица смежности и расстояния на тике `k`.
2. `ContactPlan` и `build_geometric_plan` — заранее построенный план контактов (интервалы существования каждого ребра) и поиск самого раннего пути с ожиданием («earliest_hop»); используется политикой, основанной на плане контактов.

## 2. Входы и выходы
- Вход: `SimulationConfig` (`sim_config.py`), номер тика, размер пакета в байтах, тики отправки/дедлайна.
- Выход: `(adjacency, ranges)` (`GeometryNetwork.snapshot`); `ContactPlan`; `PlannedHop(neighbor, departure_tick, arrival_tick)` или `None` (`ContactPlan.earliest_hop`).
- Файлов не читает и не пишет.

## 3. Классы и функции

### `GeometryNetwork(cfg)`
- Конструктор: `self.cfg = cfg.validate()`; `self.trajectory = make_trajectory(cfg.orbit, cfg.phase_seed)`; кэш одного снимка (`_tick`, `_snapshot`); счётчик `snapshot_builds = 0`. Докстринг: «One shared range/LOS predicate, with only the most recent snapshot cached.»
- `snapshot(tick)`: `integer(tick, "tick", 0)`; если `tick` отличается от закэшированного, считает положения `trajectory.positions_km(tick * cfg.tick_s)` и вызывает `graph_from_positions(positions, cfg.orbit)`; увеличивает `snapshot_builds`; возвращает кортеж `(adjacency, ranges)` (тот же объект при повторном запросе того же тика). Верхняя граница `tick` не проверяется (вывод из чтения: запрос тика выше `horizon_tick` допустим).
- Время в секундах для тика `k` — `k * tick_s` с отсчётом от нуля; `epoch_s` орбиты учитывается внутри `positions_km` (см. часть 4).

### `Contact(start_tick, end_tick)`
Неизменяемая запись интервала; `end_tick` — исключающий конец («exclusive cell end; completion exactly at this boundary allowed» — завершение передачи ровно на границе разрешено).

### `PlannedHop(neighbor, departure_tick, arrival_tick)`
Результат запроса. Комментарий: `arrival_tick` — прибытие в конечный пункт назначения, а не только окончание первого хопа.

### `ContactPlan(n, horizon_tick, intervals, distance_at)`
Конструктор принимает словарь «ребро → последовательность `Contact`» и функцию `distance_at(tick, u, v)` (расстояние в км в начале передачи). Проверки (все `ValueError`):
- `n` — целое `>= 2`; `horizon_tick` — целое `>= 1`;
- ребро — пара `(u, v)` целых `0 <= u < v < n` (канонический неупорядоченный вид);
- интервалы ребра упорядочены, не пересекаются (допускается касание: `previous_end <= start`), `start < end <= horizon_tick`.
Рёбра обходятся в отсортированном порядке; ребро без интервалов в план не попадает. Строятся `self.intervals` (ребро → кортеж контактов) и списки соседей `self.neighbors[u]` (отсортированные; соседом считается любой, у кого есть хотя бы один контакт за всё время).

`metadata()` → словарь: `schema="ssn-contact-grid-v1"`, `n`, `horizon_tick`, `interval_count`, `interval_sha256` (хэш списка `{"edge", "cells"}`) и `semantics="true sample at k holds on [k*dt,(k+1)*dt); ends allow completion"`. Эта строка — само определение семантики: граф, вычисленный на тике `k`, считается верным на промежутке `[k·dt, (k+1)·dt)`, а контакт `[start, end)` покрывает тики `start … end−1`.

### `ContactPlan._edge_arrival(u, v, earliest, deadline, size_bytes, cfg, limit=inf)`
Возвращает `(arrival, departure)` — лексикографический минимум среди допустимых отправлений `departure >= earliest`, либо `None`.
- Для каждого контакта ребра `(min(u,v), max(u,v))`: `start = max(earliest, contact.start_tick)`, `stop = min(contact.end_tick, deadline)`; пустые окна пропускаются.
- Для кандидата `departure` длительность `duration = service_ticks(size_bytes, cfg.rate_bytes_s, distance_at(departure, u, v), cfg.light_speed_km_s, cfg.tick_s)`, `arrival = departure + duration`. Кандидат допустим, если `arrival <= stop` (завершить можно ровно на границе контакта или дедлайна) и `arrival < limit`; лучшим считается меньшая пара `(arrival, departure)`.
- Отсечение перебора: `s_min = service_ticks(..., расстояние 0.0, ...)` (вычисляется лениво при первом непустом окне); отправления перебираются `range(start, stop − s_min + 1)` и перебор прерывается, как только `departure + s_min >= текущий лучший arrival (или limit)`. Комментарии кода обосновывают, что это отсечение даёт тот же результат, что и полный перебор («BASELINE b6f5f516», ссылки на тесты `tests/reference/contacts_ref.py` и на внутренние метки «T054», «DESIGN T048 Q5 O-1/O-1b»; эти документы и тест не входят в экспорт). Единственное названное различие: на пропущенных отправлениях `distance_at`/`service_ticks` не вызываются, поэтому недопустимые расстояния там больше не вызывают исключения.
- Ручной расчёт: при значениях по умолчанию `s_min = 15` тиков (см. часть 3: `raw = 1.44 / 0.1 = 14.4`, округление вверх до 15).

### `ContactPlan.earliest_hop(source, destination, now_tick, deadline_tick, size_bytes, cfg)`
Докстринг класса: «time-dependent Dijkstra with WAITING CLOSURE on every edge: it minimizes over all feasible departure ticks in future contacts. It is not Dijkstra on the current-neighbor graph.» Это значит: пакет может ждать в узле до начала следующего контакта; ожидание считается бесплатным (без буферных ограничений и без конкуренции за канал — вывод из чтения: в плане нет ни занятости узлов, ни буферов).
- Проверки: `source`, `destination` в `[0, n)`, иначе «contact query endpoint out of range»; `now_tick`, `deadline_tick` — целые `>= 0`; `cfg.orbit.n == self.n`, иначе «contact/config N mismatch».
- `deadline = min(deadline_tick, horizon_tick)`; если `source == destination` или `now_tick >= deadline` — возвращается `None`.
- Алгоритм: метки `labels[node]` (время прибытия, начальная `inf`, у источника `now_tick`); куча `(arrival, node)`; для каждого соседа вызывается `_edge_arrival(node, neighbor, arrival, deadline, size_bytes, cfg, limit=labels[neighbor])`; при улучшении метки запоминается первый хоп `first[neighbor]` = `(neighbor, departure)` для соседей источника или унаследованный `first[node]`. Когда из кучи извлекается узел назначения, возвращается `PlannedHop(first_neighbor, first_departure, arrival)`; если очередь исчерпана — `None`.
- Выбор при равных прибытиях: кортежи кучи упорядочиваются по `(arrival, node)`, то есть по меньшему номеру узла (вывод из чтения).
- Ограничения числа хопов и TTL (кроме `deadline_tick`) в этой функции нет; TTL передаётся вызывающим как `deadline_tick` (вывод из чтения; как именно вызывает политика — вне этой части).

### `build_geometric_plan(cfg)`
Докстринг: «Stream graphs into intervals; retain positions only, never an H*N*N cube.»
1. `cfg.validate()`; `trajectory = make_trajectory(cfg.orbit, cfg.phase_seed)`.
2. Массив `positions` формы `(horizon_tick, n, 3)`, `float64`. Ручной расчёт при значениях по умолчанию: `9000 · 132 · 3 · 8 байт = 28 512 000 байт ≈ 28.5 МБ`.
3. Для `tick` от `0` до `horizon_tick − 1`: положения на `tick * tick_s`; `adjacency` из `graph_from_positions`; множество рёбер `current` — верхний треугольник `np.triu(adjacency, 1)`; рёбра, исчезнувшие по сравнению с открытыми, закрываются: `Contact(opened.pop(edge), tick)`; новые рёбра открываются: `opened[edge] = tick`.
4. После цикла все ещё открытые рёбра закрываются в `horizon_tick`: `Contact(start, horizon_tick)`.
5. Функция `distance_at(tick, u, v)` — евклидова норма разности положений из того же массива `positions`.
6. Возвращает `ContactPlan(cfg.orbit.n, cfg.horizon_tick, intervals, distance_at)`.
Вывод из чтения: граф для плана строится той же функцией `graph_from_positions` и тем же сидом `phase_seed`, что и в `GeometryNetwork`, поэтому правило видимости и дальности для плана и для мгновенных снимков одно и то же. Ключи словаря `intervals` при этом создаются как кортежи `(int, int)` с `u < v`.

## 4. Значения по умолчанию
Собственных констант нет. Используются поля `SimulationConfig` (часть 3): `tick_s=0.1`, `observation_end_s=900.0` (→ `horizon_tick=9000`), `phase_seed=401`, `packet_bytes=18000`, `rate_bytes_s=12500.0`, `light_speed_km_s=299792.458`; и `OrbitConfig` (часть 1).

## 5. Связи с другими модулями
- Импортирует: `config.py` (`content_hash`, `integer`), `geometry.py` (`graph_from_positions`, `make_trajectory`), `sim_config.py` (`service_ticks`); `numpy`, стандартные `heapq`, `math`, `dataclasses`.
- Импортируется: `simulator.py` (`GeometryNetwork`; прочитано) и `simulate.py` (`build_geometric_plan`; по чтению его строк `import`). Использование `ContactPlan.earliest_hop` политикой плана контактов указано в `policies.py` как ожидаемый интерфейс (методы `earliest_hop` и `metadata`; по чтению отдельных файлов, не по этому шагу).

## 6. Побочные эффекты
Файлов нет. Случайности в самом модуле нет: сид `phase_seed` используется только через `make_trajectory`. Состояние: кэш последнего снимка и счётчик `snapshot_builds` в `GeometryNetwork`; `ContactPlan` после построения не изменяется (вывод из чтения: нет методов-мутаторов, но словари внутри экземпляра изменяемы).

## 7. Что в коде названо допущением или реконструкцией
- Семантика «граф на тике `k` верен на `[k·dt,(k+1)·dt)`» и разрешение завершать передачу на правой границе («ends allow completion») — явное соглашение кода, строка `semantics` в `metadata()`.
- Расстояние в длительности передачи берётся на момент отправления («start-distance», `sim_config.service_ticks`).

## 8. Что не установлено чтением (contacts.py)
- Эквивалентность оптимизированного `_edge_arrival` и «базового» варианта: основана на комментариях и на тесте, которого в экспорте нет; не проверялась запуском.
- Как политика плана контактов задаёт `now_tick`, `deadline_tick`, `size_bytes` (в `policies.py`, не разбирается в этой части).
- Время работы и память на больших горизонтах, кроме ручной оценки массива положений.
