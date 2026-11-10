# 02. Среда моделирования. Часть 6 из 8: graph.py

Файл: `src/ssn_hops/graph.py` (3775 байт). Условные обозначения — в `02_ENVIRONMENT_RU.md`. Для точности описания дополнительно прочитан `features.py` (функции `validate_adjacency`, `validate_ranges`, `delay_features`, которые вызывает `graph.py`); подробное описание `features.py` относится к другой части документации.

## 1. Назначение

Докстринг: «Undirected binary graphs, exact labels and explicit feature reconstruction.» Модуль по матрице смежности `A` строит:
- точные метки — кратчайшие числа хопов между всеми парами узлов (`shortest_hops`);
- вспомогательную структуру «1 / 0.5 / 0» (`preprocessed_structure`, `exclusive_two_hop_mask`);
- тензоры PyTorch для двух ветвей сети и список рёбер (`branch_inputs`).

## 2. Входы и выходы
- Вход: матрица смежности `[N, N]` (любой числовой тип с значениями 0/1); необязательно — матрица расстояний `ranges_km` и `ModelConfig`.
- Выход: массивы NumPy (метки, маски, структура) или тензоры `torch` (`branch_inputs`).
- Файлов не читает и не пишет. Случайности нет.

## 3. Проверка входной матрицы (`features.py`, `validate_adjacency`)
Каждая функция `graph.py` начинает с неё. Требуется: двумерный квадратный массив, `N >= 2`; тип `bool`/целый/беззнаковый/`float`; все значения конечны и равны 0 или 1; нулевая диагональ; симметрия (`array == array.T`). Результат — массив `bool`. Нарушение → `ValueError` («adjacency must be square [N,N], N>=2», «adjacency must be finite binary values», «adjacency must be undirected with zero diagonal»).

## 4. Функции

### `shortest_hops(adjacency, mask_diagonal=True)`
- Докстринг: «Exact unweighted BFS from every node. -1 denotes unreachable, diagonal=0. Axes are [destination, candidate]; undirected labels are symmetric.»
- Алгоритм: для каждого `destination` — поиск в ширину по спискам соседей; `result[destination, node]` — число хопов от `node` до `destination` (по рёбрам неориентированного графа).
- Возвращает `(result, mask)`: `result` — `int32` `[N, N]`, `-1` для недостижимых пар, `0` на диагонали; `mask = result >= 0` и, при `mask_diagonal=True` (значение по умолчанию), диагональ в маске `False`.
- Комментарий: маска — это конечные достижимые пары без диагонали; «never sentinel loss» — значения `-1` в потерю не входят.
- Вывод из чтения: из-за симметрии `A` матрица меток симметрична; число хопов — это кратчайший путь по рёбрам текущего снимка без весов и без расстояний; сложность по коду — порядка `N·(N + E)`.

### `exclusive_two_hop_mask(adjacency)`
Булева маска `[N, N]` пар, достижимых ровно через общего соседа и не являющихся соседями: `two_hop = (A·A > 0)` (целочисленное произведение `int64`), затем `two_hop &= ~A`, диагональ `False`. Значений 1/0.5 в ней нет (докстринг).

### `preprocessed_structure(adjacency)`
- Докстринг: «Paper Sec. III-B preprocessed input Q (reconstruction of its N x N layout)». В коде это реконструкция размещения, а не восстановленный оригинал.
- Возвращает `float32` `[N, N]`: `Q = A + 0.5 · two_hop_mask`, то есть `1.0` для соседей, `0.5` для пар «только через общего соседа», `0.0` для остальных; диагональ строго нулевая. Пара, которая одновременно сосед и имеет общего соседа, остаётся `1.0` (маска исключает соседей).
- Назначение (комментарий): только столбцы признаков; распространение в графовой свёртке остаётся на исходной бинарной `A`.

Ручной пример (3 узла, путь 0–1–2): `A = [[0,1,0],[1,0,1],[0,1,0]]`; `A·A = [[1,0,1],[0,2,0],[1,0,1]]`; после исключения соседей и диагонали остаются пары `(0,2)` и `(2,0)`; `Q = [[0,1,0.5],[1,0,1],[0.5,1,0]]`; `shortest_hops` даёт строки `[0,1,2]`, `[1,0,1]`, `[2,1,0]`, маска (при `mask_diagonal=True`) истинна всюду, кроме диагонали. Это ручной расчёт по тексту кода, не результат запуска.

