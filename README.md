# ssn_hops: код сравнения маршрутизации GLR / TBR / TSR / CGR на моделируемом LEO-созвездии

## 1. Назначение

Код реконструирует сравнение алгоритмов маршрутизации GLR, TBR, TSR и CGR на моделируемом низкоорбитальном (LEO) созвездии спутников по мотивам статьи arXiv 2108.08523 (реконструкция, не исходный код авторов статьи; так написано в самом коде: «independent reconstruction»). Папка содержит: симулятор пакетной сети с квантованием времени (тик), регрессионную модель числа хопов, которую использует политика GLR, четыре политики маршрутизации, конвейер экспериментов (план, обучение, выполнение, агрегирование, графики) и драйвер, который выполняет план по частям («срезам»).

## 2. СТАТУС (прочитайте до использования)

> **Эта папка написана и описана только чтением. НИЧЕГО НЕ ЗАПУСКАЛОСЬ: авторы экспорта не выполняли ни импорт модулей, ни тесты, ни одной команды. Описание в `docs/` — статическое чтение кода; независимую проверку прошла только выборка: структура папки (96 файлов на момент этой проверки) и 60 утверждений из описания (прочитана примерно часть файлов описания) сверены с кодом; результаты — в `docs/ERRATA_RU_part3.md`. Полной независимой проверки описания нет, проверяющий был из той же модельной семьи, что и автор (согласованные ошибки возможны), и ни одна проверка не выполняла код. Фразы о статусе проверки в других файлах (например, в `docs/07_LIMITATIONS_RU.md`: «не проходило независимой проверки») отражают момент их написания; актуальный статус — здесь. Код — дословная копия исходных файлов и может содержать дефекты, не найденные чтением. Ни одна фраза этой папки не означает, что код работает, проходит тесты или даёт какие-либо результаты. Результатов экспериментов в папке нет.**

Метки в описании: «в коде написано» — пересказ или цитата кода; «вывод из чтения» — заключение без запуска; «ручной расчёт» — арифметика, показанная в тексте.

## 3. Состав папки

```
README.md                      этот файл
src/ssn_hops/                  пакет, 24 файла
  __init__.py                  docstring и __version__ = "0.1.0"
  __main__.py                  вход `python -m ssn_hops`, передаёт управление в cli
  cli.py                       команды environment / generate / train / evaluate
  config.py                    конфигурации орбиты, данных, модели, обучения; проверка, хеши, JSON
  sim_config.py                SimulationConfig, ticks(), service_ticks()
  geometry.py                  положения спутников, видимость, смежность
  contacts.py                  GeometryNetwork (снимок графа по тику), план контактов, earliest_hop
  graph.py                     метки числа хопов, структура Q (1 / 0.5 / 0), входы ветвей модели
  traffic.py                   трасса пакетов, её документ и проверка, edge_tick_failure
  features.py                  проверка смежности и дальностей, признаки задержки
  data.py                      генерация набора данных train/val/test и manifest.json
  model.py                     модель предсказания хопов (torch_geometric), predict_hops
  loss.py                      функция потерь обучения
  training.py                  train, evaluate, load_trained_model
  provenance.py                хеши исходников, описание среды, запись JSON с режимом "x"
  simulator.py                 тиковый симулятор «сохранить и переслать» (store-and-forward)
  policies.py                  GLR, HopOracle (TBR_style_hop_oracle), SourceDijkstra (TSR), ContactRouting (CGR)
  tbr_policy.py                опциональная политика TBR_bounded_exhaustive_reference
  tbr_reference.py             исчерпывающий поиск простых путей с границами (ядро этой политики)
  simulate.py                  команды trace и run (одна политика, один прогон)
  experiments.py               plan / train / execute / aggregate / plot
  experiment_io.py             JSON, хеши, проверка плана, охрана запуска, запуск процесса
  experiment_results.py        проверка сохранённых прогонов, агрегирование в сводку
  experiment_plots.py          проверка сводки, рисунки PNG и данные рисунков
driver/                        8 файлов (запуск плана по срезам)
  __init__.py                  только docstring
  plan_io.py                   загрузка плана и проверка привязки (корень, ревизия, хеши)
  selector.py                  разбор файла срезов в шаги (обучение, ячейки)
  run_cell.py                  выполнение ячеек/срезов с лимитами времени и журналом
  train_unit.py                выполнение обучающих единиц
  traces.py                    создание файлов трасс трафика для среза
  finish.py                    команды preflight / marker / check
  ledger.py                    журнал времени JSONL и команда sum
configs/                       4 JSON
  suite_m1b_cgr.json           файл серии (сетки, сиды, область политик)
  n132.json                    шаблон конфигурации обучения
  simulation_n132.json         шаблон конфигурации симуляции
  slices_m1b_cgr.json          расписание срезов для этой серии
docs/                          описание на русском (группы 01-07; ERRATA_RU.md, ERRATA_RU_part2.md, ERRATA_RU_part3.md)
```

