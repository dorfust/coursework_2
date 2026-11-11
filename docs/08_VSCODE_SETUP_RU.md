# 08. Установка и запуск в VS Code (как один проект)

> **НЕ ЗАПУСКАЛОСЬ. Каждая команда этого файла — чтение кода и документации, а не результат запуска: ни один агент ничего не выполнял, ни установку, ни импорт, ни одну конфигурацию отладки. Первый запуск у вас — это первая проверка всей инструкции; что делать при сбое и что прислать для разбора — раздел 6.** Метки: «в коде написано» — цитата или пересказ кода и файлов настроек этой папки; «вывод из чтения» — заключение без запуска; «по документации» — сведение из документации сторонних проектов (VS Code, PyTorch, PyG), которой нет в этой папке и которая здесь не проверялась запуском. Ни одна фраза не означает, что код работает, проходит тесты или даёт какие-либо результаты; результатов экспериментов в этой папке нет.

Предположение: под «WS Code» в запросе на эту инструкцию понимается Visual Studio Code (далее VS Code). Если имелось в виду другое, этот файл неприменим.

## 1. Что эта настройка делает и чего не делает

Делает. В корень папки добавлены файлы `pyproject.toml`, `.gitignore`, `.vscode/settings.json`, `.vscode/extensions.json`, `.vscode/launch.json`. Они делают папку одним проектом VS Code: один корень (каталог, где лежит `pyproject.toml`), одно виртуальное окружение `.venv`, пакет `ssn_hops` ставится из `src/` в редактируемом режиме, а девять конфигураций отладки (раздел 5) запускают команды, которые описывают `README.md` (раздел 6) и `docs/05`, `docs/06`.

Не делает.
- Тестов нет: каталога `tests/` в папке нет, раздела `pytest` и дополнения `test` в `pyproject.toml` тоже нет (раздел 3.1).
- Одной кнопки «запустить всё» нет. Конвейер (план, обучение, выполнение ячеек, агрегирование, рисунки) — последовательность отдельных команд; ревизию, каталоги и журнал вы выбираете сами.
- Вычисления тяжёлые. В коде написано: лимит обучающей единицы по умолчанию — 120 минут (`DEFAULT_TRAIN_CAP_MINUTES = 120.0` в `driver/train_unit.py` и `driver/run_cell.py`), лимит ячейки задаётся `--cap-minutes`, «стена» запуска — `--wall-minutes`; суммарного бюджета времени драйвер не обеспечивает (`README.md`, раздел 6). Сколько займёт полный прогон на вашей машине, не установлено; обещаний о длительности и объёме диска нет.
- Драйвер (`driver/run_cell.py`, `driver/train_unit.py`) рассчитан на POSIX. В коде написано: «capped runs need POSIX process groups (Linux/WSL2); Windows-native is out of scope». Поэтому на Windows папку нужно открывать в WSL2 через расширение VS Code «WSL» (идентификатор `ms-vscode-remote.remote-wsl`, в VS Code оно может называться Remote - WSL). Нативный Windows драйвером не поддерживается (в коде написано); для остальных модулей он не проверялся.
- Совместимость конкретных версий пакетов и воспроизводимость окружения не установлены; файла фиксации версий нет и не создавался.

## 2. Что нужно заранее

