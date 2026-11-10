# docs/06, часть C3: driver/plan_io.py

Третья часть серии C (C1-C2: selector.py; C4: traces.py и __init__.py). Как run_cell.py и train_unit.py вызывают функции этого файла, описано в частях A и B и здесь не повторяется. Условные обозначения: «в коде написано», «вывод из чтения», «ручной расчёт». Ничего не запускалось.

## 1. Назначение

В docstring: «Plan loading and binding checks for the M1 driver (project interfaces only; nothing is run here).» (в коде написано). Файл загружает plan.json для драйвера и проверяет привязки плана: к абсолютному корню, к ревизии и к хэшам исходных файлов пакета ssn_hops. В docstring сказано, что все срезы ОДНОГО плана должны выполняться под ТЕМ ЖЕ корнем, с той же ревизией и с теми же байтами исходников, и что эти привязки проверяются ДО собственных проверок проекта (experiment_io.execution_guard и validate_plan), чтобы отказ называл конкретное различие.

Файл на верхнем уровне импортирует hashlib, json, pathlib.Path и ssn_hops.experiment_io (имя eio). Значит, в отличие от selector.py, импортировать plan_io можно только при доступном ssn_hops (в экспорте это src/ssn_hops через PYTHONPATH: вывод из чтения).

## 2. Входы и выходы

Командной строки и охраны точки входа нет: это библиотечный модуль (проверено чтением: argparse не импортируется, if __name__ отсутствует). Вход: путь к plan.json; для выполнения ещё строка ревизии. Выход: объект PlanView, либо исключение. Файл записывает только execution_started.json (функция mark_started).

Положение в экспорте (вывод из чтения, не проверенная команда). Собственных путей по умолчанию в файле нет: путь к плану приходит аргументом. Условие привязки к корню: plan.json должен лежать ПРЯМО в каталоге <root>, абсолютный путь которого записан в плане (раздел 5). Файл plan.json в экспорт не входит и создаётся на целевой машине; пакет ssn_hops импортируется из src при PYTHONPATH, включающем src.

## 3. Основные классы и функции

**BindingError(ValueError)**: «The plan, root, revision or source files do not match this execution environment.» Поднимается только из check_binding.

**source_hash_of(sources)**: один sha256 (hexdigest) от строки json.dumps(sources, sort_keys=True, separators=(",", ":")), закодированной в UTF-8. Вход: словарь «имя файла -> sha256 содержимого» (body['source_sha256'] плана). Результат (docstring: «recorded in the ledger») записывается в леджер как source_sha256. Вывод из чтения: это хэш карты хэшей, а не хэш самих байтов файлов.

**check_binding(document, plan_path, revision, *, current_sources=None, expected_plan_sha256=None)**: document это разобранный plan.json. Проверки по порядку, каждая даёт BindingError:
1. Извлечение body, root, revision и source_sha256 (planned_root = Path(body["root"]).resolve()). Если KeyError, TypeError или OSError: «plan.json has no usable body/root/revision/source_sha256».
2. plan_dir = Path(plan_path).resolve().parent. Если planned_root != plan_dir: «root mismatch: the plan was created for root <planned_root> but plan.json is at <plan_dir>; all slices must run under the planned absolute root (plan moved)». Оба пути проходят resolve (символические ссылки раскрываются), сравнение полное.
3. Если expected_plan_sha256 не None и document.get("sha256") другой: «plan sha256 mismatch: file has ..., expected ...».
4. Если revision != planned_revision: «revision mismatch: supplied ..., planned ...». Это точное равенство строк; формат 40 hex здесь НЕ проверяется (см. раздел 6).
5. current = eio.source_hashes(), если current_sources не задан. Если current != planned_sources: «source hash mismatch: the installed ssn_hops bytes differ from the planned bytes in <имена>; create a new plan or install the planned revision». Имена: отсортированные ключи, у которых значения различаются (в том числе присутствующие только с одной стороны); печатаются первые 12, дальше « ...».

**PlanView(plan)**: «Read-only lookups over a loaded plan dict». Поля __init__: plan; body = plan["body"]; sha256 = plan["sha256"]; revision = body["revision"]; root = Path(body["root"]) (без resolve); cells = list(body["cells"]); cell_by_id; scenarios = list(body["scenarios"]); scenario_by_id; seed_tuples = body["suite"]["seed_tuples"] (KeyError, если в теле плана нет suite или seed_tuples); trace_owner_by_path: для каждого trace_path первый по порядку сценарий (setdefault), то есть «владелец» трассы. Методы:
- cell(cell_id): возвращает ячейку или ValueError «<id> is not a cell of this plan (unknown, or absent by design)».
- scenario(scenario_id): scenario_by_id[...] (KeyError для неизвестного).
- scenario_of(cell): сценарий ячейки.
- scenario_n(scenario) (staticmethod): scenario["config"]["orbit"]["n"].
- scenario_p(scenario) (staticmethod): scenario["config"]["failure_probability"].
- seed_index(scenario): seed_tuples.index(scenario["seeds"]) (первая равная позиция; ValueError, если кортежа нет).
- policies(): list(body["policies"]).
- source_hash (property): source_hash_of(body["source_sha256"]).
Итого 8 методов и 1 свойство плюс __init__ (ручной расчёт: cell, scenario, scenario_of, scenario_n, scenario_p, seed_index, policies = 7 методов, плюс свойство, плюс __init__; на уровне модуля 5 функций: source_hash_of, check_binding, load_readonly, load_for_execution, mark_started).

