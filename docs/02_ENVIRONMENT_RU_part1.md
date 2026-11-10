# 02. Среда моделирования. Часть 1 из 8: config.py (начало)

Условные обозначения и список частей — в файле `02_ENVIRONMENT_RU.md`. Здесь и далее «в коде написано» означает прямую цитату или пересказ текста файла; «вывод из чтения» — заключение, сделанное при чтении, без запуска; «ручной расчёт» — арифметика, выполненная вручную и показанная.

Файл: `src/ssn_hops/config.py` (15169 байт). Продолжение (ModelConfig, TrainConfig, Config, загрузка) — в части 2.

## 1. Назначение

В коде написано (докстринг модуля): «Strict resolved configuration. Defaults are reconstruction assumptions.» То есть значения по умолчанию в этом файле авторы кода прямо называют допущениями реконструкции, а не данными оригинальной работы.

Модуль задаёт:
- пять неизменяемых (`@dataclass(frozen=True)`) классов конфигурации: `OrbitConfig`, `DataConfig`, `ModelConfig`, `TrainConfig` и объединяющий `Config`;
- проверку значений (методы `validate`) и вспомогательные функции проверки чисел;
- каноническую JSON-сериализацию и SHA-256 хэш содержимого (`canonical_json`, `content_hash`), на которых строятся ключи совместимости наборов данных, контрольных точек и планов;
- разбор словаря и JSON-файла в `Config` (`from_dict`, `load_config`, `dataset_config`);
- описание режимов входных признаков нейросети (константы `TOPOLOGY_FEATURES`, `ABLATION_FEATURES`, `DELAY_FEATURES`).

## 2. Входы и выходы

- Вход: `dict` (обычно из JSON) либо путь к JSON-файлу (`load_config(path)`).
- Выход: объект `Config` с уже выполненной проверкой (`from_dict` вызывает `.validate()`), либо исключение `ValueError`. Ошибки файловой системы и разбора JSON (`FileNotFoundError`, `json.JSONDecodeError`) в `load_config` не перехватываются (вывод из чтения: исключения проходят наружу).
- Хэши: строка из 64 шестнадцатеричных символов.
- Файлов модуль не пишет.

## 3. Константы модуля (все — в `config.py`)

| Константа | Значение в коде | Смысл |
|---|---|---|
| `TOPOLOGY_FEATURES` | `"adjacency_spliced_two_hop"` | режим признаков по умолчанию (только топология) |
| `ABLATION_FEATURES` | `"topology_only_ablation"` | устаревший синоним режима топологии |
| `DELAY_FEATURES` | `"adjacency_spliced_two_hop_propagation_delay"` | необязательное расширение с каналом задержки |
| `TOPOLOGY_ONLY_MODES` | кортеж из первых двух | режимы без задержки |
| `SUPPORTED_FEATURES` | кортеж из всех трёх | допустимые значения `ModelConfig.features` |
| `LIGHT_SPEED_KM_S` | `299792.458` | скорость света, км/с |
| `DELAY_SCALE_S` | `0.01` | масштаб канала задержки, с |
| `LEGACY_SPEC_AUTHORITY` | строка «independent reconstruction assumption, NOT recovered author H0» | значение поля `authority` в записи `feature_spec` для режимов, кроме `TOPOLOGY_FEATURES` |
| `TOPOLOGY_SPEC_AUTHORITY` | строка «paper input set (original input + 1/0.5 two-hop-encoded input); H0 row layout [A] / [A|Q] is an independent reconstruction, NOT recovered author H0» | то же для `TOPOLOGY_FEATURES` |

Комментарий в коде: обе строки `authority` сохраняются внутри манифестов наборов данных и контрольных точек и сравниваются строго; их нужно держать побайтно неизменными («never edit these two strings casually»).

## 4. Вспомогательные функции

- `canonical_json(value)` → `json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)`. Ключи упорядочены, пробелов нет, `NaN`/`Infinity` запрещены (вывод из чтения: при их наличии `json.dumps` бросает `ValueError`). Параметр `ensure_ascii` не задан, то есть действует значение по умолчанию функции `json.dumps` (экранирование не-ASCII символов).
- `content_hash(value)` → `hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()`.
- `finite_number(value, name)` — принимает `int` или `float`, но не `bool`; значение должно быть конечным; иначе `ValueError("<name> must be a finite number")`.
- `positive(value, name)` — то же плюс строго `> 0`.
- `integer(value, name, minimum=1)` — требует точный тип `int` (`type(value) is int`, поэтому `bool` и числа `numpy` отклоняются — вывод из чтения) и `value >= minimum`; иначе `ValueError("<name> must be an integer >= <minimum>")`.

