# 02. Среда моделирования. Часть 2 из 8: config.py (окончание)

Начало описания `config.py` (назначение, константы, вспомогательные функции, `OrbitConfig`, `DataConfig`) — в части 1.

## 7. ModelConfig — настройки сети и режим входных признаков

Поля и значения по умолчанию (`config.py`, класс `ModelConfig`):

| Поле | По умолчанию |
|---|---|
| `gcn_width` | `32` |
| `dense_width` | `64` |
| `gcn_bias` | `False` |
| `dense_bias` | `True` |
| `features` | `TOPOLOGY_FEATURES` = `"adjacency_spliced_two_hop"` |
| `feature_version` | `1` |
| `delay_kind` | `"propagation_only"` |
| `delay_scale_s` | `DELAY_SCALE_S` = `0.01` |
| `light_speed_km_s` | `LIGHT_SPEED_KM_S` = `299792.458` |
| `orientation` | `"destination_candidate"` |

Как эти поля используются при построении слоёв, здесь не разбирается (это `model.py`).

### Три режима `features` (в коде написано, докстринг модуля)
- `TOPOLOGY_FEATURES` (в коде помечен «DEFAULT»): низкая ветвь `low=[A]`, высокая `high=[A|Q]`. Здесь `A` — бинарная матрица смежности, `Q` — матрица «1 / 0.5 / 0» (см. `graph.py`, часть 6). Комментарий кода: раскладка строк H0 — независимая реконструкция, не восстановленная раскладка авторов.
- `ABLATION_FEATURES`: устаревший литерал `"topology_only_ablation"`. В коде назван допустимым синонимом с тем же поведением и тем же сохраняемым устаревшим описанием; конфигурации и контрольные точки не переименовываются молча (равенство `ModelConfig` сравнивает именно литерал).
- `DELAY_FEATURES`: «OPTIONAL EXTENSION, not in the paper»: `low=[A|D]`, `high=[A|Q|D]`, где `D` — канал задержки распространения.

Комментарий кода: задержка линии `f(e)` в сеть не подаётся ни в одном режиме, кроме расширения.

### `ModelConfig.validate()`
1. `gcn_width`, `dense_width` — целые `>= 1`; `gcn_bias`, `dense_bias` — точные `bool`.
2. `features` должно входить в `SUPPORTED_FEATURES`, иначе `ValueError` с перечислением допустимых значений и пометкой «legacy v1 topology config requires explicit migration».
3. `feature_version` — точно `int` и равно `1`.
4. `delay_kind == "propagation_only"`.
5. `delay_scale_s` и `light_speed_km_s` — положительные, и при этом обязаны быть равны константам `DELAY_SCALE_S` и `LIGHT_SPEED_KM_S`: «feature v1 fixes delay_scale_s=0.01 and light_speed_km_s=299792.458». Вывод из чтения: поля нельзя менять даже в режимах без задержки; в них записаны «инертные» константы.
6. `orientation == "destination_candidate"`.

### Свойства `ModelConfig`
- `uses_delay` → `True` только при `features == DELAY_FEATURES`.
- `feature_role` → текстовая метка статуса («paper-faithful default topology-only input set; H0 layout is a reconstruction» и аналогичные для двух других режимов). По комментарию кода, не сохраняется и в `feature_spec` не входит.
- `feature_spec` → словарь, который сохраняется в манифестах наборов данных, контрольных точках и планах и сравнивается строго. Вызывает `validate()`. Содержит: `schema="ssn-input-features-v1"`, `mode`, `version`, `delay_kind` (`"none"` для топологии, `"none_ablation"` для синонима, значение поля для расширения), `delay_scale_s` и `light_speed_km_s` (числа только в расширении, иначе `None`), `low` (`"[A|D]"` или `"[A]"`), `high` (`"[A|Q|D]"` или `"[A|Q]"`), `mask="absent links and diagonal zero"`, `dtype="float32"`, `propagation="original binary A with GCN A+I normalization"`, `authority` (одна из двух строк-констант из части 1).

Строка `propagation` — утверждение кода о том, как должна выполняться свёртка (на исходной бинарной `A` с нормировкой «A+I», характерной для GCN). Сама нормировка в `graph.py` не выполняется (см. часть 6); где она происходит, в этом шаге не установлено.

### `require_supported_model(model_config)`
Принимает любой допустимый режим. Бросает `ValueError`, если аргумент не `ModelConfig` («model configuration must be a ModelConfig») или не проходит `validate()`. Возвращает тот же объект. Жёсткая защита от смешения режимов и контрольных точек, по докстрингу, находится в равенстве `ModelConfig` и в сравнении `feature_spec` в местах загрузки, а не здесь.

## 8. TrainConfig — параметры обучения

Поля и значения по умолчанию (`config.py`, класс `TrainConfig`):

| Поле | По умолчанию |
|---|---|
| `seed` | `17` |
| `epochs` | `100` |
| `batch_size` | `4` |
| `learning_rate` | `0.001` |
| `beta` | `0.00001` |
| `patience` | `15` |
| `device` | `"cpu"` |
| `deterministic` | `True` |
| `threads` | `1` |
| `optimizer` | `"Adam"` |
| `adam_betas` | `[0.9, 0.999]` |
| `adam_eps` | `1e-8` |

