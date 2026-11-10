# docs/06. Драйвер и конфигурации: указатель раздела

В разделе docs/06 описаны 8 файлов `driver/` и 4 JSON-файла `configs/`. Описание разбито на 16 файлов-частей (раздел 2); этот документ — указатель. Всё получено чтением кода; ничего не запускалось, результатов запусков нет.

## 1. Какие файлы описаны

`driver/`: `run_cell.py`, `train_unit.py` (23322 байт), `selector.py` (12690), `plan_io.py` (5621), `traces.py` (6856), `__init__.py` (89), `finish.py` (13591), `ledger.py` (8067). `configs/`: `suite_m1b_cgr.json` (980), `n132.json` (1000), `simulation_n132.json` (723), `slices_m1b_cgr.json` (3128).

## 2. Файлы-части (все в каталоге `docs/`)

**`run_cell.py`** (5 частей):
- `06_DRIVER_CONFIGS_RU_partA1.md` — назначение, командная строка, 16 аргументов, раскладка экспорта, обход умолчания `--slices`.
- `..._partA2.md` — классы `CellRefused`, `TerminationSignal`, `terminate_as_exception`, функции проверки (`check_cap_minutes`, `exit_code_of`, `one_line`, `refuse_with`, `_glr_records`, `resume_verifier`, `cell_paths`, `classify`, `discard_cell`), `kill_tree`.
- `..._partA3.md` — `_spawn_and_wait`, `_judge`, `_record_interrupted`, `run_cell`, `_params`, `unknown_params`, `wall_option_problem`.
- `..._partA4.md` — ход `main`, время, файлы, сбои, повторный запуск, ревизия, побочные эффекты.
- `..._partA5.md` — связи, допущения, неустановленное, замечания к коду, охват.

**`train_unit.py`** (4):
- `..._partB1.md` — назначение, режимы, 13 аргументов, проверки аргументов, раскладка экспорта, потоки, константы.
- `..._partB2.md` — `TrainRefused` и 12 функций: `model_item`, `evaluation_output`, `step_logs`, `evaluation_logs`, `unit_paths`, `project_check`, `_readable`, `light_state`, `check_could_not_run`, `classify` (6 состояний), `_inside_root`, `discard_unit`.
- `..._partB3.md` — `run_train_unit`, `_record_interrupted_unit`, `exit_code_of`, `main`.
- `..._partB4.md` — время и учёт минут, файлы и схемы, сбои/лимит/обрыв/повтор, коды выхода, ревизия, случайность, связи, 11 замечаний, неустановленное, охват.

**`selector.py`, `plan_io.py`, `traces.py`, `__init__.py`** (4):
- `..._partC1.md` — `selector.py`: назначение, командная строка, константы, формат файла срезов, `load_slices`, `_check_item`.
- `..._partC2.md` — `selector.py`: `_matching_scenarios`, `_cap_seconds`, `resolve_item`, `check_suite_binding`, `resolve_all`, `check_partition`, `main`, пример, замечания.
- `..._partC3.md` — `plan_io.py` (`BindingError`, `PlanView`, `check_binding`, `load_readonly`, `load_for_execution`, `mark_started`).
- `..._partC4.md` — `traces.py`, `__init__.py`, находка о `light_state`, охват, поправки к C3.

**`finish.py`, `ledger.py`, конфигурации** (3):
- `..._partD1.md` — `finish.py` целиком (4 класса, 13 функций, 5 аргументов).
- `..._partD2.md` — `ledger.py` (8 функций, класс `Ledger`) и `suite_m1b_cgr.json`.
- `..._partD3.md` — `n132.json`, `simulation_n132.json`, `slices_m1b_cgr.json`.

## 3. Порядок чтения (рекомендация)

Указатель; затем C3 (привязка плана), C1-C2 (срезы); D2 (раздел 2) и D3 (конфигурации); D2 (раздел 1, журнал времени); A1-A5 (`run_cell`); B1-B4 (`train_unit`); C4 (`traces`); D1 (`finish`). Для понимания плана и серии — docs/05 (часть A), конфигураций — docs/02.

## 4. Условные обозначения

«в коде написано» — содержимое кода; «вывод из чтения» — следствие; «ручной расчёт» — арифметика с показом. Документы, которые код называет в строках (метки вида «T058», «blob 72b6fa02», «R8 addenda», «slices.json» как имя в docstring, «the m1 directory»), в экспорт не входят. Ничего не выполнялось: ни одно утверждение не значит, что код работает.

## 5. Граф импортов драйвера (прочитано в коде)

