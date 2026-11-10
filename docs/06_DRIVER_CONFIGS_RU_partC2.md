# docs/06, часть C2: driver/selector.py (разрешение срезов, привязка к набору, разбиение, main)

Продолжение части C1 (там: назначение, командная строка, константы, формат файла срезов, load_slices и _check_item). Нумерация разделов продолжается. Условные обозначения те же: «в коде написано», «вывод из чтения», «ручной расчёт».

## 5 (продолжение). Основные функции: выбор

Объект view (в коде это PlanView из plan_io.py, часть C3) используется через атрибуты: view.scenarios, view.cells, view.cell_by_id, view.body, view.trace_owner_by_path и методы scenario_n, scenario_p, seed_index, scenario_of.

**_matching_scenarios(view, item)**: берёт item.get для N, failure_probability, seed_tuple_indices и обходит view.scenarios в порядке плана. Сценарий отбрасывается, если задан N и scenario_n(сценарий) не входит в список; если задан failure_probability и scenario_p(сценарий) не входит в список; если задан seed_tuple_indices и seed_index(сценарий) не входит в список. Условия соединены по И. Сравнение точное: оператор not in, то есть равенство Python без допуска (docstring: «exact ==, no tolerance»); вывод из чтения: 0 и 0.0 равны, поэтому запись 0.0 в файле срезов совпадёт со значением 0 в плане. Возвращает список сценариев в порядке плана.

**_cap_seconds(item, params)**: если есть cap_minutes, то float(cap_minutes) * 60.0; если есть cap_minutes_param, то float(params[имя]) * 60.0; иначе None. Пример (ручной расчёт): 90 минут дают 5400.0 секунд. Селектор только вычисляет это число и кладёт его в каждый шаг cell как cap_seconds. Как оно используется вызывающими файлами, описано в частях A и B. В конфигурации configs/slices_m1b_cgr.json поле parameters пусто ({}), ни один элемент не задаёт cap_minutes, а в её ключе "note" сказано, что потолок среза задаётся значением cell_cap триггера, а ограничение на уровне элемента «older design» не используется (цитата ключа "note"; как работает cell_cap, см. часть A).

**resolve_item(view, item, params, taken)**: возвращает список шагов одного элемента; taken это множество идентификаторов ячеек, уже занятых более ранними срезами или элементами (для exclude_earlier).

Ветвь train. Для каждого n из item["N"] по порядку: model = view.body["models"].get(str(n)). Отказ «train N=<n>: no GLR model of that N in the plan», если модели нет ИЛИ "GLR" нет в view.body["policies"] (сообщение одно и то же для обоих случаев: вывод из чтения). Отказ «the model is supplied, nothing to train», если model.get("supplied") истинно. Шаг: {"kind": "train", "id": "train-n<n>", "n": "<n>" (строка), "step_ids": [s["id"] for s in model["steps"]]}.

Ветвь trace. matched = _matching_scenarios; пусто: «trace item selects nothing». Для каждого найденного сценария берётся scenario["trace_path"]; повторы путей отбрасываются (первый выигрывает). Шаг: {"kind": "trace", "id": "trace-" + view.trace_owner_by_path[путь]["id"], "trace_path": путь}. Ключ policies в этой ветви не читается.

Ветвь cell:
1. policies берётся из элемента; declared = view.body["policies"] (объединение политик плана). Если часть заданных политик отсутствует в declared: при optional_policy_absent=true и отсутствии ВСЕХ заданных политик возвращается [] (элемент молча ничего не даёт); иначе отказ «policies [...] are not in the plan union [...]» (при частичном отсутствии флаг не спасает: вывод из чтения).
2. Нет подходящих сценариев: «cell item selects nothing (no scenario matches N/failure_probability/seed_tuple_indices)».
3. Если policies заданы: для каждого сценария и каждой политики идентификатор сценарий-id + "--" + политика должен быть в view.cell_by_id, иначе отказ «selector selects <id>, which is not in body['cells'] (absent by design)». Эта проверка идёт ДО exclude_earlier.
4. chosen = ячейки из view.cells (порядок плана), у которых c["scenario"] среди найденных сценариев и (policies не заданы или c["policy"] входит в policies). Без ключа policies берутся все политики плана для найденных сценариев.
5. exclude_earlier=true убирает ячейки, чей id есть в taken. Пусто после этого: «cell item selects nothing».
6. Шаг: {"kind": "cell", "id", "scenario", "policy", "trace_path": view.scenario_of(c)["trace_path"], "cap_seconds": cap}.