`validate()`: `seed` — целое `>= 0` и `< 2**32`; `epochs`, `batch_size`, `patience`, `threads` — целые `>= 1`; `learning_rate` и `adam_eps` положительные; `beta` — конечное и `>= 0`; `optimizer == "Adam"` («only Adam is implemented»); `adam_betas` — `list` из двух конечных чисел, каждое в `[0, 1)`; `deterministic` — `bool`; `device` — только строка (допустимость конкретного устройства здесь не проверяется — вывод из чтения; `training.py` не читался). Роль `beta` (по имени — коэффициент регуляризации) определяется в `loss.py`/`training.py` и здесь не проверялась.

## 9. Config — корневой объект

Поля: `schema_version` (по умолчанию `2`), `orbit`, `data`, `model`, `train` (каждое создаётся `default_factory`).

- `validate()`: `schema_version` — точно `int` и равно `2`, иначе «unsupported configuration schema; migrate v1 configs explicitly and retrain»; затем по очереди `validate()` четырёх секций; возвращает `self`.
- `to_dict()` → `dataclasses.asdict(self)`.
- `sha256` → `content_hash(self.to_dict())` — хэш всей конфигурации.
- `data_key` → `content_hash({"schema_version": 1, "orbit": asdict(orbit), "data": asdict(data)})`. Литерал `1` в этом словаре — отдельная константа ключа, не `Config.schema_version`. По комментарию кода массивы набора данных (положения, смежность, метки, маски) зависят только от `orbit` и `data`, но не от `model.features`; это утверждение сделано в самом коде («verified by reading data.py»), в этом шаге оно не перепроверялось.

## 10. Загрузка и миграция

- `_section(cls, value)` (закрытая; используется также в `sim_config.py`): требует `dict`; неизвестные поля → `ValueError("unknown <Класс> fields: [...]")` (список отсортирован); иначе `cls(**value)`. Сам по себе `_section` значения не проверяет.
- `from_dict(value)`: требует `dict`; допустимые верхние ключи — `schema_version`, `orbit`, `data`, `model`, `train` (прочие → «unknown configuration fields»); отсутствующая секция заменяется `{}` (то есть значениями по умолчанию); в конце вызывается `Config.validate()`.
- `dataset_config(value)`: «Read-only migration of archived v1 metadata» — только для метаданных наборов данных, не для весов и не для командной строки. Если аргумент не `dict` или его `schema_version != 1`, делегирует `from_dict`. Для v1: `schema_version` должен быть точно `int` (так что `True` и `1.0` отклоняются); `model` — `dict` с в точности шестью полями `gcn_width`, `dense_width`, `gcn_bias`, `dense_bias`, `features`, `orientation`; `features` обязано быть `"adjacency_and_spliced_exclusive_two_hop"`; результат — `schema_version = 2` и `features = ABLATION_FEATURES`, затем `from_dict`. Остальные секции v1-словаря должны проходить проверку схемы 2.
- `load_config(path)`: открывает файл в UTF-8, `json.load`, `from_dict`.

## 11. Как работает проверка конфигурации (сводка по config.py)
Двухступенчатая: (1) `_section` отвергает неизвестные поля и не-объекты; (2) `validate()` каждой секции проверяет типы строго (точный `int`, точный `bool`, конечные числа) и допустимые диапазоны. Конструкторы dataclass сами значения не проверяют: объект, созданный напрямую, остаётся непроверенным, пока не вызван `validate()` (вывод из чтения). Все нарушения — `ValueError` с текстом, начинающимся с имени поля.

## 12. Связи с другими модулями
- `config.py` не импортирует модулей пакета; из стандартной библиотеки: `dataclasses`, `hashlib`, `json`, `math`, `pathlib`. Сторонних зависимостей нет.
- Импортируется (по строкам `import` в заголовках файлов): `sim_config.py`, `geometry.py`, `contacts.py`, `features.py`, `graph.py`, `traffic.py`, `data.py`, `model.py`, `training.py`, `policies.py`, `simulate.py`, `cli.py`, `experiment_io.py`, `experiment_results.py`, `experiment_plots.py`, `experiments.py`. В этом шаге полностью перечитаны только `features.py`, `graph.py`, `traffic.py`, `contacts.py`, `geometry.py`, `sim_config.py`, `simulator.py`; для остальных использовано чтение их строк `import`, сделанное отдельно.

## 13. Побочные эффекты
Чтение одного JSON-файла в `load_config`. Записи файлов, случайных чисел и глобального состояния в модуле нет.

## 14. Что в коде названо допущением или реконструкцией
- «Defaults are reconstruction assumptions» — все значения по умолчанию.
- «independent reconstruction, NOT the recovered author H0» — раскладка H0.
- «OPTIONAL EXTENSION, not in the paper» — режим задержки; поле `delay_*` «inert in topology-only modes».
- В докстринге и комментариях встречаются метки внутренних задач (`T022-S01`, `T022`) и идентификатор arXiv `2108.08523v1`; документы, на которые указывают метки, не входят в экспорт.

## 15. Что не установлено чтением (config.py)
- Как `data.py`, `training.py`, `model.py` используют `step_s`, `start_s`, `beta`, `device`, `threads`, `deterministic`.
- Где выполняется нормировка «A+I».
- Справедливость комментария о том, что `data_key` не зависит от `model.features`.
- Корректность любых значений при запуске: ничего не запускалось.
