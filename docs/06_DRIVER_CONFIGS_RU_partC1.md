# docs/06, часть C1: driver/selector.py (назначение, командная строка, формат срезов, проверка определений)

Документ входит в серию docs/06. Части A1-A5 описывают driver/run_cell.py, части B1-B4 описывают driver/train_unit.py (там же объяснено, как эти два файла ВЫЗЫВАЮТ файлы, описанные здесь; это не повторяется). Серия C описывает четыре файла: C1-C2 это selector.py, C3 это plan_io.py, C4 это traces.py и __init__.py. Файлы finish.py, ledger.py, четыре JSON-конфигурации и указатель docs/06 описываются в части D (ещё не написана).

Терминология как в частях A и B: «план» (plan.json), «срез» (slice, запись списка slices в файле срезов), «ячейка» (cell, элемент body['cells'] плана), «обучающая единица» (training unit, шаг train). Ничего не запускалось: всё ниже получено чтением кода. Пометка «в коде написано» означает цитату или прямой пересказ строки; «вывод из чтения» означает заключение автора документа; «ручной расчёт» означает арифметику вручную.

## 1. Назначение

Первая строка docstring в selector.py: «Slice selector: slices.json (DATA) -> ordered train/trace/cell steps of ONE plan. Written, NOT run.» (в коде написано). Модуль превращает документ срезов (JSON, далее «файл срезов») в упорядоченные шаги ОДНОГО плана: шаги трёх видов kind = train, trace, cell. Фильтры элемента (item) по ключам: N, failure_probability, seed_tuple_indices, policies; плюс флаги exclude_earlier и optional_policy_absent и ограничение времени cap_minutes или cap_minutes_param (перечень ключей: docstring и константа ITEM_KEYS).

Два правила отказа из docstring: селектор, называющий ячейку, которой нет в body['cells'] («absent by design»), ОТКЛОНЯЕТСЯ; селектор, который ничего не выбирает, тоже ОТКЛОНЯЕТСЯ. Функция check_partition проверяет, что объединение всех срезов равно body['cells'] (и запланированным обучениям) и ничто не выбрано дважды.

Вывод из чтения: на верхнем уровне selector.py импортирует только argparse, collections.Counter, json, sys. Пакет ssn_hops модулем selector не импортируется; plan_io импортируется лишь внутри main. Поэтому функции load_slices, resolve_item, resolve_all, check_partition сами не требуют ssn_hops: им нужен только объект «view» с атрибутами, перечисленными в разделе 5 (в реальном вызове это PlanView из plan_io.py, часть C3).

## 2. Входы и выходы, командная строка

Запуск (docstring, «from the m1 directory»): python -m driver.selector --plan <root>/plan.json --slices slices.json [--slice ID]. Охрана точки входа в конце файла: if __name__ == "__main__": sys.exit(main()).

Аргументы main (argparse, описание «resolve M1 slices against a plan (no execution)»):
- --plan (required=True): путь к plan.json.
- --slices (required=True): путь к файлу срезов. Значения по умолчанию нет.
- --slice (dest slice_id, необязателен): идентификатор одного среза.
Итого 3 аргумента (ручной расчёт). Что печатается и какие коды возврата: часть C2, раздел 9.

Положение в экспорте (вывод из чтения, не проверенная команда). В экспорте нет каталога m1: роль «каталога m1» играет каталог CODE_EXPORT, где лежат driver/ и src/. Импорт plan_io (а он делает from ssn_hops import experiment_io) требует, чтобы src оказался в PYTHONPATH. Файл срезов лежит не в корне, а в configs/ (в этом документе прочитан только configs/slices_m1b_cgr.json). Следовательно, форма вызова из чтения такая: рабочий каталог CODE_EXPORT, PYTHONPATH включает src, аргумент --slices configs/slices_m1b_cgr.json. Файл plan.json в экспорт не входит: он создаётся функциями experiments.py (docs/05) и привязан к абсолютному корню (см. часть C3).

## 3. Константы (selector.py)

