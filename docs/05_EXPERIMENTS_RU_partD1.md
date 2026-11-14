# 05. Эксперименты: `experiment_plots.py` (часть D1: назначение, входы и выходы, константы, вспомогательные функции)

Описан один модуль: `src/ssn_hops/experiment_plots.py` (26879 байт). Описание разбито на четыре файла:

- `05_EXPERIMENTS_RU_partD1.md` (этот файл): разделы 1-4: назначение, входы и выходы, константы, вспомогательные функции `_same`, `_hash`, `_number`, `_stats`, `_seed_list`.
- `05_EXPERIMENTS_RU_partD2.md`: раздел 5: `_validate_native` (проверка нативной сводки).
- `05_EXPERIMENTS_RU_partD3.md`: разделы 6-8: `_policy_label`, `prepare_plots`, `prepare_plot_data`, состав спецификаций графиков.
- `05_EXPERIMENTS_RU_partD4.md`: разделы 9-15: `plot_summary`, рисунки, значения по умолчанию, связи, побочные эффекты, допущения, не установленное, наблюдения о коде.

Метки: «в коде написано» — прямая цитата или пересказ строки кода; «вывод из чтения» — следствие, которое код явно не заявляет; «ручной расчёт» — арифметика с показом. Ничего не запускалось: в документе нет утверждений о работоспособности и нет результатов экспериментов.

## 1. Назначение

В коде написано (docstring модуля): «Lazy reconstruction plots. Native support is a new, attributed consumer layer.»; «Summary consistency is checked here; saved science is NOT rerun or authenticated.»; «No matplotlib, simulator or search is imported by pure-data preparation.»

Вывод из чтения: модуль реализует последний этап конвейера экспериментов, команду `plot` из `experiments.py` (`parser`, `main`). Он читает один JSON-файл сводки, который записывает `aggregate_plan` из `experiment_results.py` (`05_EXPERIMENTS_RU_partC5.md`), и:

1. проверяет схему и метку сводки (для нативной сводки ещё и согласованность полей, `_validate_native`);
2. строит чисто данные спецификаций графиков (`prepare_plots`, `prepare_plot_data`);
3. только после этого лениво подключает `matplotlib` и рисует PNG-файлы (`plot_summary`), рядом пишет `plot_data.json` и `complete.json`.

Модуль не читает план и артефакты ячеек, не запускает симулятор, не пересчитывает показатели и не рисует парные разности и объединённые (pooled) суммы: рисуются только оценки «равный вес повторений» (`equal_replicate`), стандартная ошибка и счётчики.

Классов в модуле нет. Функций 10 (ручной расчёт: 7 с префиксом `_` — `_same`, `_hash`, `_number`, `_stats`, `_seed_list`, `_validate_native`, `_policy_label` — и 3 без префикса: `prepare_plots`, `prepare_plot_data`, `plot_summary`). `__all__` в модуле не определён. Вне модуля в экспорте вызывается только `plot_summary` (`experiments.py`, `main`).

Два вида сводок (схемы заданы в `experiment_results.py`, `05_EXPERIMENTS_RU_partC1.md`):

- обычная: `SUMMARY_SCHEMA = "ssn-experiment-summary-v2"`; в модуле для неё проверяются только схема, метка и признак `complete` (вывод: структура групп не проверяется, раздел 6);
- нативная: `NATIVE_SUMMARY_SCHEMA = "ssn-native-exhaustive-experiment-summary-v1"`; для неё выполняется `_validate_native`, добавляются дополнительные поля спецификаций.

## 2. Входы и выходы

### 2.1. Вход

Путь `summary_path` к JSON-файлу сводки (читается `read` из `experiment_io.py`, `05_EXPERIMENTS_RU_partB1.md`, 3.5). Сводка должна быть словарём с `schema` из двух схем выше и `label == LABEL` (`"RECONSTRUCTION / NOT AUTHORS' RESULTS"`). Плана, файлов запусков и логов функции модуля не открывают. Хеши внутри сводки (`plan_sha256`, `source_sha256`, `artifact_evidence` и др.) проверяются только по формату (64 или 40 строчных hex-символов) и по взаимной согласованности; сверки с файлом плана нет (вывод: плану модуль не доступен). Модуль считает хеш самого файла сводки (`digest`) до и после чтения и после рисования.

