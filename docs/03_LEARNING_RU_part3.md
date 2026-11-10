# 03. Обучение: часть 3 — `loss.py`, `provenance.py`, `cli.py`, `__main__.py`, `__init__.py`

Обозначения — как в части 1. Нумерация разделов продолжает часть 2 (разделы 3–4: `model.py`, `training.py`).

## 5. `loss.py`

### Назначение
Docstring: «Masked MSE + beta * unsquared Euclidean norm of all trainable parameters». Импортирует только `math` и `torch`; файлов не пишет, случайности нет.

### Функции
- `masked_mse(prediction, target, mask)`: формы `prediction`, `target`, `mask` должны совпасть; `mask` — `torch.bool`; хотя бы один `True`, иначе `ValueError`. Индексация `prediction[mask]`, `target[mask]` выполняется до вычитания (комментарий кода: недопустимые метки не просачиваются через `inf * 0`); выбранные значения должны быть конечны. Результат: `mean((p - t)^2)` по всем выбранным элементам батча (микро-среднее по парам, не по снимкам).
- `parameter_l2(model)`: склеивает все параметры с `requires_grad` в один вектор и возвращает `torch.linalg.vector_norm(..., ord=2)`. Норма НЕ возводится в квадрат. Нет обучаемых параметров — `ValueError`.
- `hop_loss(prediction, target, mask, model, beta)`: `beta` конечна и `>= 0`; возвращает
  `L = masked_mse(prediction, target, mask) + beta * ||theta||_2`, где `theta` — все обучаемые параметры модели (смещения входят, если они есть).

### Значения по умолчанию и связи
`beta` берётся из `TrainConfig.beta` (`config.py`) = `0.00001`; значение передаёт `training.train`. Маска строится в `graph.shortest_hops` (достижимые пары; диагональ исключена при `DataConfig.mask_diagonal=True`; `02_ENVIRONMENT_RU.md`, часть 6). Параллельно оптимизатор `Adam` создан с `weight_decay=0.0` (`training.py`), то есть другого L2-штрафа нет (вывод из чтения).

### Не установлено чтением
Поведение градиента неквадратичной нормы при нулевом векторе параметров (математически производная не определена; код этот случай не обрабатывает).

## 6. `provenance.py`

### Назначение
Запись происхождения результатов и безопасный ввод-вывод JSON. Docstring: «No shell calls, credentials, external datasets or fabricated result evidence». Модуль импортирует `torch` на уровне модуля; поэтому любой модуль, импортирующий `provenance` (`data.py`, `training.py`, `cli.py`), требует установленного `torch` уже при импорте (вывод из чтения).

### Функции и константы
- `SOURCES` — словарь с ключами `contract`, `feature_contract`, `T001`, `T007` (пути к внутренним документам исходного проекта и hex-идентификаторы ревизий; эти документы не входят в экспорт, значения здесь не воспроизводятся), `paper` = «arXiv:2108.08523v1 (2021-08-19)», `implementation` = «independent reconstruction, not original code or published-performance equality».
- `file_sha256(path)` → hex sha256 файла, чтение блоками по `1024*1024` байт.
- `source_hashes()` → `{имя_файла: sha256}` для всех `*.py` в каталоге, где лежит `provenance.py` (отсортировано по пути). Вывод: в экспорте это 24 файла пакета `ssn_hops`; их число кодом не проверяется.
- `environment()` → `python` (`sys.version`), `platform`, `packages` (версии `numpy`, `torch`, `torch-geometric`, `ssn-hop-reconstruction`, `pytest` через `importlib.metadata`; при отсутствии — `"not-installed"`), `torch_cuda_build`, `cuda_available`, `device_count`, `torch_threads`.
- `provenance(revision)` → `declared_checkout_revision`, `revision_is_user_supplied: True`, `sources`, `source_sha256`, `environment`. Ревизия пользователем только объявляется и не сверяется с репозиторием.
- `write_json(path, value)`: файл открывается в режиме `"x"` (перезапись запрещена, комментарий: защита свидетельств), `indent=2`, `sort_keys=True`, `allow_nan=False`, в конце перевод строки. `read_json(path)` читает UTF-8.

### Побочные эффекты
Чтение исходных файлов пакета; сетевых обращений и запуска подпроцессов в коде нет. Случайности нет.

### Допущения в коде
Значение `SOURCES["implementation"]` заявляет независимую реконструкцию, а не оригинальный код.

### Не установлено чтением
Существует ли дистрибутив с именем `ssn-hop-reconstruction` (файла упаковки в этом экспорте не прочитано); состав `packages` в конкретной среде.