## 6. check_suite_binding(view, spec): точная проверка привязки к набору

Текст функции (в коде написано, по существу): declared = _declared_suite(spec); suite = view.body.get("suite"); planned = suite.get("name") if isinstance(suite, dict) else None; затем отказ SelectorError, только если declared is not None and isinstance(planned, str) and planned != declared. Сообщение: «the slice file is for suite <declared> but the plan was made from suite <planned>; use the slice file of this plan».

Ответы на вопросы:
- Что с чем сравнивается: значение верхнего ключа 'suite' файла срезов и строка view.body['suite']['name'] плана. Других ключей документа срезов проверка не касается (parameters, slices, note не участвуют). Сравнение только по имени (равенство строк); состав набора, seed_tuples и содержимое срезов не сверяются.
- Когда пропускается: (а) в файле срезов нет ключа 'suite'; (б) в теле плана suite не словарь или name не строка (docstring называет «synthetic test plans», ссылка на tests/synth.py: этот файл не входит в экспорт); (в) всегда, когда resolve_all не вызывается. По описанию в docs/06 частях A и B режимы run_cell --cell и train_unit --n файл срезов не читают, значит проверка в них не выполняется (в этом документе файлы run_cell.py и train_unit.py заново не перечитывались).
- Вывод из чтения: пункт (б) касается только словаря suite без строкового name, так как PlanView.__init__ безусловно читает body["suite"]["seed_tuples"].
- Единственное место вызова в selector.py: resolve_all. Через него проходит и main этого файла.
- Значение ключа 'suite' в configs/slices_m1b_cgr.json: "m1b_first_run_cgr" (прочитано). Как имя попадает в план, в docstring: body['suite']['name'] записывается функцией ssn_hops.experiments.make_plan из файла набора (docs/05).

## 7. resolve_all(view, spec)

Сначала check_suite_binding(view, spec). Затем params = spec.get("parameters", {}); taken = {} (id ячейки -> id среза); для каждого среза в порядке файла и каждого элемента по порядку вызывается resolve_item(view, item, params, set(taken)). Для каждого шага cell: если id уже в taken, отказ «cell <id> is selected by <A> and <B>» (A это ранее владевший срез, возможно тот же); иначе taken[id] = id среза. Вывод из чтения: так как taken пополняется по ходу, exclude_earlier действует и против ячеек более ранних элементов того же среза. Пустой список шагов: «slice <id> selects nothing». Дубликаты шагов train здесь не ловятся (их ловит check_partition).

Результат: dict id среза -> {"id", "counted", "steps", "cell_ids" (id ячеек по порядку шагов), "train_ns" (строки n), "trace_paths"}. trace_paths: уникальные trace_path шагов cell и trace по порядку первого появления. Порядок срезов в результате равен порядку файла (вывод из чтения: порядок вставки dict).

Порядок ячеек: срезы в порядке файла; внутри среза элементы по порядку; внутри cell-элемента порядок view.cells (порядок плана), а не порядок списков N, failure_probability или policies в файле. Для train: порядок списка N. Для trace: порядок сценариев плана без повторов путей.

Seed tuples: seed_tuple_indices это позиции в view.seed_tuples = body["suite"]["seed_tuples"]; позиция сценария определяется PlanView.seed_index как seed_tuples.index(scenario["seeds"]) (первое равное; часть C3).

