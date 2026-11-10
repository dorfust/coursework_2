# docs/06. Драйвер: driver/train_unit.py, часть B1 (из B1-B4)

Описание файла `driver/train_unit.py` разбито на четыре документа: B1 (этот), B2, B3, B4. В B1: разделы 1 (Назначение), 2 (Входы и выходы: командная строка, раскладка экспорта) и 3 (Значения по умолчанию и константы). В B2: раздел 4 (Основные классы и функции), первая половина: исключение `TrainRefused` и вспомогательные функции путей, проверки и удаления. В B3: раздел 4, вторая половина (`run_train_unit`, `_record_interrupted_unit`, `exit_code_of`) и раздел 5 (`main` по шагам). В B4: разделы 6-14 (время и ledger, записываемые файлы, сбои, обрыв и повторный запуск, коды выхода, ревизия, случайность, связи, побочные эффекты, допущения, замечания к коду, то, что не установлено чтением, охват).

Термины «единица обучения», «срез», «план», «ledger» употребляются так же, как в части A1 описания `driver/run_cell.py` (файл `docs/06_DRIVER_CONFIGS_RU_partA1.md`); общие для обоих файлов механизмы (запуск дочернего процесса, файлы журнала шага, сигналы) описаны в частях A2-A4 и здесь пересказываются только в той мере, в какой это нужно для `train_unit.py`.

Все утверждения получены чтением кода. Ничто не запускалось. Нигде в этом описании не утверждается, что код работает или проверен. Пометка «в коде написано» означает прямую цитату или пересказ строки кода (включая docstring и комментарии); «вывод из чтения» означает следствие из кода, не проверенное запуском; «ручной расчёт» означает арифметику, выполненную вручную по значениям из кода.

## 1. Назначение

Файл `driver/train_unit.py` исполняет «единицу обучения» плана эксперимента: шаги обучения ОДНОГО размера сети N в порядке плана. Первая строка docstring модуля: «Training unit: the plan's training steps of ONE N, in plan order (data, train, evaluate). Written, NOT run.»

Откуда берутся шаги (в коде написано, `train_unit.model_item` и `run_train_unit`): `view.body["models"][N]["steps"]`, где `N` — десятичная строка (например `"132"`). Этот список строит `src/ssn_hops/experiments.py`, функция `plan_commands` (прочитано в экспортированной копии; docs/05). По `plan_commands` для каждого N шагов три, каждый вида `{"id": ..., "command": [...]}`:
- `data-nN`: `python -m ssn_hops generate --config <root>/configs/training-nN.json --out <data> --revision <rev>`;
- `train-nN`: `python -m ssn_hops train --config <тот же файл> --data <data> --out <run> --revision <rev>`;
- `evaluate-nN`: `python -m ssn_hops evaluate --run <run> --data <data> --split test --device cpu --out <root>/training/nN/test.json --revision <rev>`.
Здесь `<root>` — корень плана, `<data>` = `<root>/training/nN/data`, `<run>` = `<root>/training/nN/run` (для модели, не поставленной через `plan --models`), `<rev>` — ревизия плана. Содержание команд `generate`, `train`, `evaluate` — docs/03.

Идентификатор единицы в ledger: `train-n{N}` (в коде написано: `uid = f"train-n{n}"`). Он совпадает по написанию с идентификатором шага `train-nN` из плана; это разные сущности (единица в ledger и шаг в `logs/`), см. раздел 7 (B4).

Как единицы попадают в работу. Срезы описывает файл срезов (`selector.py`, схема `ssn-m1-slices-v1`; описание в части C). Элемент среза вида `{"kind": "train", "N": [...]}` даёт список `train_ns`. В экспортированном `configs/slices_m1b_cgr.json` (в коде файла написано, поле `slices`) три среза обучения: `TRAIN-132` (N = 132), `TRAIN-REST` (N = 198 и 264 в одном запуске: две единицы подряд, каждая со своим лимитом), `TRAIN-330` (N = 330); у всех `"counted": true`; поле `"parameters"` этого файла пусто (`{}`).

Два режима (взаимоисключающая обязательная группа аргументов):
- `--slice ID`: единицы берутся из файла срезов (`resolved["train_ns"]`), метка среза в ledger — `ID`, флаг `counted` — из среза;
- `--n N`: ровно одна единица, без файла срезов; метка среза `ADHOC` (в коде написано: `label, counted, ns = "ADHOC", args.counted, [args.n]`).

Что модуль НЕ делает (в коде написано, docstring и чтение функций):
- не пишет `training_started.json`, `training_complete.json` (docstring: «Not mirrored (not read by the aggregator): training_started.json / training_complete.json of train_suite»), не пишет `complete.json` (его пишет только дочерний процесс `train`);
- не обучает в самом процессе драйвера: обучение, генерация данных и оценка идут в дочерних процессах; сам драйвер импортирует `torch` лишь косвенно и лениво, через проверку `project_check`;
- не читает git: ревизия приходит аргументом `--revision` (раздел 9, B4);
- не возобновляет обучение (docstring: «no resume»): неполная единица либо отвергается, либо удаляется целиком по `--discard`.