Читаемые ключи обычной сводки (в коде написано; все — из `prepare_plots`): верхний уровень `schema`, `label`, `complete`, `groups`, `policy_names`, `mode` (последний — в `plot_summary`); у группы `grid`, `variant`, `axis`, `x`, `controls`, `matched_repetitions`, `policies[<политика>].equal_replicate[<показатель>]` с полями `mean`, `se_of_mean`, `n_nonnull`; у `controls` — `tick_s`, `rate_bytes_s`, `arrival_rate_packets_s`, `traffic_end_s`, `observation_end_s`. Для нативной сводки читается больше полей (разделы 5, 6).

### 2.2. Выход

Каталог `output` (создаётся новым): `plot_data.json`, по одному файлу `<grid>--<variant>--<metric>.png` на спецификацию, `complete.json`. Возвращаемое значение `plot_summary`: `{"plots": число спецификаций, "out": str(output), "partial": summary["complete"] is not True}`; `experiments.main` печатает его как JSON. Форматы: JSON пишет `write` (отступ 2, сортировка ключей, `allow_nan=False`, режим `"x"`, часть B1, 2.2); PNG — `figure.savefig(..., dpi=150)`.

## 3. Константы модуля (experiment_plots.py)

- `LABEL = "RECONSTRUCTION / NOT AUTHORS' RESULTS"`; тот же текст проверяется в `label` сводки и стоит в заголовке каждого рисунка.
- `PLOT_CONTRACT`: словарь `path`, `commit`, `blob`, `step`. В коде `path` равен имени внутреннего документа проекта (документ не входит в экспорт); `commit` и `blob` — 40-символьные hex-строки, `step` — внутренняя метка. Используется только как справочное поле в `PLOT_CONSUMER` (вывод: на логику не влияет).
- `PLOT_CONSUMER`: словарь с `schema = "ssn-native-exhaustive-plot-consumer-v1"`, `contract = PLOT_CONTRACT`, `plots_supported = True` и тремя текстами `scope` («new native-summary plot consumer; original producer/transport/science declarations unchanged»), `validation_limit` («summary consistency only; no rereading cell artifacts or rerunning science; hashes/counters are not anti-forgery or algorithm-execution proof»), `timing_limit` («implementation CPU wall seconds only; author Fig.5 cost-axis unit and traversal unknown; no conversion or author equality»). Копируется в спецификации и в выходные документы нативных графиков.
- `METRICS`: ось -> показатели рисунков. `"failure_probability"`: `("delivered_mean_delay_s", "failure_fraction", "pending_fraction")`; `"n"`: `("delivered_mean_delay_s", "route_seconds_per_call", "simulation_seconds")`. Ключи — единственные допустимые оси (`ValueError("unsupported plot axis")`).
- `LABELS`: подписи оси Y для пяти показателей: `delivered_mean_delay_s` — "Delivered-only delay (seconds)"; `failure_fraction` — "Terminal failure fraction (failed/generated)"; `pending_fraction` — "Pending fraction (right-censored/generated)"; `route_seconds_per_call` — "CPU wall seconds per route call (including inference)"; `simulation_seconds` — "Whole simulator CPU wall seconds (NOT per-call)".
- `NATIVE_LABELS = {**LABELS, ...}`: то же, но `route_seconds_per_call` — "Whole choose-call CPU wall seconds (NOT pure-core / author Fig.5)".
- `ERROR_BARS = "one SE of the equal-replicate mean, NOT confidence intervals"`.
- `POLICIES = ("GLR", "TBR_style_hop_oracle", "TSR_source_dijkstra", "CGR_contact_plan")`; повторяет `experiments.POLICIES` (вывод: в `experiment_plots.py` эта константа определена заново, а не импортируется).
- `COST_METRICS = ("route_seconds_per_call", "simulation_seconds")`.
- `FIG5_POLICIES = ("GLR", "TBR_style_hop_oracle", "CGR_contact_plan", NATIVE_POLICY_NAME)`; значение `NATIVE_POLICY_NAME` — `"TBR_bounded_exhaustive_reference"` (`experiment_io.py`, часть B1, 2.3).
- `FIG5_EXCLUSION_REASON = "paper Fig.5 legend: GLR, TBR, CGR only"`.