**load_readonly(plan_path)**: PlanView(eio.load_plan(plan_path)). Без проверки ревизии и без хэшей исходников, без execution_guard. Проверку корня выполняет сам eio.load_plan (раздел 7).

**load_for_execution(plan_path, revision, *, expected_plan_sha256=None, current_sources=None)**: по порядку: document = eio.read(plan_path); check_binding(...) (точные сообщения); plan = eio.load_plan(plan_path); eio.execution_guard(plan, revision); возвращает PlanView(plan). Docstring: «check_binding, then load_plan, then execution_guard (authoritative, same as execute_suite)». Ошибки чтения (FileNotFoundError, json.JSONDecodeError) не перехватываются.

**mark_started(view)**: eio.write(view.root / "execution_started.json", {"plan_sha256": view.sha256, "revision": view.revision}); возвращает True; если файл уже есть (eio.write открывает файл режимом "x", FileExistsError) возвращает False. Содержимое уже существующего файла не сверяется (вывод из чтения). Docstring: «Mirror of execute_suite's execution_started.json»; «The aggregator never reads this file; it exists only so that a staged root looks like a started one.» Другие OSError не перехватываются.

## 4. Значения по умолчанию

Единственные значения по умолчанию: current_sources=None (подставляется eio.source_hashes()), expected_plan_sha256=None (проверка не выполняется), необязательные параметры только именованные (после *). Числовой константы, кроме предела 12 имён в сообщении об исходниках (check_binding), нет.

## 5. Корень: абсолютный путь и «root mismatch»

Корень записан в плане как body["root"]. check_binding сравнивает Path(body["root"]).resolve() с каталогом, где лежит plan.json. Любое расхождение даёт «root mismatch». Следствие (вывод из чтения): копирование или переименование каталога выполнения делает план непригодным для драйвера; нужен новый план. Ту же идею выражает сообщение eio.validate_plan «plan moved: absolute commands require a fresh plan» (src/ssn_hops/experiment_io.py).

## 6. Хэши исходников и ревизия

Хэши исходников считает не plan_io, а eio.source_hashes(): {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}. Вывод из чтения: берутся все файлы *.py непосредственно в каталоге, где лежит experiment_io.py (подкаталоги не обходятся, __pycache__ не входит); ключ только имя файла; digest это sha256 всех байтов файла блоками по 1 MiB (1024*1024). Набор зависит от того, откуда импортирован ssn_hops: в экспорте от src/ssn_hops (в нём 24 модуля по docs/02-docs/05). Следствие: любое изменение байтов, включая концы строк, и любой лишний *.py в этом каталоге даёт «source hash mismatch».

Проверка 40-hex выполняется не в plan_io, а в eio.revision(value): значение должно быть строкой, полностью подходящей под регулярное выражение [0-9a-f]{40} (строчные буквы). Она вызывается в eio.validate_plan для body["revision"] (внутри load_plan) и в eio.execution_guard для переданной ревизии, затем сравнивается с планом. Порядок в load_for_execution: сначала равенство строк (check_binding), потом формат (load_plan, execution_guard).

## 7. Что проверяется и возвращается; связь с experiment_io.py

load_plan (eio) делает validate_plan(read(path), каталог плана): ровно ключи schema, body, sha256; схема из PLAN_SCHEMA = "ssn-experiment-plan-v2" или NATIVE_PLAN_SCHEMA; совпадение content_hash(body) и sha256; формат ревизии; тот же корень; sha256 каждого файла из body["file_sha256"]; пути out и config_path ячеек и trace_path сценариев внутри корня; уникальность id ячеек; проверка check_scoped_plan, если сценарии объявляют policies. execution_guard добавляет проверку ревизии и source_hashes() относительно body["source_sha256"]. Описание этих функций: docs/05 часть B (experiment_io.py). Вывод из чтения: check_binding частично дублирует проверки root, ревизии и исходников из eio, но выдаёт различимые сообщения.

## 8. Побочные эффекты, связи

Побочные эффекты: чтение plan.json, файлов, перечисленных в file_sha256, и всех *.py пакета; запись execution_started.json (только mark_started). Случайности и глобального состояния нет. Используется: selector.py (load_readonly, через main), traces.py и finish.py (load_for_execution, load_readonly, mark_started: видно в прочитанных файлах), части A и B (run_cell, train_unit).

## 9. Допущения; не установлено

В коде допущением названа только фраза о том, что execution_started.json нужен лишь затем, чтобы подготовленный корень выглядел как начатый (docstring mark_started). В docstring модуля есть метка «blob 0119dfc5» (идентификатор версии experiment_io.py): сверка этого значения внутри экспорта не выполнялась.
Не установлено: содержимое реального plan.json (его строит experiments.py, docs/05); как ведёт себя resolve на конкретной файловой системе. Наблюдения: (1) mark_started не сверяет содержимое существующего файла; (2) check_binding не проверяет формат ревизии, его проверяет позже eio; (3) PlanView требует body["suite"]["seed_tuples"] безусловно.
