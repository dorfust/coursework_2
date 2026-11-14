# 02. Среда моделирования. Часть 8 из 8: сводка по шести модулям и список «Не установлено чтением»

Модули: `config.py`, `sim_config.py`, `geometry.py`, `contacts.py`, `graph.py`, `traffic.py` (каталог `src/ssn_hops/`). Подробности — в частях 1–7. Все числа ниже взяты из кода (с указанием файла и константы) либо помечены как ручной расчёт.

## 1. Сводка: ключевые параметры среды

| Вопрос | Значение по умолчанию в коде | Где |
|---|---|---|
| Число спутников | `132` | `config.py`, `OrbitConfig.n` |
| Число плоскостей | `12` (по `132 / 12 = 11` спутников в плоскости — ручной расчёт) | `OrbitConfig.planes` |
| Высота орбиты | `1050.0` км (радиус орбиты `6371 + 1050 = 7421` км — ручной расчёт) | `OrbitConfig.altitude_km`, `earth_radius_km` |
| Наклонение | `53.0` градусов | `OrbitConfig.inclination_deg` |
| Тип орбиты | только круговая: `eccentricity = 0.0` обязательно | `OrbitConfig.validate` |
| Предел дальности | `3500.0` км (нестрогое сравнение `<=`) | `OrbitConfig.range_km`; `geometry.py`, `graph_from_positions` |
| Прямая видимость | `earth_los = True`: ближайшая к центру Земли точка отрезка между спутниками не ближе `earth_radius_km` (нестрогое: касание допускается) | `geometry.py`, `graph_from_positions` |
| Длина тика | `0.1` с | `sim_config.py`, `SimulationConfig.tick_s` |
| Горизонт | `observation_end_s = 900.0` → `horizon_tick = 9000` (ручной расчёт) | `SimulationConfig` |
| Длительность хопа | вычисляется функцией: `ceil(((packet_bytes / rate_bytes_s) + distance_km / light_speed_km_s) / tick_s)`, минимум 1 тик; при значениях по умолчанию 15 тиков (ручной расчёт, часть 3) | `sim_config.py`, `service_ticks` |
| Размер пакета | `18000` байт | `SimulationConfig.packet_bytes` |
| Скорость канала | `12500.0` байт/с | `SimulationConfig.rate_bytes_s` |
| Буфер узла | `16000000` байт | `SimulationConfig.buffer_bytes` |
| TTL | `300.0` с → `3000` тиков (ручной расчёт) | `SimulationConfig.ttl_s`, `ttl_ticks` |
| Лимит хопов | не поле конфигурации; в коде `hops >= 2 * n` → `264` для `n = 132` (ручной расчёт) | `simulator.py`, `Simulator._complete` |
| Правило повтора | `additional_retries = 3`; отказ `retry_exhaustion`, когда число неудач подряд на хопе `> 3` | `SimulationConfig`; `simulator.py`, `Simulator._abort` |
| Вероятность отказа передачи | `0.04` на тик, для тиков строго внутри передачи | `SimulationConfig.failure_probability`; `simulator.py`, `Simulator.run` |
| Трафик | один пакет на `arrival_interval_s = 1.0` с до `traffic_end_s = 600.0` с, источник и назначение равновероятно, `n = 132` узла | `traffic.py`, `make_trace` |
| Сиды | `phase_seed = 401`, `traffic_seed = 501`, `failure_seed = 601`; сиды наборов данных `101–108`, `201–202`, `301–302`; сид обучения `17` | `SimulationConfig`; `DataConfig`; `TrainConfig.seed` |

Замечание: значения в JSON-файлах каталога `configs/` в этом документе не разбирались и могут отличаться от значений по умолчанию классов.

## 2. Геометрия коротко
Система координат: инерциальная геоцентрическая, единицы км и с; вращение Земли не моделируется. Положения: круговые орбиты, `phase = 2π·slot/per_plane + plane_phase + ω·(t − epoch_s)`; формулы для `x, y, z` — `geometry.py`, `Trajectory.positions_km`. Видимость: см. строки таблицы выше. Ручные оценки (часть 4): период `≈ 6362 с`; хорда между соседями одной плоскости `≈ 4181 км > 3500 км` (при значениях по умолчанию внутриплоскостных связей нет); предел по касанию Земли `≈ 7611 км`.

## 3. Контакты и смежность коротко
- Мгновенный граф: `GeometryNetwork.snapshot(tick)` → `graph_from_positions` на времени `tick · tick_s`; хранится только последний снимок.
- План контактов: `build_geometric_plan` — на каждом тике от `0` до `horizon_tick − 1` рёбра верхнего треугольника сравниваются с «открытыми»; интервал `[start, end)` на сетке тиков; последний открытый интервал закрывается на `horizon_tick`.
- Поиск пути по плану: `ContactPlan.earliest_hop` — зависящий от времени алгоритм Дейкстры с ожиданием на каждом ребре; завершение на правой границе контакта допускается.

## 4. graph.py коротко
Метки: точные кратчайшие числа хопов (поиск в ширину из каждого узла), `-1` — недостижимо, диагональ `0`, ось `[destination, candidate]`. Признаки: `A` (двоичная), `Q` (`1.0` — соседи, `0.5` — пары только через общего соседа, диагональ `0`); `low = A` (`N × N`), `high = [A | Q]` (`N × 2N`) в режиме по умолчанию; список рёбер `[2, E]` в обоих направлениях. Нормировки в `graph.py` нет.

