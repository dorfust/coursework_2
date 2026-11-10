# docs/06. Драйвер: driver/run_cell.py, часть A1 (из A1-A4)

Описание файла `driver/run_cell.py` разбито на четыре документа: A1 (этот), A2, A3, A4. В A1: разделы 1 (Назначение), 2 (Входы и выходы: командная строка, раскладка экспорта) и 3 (Значения по умолчанию и константы). В A2 и A3: раздел «Основные классы и функции» (все классы и функции файла). В A4: пошаговый ход `main`, измерение времени, записываемые файлы, сбои и коды выхода, пропуск готовых ячеек, связи с другими модулями, побочные эффекты, допущения, то, что не установлено чтением.

Все утверждения получены чтением кода. Ничто не запускалось. Нигде в этом описании не утверждается, что код работает или проверен. Пометка «в коде написано» означает прямую цитату или пересказ строки кода (в том числе docstring и комментария); «вывод из чтения» означает следствие из кода, которое не проверялось запуском. Ручной расчёт помечен как «ручной расчёт».

## 1. Назначение

Файл `driver/run_cell.py` исполняет ячейки (cells) плана эксперимента по одной, каждую в отдельном дочернем процессе, с ограничением по времени (cap) на ячейку и с записью журнала времени (ledger). Первая строка docstring модуля: «Capped single-cell runner: ONE cell exactly like experiment_io.job() (blob 0119dfc5). Written, NOT run.» Префикс 0119dfc5 совпадает с идентификатором блоба экспортированного `src/ssn_hops/experiment_io.py` (вывод из чтения метаданных файла).

План (`plan.json`) создаётся вне драйвера командой `python -m ssn_hops.experiments plan` (см. docs/05). Драйвер читает из плана: `body["cells"]` (у ячейки используются ключи `id`, `command`, `out`, `policy`, `scenario`), `body["scenarios"]` (используются `trace_path` и `config.orbit.n`), `body["models"][N]["run"]`, `body["revision"]`, `body["root"]`. Идентификатор ячейки в селекторе строится как `scenario["id"] + "--" + policy` (selector.py, resolve_item).

Два режима (взаимоисключающая обязательная группа аргументов):
- `--slice ID`: срез (slice) из файла срезов (по умолчанию `slices.json`, см. п. 2.3) задаёт упорядоченные шаги: `train` (обучение одного N), `trace` (генерация трасс) и `cell` (ячейка). `run_cell.main` выполняет их по порядку: сначала трассы, затем шаги обучения (если нет `--cells-only`) и ячейки.
- `--cell CELL_ID`: ровно одна ячейка плана, без файла срезов; метка среза `ADHOC` (в коде написано: `label, counted, trace_paths = "ADHOC", args.counted, ...`).

В коде написано (docstring, пункт (b)): драйвер НИКОГДА не пишет `complete.json`; этот файл может написать только дочерний процесс. Чтением подтверждено: единственные записи файлов самим модулем: `logs/<id>.started.json`, `logs/<id>.status.json` (через `eio.write`) и пустые при создании `logs/<id>.stdout.txt`, `logs/<id>.stderr.txt` (открытие с режимом `"x"`). Остальные записи делают вызываемые модули (ledger, plan_io, traces, train_unit).

Что такое «ячейка» с точки зрения дочернего процесса: команда `cell["command"]` плана. В коде написано: `argv = [sys.executable, *cell["command"][1:]]`: первый элемент команды плана (в плане это слово `python`) заменяется на интерпретатор, запустивший драйвер, остальные аргументы берутся из плана без изменений. Какая именно команда лежит в плане (в docstring упомянуты `python -m ssn_hops ...` и `python -m ssn_hops.simulate ...`), определяется `experiments.py` (docs/05), а выполнение симуляции — `simulate.py` (docs/04).

Коды выхода (в коде написано: `EXIT_OK, EXIT_FAILED, EXIT_CAPPED, EXIT_REFUSED = 0, 2, 3, 4`): 0 успех, 2 сбой, 3 превышение лимита (cap) или исчерпание «стены» (wall), 4 отказ или неверное использование.

## 2. Входы и выходы

### 2.1. Как запускается и что должно разрешаться

Модуль использует относительные импорты (`from . import plan_io, selector, traces`; `from .ledger import ...`). Поэтому он запускается как модуль пакета `driver`: `python -m driver.run_cell ...` из каталога, содержащего папку `driver/` (в экспорте это `CODE_EXPORT/`). Запуск файла по пути, вероятно, не сработает из-за относительных импортов (вывод из чтения, не проверялось). В docstring сказано «from the m1 directory»: каталог `m1` не входит в экспорт; в экспорте его роль играет `CODE_EXPORT/`.

