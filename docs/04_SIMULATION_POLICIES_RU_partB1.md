# 04. Симуляция и политики. Часть B1 из B2: tbr_reference.py и tbr_policy.py

Файлы `src/ssn_hops/tbr_reference.py` (6583 байта) и `tbr_policy.py` (5473 байта). «В коде написано» — пересказ или цитата; «вывод из чтения» — заключение без запуска; «ручной расчёт» — арифметика в тексте. Ничего не запускалось: о работоспособности и результатах утверждений нет. Состав набора 04 — в `04_SIMULATION_POLICIES_RU.md`. Документы из строк кода (`TBR_REFERENCE_SPEC.md`, `TBR_NATIVE_ADAPTER.md`) в экспорт не входят.

## 0. Три похожих имени

- `policies.HopOracle` (`name = "TBR_style_hop_oracle"`, есть в `POLICY_NAMES`): BFS-расстояния до назначения по текущему графу, выбор допустимого соседа с минимумом `(distance, id)`; `packet.visited` не читается, шаг назад возможен (вывод из чтения); границ нет.
- `tbr_policy.TBR_bounded_exhaustive_reference` (`name = "TBR_bounded_exhaustive_reference"`, в `POLICY_NAMES` нет): политика с `choose`; перебор допустимых простых путей, `visited` учитывается, границы есть.
- `tbr_reference.exhaustive_simple_path_reference`: функция-ядро перебора, не политика; её вызывает предыдущий класс.

`policies.py` не импортирует `tbr_*.py`; общего базового класса нет (в коде написано).

## 1. tbr_reference.py

### 1.1 Назначение
Докстринг: «Bounded exhaustive reference, independently specified; NOT author TBR code». Перебирает все допустимые простые пути `source → destination`, выбирает по ключу `(число рёбер, весь путь)`; при превышении границы вместо маршрута — исключение.

### 1.2 Входы и выходы
`exhaustive_simple_path_reference(adjacency, source, destination, *, permitted_first_hops, visited=(), max_nodes=12, max_expansions=100000)`. `adjacency` проверяет `features.validate_adjacency` (квадратная, `N >= 2`, двоичная, симметричная, нулевая диагональ). Выход — `TBRReferenceResult`; ошибки — `ValueError` (вход) и `TBRSearchIncomplete` (граница). Файлов нет.

### 1.3 Основные классы и функции
- `TBRReferenceResult(status, path, edge_count, expansions, complete_paths)`: `status` — `"route"` или `"no_route"`; `path` — кортеж `int` или `None`; `complete`, `search_identity`, `objective` — `init=False`. Докстринг: «never a partial route or incomplete no-route».
- `TBRIncompleteDetails(reason, node_count, max_nodes, max_expansions, expansions)`: `reason` — `"max_nodes"` или `"max_expansions"`; лучшего пути в нём нет намеренно. `TBRSearchIncomplete(RuntimeError)` хранит `details`.
- `_integer`, `_node_id` (`0 <= ID < n`), `_id_set`: целые (в том числе NumPy), не `bool`; наборы без повторов; нарушение — `ValueError`.

Порядок в функции: (1) проверки аргументов, границы `> 0`; (2) каждый элемент `permitted_first_hops` — настоящий сосед `source`; (3) `n > max_nodes` → `TBRSearchIncomplete("max_nodes")`, `expansions=0` (после проверок, в том числе при `source == destination`); (4) `first_hops = permitted − visited`, `blocked = visited − {source}`; (5) поиск в глубину на стеке префиксов, старт `(source,)`, соседи кладутся в обратном порядке (префиксы входят по возрастанию номеров). Перед входом при непустом стеке: `expansions == max_expansions` → `TBRSearchIncomplete("max_expansions")`, иначе `expansions += 1`. `destination` терминален: `complete_paths += 1`, лучший путь по `(len(path), path)`. Иначе в стек идут соседи вне `blocked` и вне пути; на первом шаге — только из `first_hops`. Лучшего нет → `"no_route"`; иначе `"route"`, `edge_count = len(path) − 1`.

Вывод из чтения: `visited` блокирует узлы на всех шагах (кроме `source`), `permitted_first_hops` — только первый шаг; если `destination` в `visited` (и это не `source`), результат `no_route`; возврат в узел пути или `visited` невозможен; ровно `max_expansions` входов достаточно, если стек затем пуст (докстринг: «Exactly max_expansions entries suffice»).

Ручной расчёт: рёбра 0–1, 1–2; `source=0`, `destination=2`, `permitted={1}`, `visited={0}`. Вход 1: `(0,)` → стек `[(0,1)]`; вход 2: `(0,1)`: сосед `2` добавлен, `0` в пути → `[(0,1,2)]`; вход 3: назначение. Итог: `route`, `path=(0,1,2)`, `edge_count=2`, `expansions=3`, `complete_paths=1`. При `max_expansions=2` после двух входов стек не пуст → `max_expansions`; при `max_nodes=2` → `max_nodes` (`3 > 2`).

