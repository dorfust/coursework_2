# docs/06. Драйвер: driver/ledger.py и configs/suite_m1b_cgr.json, часть D2 (из D1-D3)

В этом документе описаны `driver/ledger.py` (8067 байт) и `configs/suite_m1b_cgr.json` (980 байт). Предыдущая часть — `06_DRIVER_CONFIGS_RU_partD1.md` (`finish.py`); следующая — `06_DRIVER_CONFIGS_RU_partD3.md`. Метки: «в коде написано», «вывод из чтения», «ручной расчёт». Ничего не запускалось.

# Раздел 1. driver/ledger.py

## 1.1 Назначение

Первая строка docstring: «Append-only JSONL elapsed-time ledger and ledger_sum (standard library only). Written, NOT run.» Модуль ведёт журнал событий выполнения (одна строка JSON = одно событие) и суммирует потраченные минуты. События (docstring): `start`, `finish`, `capped`, `skipped`, плюс `refused`, `discarded`. Время берётся из `time.monotonic()`, измеренного вызывающим вокруг дочернего процесса; события `finish` и `capped` несут `elapsed_s`; `finish` с `outcome = "interrupted"` тоже, чтобы сумма не занижала прерванную работу.

## 1.2 Формат, схема, имя файла, командная строка

Формат: JSON Lines, допись в конец (`"a"`), кодировка UTF-8, каждая строка — `json.dumps(line, sort_keys=True, allow_nan=False)` с `\n`. Строка схемы: `LEDGER_SCHEMA = "ssn-m1-ledger-v1"` (поле `schema` каждой записи). Имя файла в `ledger.py` не задан: путь передаёт вызывающий (аргумент `--ledger` у `run_cell`, `train_unit`, `traces`; в примерах docstring `L.jsonl`). Вывод из чтения: один файл можно делить между срезами и драйверами; отличие срезов записано в поле `slice`.

Команда (docstring, «from the m1 directory»; в экспорте — каталог `CODE_EXPORT`, вывод из чтения): `python -m driver.ledger sum LEDGER.jsonl [LEDGER2.jsonl ...] [--json]`. Охрана точки входа: `if __name__ == "__main__": sys.exit(main())`. Аргументы `main`: подкоманда `sum` (обязательна, `dest="command"`), у неё `ledgers` (`nargs="+"`, один или больше путей) и `--json` (флаг). Код возврата всегда 0; печатает либо `json.dumps(summary, indent=1, sort_keys=True)`, либо текст `format_sum`.

## 1.3 Классы и функции (8 функций модуля, 1 класс с 4 методами, ручной счёт)

