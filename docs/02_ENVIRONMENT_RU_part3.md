# 02. Среда моделирования. Часть 3 из 8: sim_config.py

Файл: `src/ssn_hops/sim_config.py` (4718 байт). Условные обозначения — в `02_ENVIRONMENT_RU.md`.

## 1. Назначение

Докстринг модуля: «Dynamic reconstruction settings; no author experiment defaults are asserted.» (в коде написано: значения по умолчанию — реконструкция, оригинальные значения экспериментов авторов не утверждаются).

Модуль задаёт конфигурацию пакетной симуляции с дискретным временем: класс `SimulationConfig` (орбита, сиды, длина тика, горизонты, трафик, TTL, буфер, скорость канала, вероятность сбоя, число повторов), две функции перевода времени в тики (`ticks`, `service_ticks`) и загрузчики (`from_sim_dict`, `load_sim_config`).

## 2. Входы и выходы
- Вход: `dict` или путь к JSON (`load_sim_config(path)`); для функций тиков — числа.
- Выход: проверенный `SimulationConfig`; целые числа тиков; при нарушении — `ValueError`.
- Файлов не пишет; единственная операция ввода-вывода — чтение JSON в `load_sim_config`.

## 3. Функции

### `ticks(seconds, dt, name="time")`
- Принимает число `seconds` (не `bool`), конечное и `>= 0`, иначе `ValueError("<name> must be numeric / finite and nonnegative")`.
- Считает `value = seconds / dt`, `rounded = round(value)`; если `value` отличается от ближайшего целого более чем на `1e-7` (в единицах тиков; `math.isclose(..., rel_tol=0, abs_tol=1e-7)`), бросает «`<name>` must be a multiple of tick_s». Возвращает `int(rounded)`.
- Вывод из чтения: сама функция не проверяет `dt` (при `dt == 0` возникнет `ZeroDivisionError`); в `SimulationConfig.validate` `tick_s` проверяется на положительность раньше первого вызова `ticks`.

### `service_ticks(size_bytes, rate_bytes_s, distance_km, light_speed_km_s, dt)`
Докстринг: «Serialization + start-distance propagation; completion rounded UP to grid.»
- Проверки: `size_bytes`, `rate_bytes_s`, `light_speed_km_s`, `dt` — положительные конечные числа; `distance_km` — конечное и `>= 0`.
- Формула в коде: `raw = (size_bytes / rate_bytes_s + distance_km / light_speed_km_s) / dt`; результат `max(1, math.ceil(raw - 1e-12))`. То есть длительность передачи одного хопа в тиках = (время сериализации + время распространения по расстоянию в момент начала передачи), делённая на длину тика, с округлением вверх до целого, не менее 1. Поправка `1e-12` по комментарию снимает лишь машинный шум на границе сетки, а не целый тик.
- Расстояние берётся на момент начала передачи («start-distance»), а не изменяется по ходу передачи (вывод из чтения: в формуле одно значение `distance_km`).

## 4. SimulationConfig — поля и значения по умолчанию

Все значения — `sim_config.py`, класс `SimulationConfig`.

| Поле | По умолчанию | Единицы / смысл |
|---|---|---|
| `schema` | `"ssn-simulation-config-v1"` | идентификатор схемы |
| `orbit` | `OrbitConfig()` (значения см. часть 1) | параметры созвездия |
| `phase_seed` | `401` | сид фаз траектории |
| `traffic_seed` | `501` | сид трафика |
| `failure_seed` | `601` | сид испытаний отказа передачи |
| `tick_s` | `0.1` | длина тика, с |
| `traffic_end_s` | `600.0` | конец генерации трафика, с |
| `observation_end_s` | `900.0` | конец наблюдения, с |
| `arrival_interval_s` | `1.0` | интервал между пакетами, с |
| `packet_bytes` | `18000` | размер пакета, байт |
| `ttl_s` | `300.0` | время жизни пакета, с |
| `buffer_bytes` | `16000000` | буфер узла, байт |
| `rate_bytes_s` | `12500.0` | скорость канала, байт/с |
| `light_speed_km_s` | `299792.458` | скорость света, км/с |
| `failure_probability` | `0.04` | вероятность отказа передачи на тик |
| `additional_retries` | `3` | число дополнительных повторов |
| `torch_threads` | `1` | число потоков torch |
| `audit_each_tick` | `True` | проверка инвариантов симулятора на каждом тике |