Пакет `ssn_hops` (`from ssn_hops import experiment_io as eio`, ленивый `from ssn_hops import experiment_results`) в раскладке экспорта доступен только через `PYTHONPATH`, указывающий на абсолютный путь `CODE_EXPORT/src`; установка пакета не предусмотрена (вывод из чтения: в экспорте нет `pyproject.toml`). Дочерние процессы наследуют окружение и рабочий каталог (в `subprocess.Popen` не заданы `env` и `cwd`), поэтому `PYTHONPATH` должен быть задан в оболочке, из которой запущен драйвер (вывод из чтения).

Пример формы команды (вывод из чтения; НЕ проверялся запуском; `<ROOT>` — каталог плана, `<REV>` — 40 символов hex, `<M>` — число минут):

```
cd CODE_EXPORT
export PYTHONPATH="$PWD/src"
python -m driver.run_cell --plan <ROOT>/plan.json --revision <REV> --ledger <L>.jsonl --slices configs/slices_m1b_cgr.json --slice <ID> --cells-only --cap-minutes <M>
```

### 2.2. Аргументы командной строки (`main`, argparse)

Всего 16 аргументов (ручной расчёт по списку `add_argument` и группе). Столбцы: имя; тип/действие; значение по умолчанию; смысл.

1. `--plan` (обязателен, строка): путь к `plan.json`.
2. `--revision` (обязателен, строка): 40-символьный hex ревизии; сверяется с `body["revision"]` плана (plan_io.check_binding). Сам драйвер git не читает.
3. `--ledger` (обязателен, строка): путь к JSONL-журналу; создаётся при первой записи.
4. `--plan-sha256` (строка; по умолчанию `None`): ожидаемый хеш плана; при несовпадении `BindingError`.
5. `--slice` (`dest="slice_id"`; `None`): идентификатор среза.
6. `--cell` (`None`): идентификатор одной ячейки. Группа `--slice`/`--cell` взаимоисключающая и обязательная: нарушение даёт выход argparse с кодом 2 и справкой.
7. `--slices` (по умолчанию `str(Path(__file__).resolve().parents[1] / "slices.json")`): файл срезов.
8. `--param` (`action="append"`; `None`): `NAME=VALUE`, переопределение параметра файла срезов; можно повторять.
9. `--cap-minutes` (`float`; `None`): лимит минут на ячейку; отсутствие = без лимита (или лимит из среза).
10. `--train-cap-minutes` (`float`; `None`): лимит минут на единицу обучения.
11. `--wall-minutes` (`float`; `None`): общий бюджет «стены» на запуск; справка: «stop by itself when fewer than --cap-minutes remain of this wall».
12. `--counted` (флаг; `False`): в режиме `--cell` считать минуты в сумму.
13. `--cells-only` (флаг; `False`): пропускать шаги обучения.
14. `--keep-going` (флаг; `False`): не прерывать цикл после сбоя.
15. `--discard` (флаг; `False`): удалять неполные артефакты ячейки или трассы перед перезапуском.
16. `--env-label` (строка; `None`): метка окружения для журнала (иначе `describe_environment` строит её из `RUNNER_NAME` или хеша имени хоста).

Тип `float` у аргументов 9-11: значения `nan`, `inf`, `0`, отрицательные принимаются argparse, а затем отклоняются функцией `check_cap_minutes` (код 4). Нечисловое значение отклоняет сам argparse (выход с кодом 2; в docstring: «not remapped»).

### 2.3. Файл срезов по умолчанию: вывод из чтения

В коде написано: `--slices` по умолчанию = `parents[1] / "slices.json"`. Для файла `CODE_EXPORT/driver/run_cell.py` `parents[0]` — `CODE_EXPORT/driver`, `parents[1]` — `CODE_EXPORT`. То есть умолчание — `CODE_EXPORT/slices.json`. Такого файла в экспорте нет: единственный файл срезов лежит в `configs/slices_m1b_cgr.json`. Вывод из чтения (не проверялось запуском): в режиме `--slice` без явного `--slices` вызов `selector.load_slices` откроет несуществующий файл, возникнет `FileNotFoundError`, который входит в `REFUSAL_ERRORS`, и `main` напечатает строку `refused: ...` и вернёт 4. Обход без изменения кода: передать `--slices configs/slices_m1b_cgr.json` при рабочем каталоге `CODE_EXPORT` или абсолютный путь. В режиме `--cell` файл срезов не читается (аргумент `args.slices` используется только в ветке `--slice`), поэтому обход не нужен. В docstring и справке упомянут `slices.json` каталога `m1`: он не входит в экспорт.

