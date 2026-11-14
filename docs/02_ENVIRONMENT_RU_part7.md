# 02. Среда моделирования. Часть 7 из 8: traffic.py

Файл: `src/ssn_hops/traffic.py` (4699 байт). Условные обозначения — в `02_ENVIRONMENT_RU.md`.

## 1. Назначение

Докстринг: «Predetermined traffic and stateless, edge/tick-keyed transfer-abort trials.» Модуль:
- генерирует заранее определённую трассу пакетов (`make_trace`);
- проверяет, сериализует в документ с хэшем и читает обратно трассу (`validate_records`, `trace_document`, `read_trace`);
- задаёт функцию детерминированных испытаний «отказ передачи по ребру на тике» без изменяемого генератора (`edge_tick_failure`).

## 2. Входы и выходы
- `make_trace(cfg)` → список `TrafficRecord`.
- `trace_document(records, cfg)` → словарь `{"schema", "trace_key", "records", "sha256"}`.
- `read_trace(document, cfg)` → отсортированный список `TrafficRecord` или `ValueError`.
- `edge_tick_failure(seed, u, v, tick, probability)` → `bool`.
- Файлов не читает и не пишет (запись и чтение JSON-файлов трассы выполняют другие модули: упоминания вызовов `make_trace`/`trace_document` есть в `simulate.py` и `experiments.py`, проверено только по их строкам `import`).

## 3. TrafficRecord и его проверка
Неизменяемая запись: `packet_id`, `created_tick`, `source`, `destination`, `size_bytes`.
`TrafficRecord.validate(cfg)` проверяет (все `ValueError`):
- `packet_id`, `created_tick`, `source`, `destination` — точные `int >= 0`; `size_bytes` — `int >= 1`;
- `max(source, destination) < cfg.orbit.n` и `source != destination` («traffic endpoints must be distinct node IDs in [0,N)»);
- `created_tick < ticks(cfg.traffic_end_s, cfg.tick_s)` («traffic time must lie in [0, traffic_end_s)»);
- `size_bytes == cfg.packet_bytes` («trace packet size differs from configured size»).

## 4. make_trace — что генерируется

Код (по порядку):
1. `cfg.validate()`.
2. `rng = random.Random(cfg.traffic_seed)` — экземпляр генератора из стандартной библиотеки Python, инициализированный целым сидом; локальный (глобальное состояние модуля `random` не используется).
3. `stop = ticks(traffic_end_s, tick_s)`, `step = ticks(arrival_interval_s, tick_s)`.
4. Для `packet_id, tick` из `enumerate(range(0, stop, step))`:
   - `source = rng.randrange(n)`;
   - `destination = rng.randrange(n − 1)`; если `destination >= source`, то `destination += 1`.
   - Запись `TrafficRecord(packet_id, tick, source, destination, cfg.packet_bytes)`.

Что отсюда следует (вывод из чтения):
- Источники: любой из `n` узлов, равновероятно (при допущении равномерности `randrange`); назначения: любой другой узел, равновероятно (сдвиг на единицу исключает совпадение с источником и сохраняет равномерность по оставшимся `n − 1` узлам).
- Расписание детерминированное, не пуассоновское: один пакет каждые `step` тиков, начиная с тика 0; размер пакета постоянный `packet_bytes`. Случайны только пары «источник — назначение».
- Порядок обращений к генератору: на каждый пакет сначала источник, потом назначение; число обращений зависит от числа пакетов.
- Трасса не зависит от орбиты (кроме `n`), от политики, от фаз и от отказов; это отражено в `SimulationConfig.trace_key` (часть 3).
- Достижимость пары в момент создания не проверяется.

Ручной расчёт при значениях по умолчанию (`tick_s=0.1`, `traffic_end_s=600.0`, `arrival_interval_s=1.0`, `packet_bytes=18000`, `n=132`, `traffic_seed=501`): `stop = 6000`, `step = 10`; число пакетов `6000 / 10 = 600`, номера `0…599`, моменты `0, 1, 2, …, 599` секунд. Средняя скорость порождения `18000 байт · 8 / 1 с = 144 000 бит/с` на всю сеть; для сравнения скорость одного канала `rate_bytes_s = 12500 байт/с = 100 000 бит/с` (части 1 и 3). Это арифметика заданных значений, не результат запуска.

## 5. Проверка и сериализация

- `validate_records(records, cfg)`: каждая запись — именно `TrafficRecord`; вызывается `record.validate(cfg)`; повторяющийся `packet_id` → «duplicate traffic ID». Возвращает записи, отсортированные по `(created_tick, packet_id)`.
- `trace_document(records, cfg)`: строки — `asdict` для проверенных записей; `body = {"schema": "ssn-traffic-v1", "trace_key": cfg.trace_key, "records": rows}`; результат `{**body, "sha256": content_hash(body)}`.
- `read_trace(document, cfg)`: набор ключей документа должен быть в точности `{"schema", "trace_key", "records", "sha256"}`; схема `"ssn-traffic-v1"` и `trace_key == cfg.trace_key`; `content_hash(body) == sha256`; `records` — список; каждая строка превращается в `TrafficRecord(**row)` (лишние/недостающие поля → `ValueError("invalid traffic record fields")`); затем `validate_records`; наконец документ пересобирается и сравнивается с исходным: расхождение (например, нарушенный порядок записей) → «traffic records must have canonical time/ID order». Вывод из чтения: хэш проверяется раньше содержимого записей; значения-числа с плавающей точкой вместо целых будут отвергнуты проверкой типов.