### Производные величины (ручной расчёт, значения по умолчанию)
- Тик: `tick_s = 0.1 с`.
- `horizon_tick = observation_end_s / tick_s = 900 / 0.1 = 9000` тиков.
- Конец трафика: `600 / 0.1 = 6000` тиков; интервал между пакетами `1.0 / 0.1 = 10` тиков; число пакетов в трассе `range(0, 6000, 10)` → `6000 / 10 = 600` (см. `traffic.py`, часть 7).
- `ttl_ticks = 300 / 0.1 = 3000` тиков.
- Скорость сериализации: `packet_bytes / rate_bytes_s = 18000 / 12500 = 1.44 с`.
- Распространение на предельной дальности `range_km = 3500`: `3500 / 299792.458 ≈ 0.01167 с` (приближённо).
- Длительность хопа: `raw = (1.44 + 0.01167) / 0.1 ≈ 14.517`, `ceil → 15` тиков (1.5 с). При расстоянии 0 `raw = 14.4`, тоже `15`. Чтобы получить 16 тиков, нужно `distance_km / light_speed_km_s > 0.06 с`, то есть `distance_km > 0.06 · 299792.458 ≈ 17987 км`. Так как предел дальности связи по умолчанию равен 3500 км, вывод из этого расчёта: при значениях по умолчанию любая передача по ребру занимает ровно 15 тиков (пограничные эффекты плавающей точки не учитывались).
- Буфер: `16000000 / 18000 ≈ 888.9`, то есть в буфер узла помещается не более 888 пакетов полного размера (целая часть).

## 5. Валидация: `SimulationConfig.validate()`
По порядку:
1. `schema` равно `"ssn-simulation-config-v1"`.
2. `orbit.validate()`.
3. `phase_seed`, `traffic_seed`, `failure_seed` — целые `>= 0` и `< 2**32`.
4. `tick_s`, `traffic_end_s`, `observation_end_s`, `arrival_interval_s`, `ttl_s`, `rate_bytes_s`, `light_speed_km_s` — положительные конечные.
5. `packet_bytes`, `buffer_bytes`, `torch_threads` — целые `>= 1`; `additional_retries` — целое `>= 0`.
6. `traffic_end_s`, `observation_end_s`, `arrival_interval_s`, `ttl_s` должны быть кратны `tick_s` (через `ticks`) и занимать не менее одного тика.
7. `observation_end_s >= traffic_end_s` («observation must cover the entire traffic horizon»).
8. `failure_probability` — число (не `bool`), конечное, в `[0, 1]`.
9. `audit_each_tick` — `bool`.
Возвращает `self`. Не проверяется (вывод из чтения): `packet_bytes <= buffer_bytes` (случай обрабатывается в `simulator.py`, где пакет больше буфера получает причину отказа `packet_oversize`), а также равенство `light_speed_km_s` константе `LIGHT_SPEED_KM_S` (в отличие от `ModelConfig`).

## 6. Свойства и методы
- `to_dict()` → `asdict(self)` (вложенный `orbit` тоже превращается в словарь).
- `sha256` → `content_hash(self.to_dict())`.
- `trace_key` → `content_hash` от словаря `{n, traffic_seed, tick_s, traffic_end_s, arrival_interval_s, packet_bytes}` (`n` берётся из `orbit.n`). Комментарий в коде: исключает политику, фазы, отказы и скорость канала, чтобы трассы были парными при изменении этих параметров. Трасса и `read_trace` привязаны к этому ключу.
- `horizon_tick` → `ticks(observation_end_s, tick_s)`.
- `ttl_ticks` → `ticks(ttl_s, tick_s)`.

