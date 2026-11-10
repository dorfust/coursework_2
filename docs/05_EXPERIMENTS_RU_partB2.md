# 05. Эксперименты: `experiment_io.py` (часть B2: проверка плана и запуска)

Продолжение `05_EXPERIMENTS_RU_partB1.md` (назначение, форматы, правила хеширования, функции 3.1-3.10). Здесь — функции 3.11-3.16 модуля `src/ssn_hops/experiment_io.py`. Метки те же: «в коде написано», «вывод», «ручной расчёт». Ничего не запускалось. Ошибки — `ValueError` с указанным текстом, возврат — `None`, если не сказано иначе.

## 3. Основные функции (часть 2)

### 3.11. `schema_guard(plan)`

- `plan.get("schema")` не входит в (`PLAN_SCHEMA`, `NATIVE_PLAN_SCHEMA`) -> `"unsupported plan schema; v1 plans/results must be regenerated for the T022-S01 input contract"` (`T022-S01` — внутренняя метка в строке кода; документ не входит в экспорт).
- Для `PLAN_SCHEMA` (`body = plan.get("body", {})`) ошибка `"native plans require the isolated native schema, not legacy v2"`, если: в `body` есть ключ `native_reference` или `resolved_templates`; `NATIVE_POLICY_NAME` в `body.get("policies", [])`; любая ячейка имеет `policy == NATIVE_POLICY_NAME` или среди элементов `command` есть `"--tbr-max-nodes"` или `"--tbr-max-expansions"`.
- Для `NATIVE_PLAN_SCHEMA` больше ничего не проверяется; хеш не проверяется. Вывод: вход не словарь даёт `AttributeError` (нет `.get`). Вызывают: `validate_plan`, `execution_guard`, `experiment_results.scientific_plan_guard`.

### 3.12. `validate_native_plan(plan)`

Docstring: «Reconstruct every resolved scenario and exact argv; no execution/import ML.»; «Saved resolved templates avoid rereading movable original suite/template paths.» Ленивый импорт из `.experiments`: `CONTRACT`, `FEATURE_CONTRACT`, `POLICIES`, `merge`, `plan_commands`, `resolve_plan_inputs`, `validate_suite`. Проверки по порядку:

1. `set(body)` равен ровно 16 ключам (ручной подсчёт): `suite`, `revision`, `root`, `contract`, `feature_contract`, `mode`, `source_sha256`, `policies`, `models`, `scenarios`, `cells`, `offline_steps`, `file_sha256`, `execution`, `native_reference`, `resolved_templates` -> `"native plan fields mismatch"`.
2. `content_hash(body["native_reference"])` равен `content_hash(native_options(True, native["max_nodes"], native["max_expansions"]))` -> `"native plan metadata mismatch"` (сам `native_options` может поднять ошибку об пределах).
3. `mode` ∈ {`"baselines_only"`, `"with_trained_GLR"`} -> `"native plan mode mismatch"`.
4. `body["policies"] == list(POLICIES[1:] if baselines_only else POLICIES) + [NATIVE_POLICY_NAME]` -> `"native plan policy order/set mismatch"` (нативная политика всегда последняя).
5. `contract == CONTRACT`, `feature_contract == FEATURE_CONTRACT`, `execution == "sequential user invocation only; no resume/overwrite"` (обычное `!=`, не хеш) -> `"native plan contract/execution mismatch"`.
6. `str(Path(body["root"]).resolve()) == body["root"]` -> `"native plan root must be canonical and absolute"`.
7. `resolved_templates` — ровно `{"core", "simulation"}` (иначе `"native resolved template fields mismatch"`); `from_dict` / `from_sim_dict` и `to_dict()` должны вернуть то же содержимое -> `"native templates must be fully resolved"`.
8. Если в `suite` есть `policy_scope` -> `"native plans do not support policy_scope"` (комментарий кода: «the native plan schema is frozen»). Затем `validate_suite(suite, core, sim)`; `merge(core.to_dict(), suite["training_overrides"])` и `merge(sim.to_dict(), suite["simulation_overrides"])` должны равняться своим шаблонам -> `"native resolved templates disagree with suite overrides"`.
9. Не `baselines_only`: `require_supported_model(core.model)`.
10. `body["models"]`: ключ — `str` из цифр, `item["supplied"]` — ровно `bool` (`"native model mapping mismatch"`), `item["run"]` — `str` (`"native model run path mismatch"`); пути готовых моделей собираются в словарь `supplied`.
11. `resolve_plan_inputs(suite, core, sim, root, supplied, baselines_only, expected_native)` и `plan_commands(root, training, scenarios, policies, body["revision"], expected_native)` заново строят модели, сценарии, шаги, ячейки; `content_hash` каждого из `body["models"]`, `body["scenarios"]`, `body["offline_steps"]`, `body["cells"]` должен совпасть -> `f"native resolved {label}/command mismatch"`. Вывод: внутри `resolve_plan_inputs` повторно выполняются предел N ≤ `max_nodes` и, при `with_trained_GLR`, `check_model` (`05_EXPERIMENTS_RU_partA2.md`, `partA3.md`).
12. Ключи `body["file_sha256"]` должны точно совпадать со всеми `config_path` моделей и сценариев -> `"native configuration file hash map mismatch"`; для каждого `content_hash(read(inside(root, путь)))` равен `content_hash(config)` -> `"native saved config differs from resolved scenario/model"`.