## 6. edge_tick_failure — испытания отказа передачи

Докстринг: «Exact-p Bernoulli construction using rejection, not reciprocal quantization. SHA256 domain-separated blocks provide deterministic pseudo-random bits. p is interpreted as the exact rational represented by the supplied Python number. There is no mutable RNG consumption and no persistent edge outage state.»

Проверки: `seed`, `u`, `v`, `tick` — целые `>= 0`; `u != v` («self-edge failure key»); `probability` — число (не `bool`), `0 <= p <= 1`.
Алгоритм:
1. `p == 0` → `False`; `p == 1` → `True`.
2. `numerator, denominator = Fraction(p).as_integer_ratio()` — точная рациональная запись числа.
3. `width = (denominator − 1).bit_length()`; префикс `b"ssn-edge-tick-v1:{seed}:{min(u,v)}:{max(u,v)}:{tick}:"` (ASCII; ребро неупорядоченное: используются `min` и `max`).
4. `blocks = (width + 255) // 256` блоков SHA-256 на попытку; для попытки `attempt = 0, 1, …` собирается `raw` из `sha256(prefix + "{attempt}:{block}")`; `value = int.from_bytes(raw, "big") & ((1 << width) − 1)`.
5. Если `value < denominator`, результат `value < numerator`; иначе `attempt += 1` и повтор (метод отбраковки).

Свойства (вывод из чтения):
- Результат — чистая функция пяти аргументов: нет изменяемого генератора и нет состояния; один и тот же `(seed, u, v, tick, p)` всегда даёт тот же ответ, порядок вызовов не влияет.
- Вероятность результата `True` равна `numerator / denominator`, то есть точно `p` как рационального числа, которое представляет float (при равномерности бит SHA-256 — это допущение, не проверявшееся).
- Для любого `float` знаменатель в `as_integer_ratio` — степень двойки, поэтому `value < denominator` выполняется всегда, и цикл отбраковки фактически завершается на попытке 0; ветвь повтора и многоблочный режим нужны для общности (комментарий кода называет случай «wide denominators (e.g. subnormal floats)»). Это математический вывод; запуском не проверялся.
- Независимость испытаний для разных `(u, v, tick)` основана на хэш-функции; статистические свойства не проверялись.

Использование: в `simulator.py` (`Simulator.run`) вызывается как `failure_sampler(cfg.failure_seed, sender, receiver, tick, cfg.failure_probability)` для тиков строго между началом и окончанием передачи и только при `failure_probability != 0`. С значениями по умолчанию: `failure_seed=601`, `failure_probability=0.04`; ручной расчёт: при передаче в 15 тиков 14 испытаний, шанс отсутствия сбоя при независимости испытаний `0.96^14 ≈ 0.565` (`ln 0.96 ≈ −0.0408`, `·14 ≈ −0.571`, `e^−0.571 ≈ 0.565`). Это арифметика заданных чисел, не измерение.

## 7. Значения по умолчанию
Собственных констант нет, кроме строк схемы `"ssn-traffic-v1"` и префикса `"ssn-edge-tick-v1"`. Числа берутся из `SimulationConfig` (часть 3): `traffic_seed=501`, `failure_seed=601`, `traffic_end_s=600.0`, `arrival_interval_s=1.0`, `packet_bytes=18000`, `tick_s=0.1`, `failure_probability=0.04`.

## 8. Связи с другими модулями
- Импортирует: `config.py` (`content_hash`, `integer`), `sim_config.py` (`ticks`); стандартные `dataclasses`, `fractions`, `hashlib`, `random`. Сторонних зависимостей нет.
- Импортируется: `simulator.py` (`edge_tick_failure`, `validate_records`; прочитано); `simulate.py`, `experiment_results.py` (`read_trace`), `experiments.py` (ленивый импорт `make_trace`, `trace_document`); `driver/traces.py` (ленивый импорт; каталога `driver/` нет в поставке); по чтению строк `import` этих файлов.

## 9. Побочные эффекты и случайность
Файлов нет; глобальное состояние не изменяется. Случайность: (1) `random.Random(traffic_seed)` в `make_trace`; (2) хэш-испытания в `edge_tick_failure` (без генератора). Других источников случайности в модуле нет.

## 10. Допущения и реконструкция в коде
Модуль не содержит явных пометок «допущение/реконструкция»; в докстринге `SimulationConfig` (`sim_config.py`) значения по умолчанию названы реконструкцией (часть 3). Равномерный случайный трафик с фиксированным интервалом — выбор кода; его соответствие какому-либо источнику в коде не заявлено.

## 11. Что не установлено чтением (traffic.py)
- Конкретные пары «источник — назначение» для сида `501` (генератор не запускался).
- Фактическая статистика отказов при `p = 0.04` (не измерялась).
- Как другие модули сохраняют/читают файл трассы (кроме проверки формата `read_trace`).