## 8. check_partition(view, resolved)

Проверяет: ни одна ячейка не входит больше чем в один срез («cells in more than one slice: [...]», первые 5); множество всех cell_ids равно множеству id из view.cells («slices miss <k> plan cells and add <m> unknown cells»); множество обучений из train_ns равно множеству ключей body["models"] (если "GLR" в политиках плана, иначе пустому) и каждое n встречается ровно один раз («trainings {...} differ from the planned models [...]»). Возвращает {"cells": число, "slices": {id: число ячеек}, "trainings": отсортированный список}. Вызов в selector.py только из main (без --slice). Вызовы из других файлов в этом документе не устанавливались; finish.py и ledger.py его не используют (прочитаны).

## 9. main(argv=None): что печатается

1. from . import plan_io (нужен пакетный контекст: запуск через python -m driver.selector).
2. view = plan_io.load_readonly(--plan); resolved = resolve_all(view, load_slices(--slices)).
3. С --slice: print(json.dumps(resolved[id], indent=1, sort_keys=True)). Неизвестный id даёт KeyError (traceback).
4. Без --slice: сначала JSON с отступом 1: на каждый срез {"counted", "cells" (число), "train" (список n), "traces" (число путей)}; затем одной строкой (sort_keys) результат check_partition.
5. Возврат 0. Исключения (SelectorError, ValueError из plan_io и experiment_io, OSError, JSONDecodeError) не перехватываются: процесс завершится с трассировкой (вывод из чтения: код 1 по умолчанию Python). Явно возвращаются только 0.

## 10. Пример фильтров (configs/slices_m1b_cgr.json, прочитан)

В файле 11 срезов (ручной расчёт): TRAIN-132, TRAIN-REST (N 198 и 264), TRAIN-330 (train); PILOT, B1B (N [132, 198], exclude_earlier: true), B264, B330; CGR-PILOT, CGR-EXT1, CGR-EXT2, CGR-EXT3 (policies ["CGR_contact_plan"], N [132], failure_probability и seed_tuple_indices разные). Вывод из чтения: в B1B флаг exclude_earlier убирает ячейки PILOT, так как PILOT идёт раньше в файле. Из фильтров CGR-срезов: CGR-EXT2 задаёт 2 вероятности x 3 кортежа = 6 сценариев (ручной расчёт); сумма 3+117+15+15+1+2+6+3 из ключа "note" равна 162 (ручной расчёт; сам "note" это текст в конфигурации, а не результат расчёта кода).

## 11. Связи и побочные эффекты

Импортирует: стандартную библиотеку; plan_io (внутри main). Используется: traces.py (selector.resolve_all, selector.load_slices); run_cell.py и train_unit.py (части A и B). finish.py не импортирует selector (прочитан). Побочных эффектов нет: файлы не пишутся, случайность не используется, глобального состояния нет (только константы); main читает plan и файл срезов и печатает.

## 12. Допущения и метки в коде

Docstring несёт внутренние метки «T068, P2-X1», ссылку на tests/synth.py и слова «Written, NOT run»; метки и tests/synth.py не входят в экспорт. Слова «absent by design» обозначают ячейки, намеренно не включённые в план. Реконструкций или допущений под этим названием в selector.py нет (не установлено, кроме названного).

## 13. Не установлено чтением; наблюдения (не исправлялось)

Не установлено: как run_cell и train_unit используют cap_seconds шага (части A и B); есть ли вызовы check_partition вне selector.py. Наблюдения: (1) train без N даёт KeyError, а не SelectorError; (2) SelectorError не перехватывается в main; (3) _check_item и load_slices не защищены от значений не-словарей (AttributeError); (4) сообщение «no GLR model of that N» одинаково для отсутствия модели и отсутствия GLR; (5) NaN в parameters проходит проверку; (6) seed_index при отсутствии кортежа даёт ValueError, а не SelectorError. Определённой логической ошибки чтением не установлено.