- `utc_now()`: `datetime.datetime.now(datetime.timezone.utc).isoformat()` (строка ISO 8601, UTC).
- `_version(package)`: `importlib.metadata.version(package)`; любое исключение — `None` (пакет не импортируется).
- `_proc_value(path, key)`: первая строка файла, начинающаяся с `key`, значение после первого `:` (обрезанное); `OSError` или отсутствие строки — `None`.
- `describe_environment(label=None)`: словарь из 11 ключей: `label` (аргумент, иначе `"runner:<RUNNER_NAME>"` если переменная окружения `RUNNER_NAME` задана, иначе `"host:<хеш>"`), `hostname_sha256_12` (первые 12 hex-знаков SHA-256 от имени хоста), `runner_name`, `github_actions` (`GITHUB_ACTIONS == "true"`), `os` (`platform.platform()`), `python` (`platform.python_version()`), `numpy`, `torch` (версии через `importlib.metadata`, без импорта `torch`), `cpu_model` (строка `model name` из `/proc/cpuinfo`), `logical_cpus` (`os.cpu_count()`), `ram_kib` (`MemTotal` из `/proc/meminfo`, целое число; `ValueError` — `None`). Имя хоста в открытом виде не записывается.
- `read_events(path)`: генератор; несуществующий файл — ничего не даёт; пустые строки пропускаются; неразбираемая строка (`ValueError`) даёт `{"_bad_line": <первые 80 символов>}`.
- `class Ledger(path, *, plan_sha256, revision, source_sha256, environment=None)`: сохраняет путь, три привязки и окружение (по умолчанию `describe_environment()`).
  - `_env_minutes()`: сумма `elapsed_s` событий `finish` и `capped` с той же меткой окружения (`environment.label`), делённая на 60; пустое `elapsed_s` считается 0.
  - `_needs_newline()`: истина, если файл существует, не пуст и последний байт не `\n` («оборванная» последняя строка; в docstring метка «R-4», вне экспорта).
  - `record(event, kind, item_id, *, slice_id=None, counted=True, started_utc=None, finished_utc=None, elapsed_s=None, exit_code=None, **extra)`: собирает словарь из 15 ключей: `schema`, `event`, `kind`, `id`, `slice` (значение `slice_id`), `counted`, `started_utc`, `finished_utc`, `logged_utc` (`utc_now()`), `elapsed_s`, `exit_code`, `environment`, `plan_sha256`, `revision`, `source_sha256`; затем `line.update(extra)` (дополнительные поля события; они также могли бы переписать один из 15 ключей, вывод из чтения); поле `cumulative_minutes_environment` = (минуты по уже записанным событиям этой метки окружения) + `elapsed_s / 60` (только если `event` — `finish` или `capped`, иначе + 0). Далее `mkdir(parents=True, exist_ok=True)` для каталога файла; если `_needs_newline()`, перед строкой ставится `\n` (в том же `write`, чтобы оборванный текст остался отдельной неразбираемой строкой — её считает `bad_lines`); запись, `flush`, `os.fsync`; возвращается словарь строки. `NaN` в полях даёт `ValueError` (`allow_nan=False`).
- `ledger_sum(paths)`: проходит по всем путям и событиям; `_bad_line` даёт +1 к `bad_lines`; каждое другое событие даёт +1 к `events`; минуты (`elapsed_s / 60`) суммируются только по `finish` и `capped` по метке окружения (по умолчанию `"unknown"`), по `slice` (без `slice` — ключ `None`), по `kind`, и делятся на `counted` (истинное значение поля) и непосчитанные. Возвращает ключи: `events`, `bad_lines`, `minutes_by_environment`, `minutes_by_slice`, `minutes_by_kind`, `counted_minutes`, `not_counted_minutes`, `total_minutes` (= сумма двух предыдущих).
- `format_sum(summary)`: текст: строка `events N (unparsable lines M)`, блоки `minutes by environment|slice|kind` (по одной строке на ключ, 2 знака после запятой, ключи отсортированы), итог `COUNTED x min | NOT counted y min | total z min`.
- `main(argv=None)`: разбор аргументов, `ledger_sum`, печать (см. 1.2).

## 1.4 Как суммируются минуты; пределы

Минуты несут только события из `ELAPSED_EVENTS = ("finish", "capped")`; `start`, `skipped`, `refused`, `discarded` минут не добавляют. Флаг `counted` (по умолчанию `True` в `record`) в контексте драйвера берётся из файла срезов (docstring: «copied from slices.json»; срезы, термины `B0` и «установка» и решение пользователя «R8_ADDENDUM_4 item 3» названы только в строке docstring и вне экспорта; имена «TRAIN/PILOT/B1B/E*» в экспортированном `slices_m1b_cgr.json` бывают другими: см. `partD3`). Итог `counted_minutes` и `not_counted_minutes` — разбиение одной и той же суммы; `cumulative_minutes_environment` учитывает все минуты метки окружения, считанные и несчитанные (флаг `counted` его не влияет, чтение).