Замечание (вывод из чтения): `finite_number` и `positive` принимают любой подкласс `float`, а `integer` — только точный `int`. Целое число, записанное в JSON как `1.0`, будет отклонено там, где требуется `integer`.

## 5. OrbitConfig — параметры созвездия и связей

Класс `OrbitConfig(frozen dataclass)`; поля и значения по умолчанию (все — `config.py`, класс `OrbitConfig`):

| Поле | По умолчанию | Единицы / смысл |
|---|---|---|
| `n` | `132` | число спутников |
| `planes` | `12` | число орбитальных плоскостей |
| `earth_radius_km` | `6371.0` | радиус Земли, км |
| `altitude_km` | `1050.0` | высота орбиты над радиусом Земли, км |
| `inclination_deg` | `53.0` | наклонение, градусы |
| `eccentricity` | `0.0` | эксцентриситет (реализованы только круговые орбиты) |
| `mu_km3_s2` | `398600.4418` | гравитационный параметр Земли, км³/с² |
| `walker_f` | `1` | параметр фазирования Уокера F |
| `phase_mode` | `"independent_plane_offsets"` | способ начальных фаз (см. `geometry.py`) |
| `epoch_s` | `0.0` | опорный момент времени, с |
| `range_km` | `3500.0` | предел дальности связи, км |
| `earth_los` | `True` | включить проверку прямой видимости с учётом Земли |

Ручной расчёт: `n / planes = 132 / 12 = 11` спутников в плоскости (при условии значений по умолчанию).

### Метод `OrbitConfig.validate()`
Проверки по порядку (все при нарушении дают `ValueError`):
1. `n` — целое `>= 2`; `planes` — целое `>= 1`; `planes <= n` и `n % planes == 0`, иначе «n must be divisible by planes».
2. `earth_radius_km`, `altitude_km`, `mu_km3_s2`, `range_km` — положительные конечные числа.
3. `inclination_deg` — конечное число в `[0, 180]`.
4. `eccentricity` — конечное число и строго равно `0`; иначе «only eccentricity=0 circular orbits are implemented».
5. `walker_f` — целое `>= 0` и `< planes`.
6. `phase_mode` — одно из `"walker"`, `"independent_plane_offsets"`.
7. `epoch_s` — конечное число.
8. `earth_los` — точный тип `bool`.

Правило прямой видимости в `OrbitConfig` лишь включается флагом `earth_los`; само правило реализовано в `geometry.py`, `graph_from_positions` (см. часть 4). Предел дальности `range_km` также применяется там.

Вывод из чтения: `validate` не сравнивает `altitude_km` с чем-либо, кроме положительности; не проверяется, что `range_km` меньше максимальной хорды, допускаемой геометрией.

## 6. DataConfig — параметры генерации набора данных

Поля и значения по умолчанию (`config.py`, класс `DataConfig`):

| Поле | По умолчанию |
|---|---|
| `train_seeds` | `[101, 102, 103, 104, 105, 106, 107, 108]` |
| `val_seeds` | `[201, 202]` |
| `test_seeds` | `[301, 302]` |
| `snapshots_per_trajectory` | `24` |
| `step_s` | `120.0` (секунды между снимками) |
| `start_s` | `0.0` |
| `mask_diagonal` | `True` |

Списки заданы через `field(default_factory=...)`. Класс помечен `frozen=True`, но сами списки остаются изменяемыми объектами Python (вывод из чтения).

### Метод `DataConfig.validate()`
- Для каждого разбиения `train`, `val`, `test`: значение — непустой `list` (кортеж отвергается); каждый элемент — целое `>= 0` и `< 2**32` («phase seeds must be smaller than 2**32»).
- Все сиды по трём разбиениям вместе должны быть уникальны («trajectory seeds must be globally unique across all splits»).
- `snapshots_per_trajectory` — целое `>= 1`; `step_s` — положительное конечное; `start_s` — конечное число; `mask_diagonal` — `bool`.

Ручной расчёт: `snapshots_per_trajectory * step_s = 24 * 120.0 = 2880 с` — длина интервала, покрытого снимками одной траектории, если снимки равномерны с шагом `step_s`. Как именно `start_s` и `step_s` превращаются во времена снимков, определяется в `data.py`, который в этом описании не разбирается; поэтому здесь это не установлено.

Роль сидов (в коде названо «phase seeds»): сид передаётся в `geometry.make_trajectory` и определяет случайные фазы и долготы узлов (см. часть 4). Использование сидов набором данных (`data.py`) здесь не проверялось.