## 4. Что НЕ входит в папку

- Тесты (каталог `tests/`, эталонные реализации): в строках кода упомянуты, например, `tests/reference/contacts_ref.py`; в экспорте их нет, поэтому проверок, на которые ссылаются комментарии кода, здесь нет: в `contacts.py` комментарий называет эталонную функцию из `tests/reference/contacts_ref.py`, в `geometry.py` комментарий называет довод о побитовом равенстве ветвей в документе, не входящем в экспорт (пересказ, не цитата).
- Инструменты анализа и построения отчётов, кроме `experiment_plots.py`.
- Файл метаданных проекта: **нет ни `pyproject.toml`, ни файла requirements**; пакет не устанавливается, а подключается через `PYTHONPATH` (раздел 6).
- Другие файлы срезов и серий: код называет в строках `slices.json`, `suite_m1`, `suite_m1_nocgr` (не входит в экспорт); готового `plan.json` тоже нет.
- Документы, которые код называет только строками (не входит в экспорт): `SIMULATION_PROTOCOL.md`, `R3_FEATURES.md`, `TBR_NATIVE_ADAPTER.md`, `TBR_NATIVE_SINGLE_RUN.md`; пути вида `Repo_Orchestrator_2/tasks/...` в словарях `CONTRACT`, `FEATURE_CONTRACT`, `NATIVE_CONTRACT`, `SCIENTIFIC_CONTRACT` и в `provenance.SOURCES` (`Repo_Research_2/artifacts/...`); `Repo_Code_2/artifacts/T056/S02_CHANGED_PATHS.md` (комментарий в `geometry.py`); метки задач и аудитов в комментариях (`T0xx`, `DESIGN T048`, `R8 addenda`) и слова «the m1 directory» в docstring драйвера. Эти строки код только записывает в документы плана и результатов; файлы по ним не читаются (вывод из чтения; подробности — в `docs/02`-`docs/06`).

## 5. Зависимости (вывод из чтения строк `import`)

- Python 3.10 или новее: в коде есть аннотации `int | None`, `list[int] | None`, `Decision | None`, вычисляемые при определении класса или функции (`simulator.py`, `tbr_policy.py`, `tbr_reference.py`).
- Сторонние пакеты: `numpy` (напрямую его импортируют data, features, geometry, contacts, graph, model, policies, simulator, tbr_policy, tbr_reference, training), `torch` (graph, provenance и др.), `torch_geometric` (model).
- `matplotlib`: подключается лениво, только внутри `experiment_plots.py` (команда `plot`); в метаданных исходного проекта не объявлена.
- Версии. По прочтению метаданных исходного проекта (файл не входит в экспорт): `python >=3.10,<3.15`, `numpy>=1.26,<3`, `torch>=2.6,<3`, `torch-geometric>=2.6.1,<3`. Это пересказ прежнего чтения; в этой папке проверить его нельзя; совместимость конкретных версий не установлена.
- `torch` нужен и командам, которые выглядят лёгкими. `provenance.py` делает `import torch` на уровне модуля (проверено по тексту файла); его импортируют `cli.py`, `data.py`, `training.py` и `simulate.py`. Поэтому `python -m ssn_hops environment` и даже `python -m ssn_hops.simulate trace` требуют установленного `torch`. Каждой команде `python -m ssn_hops` нужен и `torch_geometric`: `cli.py` на верхнем уровне импортирует `training`, `training.py` импортирует `model`, а `model.py` — `torch_geometric.nn` (цепочка `cli` → `training` → `model`), тогда как в `simulate.py` модули `model` и `training` подключаются лениво и только для политики GLR (вывод из чтения). Цепочка `config` → `sim_config` → `traffic` импортирует только стандартную библиотеку (`sim_config.py` и `traffic.py` прочитаны, `config.py` — по индексу `docs/02`); значит, команда `plan` и модули драйвера, кроме `finish preflight`, по чтению обходятся без `torch`, но `docs/05` отмечает это как не установленное. Обучение и `finish preflight` требуют `torch` (см. `docs/03`, `docs/04` часть B2, `docs/06`).
- Драйвер сам использует только стандартную библиотеку и пакет `ssn_hops`; он рассчитан на POSIX (Linux, WSL2): `run_cell` и `train_unit` при другой ОС бросают `OSError` (по `docs/06`).