## 7. Загрузка
- `from_sim_dict(value)`: требует `dict`; копирует его; значение `orbit` (по умолчанию `{}`) превращается в `OrbitConfig` через `config._section` (неизвестные поля отвергаются); затем `_section(SimulationConfig, data).validate()` (неизвестные верхние поля отвергаются).
- `load_sim_config(path)`: UTF-8, `json.load`, `from_sim_dict`.

## 8. Правило повтора, лимит хопов и отказы (где они реализованы)
В `SimulationConfig` хранится только число `additional_retries` (по умолчанию `3`) и вероятность `failure_probability` (по умолчанию `0.04`). Сами правила выполняются в `simulator.py` (прочитан для этого раздела):
- Повтор: в `Simulator._abort` счётчик `packet.hop_failures` увеличивается на 1; если `hop_failures > additional_retries`, пакет получает статус `failed` с причиной `retry_exhaustion`; иначе тот же пакет может начать передачу заново с нулевого байта. При успешном хопе (`Simulator._complete`) `hop_failures` обнуляется. Вывод из чтения: при `additional_retries = 3` пакет переживает 3 неудачные попытки на хоп и терпит отказ на четвёртой.
- Лимит хопов: `Simulator._complete` — при `packet.hops >= 2 * self.cfg.orbit.n` пакет получает `failed` с причиной `hop_limit`. Ручной расчёт: `2 * 132 = 264`. Это не поле конфигурации.
- Отказ передачи: в `Simulator.run` при `failure_probability != 0` вызывается `failure_sampler(failure_seed, sender, receiver, tick, failure_probability)` для тиков `transfer.start_tick < tick < transfer.finish_tick`; ручной расчёт при хопе в 15 тиков: тики `start+1 … start+14`, то есть 14 испытаний за передачу. Потеря связи (`adjacency[sender, receiver]` ложна на тике) отменяет передачу с причиной `link_loss`. Подробности — в описании симулятора; здесь перечислено только то, что нужно для значений `sim_config.py`.
- TTL: `Packet.expiry_tick = created_tick + cfg.ttl_ticks`; по истечении ожидающий пакет получает `failed` с причиной `ttl` (`simulator.py`, `Simulator.run`).
- Буфер: `buffer_bytes` сравнивается с занятыми и зарезервированными байтами при приёме в очередь и при выборе получателя (`simulator.py`, `Simulator._inject`, `Simulator._schedule`).

## 9. Связи с другими модулями
- Импортирует: `config.py` (`OrbitConfig`, `_section`, `content_hash`, `integer`, `positive`); стандартную библиотеку `dataclasses`, `json`, `math`, `pathlib`. Сторонних зависимостей нет.
- Импортируется: `contacts.py` (`service_ticks`), `traffic.py` (`ticks`), `simulator.py` (`service_ticks`), а также `simulate.py`, `experiment_io.py`, `experiment_results.py`, `experiments.py` (по чтению их строк `import`; сами эти файлы здесь не перечитывались, кроме `simulator.py`).

## 10. Побочные эффекты
Чтение JSON. Случайность отсутствует; сами сиды только хранятся и проверяются. Глобального состояния нет.

## 11. Допущения и реконструкция в коде
- «Dynamic reconstruction settings; no author experiment defaults are asserted.»
- Названия сидов `401`, `501`, `601` и остальные значения — просто значения по умолчанию кода; обоснования в коде не приведено.

## 12. Что не установлено чтением (sim_config.py)
- Какие значения этих полей реально заданы в JSON-файлах каталога `configs/` (не читались при составлении этой части): они могут переопределять значения по умолчанию.
- Поведение на практике: ничего не запускалось.