## 5. traffic.py коротко
Заранее заданная трасса: фиксированный интервал, `random.Random(traffic_seed)`, пары «источник — назначение» равновероятны, размер постоянный; документ с хэшем `sha256` и ключом `trace_key`; отказы передачи — чистая функция `edge_tick_failure` на основе SHA-256.

## 6. Где входит случайность и как задан сид

| Место | Источник | Сид |
|---|---|---|
| `geometry.make_trajectory` | `np.random.default_rng(seed)`: порядок — общий поворот долготы узлов, общий сдвиг фаз, затем (при `independent_plane_offsets`) вектор смещений по плоскостям | `SimulationConfig.phase_seed` (через `contacts.py`); сиды `DataConfig` (через `data.py`, не читался) |
| `traffic.make_trace` | `random.Random(traffic_seed)`: на пакет источник, затем назначение | `SimulationConfig.traffic_seed` |
| `traffic.edge_tick_failure` | хэш SHA-256 по `(seed, min(u,v), max(u,v), tick)`; без состояния | `SimulationConfig.failure_seed` |
| обучение | поле `TrainConfig.seed` (использование в `training.py` не читалось) | — |

В `config.py`, `sim_config.py`, `contacts.py`, `graph.py` собственной случайности нет. Глобальный генератор (`random.seed`, `numpy.random.seed`) в этих шести модулях не используется (по чтению).

## 7. Как работает проверка конфигурации (итог)
- Конфигурации — неизменяемые dataclass; конструктор значения не проверяет.
- `Config.validate()` и `SimulationConfig.validate()` проверяют типы (точный `int`, точный `bool`, конечные числа), диапазоны и согласованность (`n % planes == 0`; кратность времён `tick_s`; `observation_end_s >= traffic_end_s`; уникальность сидов набора данных; фиксированные `delay_scale_s` и `light_speed_km_s` в `ModelConfig`).
- Разбор из словаря (`from_dict`, `from_sim_dict`) отвергает неизвестные поля (`config._section`) и вызывает `validate()`; загрузка из файла — `load_config`, `load_sim_config`.
- Хэши/ключи совместимости: `Config.sha256`, `Config.data_key`, `ModelConfig.feature_spec`, `SimulationConfig.sha256`, `SimulationConfig.trace_key`, `Trajectory.trajectory_id`, `ContactPlan.metadata()["interval_sha256"]`, `trace_document()["sha256"]`; все строятся через `canonical_json` + SHA-256.
- Ошибки всегда `ValueError` (кроме ошибок файла/JSON и `ZeroDivisionError` при некорректном `dt` в `ticks`, если функцию вызвать мимо валидации).

## 8. Наблюдения при чтении (не ошибки; код не менялся)
1. `DataConfig`: списки сидов внутри `frozen=True` остаются изменяемыми.
2. `Trajectory` — `frozen` dataclass с полями-массивами NumPy; сравнение по полям и хэширование для массивов, скорее всего, неприменимы; в коде сравнение не используется (вывод, не проверено).
3. `sim_config.ticks` не проверяет `dt`.
4. `SimulationConfig.light_speed_km_s` свободно задаётся (только `> 0`), а `ModelConfig.light_speed_km_s` обязан равняться константе: два независимых поля с одним смыслом.
5. `SimulationConfig.validate` не требует `packet_bytes <= buffer_bytes`.
6. В комментариях и строках встречаются ссылки на внутренние документы, не входящие в экспорт (путь служебной выгрузки в `geometry.py`; тест `tests/reference/contacts_ref.py` в `contacts.py`; метки задач, ревизия `b6f5f516`). Это только текст; на импорт они не влияют (по чтению).
7. В `geometry.py` есть две ветви проверки видимости (оптимизированная и «базовая»); их равенство в коде аргументируется внешним документом.

## 9. Не установлено чтением (сводный список)
1. Ничего из описанного не запускалось: не проверены импорт, синтаксис разбором, тесты, результаты расчётов; всё, что названо «выводом», — результат чтения.
2. Значения полей в JSON каталога `configs/` (могут переопределять значения по умолчанию).
3. Использование полей `step_s`, `start_s`, `mask_diagonal`, `beta`, `device`, `threads`, `deterministic`, `gcn_width`, `dense_width` в `data.py`, `training.py`, `model.py`, `loss.py` (эти файлы не разбирались в этой части).
4. Место и способ нормировки «A+I» (`feature_spec["propagation"]` лишь заявляет её).
5. Справедливость комментария `Config.data_key` о независимости массивов от `model.features`.
6. Равенство двух ветвей `graph_from_positions` и оптимизированного/базового `ContactPlan._edge_arrival` (проверки вынесены в тесты и документы, которых нет в экспорте).
7. Смысл «unresolved 50.4 deg» в докстринге `graph_from_positions`.
8. Побитовая воспроизводимость `numpy.random.default_rng`, SHA-256-испытаний и вычислений с плавающей точкой между версиями и платформами.
9. Статистические свойства трассы и отказов (равномерность `randrange`, независимость хэш-испытаний); конкретные значения пар «источник — назначение» для сидов.
10. Как политика плана контактов (`policies.py`) формирует аргументы `earliest_hop`; как `simulate.py` и `experiments.py` сохраняют трассу и план.
11. Список импортирующих модулей для `data.py`, `model.py`, `training.py`, `policies.py`, `simulate.py`, `cli.py`, `experiment_*.py`, `experiments.py` составлен по чтению их строк `import`; тела этих файлов не перечитывались полностью в этой части.
12. Производительность, расход памяти (кроме ручных оценок), поведение на `cuda`.