## 6. Как код предполагается запускать (чтение; НЕ ПРОВЕРЕНО ЗАПУСКОМ)

Условия, найденные при чтении (`docs/06_DRIVER_CONFIGS_RU.md`, раздел 7):

1. Рабочий каталог — корень экспорта (папка, где лежат `src/`, `driver/`, `configs/`); `PYTHONPATH` — абсолютный путь к `src`. Модули драйвера делают `from ssn_hops import ...`, а дочерние процессы наследуют окружение и каталог.
2. `--slices`: умолчание в `run_cell.py` и `train_unit.py` — `Path(__file__).resolve().parents[1] / "slices.json"`, то есть `slices.json` в корне экспорта; такого файла нет. Обход (вывод из чтения): `--slices configs/slices_m1b_cgr.json`. В режимах `run_cell --cell` и `train_unit --n` файл срезов не читается; у `selector` и `traces` `--slices` обязателен.
3. План привязан к абсолютному корню: `plan_io.check_binding` требует, чтобы `body["root"]` совпадал с каталогом `plan.json`. Перенесённый или скопированный план отвергается с текстом «root mismatch»: создайте новый план в окончательном месте (каталог `--out` не должен существовать).
4. `--revision` — строка из 40 шестнадцатеричных знаков, задаваемая вызывающим; код git не читает. Проверка в `experiment_io.revision` требует строчные буквы; во всех командах одного плана значение одно и то же.
5. План также хранит хеши всех `*.py` пакета `ssn_hops`; при изменении файлов между планом и выполнением привязка откажет.

```
# НЕ ЗАПУСКАЛОСЬ. Чтение кода. Подготовка окружения (оболочка bash):
cd <корень экспорта>
export PYTHONPATH="$PWD/src"
```

```
# НЕ ЗАПУСКАЛОСЬ. Чтение cli.py: python -m ssn_hops <команда>
python -m ssn_hops environment
python -m ssn_hops generate --config <config.json> --out <новый каталог> --revision <40 hex>
python -m ssn_hops train --config <config.json> --data <каталог набора> --out <новый каталог> --revision <40 hex>
python -m ssn_hops evaluate --run <каталог прогона> --data <каталог набора> [--split train|val|test] [--device cpu] --out <новый файл.json> --revision <40 hex>
```

```
# НЕ ЗАПУСКАЛОСЬ. Чтение simulate.py: python -m ssn_hops.simulate <trace|run>
python -m ssn_hops.simulate trace --config <simulation.json> --out <новый файл.json>
python -m ssn_hops.simulate run --config <simulation.json> --trace <файл трассы> --policy <имя> --out <новый каталог> --revision <40 hex> [--checkpoint-run <каталог прогона обучения>] [--p <вероятность>] [--rate-bytes-s <число>] [--tbr-max-nodes N] [--tbr-max-expansions N]
# имя политики: GLR | TBR_style_hop_oracle | TSR_source_dijkstra | CGR_contact_plan | TBR_bounded_exhaustive_reference
# --checkpoint-run нужен только для GLR (код отказывает в остальных случаях)
```