- `ledger.py`: только стандартная библиотека.
- `plan_io.py`: `ssn_hops.experiment_io`.
- `selector.py`: стандартная библиотека; лениво в `main` — `plan_io`.
- `traces.py`: `experiment_io`, `ledger.utc_now`; лениво — `plan_io`, `selector`, `Ledger`, `describe_environment` (в `main`), `sim_config`, `traffic` (в `default_make`).
- `run_cell.py`: `experiment_io`, `plan_io`, `selector`, `traces`, `ledger`; лениво — `train_unit` (`main`), `experiment_results` (`resume_verifier`).
- `train_unit.py`: `experiment_io`, `plan_io`, `run_cell`, `selector`, `ledger`; лениво — `experiments`.
- `finish.py`: `experiment_io`, `plan_io`, `run_cell`; лениво — `experiments`, `experiment_results`.
- Цикл `run_cell` ↔ `train_unit` (в `run_cell.main` импорт `train_unit` отложен). Никто из драйвера не импортирует `finish`. `__init__.py` импортов не имеет.

## 6. Командные строки шести модулей с `if __name__ == "__main__"` (из docstring и `argparse` кода)

`plan_io.py` и `__init__.py` охраны точки входа не имеют. Все команды — из «the m1 directory» (в экспорте — `CODE_EXPORT`, вывод из чтения).

```
python -m driver.run_cell --plan <root>/plan.json --revision <sha> --ledger L.jsonl --slices slices.json --slice PILOT
python -m driver.run_cell --plan ... --revision ... --ledger L.jsonl --cell <cell-id> [--counted] [--cap-minutes M]
python -m driver.run_cell --plan ... --revision ... --ledger L.jsonl --slice B1B --cells-only --cap-minutes C --wall-minutes W
python -m driver.train_unit --plan <root>/plan.json --revision <sha> --ledger L.jsonl --slices slices.json --slice TRAIN-132
python -m driver.train_unit --plan ... --revision ... --ledger L.jsonl --n 132 [--counted]
python -m driver.selector --plan <root>/plan.json --slices slices.json [--slice ID]
python -m driver.traces --plan <root>/plan.json --revision <sha> --ledger L.jsonl --slices slices.json --slice ID
python -m driver.finish preflight --plan <root>/plan.json --revision <sha>
python -m driver.finish marker    --plan <root>/plan.json --revision <sha>
python -m driver.finish check     --plan <root>/plan.json [--revision <sha>] [--deep]
python -m driver.ledger sum LEDGER.jsonl [LEDGER2.jsonl ...] [--json]
```

Коды выхода (в коде написано): `run_cell` и `train_unit` — 0, 2, 3, 4; `traces` — 0 и 4; `finish` — 0, 3, 4, 5; `selector` и `ledger` — 0 (при ошибке срезов — неперехваченное исключение).

## 7. Раскладка экспорта (вывод из чтения; не проверенные команды)

В `CODE_EXPORT/{src,driver,configs}` не разрешаются три вещи:

1. **Путь `--slices` по умолчанию.** В `run_cell.py` и `train_unit.py` это `str(Path(__file__).resolve().parents[1] / "slices.json")`. Для `CODE_EXPORT/driver/...` это `CODE_EXPORT/slices.json`; такого файла нет (файл срезов — `configs/slices_m1b_cgr.json`). Обход: явный `--slices configs/slices_m1b_cgr.json` (рабочий каталог `CODE_EXPORT`) или абсолютный путь. У `selector` и `traces` `--slices` обязателен без умолчания; в режимах `run_cell --cell` и `train_unit --n` файл срезов не читается.
2. **`src` не на пути импорта.** Модули драйвера делают `from ssn_hops import ...`, пакет лежит в `CODE_EXPORT/src/ssn_hops`. Запуск `python -m driver.<модуль>` из `CODE_EXPORT` делает доступным `driver`, но не `src`. Обход: добавить `CODE_EXPORT/src` в `PYTHONPATH` (или установить пакет иным способом; способ установки в этом разделе не установлен). То же нужно для `python -m ssn_hops.experiments`.
3. **Абсолютный корень в планах.** `body["root"]` — абсолютный путь; `plan_io.check_binding` требует, чтобы он совпадал с каталогом `plan.json` (иначе «root mismatch»), а также с ревизией плана и хешами `*.py` пакета `ssn_hops`. Готового `plan.json` в экспорте нет. Обход: создать план на машине назначения командой `python -m ssn_hops.experiments plan --suite configs/suite_m1b_cgr.json --out <новый абсолютный каталог> --revision <40 hex>` (docs/05 partA1; каталог должен не существовать) и потом указывать `--plan <этот каталог>/plan.json` только по тому же абсолютному пути и при тех же файлах `ssn_hops`. Ревизия — строка из 40 строчных hex-знаков, её задаёт вызывающий; git драйвер не читает. Шаблоны `n132.json` и `simulation_n132.json` лежат рядом с файлом серии, как требует `resolve_suite`.