Комментарий над `COST_METRICS` (в коде написано): рисунки стоимости по оси `n` не содержат `TSR_source_dijkstra`; ячейки TSR остаются в сводках, а TSR остаётся на рисунке задержки по оси `n` и на всех рисунках оси `failure_probability`. В комментарии стоит внутренняя метка правки; расшифровка не входит в экспорт.

Ручной расчёт: показатели рисунков — объединение значений `METRICS`: `delivered_mean_delay_s` (общий), `failure_fraction`, `pending_fraction`, `route_seconds_per_call`, `simulation_seconds` = 5 имён, столько же ключей в `LABELS`. В `FIELDS` (`experiment_results.py`, 7 имён) остаются неотрисованными `nondelivery_fraction` и `goodput_bits_s` (7 − 5 = 2).

## 4. Основные функции: вспомогательные проверки

### 4.1. `_same(actual, expected, label)`

Сравнивает `content_hash(actual)` и `content_hash(expected)` (`config.py`: SHA-256 канонического JSON). Различие даёт `ValueError("native summary " + label + " mismatch")`. Возврата нет. Вывод: сравнение по каноническому тексту отличает `1`, `1.0` и `true` (часть B1, 2.2); `NaN` в любой стороне даёт `ValueError` самой `content_hash` (`allow_nan=False`), не сообщение с `label`.

### 4.2. `_hash(value, length=64)`

`ValueError("native summary invalid hash/revision")`, если значение не `str` или не соответствует `[0-9a-f]{length}` целиком. Длина 64 — SHA-256, 40 — ревизия. Заглавные буквы отвергаются.

### 4.3. `_number(value, label, positive=False)`

Возвращает значение, если оно не `bool`, типа `int` или `float`, конечное, не меньше 0 и (при `positive=True`) не равно 0. Иначе `ValueError("native summary invalid " + label)`. Вывод: отрицательные числа отвергаются; `numpy`-скаляры и `Decimal` отвергаются (проверка типа точная).

### 4.4. `_stats(stats, matched)`

Проверяет блок статистики из `describe` (`experiment_results.py`, часть C1: шесть ключей). Аргументы: словарь и число сопоставленных повторений группы. По порядку:

1. Ключи ровно `{"n_total", "n_nonnull", "n_null", "mean", "sample_sd", "se_of_mean"}`, иначе `"native summary statistics fields mismatch"`.
2. `n_total`, `n_nonnull`, `n_null` — через `count` (неотрицательные `int`, `experiment_results.py`); должны выполняться `n_total == matched` и `n_nonnull + n_null == n_total`, иначе `"inconsistent matched/statistic counts"`.
3. `n_nonnull == 0`: `mean`, `sample_sd`, `se_of_mean` обязаны быть `None` (`"null estimates must stay null"`); возврат.
4. `mean` — не `bool`, `int` или `float`, конечное (`"invalid mean"`); знак не проверяется (комментарий кода: парные разности могут быть отрицательными).
5. `n_nonnull == 1`: SD и SE обязаны быть `None` (`"one observation has null SD/SE"`).
6. `n_nonnull >= 2`: `sample_sd` и `se_of_mean` проходят `_number` (неотрицательные конечные), затем `close(se_of_mean, sd / math.sqrt(n_nonnull), "native summary SE")` с допусками `rel_tol = abs_tol = 1e-10` (`close`, часть C1).

Ручной расчёт: `n_total = 3`, `n_nonnull = 2`, `n_null = 1`, `mean = 2.0`, `sample_sd = sqrt(2)`, `se_of_mean = 1.0`, `matched = 3` проходят проверку (`sqrt(2) / sqrt(2) = 1`). Вывод: значение `mean` для показателей с `None` в `n_null` разрешено только при `n_nonnull > 0`.

### 4.5. `_seed_list(values)`

Проверяет список троек зёрен. Не список — `"seed list malformed"`. Каждая тройка — список длины 3, элементы `type(v) is int` и `0 <= v < 2**32` (ручной расчёт: 4294967296), иначе `"seed tuple malformed"`. Дубликаты троек — `"duplicate seed tuples"`. Возврат: множество кортежей. Вывод: непересечение зёрен между разными тройками (требование `experiments.validate_suite`) здесь не проверяется, только уникальность троек.