Бюджет и предел: в `ledger.py` нет константы бюджета и нет сравнения суммы с лимитом: код только суммирует и ничего не ограничивает. Число 700 в прочитанных файлах драйвера (`ledger.py`, `finish.py`, `run_cell.py`, `train_unit.py`, `selector.py`, `traces.py`, `plan_io.py`) не встречается. В строках `run_cell.py` и `train_unit.py` (сообщение при запуске без `--counted`) упомянута «360-minute sum»; это текст сообщения, не константа и не проверка. Событие `capped` — это остановка одной ячейки или единицы обучения по лимиту времени (`run_cell.py`, `train_unit.py`), а не ограничение суммы.

## 1.5 Значения по умолчанию, связи, побочные эффекты

Умолчания `record`: `slice_id=None`, `counted=True`, остальные поля `None`; `Ledger.environment` — `describe_environment()`. Импорты: только стандартная библиотека (`argparse`, `datetime`, `hashlib`, `importlib.metadata`, `json`, `os`, `platform`, `socket`, `sys`, `pathlib.Path`). Импортируется из `run_cell.py` (`Ledger`, `describe_environment`, `utc_now`), `train_unit.py` (те же три), `traces.py` (`utc_now` вверху; `Ledger`, `describe_environment` — лениво в `main`); `finish.py` его не импортирует. События и дополнительные поля, которые пишут эти модули, описаны в docs/06 partA3, partA4 (ячейки), partB3, partB4, раздел 6 (обучение), partC4 (трассы). Побочные эффекты: чтение всего файла журнала при каждом `record` (через `_env_minutes`); допись с `fsync`; создание каталогов; чтение `/proc/meminfo`, `/proc/cpuinfo`, имени хоста и переменных окружения; при `sum` — только чтение и печать. Случайности нет. `light_state` в `ledger.py` не встречается.

## 1.6 Допущения, непроверенное, замечания

Названо в коде: «Written, NOT run.»; флаг `counted` — «пользователь может его изменить» («the user may change a flag»). Не установлено чтением: поведение при параллельной записи в один файл из нескольких процессов (в коде блокировок нет); атомарность `write` на конкретной файловой системе; фактическое содержимое журнала. Замечания (не исправлялись, определённой логической ошибки не установлено): (1) несуществующий путь в `sum` тихо даёт нули и код 0 (вывод из чтения `read_events`); (2) один и тот же файл, переданный дважды, суммируется дважды; (3) строка, являющаяся корректным JSON, но не объектом (например число), не отмечается как `_bad_line`, и обращение `event.get` к ней даст исключение; (4) поля `extra` могут переписать служебные ключи.

# Раздел 2. configs/suite_m1b_cgr.json

## 2.1 Назначение и ключи

Это файл серии (suite) для `experiments.py` (`resolve_suite`, `validate_suite`, `make_plan`; docs/05, часть A2, разделы 4-7). В файле 10 ключей верхнего уровня (ручной счёт): девять обязательных (`SUITE_REQUIRED_KEYS`) и один необязательный (`policy_scope`, `SUITE_OPTIONAL_KEYS`).