- VS Code и расширение Python (`ms-python.python`). Вывод из документации VS Code: отладка Python идёт через расширение Python Debugger (`debugpy`), тип конфигурации в `launch.json` — `"debugpy"`; Pylance (`ms-python.vscode-pylance`) нужен для подсказок в редакторе, не для запуска.
- Windows: WSL2 с дистрибутивом Linux и расширение «WSL» в VS Code (по документации Microsoft, установка WSL — команда `wsl --install` в PowerShell; здесь не проверялось). Linux и macOS: расширение «WSL» не нужно.
- Python 3.10, 3.11, 3.12, 3.13 или 3.14 внутри Linux / WSL / macOS: в `pyproject.toml` написано `requires-python = ">=3.10,<3.15"`. Для `python3 -m venv` в некоторых дистрибутивах Linux нужен отдельный пакет (например, `python3-venv` в Debian/Ubuntu; вывод из общего опыта, не проверялось).
- `git`, если папку проекта вы получаете клонированием. Код git не читает: ревизию вы задаёте сами (раздел 5).
- Доступ в сеть для `pip`: пакеты скачиваются; для `pip install -e .` по умолчанию собирается изолированное окружение, которому нужен `setuptools>=68` (вывод из чтения `pyproject.toml`).
- Место на диске и время: не оценивались. Пакет `torch` велик, а выходные каталоги планов и прогонов растут с числом ячеек.
- GPU не нужен. В коде написано: `TrainConfig.device` по умолчанию `"cpu"`, в `configs/n132.json` — `"device": "cpu"`; шаг `evaluate` плана получает `--device cpu` (`experiments.plan_commands`); `training.resolve_device` принимает только `cpu` и `cuda[:индекс]`. Достаточно сборки `torch` для CPU.
- Если проект на Windows: держите папку проекта и каталоги вывода в файловой системе Linux внутри WSL (например, в домашнем каталоге), а не в `/mnt/c/...`. Причина (вывод из чтения): `driver/finish.py` и `driver/traces.py` создают файлы жёсткой ссылкой `os.link` и отказывают, если файловая система её не поддерживает (`docs/07_LIMITATIONS_RU.md`, раздел 3); поддержку жёстких ссылок на `/mnt/c` чтением установить нельзя.

## 3. Установка по шагам (интегрированный терминал VS Code)

Все команды — для bash в Linux / WSL / macOS (НЕ ЗАПУСКАЛОСЬ).

1. Откройте папку: File → Open Folder → корень проекта (каталог, где лежат `pyproject.toml`, `src/`, `driver/`, `configs/`, `docs/`). В WSL: Command Palette (Ctrl+Shift+P) → «WSL: Open Folder in WSL...» либо `code .` в терминале WSL. Согласитесь на установку рекомендованных расширений (`.vscode/extensions.json`).
2. Откройте терминал (меню Terminal → New Terminal). Он стартует в корне проекта. Создайте и включите окружение:

```
# НЕ ЗАПУСКАЛОСЬ
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

3. Поставьте `torch` для вашей платформы по официальному селектору PyTorch (https://pytorch.org/get-started/locally/; выберите Pip и CPU, скопируйте предложенную команду). Для CPU на Linux такая команда обычно выглядит так (по документации PyTorch; проверьте актуальный вид на сайте, здесь не проверялось):

```
# НЕ ЗАПУСКАЛОСЬ
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

   Версия должна подходить под `torch>=2.6,<3`. Если пропустить этот шаг, `pip install -e .` (шаг 5) сам потянет `torch` из PyPI; какая это будет сборка и сколько она займёт места, чтением не установлено.
4. `torch-geometric`. В коде написано: из PyG импортируется только `from torch_geometric.nn import GCNConv` (`src/ssn_hops/model.py`); по `README.md`, раздел 5, и по строкам `import` других модулей `torch_geometric` импортирует только `model.py` (программный поиск по файлам не выполнялся). Опциональные расширения PyG (`pyg_lib`, `torch_scatter`, `torch_sparse` и подобные) в прочитанном коде не импортируются. По документации PyG, начиная с версии 2.3 библиотеку можно поставить и использовать без внешних библиотек, кроме PyTorch (`pip install torch_geometric`). Отдельная команда не обязательна: `torch-geometric>=2.6.1,<3` входит в зависимости проекта и ставится на шаге 5. Если нужна установка строго по инструкции PyG для вашей версии `torch`, выполните её до шага 5.
5. Установите проект в редактируемом режиме из корня:

