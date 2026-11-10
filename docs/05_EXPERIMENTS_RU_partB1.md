# 05. Эксперименты: `experiment_io.py` (часть B1: назначение, форматы, хеши, служебные функции)

Описан один модуль: `src/ssn_hops/experiment_io.py` (19407 байт). Части: `partB1` (разделы 1-2, функции 3.1-3.10), `partB2` (проверка плана, 3.11-3.16), `partB3` (3.17-3.18 и разделы 4-10). Вызывающий модуль `experiments.py` — `05_EXPERIMENTS_RU_partA1.md`-`partA3.md`; `experiment_results.py`, `experiment_plots.py` — планируемые части C, D.

Метки: «в коде написано» — содержимое кода; «вывод» — вывод из чтения; «ручной расчёт» — арифметика с показом. Ничего не запускалось: утверждений о работоспособности и результатах нет.

## 1. Назначение

В коде написано (docstring): «Standard-library experiment records; no execution occurs on import.»

Вывод: слой ввода-вывода и проверки форматов конвейера экспериментов. Модуль (а) читает и пишет JSON; (б) задаёт строки схем; (в) считает SHA-256 файлов и исходников; (г) проверяет `plan.json`; (д) охраняет запуск (`execution_guard`); (е) запускает дочерний процесс с журналами (`job`); (ж) проверяет файлы результата «нативной» политики `TBR_bounded_exhaustive_reference` (`04_SIMULATION_POLICIES_RU_partB1.md`). Метрик не считает, не обучает, не рисует; случайности и меток времени нет.

Классов нет. Функций верхнего уровня 17, все публичные (имён с `_` нет); описаны в заголовках 3.2-3.18 (ручной подсчёт: 9 в 3.2-3.10, 6 в 3.11-3.16, 2 в 3.17-3.18; 9+6+2 = 17).

Чего модуль не делает (вывод): не пишет файлы результатов ячеек (их пишет `python -m ssn_hops.simulate run`, `04_SIMULATION_POLICIES_RU_partB2.md`), не читает записи обучения, не создаёт маркеры `training_*.json`, `model_preflight.json`, `execution_*.json` (пишет `experiments.py` через `write`). Сам создаёт файлы только в `job` (`logs/`).

## 2. Входы и выходы

### 2.1. Документы (пути относительно корня плана `<root>` = `body["root"]`)

| Документ | Кто пишет (вывод) | Роль `experiment_io.py` |
|---|---|---|
| `plan.json` = `{schema, body, sha256}` | `experiments.make_plan` | проверка: `validate_plan`, `load_plan`, `execution_guard` |
| `configs/training-n<N>.json`, `configs/s-<id>.json` | `make_plan` | хеш файла сверяется с `body["file_sha256"]` |
| `traces/t-<trace_key>.json` | `execute_suite` | читает `native_transport_check` |
| `runs/<ячейка>/{complete,result,config,traffic,provenance,packets}.json`, `events.jsonl` | `simulate run` | читает `native_transport_check` (`packets.json`, `events.jsonl` — только хеш) |
| `logs/<id>.{started,status}.json`, `.stdout.txt`, `.stderr.txt` | `job` | пишет `job` |

### 2.2. Формат записи и хеши

- `write`: `json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)` и `"\n"`, кодировка `utf-8`; `ensure_ascii` не задан (по умолчанию `json` экранирует не-ASCII: вывод).
- Каноническая форма — из `config.py`: `canonical_json(value) = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)`; `content_hash(value) = sha256(canonical_json(value).encode("utf-8")).hexdigest()`. `experiment_io.py` импортирует `content_hash`.

| Хеш | Какие байты | Где |
|---|---|---|
| `digest(path)` | байты файла, блоками по 1 MiB; 64 hex-символа | `digest` |
| `plan["sha256"]` | UTF-8 канонического JSON РАЗОБРАННОГО `body`, не байтов `plan.json` | `validate_plan`; запись — `make_plan` |
| `body["file_sha256"][путь]` | `digest` записанного файла конфигурации (зависит от формата `write`) | `make_plan`, `validate_plan` |
| `body["source_sha256"][имя]` | `digest` каждого `*.py` рядом с `experiment_io.py` | `source_hashes` |

В нативных проверках сравнивается `content_hash` обеих сторон. Вывод: пробелы и отступы `plan.json` на хеш не влияют, значения — влияют; `1`, `1.0`, `true` в каноническом тексте различны (комментарий кода: «Canonical hashes also distinguish booleans/floats from integer metadata.»); `NaN`/`Infinity` дают `ValueError` при записи и хешировании, но `read` их принимает; ключа или подписи нет. Docstring `validate_native_plan`: «Hashes detect accidental mismatch, not deliberate forgery of all inputs.» Ручной расчёт: 256 бит / 4 = 64 hex-символа; 40 hex = 160 бит.

### 2.3. Строки схем (точные, `experiment_io.py`)

| Константа | Значение |
|---|---|
| `PLAN_SCHEMA` | `"ssn-experiment-plan-v2"` |
| `NATIVE_PLAN_SCHEMA` | `"ssn-native-exhaustive-experiment-plan-v1"` |
| `NATIVE_RESULT_SCHEMA` | `"ssn-native-exhaustive-simulation-result-v1"` |
| `NATIVE_POLICY_NAME` | `"TBR_bounded_exhaustive_reference"` |