### 1.4 Значения по умолчанию
`SEARCH_IDENTITY = "bounded_exhaustive_simple_paths_v1"`, `OBJECTIVE = "min_edges_then_lexicographic_full_path"`, `DEFAULT_MAX_NODES = 12`, `DEFAULT_MAX_EXPANSIONS = 100000`. Ручной расчёт: `config.OrbitConfig.n = 132 > 12`, значит при умолчаниях отказ по `max_nodes` наступает до поиска.

### 1.5 Связи с другими модулями
Импортирует `features.validate_adjacency`, `numpy` и стандартные модули. Используется `tbr_policy.py` и `simulate.py`; прочие импортёры не установлены.

### 1.6 Побочные эффекты
Нет: ни файлов, ни глобального состояния, ни случайности; аргументы не изменяются («No mutation of caller arrays/masks»).

### 1.7 Что в коде названо допущением или реконструкцией
«independently specified; NOT author TBR code»; «No policy registration, runtime measurement, BFS fallback or shortest-path pruning».

### 1.8 Что не установлено чтением
Соответствие алгоритму авторов; число префиксов на геометрических графах; работоспособность и тесты (не в экспорте).

## 2. tbr_policy.py

### 2.1 Назначение
Докстринг: «Isolated native Decision adapter; independently specified, NOT author TBR». `TBR_bounded_exhaustive_reference` переводит результат ядра в `policies.Decision`; каждый `choose` — новый перебор («A fresh exhaustive search per choose call»); кэша, заголовка пакета и запасного BFS нет (докстринг).

### 2.2 Входы и выходы
`TBR_bounded_exhaustive_reference(*, max_nodes=12, max_expansions=100000)`; `_positive_budget`: целое, не `bool`, `> 0`, иначе `ValueError`. `choose(packet, context)` → `Decision(path[1], context.tick)` или `None`; `stats()` → словарь; свойства `max_nodes`, `max_expansions`. Файлов нет.

### 2.3 Основные классы и функции
`choose`: `_policy_calls += 1`; ядро получает `context.adjacency`, `packet.location`, `packet.destination`, `permitted_first_hops=context.permitted_neighbors`, `visited=packet.visited`, границы. Далее:
- `TBRSearchIncomplete`: `_incomplete_searches += 1`, `_incomplete_prefix_entries += details.expansions`, счётчик причины (кроме `max_nodes` засчитывается `max_expansions`); тот же объект пробрасывается, «never a route/drop».
- `ValueError`: `_invalid_input_calls += 1`, проброс («NOT complete no-route»).
- успех: `_completed_searches`, `_completed_prefix_entries += expansions`, `_completed_destination_paths += complete_paths`; нет пути → `None`; `len(path) == 1` → `None` (комментарий «Terminal zero-hop: do not forward to the current node»); иначе `Decision`.

Вывод из чтения: `path[1]` лежит в `first_hops`, то есть среди `permitted_neighbors`, и имеет тип `int` (ядро строит соседей через `int(v)`), поэтому проверки `Simulator._schedule` (тип, `in permitted`) для него выполняются; `not_before_tick = context.tick`. Исключения проходят через `Simulator._schedule` без перехвата (вокруг `policy.choose` нет `try`), `Simulator.run` прерывается. `None` оставляет пакет в голове очереди, поиск повторяется на следующем тике.

`stats()`: 20 ключей — 5 строк идентичности (`policy_identity`, `search_identity`, `objective`, `algorithm`, `budget_scope`), `max_nodes`, `max_expansions`, 12 счётчиков с теми же именами, что внутренние (`policy_calls`, `completed_searches`, `incomplete_searches`, `invalid_input_calls` и др.), и `total_prefix_entries` (сумма `completed_` и `incomplete_prefix_entries`).

### 2.4 Значения по умолчанию
Границы 12 и 100000 (`tbr_reference.py`); счётчики 0; `name = "TBR_bounded_exhaustive_reference"`.

### 2.5 Связи с другими модулями
Импортирует `numbers.Integral`, `numpy`, `policies.Decision`, `tbr_reference`. Используется `simulate.py`; прочие импортёры не установлены.

### 2.6 Побочные эффекты
Счётчики экземпляра; файлов нет; «Instances are intended for sequential use».

### 2.7 Что в коде названо допущением или реконструкцией
«independently specified, NOT author TBR»; «Bounds are independent safety controls, not settings attributed to authors». Отсутствие в `POLICY_NAMES` в коде объяснено так: докстринг — «No registration»; комментарий `simulate.py` — «ONLY this command opts in. Do not extend legacy POLICY_NAMES or suite defaults» (часть B2).

### 2.8 Что не установлено чтением
Соответствие алгоритму авторов; как часто поиск укладывается в границы на геометрических графах; работоспособность и тесты (не в экспорте).