```
# НЕ ЗАПУСКАЛОСЬ (нужна сеть)
pip install -e .
# дополнительно, только для команды plot (рисунки):
pip install -e '.[plot]'
```

   `pip install -e .` ставит только пакет `ssn_hops` (`packages.find`, `where = ["src"]`); `driver/` и `configs/` не устанавливаются, их находят по рабочему каталогу.
   Почему редактируемый режим важен (вывод из чтения кода). `provenance.source_hashes()` и `experiment_io.source_hashes()` хешируют файлы `*.py`, лежащие рядом с собственным модулем; план хранит эти хеши (`body["source_sha256"]`), и `driver/plan_io.check_binding` отказывает при расхождении («source hash mismatch»). При обычной (не редактируемой) установке модули копируются в `site-packages`, и хеши относились бы к копии, а не к `src/ssn_hops`. В редактируемом режиме модули остаются в `src/ssn_hops`. Следствие: любая правка файла в `src/ssn_hops` и любой лишний `*.py` рядом с ними меняют хеши, и существующие планы отвергаются (создайте новый план).
   Дополнение `plot = ["matplotlib"]` добавлено для этой настройки: `matplotlib` подключается лениво командой `plot` (`experiment_plots.py`) и в исходных метаданных не был объявлен; версия не закреплена.
6. Выберите интерпретатор: Ctrl+Shift+P → «Python: Select Interpreter» → `.venv/bin/python` внутри проекта. Параметр `python.defaultInterpreterPath` в `.vscode/settings.json` указывает на него же, но это лишь значение по умолчанию (по документации VS Code), поэтому проверьте выбор в строке состояния.

Что ещё содержит `.vscode/settings.json` (в файле написано): `python.analysis.extraPaths = ["${workspaceFolder}/src"]` (подсказки редактора), переменная терминала `PYTHONPATH=${workspaceFolder}/src` для Linux как запасной путь, если редактируемая установка не сделана, и исключения `__pycache__` и `*.egg-info` из проводника и наблюдателя файлов. Файлы `settings.json`, `launch.json`, `extensions.json` — обычный JSON без комментариев (допустим и как JSONC, которым VS Code читает такие файлы).

### 3.1. Что изменено по сравнению с исходными метаданными проекта

Исходный файл метаданных в эту папку не входил; его git blob SHA для сверки: `c6164fef99f495c43d57b61589ca3786aa30b3f1` (исходный `.gitignore`: `1eb823909299ee28cf5e8247573a3f9b25a316ea`). Новый `pyproject.toml` — в корне папки; в его первой строке стоит комментарий, что он выведен из исходных метаданных.

| Элемент | В исходном файле | В этом `pyproject.toml` |
|---|---|---|
| имя проекта | `name = "ssn-hop-reconstruction"` | без изменений |
| версия | `version = "0.1.0"` | без изменений |
| `requires-python` | `">=3.10,<3.15"` | без изменений |
| зависимости | `["numpy>=1.26,<3", "torch>=2.6,<3", "torch-geometric>=2.6.1,<3"]` | без изменений |
| команда-скрипт | `ssn-hop = "ssn_hops.cli:main"` | без изменений |
| сборка и раскладка | `setuptools>=68`, `setuptools.build_meta`; `packages.find` с `where = ["src"]` | без изменений |
| дополнение `test` | `test = ["pytest>=8,<10"]` | удалено (тестов в папке нет) |
| раздел `[tool.pytest.ini_options]` | `testpaths = ["tests"]` | удалён |
| дополнение `plot` | нет | добавлено: `plot = ["matplotlib"]`, версия не закреплена (добавление для этой настройки) |

Описание проекта (`description`) тоже без изменений. Следствие для вывода команды `environment`: запись `pytest` в `packages` будет `"not-installed"`, потому что дополнение `test` убрано (в коде написано: `provenance.environment()` ищет дистрибутивы `numpy`, `torch`, `torch-geometric`, `ssn-hop-reconstruction`, `pytest` и пишет `"not-installed"`, если дистрибутива нет).

## 4. Первая проверка по порядку

Каждый шаг — после предыдущего; при сбое остановитесь и перейдите к разделу 6. Команды выполняются в терминале с включённым `.venv`, из корня проекта (НЕ ЗАПУСКАЛОСЬ).

1. Импорт пакета (вывод из чтения: `src/ssn_hops/__init__.py` содержит docstring и `__version__`; `torch` для него не нужен):

```
python -c "import ssn_hops"
```

   Ожидается отсутствие вывода и код возврата 0. `ModuleNotFoundError: No module named 'ssn_hops'` значит, что установка не сделана или выбран другой интерпретатор.