Вывод: значения `file_sha256` здесь не проверяются (делает `validate_plan`), так же как формат `revision`; `source_sha256` — `execution_guard`; чекпойнты и файл suite не требуются. Единственный побочный эффект — чтение файлов конфигурации.

### 3.13. `check_scoped_plan(document)`

Вызывается из `validate_plan` только если хотя бы у одного сценария есть ключ `policies` (план с `policy_scope`, `experiments.validate_policy_scope`, `05_EXPERIMENTS_RU_partA2.md`). Ленивый импорт `POLICIES`. Проверки:

1. схема равна `NATIVE_PLAN_SCHEMA` -> `"native plans do not support policy_scope"`;
2. каждый сценарий имеет `policies` (иначе `"scoped plan: every scenario must declare policies (mixed plans are rejected)"`);
3. `policies` сценария — непустой `list` строк из `POLICIES`, без повторов, в каноническом порядке (`[rank[p] ...] == sorted({rank[p] ...})`) -> `"scoped plan: scenario policies must be a nonempty canonical-order list of distinct known policies"`; нативная политика не входит в `POLICIES` и отвергается (вывод);
4. `body["policies"] == [p for p in POLICIES if p in union]` (объединение списков сценариев) -> `"scoped plan: body policies differ from the union of scenario policies in canonical order"`;
5. список `(c["id"], c["scenario"], c["policy"])` по `body["cells"]` равен (с порядком) `[(s["id"] + "--" + p, s["id"], p) for s in scenarios for p in s["policies"]]` -> `"scoped plan: cells differ from scenarios x their declared policies"`.

Команды и `out` ячеек не перевыводятся (комментарий кода: «Cell commands/out paths are not re-derived here (as for legacy plans).»).

### 3.14. `validate_plan(document, expected_root=None)`

Порядок проверок:

1. `set(document) == {"schema", "body", "sha256"}` -> `"unsupported plan fields"`.
2. `schema_guard(document)` (3.11).
3. `content_hash(body) == document["sha256"]` -> `"plan content hash mismatch"`.
4. `revision(body["revision"])` (3.8).
5. `root = Path(body["root"]).resolve()`; если `expected_root` задан и `root != Path(expected_root).resolve()` -> `"plan moved: absolute commands require a fresh plan"`.
6. Для каждой пары `body["file_sha256"]`: `digest(inside(root, имя)) == ожидаемое` -> `f"planned file hash mismatch: {name}"` (отсутствующий файл — `FileNotFoundError`).
7. Для каждой ячейки `inside(root, cell["out"])`, `inside(root, cell["config_path"])`; для каждого сценария `inside(root, scenario["trace_path"])`.
8. Уникальность `id` ячеек -> `"duplicate plan cell"`.
9. Если у какого-либо сценария есть `policies` — `check_scoped_plan(document)` (3.13).
10. Если схема нативная — `validate_native_plan(document)` внутри `try`; `KeyError`, `TypeError`, `AttributeError`, `OverflowError` превращаются в `ValueError("malformed native plan")`; собственные `ValueError` проходят как есть, `OSError` не оборачивается.

Возвращает `document`. Вывод: (а) для `PLAN_SCHEMA` сценарии, ячейки и команды не пересчитываются: проверяются самосогласованность хеша, пути и хеши конфигов; (б) `sha256` не зависит от секрета: кто изменит `body` и пересчитает `sha256`, пройдёт шаг 3, а команды `PLAN_SCHEMA` не перепроверятся; `job` (3.18) исполняет argv из плана, поэтому план из недоверенного источника исполнять нельзя; (в) отсутствующий ключ в плане `PLAN_SCHEMA` даёт `KeyError`, не `ValueError`; (г) `source_sha256` здесь не сравнивается.

### 3.15. `load_plan(path)`

`path = Path(path).resolve()`; `validate_plan(read(path), path.parent)`; возвращает документ. Ошибки: `OSError`, `json.JSONDecodeError`, ошибки 3.14, в частности «plan moved», если папка файла не равна `body["root"]`. Вывод: перенос или переименование папки плана (включая другой репозиторий) делает план непригодным: команды содержат абсолютные пути, нужен новый `plan`. Ревизия не сравнивается. Вызывается из `experiments.main` для `train`, `execute`, `aggregate`.

### 3.16. `execution_guard(plan, supplied_revision)`

1. `schema_guard(plan)`.
2. Для нативной схемы — `validate_plan(plan)` без `expected_root` (комментарий кода: «Direct API execution gets the same hash/path/config/bounds/argv preflight.»).
3. `revision(supplied_revision) == plan["body"]["revision"]` -> `"execution revision differs from planned revision"`.
4. `source_hashes() == plan["body"]["source_sha256"]` -> `"source files changed since planning; create a new plan"`.

Вывод: словари сравниваются целиком: любое добавление, удаление или правка `*.py` в пакете после плана даёт ошибку. Ревизия — строка, заявленная пользователем; с реальным git модуль её не сверяет (git не вызывается). Для плана `PLAN_SCHEMA`, переданного напрямую без `load_plan`, `validate_plan` не вызывается; в командах `train`, `execute` план проходит `load_plan` раньше (`experiments.main`). Вызывают: `train_suite`, `execute_suite`.