- `schema`: `"ssn-experiment-suite-v1"` — равно `SUITE_SCHEMA` (сравнение по чтению).
- `name`: `"m1b_first_run_cgr"`; должно подходить под шаблон `[a-z][a-z0-9_-]{0,39}`; длина 17 (ручной счёт: 4 + 5 + 1 + 3 + 1 + 3 знаков с подчёркиваниями). Тем же именем файл срезов привязан к плану (ключ `suite`, `partD3`).
- `core_template`: `"n132.json"`, `simulation_template`: `"simulation_n132.json"`. Пути читаются относительно каталога файла серии (`suite_path.parent`, docs/05 partA2); в экспорте оба шаблона лежат в `configs/` рядом с файлом серии (вывод из чтения).
- `training_overrides`: `{"model": {"features": "adjacency_spliced_two_hop", "feature_version": 1}, "train": {"epochs": 300}}`. Слияние с шаблоном — `merge` (рекурсивно по словарям): значения `features` и `feature_version` совпадают со значениями в `n132.json` (их замена ничего не меняет), `train.epochs` = 300 вместо 100 шаблона.
- `simulation_overrides`: `{}` (пусто: шаблон симуляции не меняется).
- `seed_tuples`: 5 троек `[phase, traffic, failure]`: `[401,501,601]`, `[402,502,602]`, `[403,503,603]`, `[404,504,604]`, `[405,505,605]`. По `validate_suite` нужно не менее 5 троек, все 15 чисел различны и не пересекаются с `core.data.train_seeds + val_seeds + test_seeds + [train.seed]` (101-108, 201, 202, 301, 302, 17); условия выполняются по ручной сверке (401-405, 501-505, 601-605). Каждая тройка заменяет `phase_seed`, `traffic_seed`, `failure_seed` шаблона симуляции; индекс тройки (0-4) — то, что в файле срезов называется `seed_tuple_indices`.
- `grids` (2 сетки; ключи `name`, `axis`, `sizes`, `probabilities`): `"interruption"`, `axis = "failure_probability"`, `sizes = [{n: 132, planes: 12}]`, `probabilities = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]` (7 значений); `"size"`, `axis = "n"`, `sizes = [{132, 12}, {198, 18}, {264, 24}, {330, 30}]`, `probabilities = [0.04]`. Проверки по коду (docs/05 partA2, раздел 5.2) выполняются по ручной сверке: N не повторяется внутри сетки; N=132 во обеих сетках имеет одинаковые `planes = 12`; `n % planes == 0` (132/12 = 11, 198/18 = 11, 264/24 = 11, 330/30 = 11).
- `sensitivities`: `[{"name": "reference", "overrides": {}}]` — один вариант без переопределений (разрешены только `tick_s`, `rate_bytes_s`, `arrival_interval_s`).
- `policy_scope`: `{"CGR_contact_plan": {"n": [132], "failure_probability": [0.0, 0.02, 0.04, 0.06], "seed_tuple_indices": [0, 1, 2]}}`. По коду (`validate_policy_scope`, `scope_policies`, partA2 раздел 5.4): политика `CGR_contact_plan` выполняется только там, где выполнены все три фильтра; политики без записи (`GLR`, `TBR_style_hop_oracle`, `TSR_source_dijkstra`) — везде. Допустимость значений (132 — размер сетки; 0.0, 0.02, 0.04, 0.06 есть среди вероятностей сетки `interruption`; индексы 0-2 < 5) — по ручной сверке.

## 2.2 Ручной расчёт числа сценариев, ячеек и обучений

Сетка `interruption`: 1 размер × 7 вероятностей × 1 вариант × 5 троек = 35. Сетка `size`: 4 × 1 × 1 × 5 = 20. Сценарии N=132, p=0.04 входят в обе сетки с той же конфигурацией и тем же именем варианта, поэтому в плане они одиночные (вывод из чтения partA2, раздел 5.2: слияние по `memberships`): 5 совпадений. Итого 35 + 20 − 5 = 50 сценариев. Ячейки: три политики без записи в `policy_scope` на каждый сценарий: 50 × 3 = 150; `CGR_contact_plan`: N=132, 4 вероятности × 3 индекса = 12; всего 150 + 12 = 162 (совпадает с числом в поле `note` файла срезов). Обучающих единиц: по одной на каждый N из размеров сеток — 132, 198, 264, 330, то есть 4 (partA2 раздел 5.3). Для каждого N конфигурация обучения = `merge(core, {"orbit": size})` (подставляются `n` и `planes`).

## 2.3 Допущения и неустановленное

В файле нет комментариев (JSON их не допускает). Не установлено чтением: реальный проход `validate_suite` на этом файле (ничего не запускалось; выводы выше — сверка текста файла с правилами, описанными в docs/05); точный состав `body["cells"]` и правило слияния сценариев при реальном создании плана.