## 7. `cli.py`

### Назначение
Командная строка (docstring: «Commands only execute when the user explicitly runs them»).

### Функции
- `revision(value)`: тип аргумента `argparse`; принимает ровно 40 шестнадцатеричных символов (`re.fullmatch`), возвращает значение в нижнем регистре, иначе `ArgumentTypeError`.
- `build_parser()`: подкоманды (обязательны, `dest="command"`):

| Команда | Аргументы | Вызов |
|---|---|---|
| `environment` | нет | `provenance.environment()` |
| `generate` | `--config`, `--out`, `--revision` (все обязательны) | `data.generate_dataset(load_config(config), out, revision)` |
| `train` | `--config`, `--data`, `--out`, `--revision` (обязательны) | `training.train(load_config(config), data, out, revision)` |
| `evaluate` | `--run`, `--data`, `--out`, `--revision` (обязательны); `--split` из `train|val|test`, по умолчанию `test`; `--device`, по умолчанию `cpu` | `training.evaluate(run, data, split, out, revision, device)` |

- `main(argv=None)`: разбирает аргументы, вызывает функцию и печатает результат в stdout как JSON (`indent=2`, `sort_keys=True`, `allow_nan=False`). Возвращает `None`. Исключений перехватывает не — ошибки проверки выходят трассировкой Python (вывод).

### Особенности (вывод из чтения)
- Устройство обучения задаётся только `train.device` в конфигурации; у `train` нет аргумента `--device`. `evaluate` берёт конфигурацию из чекпойнта, а не из аргумента.
- Из-за импортов верхнего уровня (`training` → `model` → `torch_geometric`) даже команда `environment` требует импортируемых `torch` и `torch_geometric`.
- `generate` печатает весь манифест целиком (включая траектории).
- Команды расчёта политик маршрутизации в `cli.py` отсутствуют; соответствующие модули — в планируемых `docs/04_SIMULATION_POLICIES_RU.md` и `docs/06_DRIVER_CONFIGS_RU.md`.
- Шаблоны вызова (не запускались), при `PYTHONPATH`, указывающем на каталог `src`: `python -m ssn_hops environment`; `python -m ssn_hops generate --config <config.json> --out <новый_каталог> --revision <40 hex>`; `python -m ssn_hops train --config <config.json> --data <каталог_данных> --out <новый_каталог> --revision <40 hex>`; `python -m ssn_hops evaluate --run <каталог_прогона> --data <каталог_данных> --out <файл.json> --revision <40 hex>`.

### Связи
Импортирует `config.load_config`, `data.generate_dataset`, `provenance.environment`, `training.train`, `training.evaluate`; импортируется `__main__.py`.

## 8. `__main__.py`
Две строки: `from .cli import main` и вызов `main()` при `__name__ == "__main__"`; запуск `python -m ssn_hops`. Вызов `sys.exit` отсутствует.

## 9. `__init__.py`
Docstring: «Independent reconstruction, not original author code. Runtime not validated.» Единственное имя: `__version__ = "0.1.0"`. Импортов, `__all__` и реэкспортов нет; подмодули подключаются явным импортом (`ssn_hops.config` и т. д.). Вывод: импорт самого пакета не загружает `torch`.

## 10. Не установлено чтением (сводка по девяти модулям)
1. Какие модули вне этих девяти (политики, эксперименты, драйвер) импортируют `features`, `model`, `training`, `data`; поиск по коду не дал результатов, чтение остальных модулей — в других документах.
2. Dtype `positions_km` и `adjacency` в `.npz`; содержимое `trajectory.metadata()`.
3. Фактическое число параметров и поведение `GCNConv` (расчёт в разделе 3 — ручной, при допущении о его устройстве).
4. `deterministic=True` на CUDA; совместимость `optimizer_state` с `torch.load(weights_only=True)`.
5. Существование дистрибутива `ssn-hop-reconstruction`.
6. Время, память, значения метрик: код не запускался, результаты не приводятся.

### Замечания по коду (не исправлялись)
- `data.generate_dataset` создаёт каталог до проверки манифеста: при сбое после записи `.npz` остаётся каталог без `manifest.json`.
- `training.evaluate` отвергает набор данных, чей `manifest.json` не побайтово равен манифесту обучения; заново сгенерированный набор той же конфигурации отличается полем `provenance`.
- `training.train` импортирует `canonical_json` внутри блока `with` (стиль, не ошибка).
- Явных логических ошибок при чтении не установлено.