2. Описание среды:

```
python -m ssn_hops environment
```

   В коде написано (`cli.py`, `provenance.environment`): печатается JSON с отступами с ключами `python`, `platform`, `packages` (`numpy`, `torch`, `torch-geometric`, `ssn-hop-reconstruction`, `pytest`), `torch_cuda_build`, `cuda_available`, `device_count`, `torch_threads`. Команде нужны `torch` и `torch_geometric` (цепочка `cli` → `training` → `model`). После редактируемой установки у `ssn-hop-reconstruction` ожидается строка версии (`0.1.0` по метаданным; вывод из чтения), у `pytest` — `"not-installed"` (раздел 3.1). Если у `ssn-hop-reconstruction` стоит `"not-installed"`, пакет не установлен в этот интерпретатор.
3. Та же проверка из VS Code: Run and Debug (Ctrl+Shift+D) → конфигурация «a) ssn_hops environment» → F5. Вывод должен совпасть с пунктом 2 (вывод из чтения; не проверялось).

Эквивалент пункта 2 — команда-скрипт `ssn-hop environment` (в `pyproject.toml` написано `ssn-hop = "ssn_hops.cli:main"`; `cli.main` возвращает `None`, вывод из чтения).

## 5. Конфигурации запуска и порядок команд

Как пользоваться: Ctrl+Shift+D → список конфигураций → выбрать → F5. Значения, которые выбираете вы (каталог, ревизия, путь плана, журнал, срез), VS Code запрашивает окнами ввода (`inputs`). Каждая конфигурация задаёт: `cwd = ${workspaceFolder}` (корень проекта: `python -m driver.<модуль>` ищет `driver/` в текущем каталоге, а пути `configs/...` относительны к нему), `env` с `PYTHONPATH=${workspaceFolder}/src` (запасной путь на случай, если редактируемая установка не сделана; при сделанной установке тот же каталог, вывод из чтения: вреда нет), `justMyCode = false` и `subProcess = false`. Последнее — чтобы отладчик не подключался к дочерним процессам: `experiments` и драйвер порождают их через `sys.executable` (`experiment_io.job`, `run_cell._spawn_and_wait`; по документации VS Code, `subProcess` включает отладку подпроцессов). Вывод из чтения; не проверялось.

Аргументы каждой конфигурации сверены чтением с кодом `argparse` в `cli.py`, `experiments.py`, `driver/run_cell.py`, `driver/train_unit.py`, `driver/selector.py`, `driver/finish.py`, `driver/ledger.py`; запускать их не пробовали.

| Конфигурация | Эквивалент в терминале | Запрашивается | Что делает |
|---|---|---|---|
| a) ssn_hops environment | `python -m ssn_hops environment` | ничего | печатает JSON о среде, ничего не пишет |
| b) experiments plan | `python -m ssn_hops.experiments plan --suite configs/suite_m1b_cgr.json --out <каталог> --revision <40 hex>` | `planOut`, `revision` | создаёт НОВЫЙ каталог с `plan.json` и конфигурациями |
| c) driver.selector | `python -m driver.selector --plan <plan.json> --slices configs/slices_m1b_cgr.json` | `planPath` | только читает; печатает срезы и проверку разбиения |
| d) driver.finish check | `python -m driver.finish check --plan <plan.json>` | `planPath` | только читает; печатает отчёт (`--revision`, `--deep` не заданы) |
| e) driver.run_cell --slice | `python -m driver.run_cell --plan <plan.json> --revision <40 hex> --ledger <L.jsonl> --slices configs/slices_m1b_cgr.json --slice <ID>` | `planPath`, `revision`, `ledgerPath`, `sliceId` | ВЫПОЛНЯЕТ срез (тяжело); пишет в каталог плана и дописывает журнал |
| f) driver.train_unit --slice | `python -m driver.train_unit --plan ... --revision ... --ledger ... --slices configs/slices_m1b_cgr.json --slice <ID>` | `planPath`, `revision`, `ledgerPath`, `trainSliceId` | ВЫПОЛНЯЕТ обучение (тяжело); лимит единицы 120 минут по умолчанию |
| g) driver.ledger sum | `python -m driver.ledger sum <L.jsonl>` | `ledgerPath` | читает журнал, печатает суммы минут |
| h) experiments aggregate | `python -m ssn_hops.experiments aggregate --plan <plan.json> --out <новый файл.json> --allow-partial` | `planPath`, `summaryOut` | читает прогоны, пишет НОВЫЙ файл сводки |
| i) experiments plot | `python -m ssn_hops.experiments plot --summary <сводка.json> --out <новый каталог> --allow-partial` | `summaryPath`, `plotOut` | читает сводку, пишет НОВЫЙ каталог с рисунками; нужен `matplotlib` |