### 2.4. Проверки сочетаний аргументов (все дают `refused: ...` и выход 4, до загрузки плана)

Порядок в `main` после `parse_args`:
1. `check_cap_minutes(cap_minutes=..., train_cap_minutes=..., wall_minutes=...)`: первый заданный аргумент, не лежащий строго между 0 и бесконечностью, даёт текст `--<имя-с-дефисами> must be a positive finite number of minutes (got X); omit the option for no cap`.
2. `_params(args.param)`: ошибка формата или значения `--param`.
3. `--cell` вместе с `--param`: отказ (параметры влияют только на срезы).
4. `wall_option_problem(args)`: `--wall-minutes` с `--cell`; без `--cap-minutes`; без `--cells-only`.
5. Неизвестное имя `--param` (после загрузки файла срезов, п. A4).

Отдельно: `--cell` без `--counted` печатает в stderr одну строку, начинающуюся `note: --cell without --counted: the minutes of this run are NOT counted in the 360-minute sum (label ADHOC, counted false)...`. Число 360 в коде есть только в тексте сообщения: бюджет-сумма вне экспорта, нигде в `run_cell.py` не проверяется (вывод из чтения).

### 2.5. Выходные потоки и возвращаемое значение

- stdout: по одной строке `json.dumps(result, sort_keys=True)` на каждый выполненный шаг `cell` или `train`; строки `refused: <текст>` при отказе. Шаги `trace` и пропущенные (`--cells-only`) шаги `train` строк не печатают.
- stderr: строка `note:` режима `--cell` без `--counted`; предупреждения `warning: ...` записи прерванных событий журнала; traceback необработанных исключений.
- `main` возвращает целое число; `sys.exit(main())` под охраной `if __name__ == "__main__":`. Вызов `main(argv)` из другого кода допустим: `argv` — список строк (`parse_args(argv)`).

## 3. Значения по умолчанию и константы (файл `driver/run_cell.py`)

- `STATUS_SUFFIXES = (".started.json", ".stdout.txt", ".stderr.txt", ".status.json")`: суффиксы четырёх файлов журнала ячейки в `logs/`.
- `EXIT_OK, EXIT_FAILED, EXIT_CAPPED, EXIT_REFUSED = 0, 2, 3, 4`.
- `DEFAULT_TRAIN_CAP_MINUTES = 120.0`: лимит обучения, если он не задан параметром среза `train_cap_minutes` и аргументами (то же имя и значение объявлены в `train_unit.py`). В `run_cell.py` значение используется только в `main` (`train_minutes`).
- `REFUSAL_ERRORS = (selector.SelectorError, plan_io.BindingError, FileNotFoundError, json.JSONDecodeError)`: классы, превращаемые в `refused: ...` и код 4.
- Лимиты: без `--cap-minutes` и без лимита `cap_minutes`/`cap_minutes_param` в элементе среза лимита нет (`cap_seconds=None` ведёт к `proc.wait(timeout=None)`).
- Сигнал по истечении лимита: `signal.SIGKILL` на группу процессов.
- Сигналы по умолчанию в `terminate_as_exception`: `SIGTERM`, `SIGHUP` (если определены на платформе).
- Код выхода при сигнале: `128 + номер` (ручной расчёт на Linux: SIGTERM=15 даёт 143, SIGHUP=1 даёт 129; номера сигналов — внешнее знание, в коде не заданы).
- Минуты в секунды: умножение на 60 в `main` (`args.cap_minutes * 60`, `train_minutes * 60`, `args.wall_minutes * 60`).
- Случайность: в файле нет. Часы: только `time.monotonic()` и `utc_now()` из `ledger.py`.
- Формат записи JSON: `eio.write` (`ssn_hops/experiment_io.py`): `indent=2`, `sort_keys=True`, `allow_nan=False`, режим `"x"` (существующий файл не перезаписывается, `FileExistsError`), родительские каталоги создаются.

Продолжение: A2 (классы и вспомогательные функции), A3 (запуск процесса и `run_cell`), A4 (`main` по шагам, файлы, сбои, связи, допущения).