```
# НЕ ЗАПУСКАЛОСЬ. Чтение experiments.py: python -m ssn_hops.experiments <plan|train|execute|aggregate|plot>
python -m ssn_hops.experiments plan --suite configs/suite_m1b_cgr.json --out <новый абсолютный каталог> --revision <40 hex> [--models <файл.json>] [--baselines-only] [--include-native-tbr] [--tbr-max-nodes N] [--tbr-max-expansions N]
python -m ssn_hops.experiments train --plan <корень>/plan.json --revision <40 hex>
python -m ssn_hops.experiments execute --plan <корень>/plan.json --revision <40 hex>
python -m ssn_hops.experiments aggregate --plan <корень>/plan.json --out <новый файл.json> [--allow-partial] [--reference <имя политики>]
python -m ssn_hops.experiments plot --summary <файл сводки.json> --out <новый каталог> [--allow-partial]
```

Поставляемый `configs/suite_m1b_cgr.json` содержит ключ `policy_scope`, а `plan` с флагом `--include-native-tbr` отвергает серию с этим ключом (в `experiments.make_plan` написано: «policy_scope is not supported by native plans (native schema is frozen)»), поэтому команда `plan` с `--include-native-tbr` и этим файлом серии по чтению откажет (вывод из чтения, команда не запускалась).

```
# НЕ ЗАПУСКАЛОСЬ. Чтение docstring и argparse драйвера (docs/06, раздел 6); --slices дан явно (см. пункт 2)
python -m driver.run_cell --plan <корень>/plan.json --revision <40 hex> --ledger L.jsonl --slices configs/slices_m1b_cgr.json --slice PILOT
python -m driver.run_cell --plan <корень>/plan.json --revision <40 hex> --ledger L.jsonl --cell <id ячейки> [--counted] [--cap-minutes M]
python -m driver.run_cell --plan <корень>/plan.json --revision <40 hex> --ledger L.jsonl --slices configs/slices_m1b_cgr.json --slice B1B --cells-only --cap-minutes C --wall-minutes W
python -m driver.train_unit --plan <корень>/plan.json --revision <40 hex> --ledger L.jsonl --slices configs/slices_m1b_cgr.json --slice TRAIN-132
python -m driver.train_unit --plan <корень>/plan.json --revision <40 hex> --ledger L.jsonl --n 132 [--counted]
python -m driver.selector --plan <корень>/plan.json --slices configs/slices_m1b_cgr.json [--slice ID]
python -m driver.traces --plan <корень>/plan.json --revision <40 hex> --ledger L.jsonl --slices configs/slices_m1b_cgr.json --slice ID
python -m driver.finish preflight --plan <корень>/plan.json --revision <40 hex>
python -m driver.finish marker    --plan <корень>/plan.json --revision <40 hex>
python -m driver.finish check     --plan <корень>/plan.json [--revision <40 hex>] [--deep]
python -m driver.ledger sum LEDGER.jsonl [LEDGER2.jsonl ...] [--json]
```

Шесть модулей драйвера с охраной точки входа: `run_cell`, `train_unit`, `selector`, `traces`, `finish`, `ledger`; у `plan_io.py` и `__init__.py` её нет. Команды записывают файлы (планы, трассы, журналы, результаты) и запускают тяжёлые вычисления; в корне, где это выполняется, нужны свободное место и время. Порядок срезов по файлу `slices_m1b_cgr.json`: `TRAIN-132`, `TRAIN-REST`, `TRAIN-330`, затем ячейки `PILOT`, `B1B`, `B264`, `B330`, затем ячейки CGR `CGR-PILOT`, `CGR-EXT1`, `CGR-EXT2`, `CGR-EXT3` (подробно — `docs/01_ARCHITECTURE_RU.md` и `docs/06`).