## 2. Входы и выходы

### 2.1. Как запускается и что должно разрешаться

Модуль использует относительные импорты (`from . import plan_io, run_cell, selector`; `from .ledger import Ledger, describe_environment, utc_now`), поэтому запускается как модуль пакета `driver`: `python -m driver.train_unit ...` из каталога, содержащего папку `driver/` (в экспорте это `CODE_EXPORT/`; в docstring сказано «from the m1 directory»: каталог `m1` не входит в экспорт). Пакет `ssn_hops` импортируется на верхнем уровне (`from ssn_hops import experiment_io as eio`) и лениво в `project_check` (`from ssn_hops import experiments`); в раскладке экспорта он доступен только через переменную `PYTHONPATH`, указывающую на абсолютный путь `CODE_EXPORT/src` (вывод из чтения: в экспорте нет `pyproject.toml`). Дочерние процессы наследуют окружение и рабочий каталог (раздел 5 в B3), поэтому `PYTHONPATH` должен быть задан в оболочке запуска драйвера.

Для запуска `python -m driver.train_unit` модуль `train_unit` загружается один раз (как `__main__`): `run_cell` импортирует `train_unit` лишь лениво внутри своей `main`, а она здесь не вызывается (вывод из чтения; в этом отличие от `run_cell`, см. часть A5).

### 2.2. Аргументы командной строки (`main`, argparse)

Всего 13 аргументов (ручной расчёт по списку `add_argument` и группе). Для каждого: тип, значение по умолчанию, смысл.

1. `--plan` (обязателен, строка): путь к `plan.json`.
2. `--revision` (обязателен, строка): 40-символьный hex ревизии плана; сверяется с `body["revision"]` (`plan_io.check_binding`, затем `experiment_io.execution_guard`).
3. `--ledger` (обязателен, строка): путь к JSONL-журналу времени; создаётся при первой записи события.
4. `--plan-sha256` (строка; `None`): ожидаемый хеш плана; при несовпадении `BindingError` (отказ, код 4).
5. `--slice` (`dest="slice_id"`; `None`): идентификатор среза обучения.
6. `--n` (строка; `None`): размер N одной единицы, как десятичная строка (например `132`). Группа `--slice`/`--n` взаимоисключающая и обязательная: нарушение даёт выход argparse с кодом 2 и справкой.
7. `--slices` (по умолчанию `str(Path(__file__).resolve().parents[1] / "slices.json")`): файл срезов; читается только в режиме `--slice`.
8. `--param` (`action="append"`; `None`): `NAME=VALUE`, переопределение числового параметра; можно повторять; значение — `float`, строго положительное и конечное (`run_cell._params`).
9. `--train-cap-minutes` (`float`; `None`): лимит минут на ОДНУ единицу обучения; положительное конечное число; отсутствие = параметр `train_cap_minutes` или значение по умолчанию (раздел 3).
10. `--counted` (флаг; `False`): справка: «--n mode: count in the SUM»; в режиме `--slice` не используется (флаг берётся из среза; вывод из чтения: `counted` присваивается из `resolved["counted"]`, `args.counted` дальше не читается).
11. `--discard` (флаг; `False`): удалять неполные артефакты единицы перед перезапуском (раздел 4, B2-B3).
12. `--keep-going` (флаг; `False`): после неудачной единицы продолжать со следующим N; на отказ (`TrainRefused`) не влияет.
13. `--env-label` (строка; `None`): метка окружения для ledger (`describe_environment`).

Отсутствуют (в отличие от `run_cell`): `--cell`, `--cap-minutes`, `--wall-minutes`, `--cells-only`. В docstring: «There is NO wall option here (S02c-1, D8): training slices keep the per-unit cap.» Такие опции дают выход argparse с кодом 2.

Тип `float` у `--train-cap-minutes`: `nan`, `inf`, `0` и отрицательные значения принимает argparse, после чего их отклоняет `run_cell.check_cap_minutes` (код 4). Нечисловое значение отклоняет сам argparse (выход с кодом 2; в docstring: «not remapped»).

### 2.3. Проверки аргументов до загрузки плана

Порядок в `main` после `parse_args`; каждое нарушение печатает строку `refused: <текст>` в stdout и возвращает 4:
1. `run_cell.check_cap_minutes(train_cap_minutes=...)`;
2. `run_cell._params(args.param)`: ошибка формата `NAME=VALUE` или значения;
3. при `--n`: любое имя `--param`, кроме `train_cap_minutes`, отклоняется (`have no effect with --n (only train_cap_minutes is read)`);
4. при `--n` без `--counted` в stderr печатается одна строка `note: --n without --counted: the minutes of this run are NOT counted in the 360-minute sum (label ADHOC, counted false); add --counted to count them` (это не отказ). Число 360 в коде встречается только в тексте сообщения; сумма нигде в файле не проверяется (вывод из чтения).