Рядом: `"ssn-native-experiment-transport-complete-v1"` (маркер `experiments.execute_suite`; здесь не используется), `"ssn-experiment-suite-v1"` (`experiments.SUITE_SCHEMA`), `"ssn-simulation-result-v2"` (`experiment_results.py`). Версия плана задана только строкой схемы; `schema_guard` называет планы и результаты v1 неподдерживаемыми. Все пути плана проверяются `inside` (3.10); `plan.json` должен лежать прямо в `<root>` (3.15).

## 3. Основные функции (часть 1)

### 3.1. Константа `NATIVE_CONTRACT`

`NATIVE_CONTRACT = {"path", "commit", "blob", "step"}` — строки, называющие документ вне экспорта (не входит в экспорт; `step = "R3/A09/S02B2A"`; `commit`, `blob` — 40-символьные hex-строки; содержание документа не установлено). Копия входит в `contract` словаря `native_options` и тем самым в хеш нативного плана (вывод).

### 3.2. `positive_budget(value, name)`

Возвращает `int(value)`. `ValueError(f"{name} must be a positive integer, not bool")`, если значение `bool`, не `numbers.Integral` или `<= 0`. Комментарий кода: целые NumPy — `Integral`, булевы скаляры NumPy — нет; `numpy`, `torch`, `simulate` для этого не импортируются.

### 3.3. `native_options(include, max_nodes=None, max_expansions=None)`

- `type(include) is not bool` -> `ValueError("include_native_tbr must be boolean")`.
- `include` ложно: любой предел не `None` -> `ValueError("TBR budgets require explicit native opt-in")`; иначе возврат `None`.
- `include` истинно: `max_nodes` по умолчанию 12 (имя в сообщении `tbr_max_nodes`), `max_expansions` — 100000 (`tbr_max_expansions`), оба через `positive_budget`.
- Возвращает словарь из 15 ключей (ручной подсчёт): `policy_identity` (= `NATIVE_POLICY_NAME`), `search_identity` (`"bounded_exhaustive_simple_paths_v1"`), `objective` (`"min_edges_then_lexicographic_full_path"`), `max_nodes`, `max_expansions`, `budget_scope` (`"independent safety controls; NOT author settings"`), `node_preflight_scope`, `scope`, `aggregation_supported` (`False`), `plots_supported` (`False`), `authority`, `contract`, `core_source_commit`, `adapter_source_commit`, `single_run_source_commit` (последние три — 40-символьные hex-строки; начала `6df24259`, `245aa27a`, `1e3c6245`).
- Вывод: словарь хешируется целиком (3.12), поэтому правка любой его строки делает прежние нативные планы непроходимыми.

### 3.4. `single_run_native_reference(native)`

Читает только `native["max_nodes"]`, `native["max_expansions"]` (иначе `KeyError`). Возвращает 13 ключей: `policy_identity`, `search_identity`, `objective`, `max_nodes`, `max_expansions`, `budget_scope`, `scope`, `node_preflight_scope`, `route_timing_scope`, `authority`, `contract` (иные `path`/`commit`/`blob`, `step = "R3/A08/S02B1B"`), `core_source_commit`, `adapter_source_commit`. Docstring: «Exact frozen single-run declaration, NOT relabeled as aggregated evidence.» Вывод: эталон для сверки `result.json` и `provenance.json` нативной ячейки (3.17).

### 3.5. `read(path)`

`json.load` из файла `utf-8`; структуру не проверяет; ошибки — `OSError`, `json.JSONDecodeError`. Вывод: `json.load` принимает `NaN`/`Infinity`, при повторе ключей берёт последнее значение.

### 3.6. `write(path, value)`

`mkdir(parents=True, exist_ok=True)` для папки файла; файл открывается в режиме `"x"`: существующий — `FileExistsError`, перезаписи нет. Формат — 2.2. Возврата нет. Вывод: запись НЕ атомарна (нет временного файла и переименования); если `json.dump` упадёт после открытия, останется неполный файл, и повторная запись по тому же пути даст `FileExistsError`.

### 3.7. `digest(path)`

SHA-256 байтов файла, блоки `1024 * 1024` байт (ручной расчёт: 1048576); возврат — 64 hex-символа. Каталог или отсутствующий файл — `OSError`.

### 3.8. `revision(value)`

Возвращает `value`, если это `str` и `re.fullmatch(r"[0-9a-f]{40}", value)`; иначе `ValueError("revision must be the actual lowercase 40-character checkout SHA")`. Только формат, не существование коммита.

### 3.9. `source_hashes()`

`{p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}`: имя -> SHA-256 каждого `*.py` в папке модуля (нерекурсивно), включая сам `experiment_io.py`. Вывод: любое изменение такого файла, включая окончания строк, меняет словарь. Все ли 24 файла `src/ssn_hops` — `*.py`, не проверялось.

### 3.10. `inside(root, relative)`

`ValueError("artifact paths must be relative without parent traversal")` для абсолютного пути или компонента `..`. Затем `path = (Path(root) / relative).resolve()`; если `not path.is_relative_to(Path(root).resolve())` — `ValueError("artifact path escapes the output root")`. Возвращает разрешённый `Path`. Вывод: символьная ссылка внутри `root`, ведущая наружу, отвергается; существование пути не требуется. `Path.is_relative_to` — библиотека Python 3.9+ (знание о библиотеке, не из кода).