**Бюджета в 700 минут драйвер не обеспечивает.** `ledger.py` ведёт журнал (`Ledger.record` дописывает событие в файл) и суммирует минуты (`ledger sum`), константы-предела и сравнения суммы с пределом в нём нет (файл прочитан целиком); число 700 не встречается ни в одном файле драйвера по чтению (`docs/06`, часть D2). Есть лишь лимиты на отдельную ячейку (`--cap-minutes`), на обучающую единицу (по умолчанию 120 минут, `train_cap_minutes`) и на «стену» запуска (`--wall-minutes`); суммарный бюджет вызывающий должен контролировать сам по выводу `ledger sum`.

## 7. Порядок чтения и состав `docs/`

Рекомендуемый порядок: `docs/01_ARCHITECTURE_RU.md` (вся система целиком), затем группы 02-06 по мере интереса, затем `docs/07_LIMITATIONS_RU.md` и `docs/ERRATA_RU.md`. Каждая группа имеет файл-индекс и файлы-части в той же папке.

| Группа | Модули | Файл-индекс | Файлов-частей |
|---|---|---|---|
| 01 | вся система: слои, зависимости, потоки данных, модель времени | `docs/01_ARCHITECTURE_RU.md` | 3 (`_part1`-`_part3`) |
| 02 | `config`, `sim_config`, `geometry`, `contacts`, `graph`, `traffic` | `docs/02_ENVIRONMENT_RU.md` | 8 |
| 03 | `features`, `data`, `model`, `loss`, `training`, `provenance`, `cli`, `__main__`, `__init__` | `docs/03_LEARNING_RU.md` | 3 |
| 04 | `simulator`, `policies`, `tbr_policy`, `tbr_reference`, `simulate` | `docs/04_SIMULATION_POLICIES_RU.md` | 5 (A1-A3, B1-B2) |
| 05 | `experiments`, `experiment_io`, `experiment_results`, `experiment_plots` | `docs/05_EXPERIMENTS_RU.md` | 15 (A1-A3, B1-B3, C1-C5, D1-D4) |
| 06 | 8 файлов `driver/` и 4 файла `configs/` | `docs/06_DRIVER_CONFIGS_RU.md` | 16 (A1-A5, B1-B4, C1-C4, D1-D3) |
| 07 | ограничения и неустановленное по всей системе | `docs/07_LIMITATIONS_RU.md` | 1 файл, без частей |
| — | оговорки в формулировках и наблюдения при чтении | `docs/ERRATA_RU.md` | 3 файла (`ERRATA_RU.md`, `ERRATA_RU_part2.md`, `ERRATA_RU_part3.md`) |

В группах 02-06 вместе 52 файла (индексы и части; ручной подсчёт по перечню `docs/`: 9 + 4 + 6 + 16 + 17); группа 01 — индекс и три части.

Оговорки в формулировках отдельных частей (там, где часть описания уточнена позже) собраны в `docs/ERRATA_RU.md` (индекс и раздел A: таблица поправок); наблюдения о возможных дефектах кода, найденные чтением (раздел B: нейтральный перечень, не список дефектов), и пункты, которые описание называет проверяемыми, но которые не проверены (раздел C), — в `docs/ERRATA_RU_part2.md`. Ограничения реконструкции и папки, платформенные и поведенческие ограничения, сводный список того, что чтением не установлено, и перечень того, что читателю стоит проверить самому, — в `docs/07_LIMITATIONS_RU.md`. Поправки, сделанные после независимой выборочной проверки описания по коду, собраны в `docs/ERRATA_RU_part3.md`: раздел D (поправки к формулировкам), раздел E (ответы на пункты раздела C, решённые чтением), раздел F (нейтральные заметки). Все четыре файла лежат в `docs/` и названы здесь по точным именам.

## 8. Что можно проверить

Файлы кода (`src/`, `driver/`, `configs/`) заявлены как дословная копия исходных. Тот, кто делал экспорт, может сравнить git blob SHA каждого файла с исходным репозиторием; список таких SHA хранится вне этой папки. Получатель без доступа к исходному репозиторию сделать это не может. Хеш-привязку плана к исходникам (`source_sha256`) код проверяет сам, но только относительно файлов, лежащих рядом с `experiment_io.py`.