### 2.4. Файл срезов по умолчанию: вывод из чтения

В коде написано: `--slices` по умолчанию = `parents[1] / "slices.json"`. Для файла `CODE_EXPORT/driver/train_unit.py` `parents[1]` — `CODE_EXPORT`, то есть умолчание `CODE_EXPORT/slices.json`. Такого файла в экспорте нет: единственный файл срезов лежит в `configs/slices_m1b_cgr.json`.

Вывод из чтения (не проверялось запуском): в режиме `--slice` без явного `--slices` вызов `selector.load_slices` откроет несуществующий файл, возникнет `FileNotFoundError`, входящий в `run_cell.REFUSAL_ERRORS`; `main` напечатает `refused: ...` и вернёт 4. К этому моменту уже выполнены `plan_io.load_for_execution`, `plan_io.mark_started` (записан `execution_started.json`) и создан объект `Ledger` (файл ledger при этом ещё не создан: он появляется при первой записи события). Обход без изменения кода: `--slices configs/slices_m1b_cgr.json` (рабочий каталог `CODE_EXPORT`) или абсолютный путь. В режиме `--n` файл срезов не читается, обход не нужен.

Форма команды (вывод из чтения; НЕ проверялась запуском; `<ROOT>` — каталог плана, `<REV>` — 40 символов hex, `<LEDGER>` — путь JSONL):

```
cd CODE_EXPORT
export PYTHONPATH="$PWD/src"
python -m driver.train_unit --plan <ROOT>/plan.json --revision <REV> --ledger <LEDGER>.jsonl --slices configs/slices_m1b_cgr.json --slice TRAIN-132
python -m driver.train_unit --plan <ROOT>/plan.json --revision <REV> --ledger <LEDGER>.jsonl --n 132 --counted
```

Строки в docstring с `slices.json` (каталог `m1`) в экспорт не входят.

### 2.5. Выходные потоки и возвращаемое значение

- stdout: по одной строке `json.dumps(result, sort_keys=True)` на каждую выполненную единицу; строки `refused: <текст>` при отказе.
- stderr: строка `note:` режима `--n` без `--counted`; предупреждения `warning: the ledger finish event of the interrupted training unit ... could not be written: ...`; traceback необработанных исключений.
- `main` возвращает целое число; `sys.exit(main())` под охраной `if __name__ == "__main__":`. Вызов `main(argv)` из другого кода допустим (`parse_args(argv)`).

## 3. Значения по умолчанию и константы (файл `driver/train_unit.py`)

- `EXIT_OK, EXIT_FAILED, EXIT_CAPPED, EXIT_REFUSED = 0, 2, 3, 4`.
- `DEFAULT_TRAIN_CAP_MINUTES = 120.0`: лимит одной единицы в минутах, если нет ни `--train-cap-minutes`, ни параметра `train_cap_minutes`. В секундах: `120.0 * 60 = 7200` (ручной расчёт; умножение на 60 в `main`: `cap_seconds=minutes * 60`). Та же константа с тем же значением объявлена в `run_cell.py`; `train_unit.main` использует свою.
- Имя параметра, меняющего лимит: `train_cap_minutes` (ключ `parameters` файла срезов или `--param train_cap_minutes=NN`). В экспортированном `configs/slices_m1b_cgr.json` словарь `parameters` пуст, поэтому лимит определяется константой 120.0 либо `--param`/`--train-cap-minutes`; имя `train_cap_minutes` принимается всегда (`run_cell.unknown_params`).
- Приоритет лимита (в коде написано, `main`): `--train-cap-minutes`, иначе `params.get("train_cap_minutes", DEFAULT_TRAIN_CAP_MINUTES)`, где `params = {**spec["parameters"], **overrides}` (режим `--slice`) или `overrides` (режим `--n`).
- `OK_OUTCOMES = ("ok", "skipped_complete", "supplied_verified")`: исходы, дающие код 0.
- Лимит применяется ко всему времени единицы (все её шаги вместе, раздел 6 в B4), а не к каждому шагу.
- Случайность: в файле нет. Часы: `time.monotonic()` (интервалы) и `utc_now()` из `ledger.py` (метки).
- Условие платформы: `os.name != "posix"` даёт `OSError` в `run_train_unit` (обязательны группы процессов POSIX).

Продолжение: B2 (раздел 4: исключение и вспомогательные функции), B3 (`run_train_unit` и `main`), B4 (время, файлы, сбои, связи, допущения, не установлено).