Прочее: `run_cell` и `train_unit` понимают только POSIX (иначе `OSError`); `preflight` и обучение требуют `torch`.

## 8. Уточнения к частям (общая сводка; сами части не переписывались)

| Часть, раздел | Неверная формулировка | Верно |
|---|---|---|
| A1, A2, A3 (введения) | «четыре документа» | пять: A1-A5 |
| A1, п. 2.4, пункт 5 | «п. A4» | раздел 6, шаг 10 документа A4 |
| A1, раздел 1 | порядок шагов «трассы, обучение, ячейки» | A4, раздел 6, шаги 13-14: сначала трассы, затем шаги среза в его порядке |
| A5, раздел 12 | «импортирует ли `finish.py` `run_cell`, не проверялось» | импортирует (`from . import plan_io, run_cell`) и берёт `run_cell.resume_verifier` (D1, разделы 5, 9) |
| B2, п. 4.1 | фраза о `run_cell.main` (точный текст не перечитывался) | `run_cell.main` тоже перехватывает `TrainRefused` (B4, раздел 12) |
| B3, п. 4.14, последняя фраза «Вывод из чтения...» | шире, чем нужно | результат пропуска содержит только `outcome` и `id`; событие `skipped` в ledger несёт `elapsed_s=0.0` (B4, раздел 12) |
| B4, раздел 13 | «вызовы `light_state` из `finish.py`, `traces.py` не установлены» | имя не определено и не используется в `finish.py`, `ledger.py`, `traces.py`, `selector.py`, `plan_io.py`, `__init__.py`, `run_cell.py` (все прочитаны целиком); определено только в `train_unit.py` и там не вызывается; файлы `src/ssn_hops` на вызовы не проверялись |
| C3, раздел 3 | «8 методов и 1 свойство» у `PlanView` | 7 методов, 1 свойство и `__init__` (C4, раздел 3, п. а) |
| C3, раздел 8 | список вызывающих функций `plan_io` | `traces.py` — `load_for_execution`, `mark_started`; `finish.py` — `load_for_execution`, `load_readonly`, без `mark_started`; `selector.main` — `load_readonly` (C4, раздел 3, п. б) |
| C4, раздел 1.6 и сводка | «отсутствие вызовов `light_state` в `run_cell.py` не установлено» | в `run_cell.py` имя не встречается (строка выше) |
| C4, сводка | «использование `cap_seconds` вызывающими не установлено» | `run_cell.main`: `cap = cell_cap if cell_cap is not None else step.get("cap_seconds")` (D3, раздел 3.4) |
| B4, раздел 13 | «поведение `resolve_all` и `ledger_sum` — в частях C и D» | описаны: C1-C2, D2 (раздел 1) |

## 9. Что не установлено чтением (заголовки; подробности — в конце частей A5, B4, C4, D1-D3)

- Работа любой команды; раскладка экспорта (`PYTHONPATH`, `--slices`, новый корень плана) — только вывод из чтения.
- Что именно проверяют `experiment_results.verify_cell`, `verify_models`, `aggregate_plan` и `experiments.preflight_models`; вернёт ли `verify_cell` `None` для ячейки, убитой по лимиту.
- Команды и выходные файлы ячейки по плану; совпадение с текстом `execute_suite`; совпадение трассы с файлом команды `simulate trace`; точные имена файлов трасс; содержимое настоящего `plan.json`.
- Код выхода интерпретатора при необработанном исключении, `KeyboardInterrupt`, `SIGKILL`; `proc.wait(timeout=inf)`; блокировка дочернего процесса на stdin; системы без `/proc` и без POSIX-групп.
- Состав каталога `data`, содержимое `test.json`, режим записи `write_json`; длительность шагов и достаточность лимита 120 минут.
- Вызовы `check_partition` вне `selector.py` (в прочитанных файлах драйвера он вызывается только из `selector.main`; `src` не проверялся).
- Поведение `os.link` на конкретных файловых системах; параллельная запись в один ledger.
- Реальный результат `validate_suite`, `resolve_all`, `check_partition` на этом наборе конфигураций (числа 50, 162, 4 — ручной расчёт); хешируются ли байты шаблонов; содержимое трассы.
- Установка зависимостей (`torch`, `numpy`) и точные версии.