Что запрашивается. `planOut` — абсолютный путь к каталогу, которого ещё нет (в коде написано: `make_plan` берёт `Path(output).resolve()` и бросает `FileExistsError("plan output must be a new directory")`, если каталог есть; относительный путь код принимает, но план привязан к абсолютному корню, поэтому вводите абсолютный). `revision` — ровно 40 строчных шестнадцатеричных знаков (`experiment_io.revision`: `[0-9a-f]{40}`); код git не читает, значение выбираете вы (например, `git rev-parse HEAD`, если папка проекта — клон git; это лишь способ получить подходящую строку), и оно должно быть одним и тем же во всех командах одного плана. `planPath` — `<каталог плана>/plan.json` по тому же абсолютному пути, что при планировании. `ledgerPath` — файл `.jsonl`: журнал дописывается; создаётся при первой записи (`Ledger.record` делает `mkdir(parents=True)`). `sliceId` — список из 11 идентификаторов `configs/slices_m1b_cgr.json`: `TRAIN-132`, `TRAIN-REST`, `TRAIN-330`, `PILOT`, `B1B`, `B264`, `B330`, `CGR-PILOT`, `CGR-EXT1`, `CGR-EXT2`, `CGR-EXT3` (прочитаны в файле); `trainSliceId` — первые три (срез без шага обучения `train_unit` отвергает: «slice ... has no train step»).

Порядок команд (вывод из чтения `README.md`, раздела 6, `docs/01`, части 2, и `docs/06`; подробности там, здесь не повторяются):
1. Выберите ревизию и абсолютный каталог для плана. Рекомендуется каталог вне папки проекта (например, `~/ssn_runs/plan1`): выходные файлы многочисленны. Если нужен каталог внутри проекта, `outputs/` занесён в `.gitignore`.
2. Конфигурация b) создаёт план: `plan.json` привязан к абсолютному корню, ревизии и хешам `*.py` пакета `ssn_hops`. Серия `configs/suite_m1b_cgr.json` содержит ключ `policy_scope`, поэтому флаг `--include-native-tbr` с ней отказывает (`README.md`, раздел 6); в конфигурациях его нет.
3. Конфигурации c) и d) — безопасные проверки: файл срезов подходит к плану (в обоих файлах имя серии `m1b_first_run_cgr`), `finish check` показывает, что уже есть.
4. Обучение: срезы `TRAIN-132`, `TRAIN-REST` (N = 198 и 264 одним запуском), `TRAIN-330` — конфигурацией f) (или e): срез с шагом обучения в `run_cell` передаётся в `train_unit`). На каждую единицу действует лимит 120 минут.
5. Перед агрегированием: `python -m driver.finish preflight --plan <plan.json> --revision <40 hex>` (в терминале; в девяти конфигурациях его нет). В коде написано: `verify_models` требует `model_preflight.json`, если в плане есть GLR, и при `--allow-partial` (`docs/ERRATA_RU_part2.md`, B48); `preflight` требует, чтобы были обучены ВСЕ модели плана.
6. Ячейки: срезы `PILOT`, `B1B`, `B264`, `B330`, затем `CGR-PILOT`, `CGR-EXT1`, `CGR-EXT2`, `CGR-EXT3` — конфигурацией e). Дополнительные параметры (`--cells-only`, `--cap-minutes M`, `--wall-minutes W`, `--discard`, `--keep-going`) допишите в `args` вручную; в коде написано: `--wall-minutes` требует одновременно `--cap-minutes` и `--cells-only` и отвергается вместе с `--cell`. Без `--cap-minutes` ячейка по времени не ограничена (в `configs/slices_m1b_cgr.json` лимитов ячеек нет); конфигурация e) лимита не задаёт.
7. Конфигурация g) суммирует минуты журнала. Бюджета в 700 минут драйвер не обеспечивает: следить за суммой должны вы.
8. Конфигурация h) собирает сводку, i) строит рисунки. Для полной сводки (`complete = true`) флаг `--allow-partial` у `plot` не нужен (`experiment_plots.prepare_plots`; `docs/ERRATA_RU.md`, A2); для неполной нужен.