- SLICES_SCHEMA = "ssn-m1-slices-v1": строка схемы документа срезов. Конфигурация configs/slices_m1b_cgr.json начинается с "schema": "ssn-m1-slices-v1" (прочитано).
- POLICY_NAMES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan"): допустимые имена политик в ключе policies.
- ITEM_KEYS = {kind, N, failure_probability, seed_tuple_indices, policies, exclude_earlier, optional_policy_absent, cap_minutes, cap_minutes_param}: 9 допустимых ключей элемента (ручной расчёт); любой другой ключ приводит к отказу.
- SelectorError(ValueError): единственный класс исключения модуля; им сообщаются все ошибки определений и выбора.

## 4. Формат файла срезов (по load_slices и _check_item)

Верхний уровень: schema (обязателен, строго равен SLICES_SCHEMA); suite (необязателен, непустая строка: имя набора, см. check_suite_binding в части C2); parameters (необязателен, по умолчанию {}; словарь «имя -> положительное число»); slices (обязателен, непустой список). Прочие верхние ключи не проверяются (в configs/slices_m1b_cgr.json есть текстовый ключ "note", код его не читает: вывод из чтения).

Срез: словарь с ключами id (строка, уникальная), counted (строго bool) и items (непустой список элементов). Смысл counted: селектор лишь копирует флаг в результат (resolve_all: "counted": entry["counted"]) и сам ничего по нему не решает (вывод из чтения). Что с ним делают дальше, описано в ledger.py (docstring: флаг «copied from slices.json», по нему делится сумма минут на counted и not counted; часть D) и в частях A и B.

Элемент (item): kind (train, trace или cell) и необязательные ключи. Типы значений в списках: N и seed_tuple_indices: строго int (bool не проходит, потому что проверяется type(v) is int); failure_probability: int или float без bool (функция _is_number); policies: элементы из POLICY_NAMES. Все такие значения задаются НЕПУСТЫМ списком. Отсутствие ключа означает «фильтра нет» (resolve_item и _matching_scenarios используют item.get).

## 5. Основные функции, часть 1: проверка определений

**_is_number(value)**: True, если type(value) in (int, float). Значит, bool и числа NumPy не считаются числами. NaN из JSON этим тестом не отвергается (вывод из чтения: в load_slices условие v <= 0 для NaN ложно, и NaN в parameters пройдёт).

**_declared_suite(spec)**: возвращает None, если ключа 'suite' нет; иначе значение; если оно не непустая строка, SelectorError «the slices key 'suite' must be a nonempty string (the suite name of the plan)». Вызывается из load_slices и из check_suite_binding.

**load_slices(source)**: source: путь или dict. Для не-dict файл открывается в UTF-8 и разбирается json.load. Проверки по порядку: schema равна SLICES_SCHEMA («unsupported slices schema»); _declared_suite; parameters: dict с положительными числами («parameters must map names to positive numbers»); slices непустой список; id уникальны («duplicate slice id»); у каждого среза id строка и counted bool («each slice needs a string id and a boolean counted flag»); items непустой список («slice <id> has no items»); каждый элемент проходит _check_item. Возвращает тот же dict spec. Отказы без SelectorError (вывод из чтения): OSError и json.JSONDecodeError при чтении файла; AttributeError, если корень JSON или запись среза не словарь (spec.get, s.get, entry.get).

**_check_item(slice_id, item, params)**: сообщения начинаются с «slice <id>:». Правила по порядку:
1. kind не из (train, trace, cell) или есть ключи вне ITEM_KEYS: «bad item kind or unknown item keys».
2. Для ключей N, seed_tuple_indices, failure_probability, policies, если ключ есть: непустой список допустимых значений («must be a nonempty list of valid values»). Неотрицательность N и индексов не проверяется (вывод из чтения: неверное значение просто ничего не найдёт и вызовет отказ «selects nothing» в C2).
3. train: допускаются только ключи kind и N («a train item takes only N»). Наличие самого N не проверяется: train без N даст KeyError в resolve_item (вывод из чтения).
4. Для kind не cell запрещены cap_minutes, cap_minutes_param, exclude_earlier, optional_policy_absent («cap/exclude/optional keys belong to cell items only»).
5. cap_minutes и cap_minutes_param вместе запрещены; cap_minutes: число > 0; cap_minutes_param: имя из parameters; exclude_earlier и optional_policy_absent: строго bool.
Для kind = trace ключ policies проходит проверку, но resolve_item для trace его не читает (вывод из чтения, C2).

Продолжение (_matching_scenarios, _cap_seconds, resolve_item, check_suite_binding, resolve_all, check_partition, main) в части C2.