### `exclusive_two_hop`
Присваивание `exclusive_two_hop = preprocessed_structure`. Комментарий кода: «thin backward-compatible alias»; несмотря на название, возвращает комбинированную структуру `Q` (значения 1/0.5/0), а не булеву маску; «Remove after tests migrate» (тесты в экспорт не входят). В докстринге `preprocessed_structure` упомянута внутренняя метка аудита «T021 F003» (документ не входит в экспорт).

### `branch_inputs(adjacency, device="cpu", *, ranges_km=None, model_config=None)`
- Если `model_config is None`, берётся `ModelConfig()` (режим `TOPOLOGY_FEATURES`); вызывается `config.validate()`.
- Строятся `a` — `float32`-тензор `A`; `q` — тензор `Q`; оба на `device`.
- Режим без задержки (по умолчанию и устаревший синоним): `low = A` (`N × N`), `high = [A | Q]` (`torch.cat((a, q), dim=1)`, `N × 2N`); `ranges_km` не используется.
- Режим расширения с задержкой: `ranges_km` обязателен (иначе `ValueError("delay mode requires ranges_km in km")`); `d = delay_features(...)`; `low = [A | D]` (`N × 2N`), `high = [A | Q | D]` (`N × 3N`).
- Список рёбер: `edges = torch.tensor(np.stack(np.nonzero(array)), dtype=torch.long)`, форма `[2, E]`; так как `A` симметрична, каждое ребро присутствует в обоих направлениях (комментарий: «Both directions of ORIGINAL binary A; no delay/two-hop propagation weights.»).
- Возвращает кортеж `(low, high, edges)`.
- Ручной расчёт форм при `N = 132`: `low` `132×132`, `high` `132×264`; в режиме задержки `132×264` и `132×396`.
- Сбои: ошибки `validate_adjacency` и `ModelConfig.validate`; отсутствие `ranges_km` в режиме задержки; неверная строка `device` приведёт к ошибке `torch` (вывод из чтения; не проверялось).

### Канал задержки `D` (`features.py`, `delay_features`)
Только для режима расширения. Нужен `ModelConfig` в режиме `DELAY_FEATURES` (иначе `ValueError`); `ranges_km` проверяется (`validate_ranges`: вещественный, конечный, неотрицательный, симметричный). `D[i, j] = (ranges[i, j] / light_speed_km_s) / delay_scale_s` только там, где `A[i, j]` истинно; в остальных местах и на диагонали — ноль; результат приводится к `float32` и обязан быть конечным. С константами по умолчанию (`299792.458`, `0.01`) расстояние `3500 км` соответствует значению `3500 / 299792.458 / 0.01 ≈ 1.167` (ручной расчёт).

## 5. Нормировка
В `graph.py` нормировки нет: тензоры `a`, `q`, `edges` отдаются «как есть» (двоичные значения и значения `0.5`). В `config.py`, `ModelConfig.feature_spec`, записано, что распространение выполняется на «original binary A with GCN A+I normalization». Где и чем эта нормировка выполняется (вероятно, свёрточным слоем в `model.py`), чтением `graph.py` не установлено.

## 6. Значения по умолчанию
`mask_diagonal=True` (`shortest_hops`); `device="cpu"` (`branch_inputs`); `model_config=None` → `ModelConfig()`. Числовых констант модель/сеть в `graph.py` нет.

## 7. Связи с другими модулями
- Импортирует: `config.py` (`ModelConfig`), `features.py` (`delay_features`, `validate_adjacency`); `numpy`, `torch`, `collections.deque`. Сторонние зависимости: `numpy` и `torch` на уровне модуля (поэтому импорт `graph.py` требует установленного `torch`).
- Импортируется (по чтению строк `import`): `model.py`, `data.py`, `training.py`. Сами эти файлы в этой части не перечитывались.

## 8. Побочные эффекты
Нет файлов, нет случайности, нет глобального состояния. Создаются тензоры на указанном `device`.

## 9. Допущения и реконструкция в коде
- «Paper Sec. III-B preprocessed input Q (reconstruction of its N x N layout)».
- Режим по умолчанию в `branch_inputs` назван «paper-faithful topology-only».
- Режим задержки — «optional, not in the paper».

## 10. Что не установлено чтением (graph.py)
- Где выполняется нормировка «A+I» и что именно делают `model.py`/`training.py` с тремя возвращаемыми тензорами.
- Как `data.py` вызывает `shortest_hops` (какое именно `mask_diagonal` и откуда берётся `A`).
- Поведение на устройствах `cuda` (в коде не разбирается здесь).
- Ничего не запускалось: корректность функций проверена только чтением и ручным примером.