Условия, которые нужно помнить (в коде написано): план нельзя переносить или копировать — отказ «root mismatch»; `--slices` у `run_cell` и `train_unit` по умолчанию указывает на несуществующий `slices.json`, поэтому конфигурации e) и f) задают `--slices configs/slices_m1b_cgr.json`; два драйвера одновременно на один план и один журнал не запускайте (блокировок в коде нет, `docs/07_LIMITATIONS_RU.md`, раздел 4).

Долгие запуски (e, f) надёжнее запускать в терминале (`README.md`, раздел 6): `run_cell` обрабатывает SIGINT, SIGTERM и SIGHUP и чистит за собой, но SIGKILL драйвера оставляет дочерний процесс-«сироту» в отдельном сеансе, а как именно VS Code останавливает отлаживаемый процесс, чтением не установлено. Перед `--discard` после обрыва проверьте процессы (`ps -eo pid,pgid,etime,args | grep ssn_hops`, как советует docstring `run_cell.py`). Отладчик замедляет выполнение; сколько именно, не установлено.

## 6. Если что-то не работает

Таблица тех текстов, которые названы в коде или документах этой папки. Текст — «в коде написано»; причина — по указанному месту, вывод из чтения; запуском не проверялось.

Строки `refused: ...` печатают `run_cell`, `train_unit` и `finish`; `selector` и `ledger` завершаются трассировкой Python; префикс с именем класса исключения печатает только `finish`.

| Текст сбоя | Вероятная причина | Что сделать |
|---|---|---|
| `ModuleNotFoundError: No module named 'ssn_hops'` | не выполнен `pip install -e .`, выбран другой интерпретатор или другой терминал | включить `.venv`, повторить шаг 5 раздела 3; конфигурации VS Code имеют запасной `PYTHONPATH` |
| `ModuleNotFoundError: No module named 'torch'` / `'torch_geometric'` | пакет не поставлен в этот интерпретатор (`README.md`, раздел 5: нужны даже `environment` и `simulate trace`) | шаги 3-5 раздела 3 |
| `ModuleNotFoundError: No module named 'driver'` | текущий каталог — не корень проекта | запускать из корня (`cwd = ${workspaceFolder}`) |
| `ModuleNotFoundError: No module named 'matplotlib'` при `plot` | дополнение `plot` не поставлено (`experiment_plots.py` подключает его лениво) | `pip install -e '.[plot]'` |
| `FileExistsError: plan output must be a new directory` | каталог плана уже существует (`experiments.make_plan`) | указать новый путь |
| `refused: root mismatch: the plan was created for root ... but plan.json is at ...` | план перенесён или скопирован (`plan_io.check_binding`) | создать новый план на окончательном месте |
| `ValueError: plan moved: absolute commands require a fresh plan` | план читается только для чтения по пути, не совпадающему с корнем плана (`experiment_io.validate_plan`) | создать новый план на окончательном месте |
| `refused: revision mismatch: supplied ..., planned ...` | другая ревизия, чем при планировании | использовать то же значение |
| `ValueError: revision must be the actual lowercase 40-character checkout SHA` или `record a complete 40-character git checkout SHA` | ревизия не из 40 строчных hex (у `cli.py` верхний регистр допустим) | исправить значение |
| `refused: source hash mismatch: the installed ssn_hops bytes differ from the planned bytes in ...` | изменён файл `src/ssn_hops`, добавлен лишний `*.py` или пакет установлен не редактируемо | вернуть файлы, сделать `pip install -e .`, иначе создать новый план |
| `refused: unknown slice '...' ... (known: [...])` | опечатка в идентификаторе среза | выбрать из списка |
| `refused: the slice file is for suite ... but the plan was made from suite ...` | файл срезов от другой серии | использовать `configs/slices_m1b_cgr.json` с планом серии `m1b_first_run_cgr` |
| `OSError: capped runs need POSIX process groups (Linux/WSL2); Windows-native is out of scope` | запуск в нативном Windows | открыть проект в WSL2 |
| `FileNotFoundError` на `model_preflight.json` при `aggregate` | не выполнен `finish preflight` (B48 в `docs/ERRATA_RU_part2.md`) | выполнить `preflight` (раздел 5, п. 5) |
| `not ready: preflight needs ALL trained models of the plan; not complete: ...` | обучены не все модели | завершить срезы `TRAIN-*` |
| `refused: ... incomplete cell artifacts exist ...` или `... incomplete training artifacts exist ...` | прежний запуск оборван; повторный запуск отказывает, пока нет `--discard` | проверить процессы (`ps`), затем повторить с `--discard` |
| `refused: ... the project's completeness check could not run (ImportError ...)` | в этом интерпретаторе нет `torch` (`train_unit` не удаляет данные даже с `--discard`) | поставить `torch`, повторить |
| `refused: FileNotFoundError ...` или `JSONDecodeError` | неверный путь или повреждённый JSON | проверить пути |
| `refused: cannot create ... by hard link ...` | файловая система без жёстких ссылок (`finish.py`) | перенести каталог плана в файловую систему Linux |
| `error: the following arguments are required: ...` / `unrecognized arguments` | правка `args` в `launch.json` (выход `argparse` — код 2) | сверить с таблицей раздела 5 |

Что прислать для разбора (первый запуск — первая проверка; уберите секреты и личные данные: токены, пароли, адреса):
1. Точную команду (или имя конфигурации VS Code и введённые значения) и текущий каталог.
2. Весь вывод терминала целиком, с первой строки (stdout и stderr) и код возврата (`echo $?` сразу после команды в терминале).
3. Вывод `python -m ssn_hops environment`, если он запускается; иначе `python --version` и `pip list`.
4. Версии ОС: `cat /etc/os-release`, `uname -a`; для Windows — версию WSL (`wsl --version` в PowerShell) и дистрибутив.
5. Листинг каталога вывода: `ls -la <каталог плана>` и, для сбоя ячейки, содержимое `logs/<id>.stderr.txt` и `logs/<id>.status.json`; для драйвера — файл журнала `.jsonl`.
6. Если сбой при установке: полный вывод `pip install -e .` (и `pip install torch ...`).

## 7. Что здесь чтение, а что вывод; что не установлено

- Ничего из этого файла не запускалось: ни установка, ни команды, ни конфигурации отладки, ни сборка редактируемого пакета.
- В коде или в файлах настроек написано (прочитано): аргументы `argparse` всех девяти команд; значения по умолчанию (`--slices`, 120 минут, `--reference`); тексты отказов из раздела 6; метаданные `pyproject.toml`; идентификаторы срезов и имя серии; предложение `POSIX only`.
- Вывод из чтения: поведение редактируемой установки с точки зрения хешей; безвредность запасного `PYTHONPATH`; необходимость `subProcess = false`; причины сбоев в таблице раздела 6; порядок команд.
- По документации сторонних проектов (не проверялось запуском): форма команды для `torch` на CPU; установка PyG без внешних библиотек; тип конфигурации `debugpy`; параметр `subProcess`; установка и работа расширения «WSL».
- Не установлено: удастся ли `pip install -e .` на вашей платформе; совместимость конкретных версий `torch`, `torch-geometric`, `numpy`; время и объём диска; поведение VS Code при остановке сеанса отладки; поддержка жёстких ссылок на `/mnt/c`.
- Другие файлы `docs/` и `README.md` писались для папки без метаданных проекта и местами говорят «нет `pyproject.toml`» и «только через `PYTHONPATH`»; актуальные формулировки — в `docs/ERRATA_RU_part4.md`, раздел G.
