# 05. Эксперименты: `experiment_plots.py` (часть D3: `_policy_label`, `prepare_plots`, `prepare_plot_data`)

Продолжение `05_EXPERIMENTS_RU_partD2.md`; модуль `src/ssn_hops/experiment_plots.py`. Метки: «в коде написано», «вывод из чтения», «ручной расчёт». Ничего не запускалось.

## 6. Основные функции: `_policy_label` и уровень проверки обычной сводки

### 6.1. `_policy_label(policy, native)`

Аргументы: имя политики и словарь `native` (`summary["producer_native_reference"]`) либо `None` (для обычной сводки). Возврат: строка подписи линии в легенде. Правила по порядку (в коде написано):

1. `policy == "TBR_style_hop_oracle"`: `policy + " (BFS practical alternative; NON-COMPARABLE to Fig.5)"`. Правило действует и для нативной, и для обычной сводки.
2. `native` истинно и `policy == NATIVE_POLICY_NAME`: `policy + " (bounded exhaustive; whole choose CPU wall time; NOT pure-core / author Fig.5)"` плюс перевод строки и `"Safety limits: max_nodes=<native['max_nodes']>, max_expansions=<native['max_expansions']> (NOT author settings)"` (значения подставляются через f-строку).
3. Иначе возвращается имя политики без пояснений (`GLR`, `TSR_source_dijkstra`, `CGR_contact_plan`).

Вывод из чтения: ошибок функция не поднимает (при `native` без ключей `max_nodes` — `KeyError`, но после `_validate_native` этого не бывает); подпись нативной политики двустрочная.

### 6.2. Какую проверку получает обычная сводка (вывод из чтения)

Для схемы `SUMMARY_SCHEMA` `_validate_native` не вызывается. Проверяются: словарь, схема, метка (`prepare_plots`, п. 7.1), `complete` (п. 7.1) и условия на группы (п. 7.2-7.4: допустимая ось, уникальность `x`, равенство пяти полей `controls`). Остальные ключи читаются без проверки структуры: отсутствующий ключ даёт `KeyError`, нечисловое значение — `TypeError` либо ошибку в `matplotlib`, и эти исключения не переводятся в `ValueError`. Названия сетки и варианта в обычной сводке не проверяются на допустимые символы (в нативной это делает `_validate_native`, п. 19), хотя имя файла рисунка строится из них (раздел 7.5).

## 7. Основные функции: `prepare_plots(summary, allow_partial=False)`

Docstring: «Pure-data preparation; preserve equal-replicate values, SE and null gaps.» Возврат: список спецификаций рисунков (словари). Не обращается к файлам и к `matplotlib`; входную сводку не изменяет (вывод: нижележащие структуры копируются `deepcopy` или строятся заново).

### 7.1. Допуск сводки

1. Не `dict`, либо `schema` не из двух допустимых, либо `label != LABEL` — `ValueError("only explicitly labeled experiment summaries are accepted")`.
2. Нативная схема: `_validate_native(summary)` (часть D2).
3. `summary["complete"] is not True` и `allow_partial` ложно — `ValueError("partial suite plots require --allow-partial and explicit labeling")`. Вывод: у нативной сводки `complete` уже проверен как `bool` (D2, п. 9); у обычной отсутствие ключа даёт `KeyError`. С `allow_partial` неполная сводка строится, и спецификации получают `partial = True`.

### 7.2. Корзины

Для каждой группы: `axis` должна быть ключом `METRICS` (иначе `ValueError("unsupported plot axis")`); группа попадает в корзину `(grid, variant, axis)`. Рисунки строятся по корзинам в порядке `sorted(buckets.items())` (строковая сортировка по `grid`, `variant`, `axis`); внутри корзины группы упорядочены по `x`. Повторяющиеся `x` в корзине — `ValueError("duplicate x in plot series")`. Вывод: корзина — одна линия на политику, точки — значения `x` (размер созвездия `N` или вероятность `p`).

### 7.3. Контроль постоянства условий

`controls` берутся у первой группы корзины. Ключи сверки `fixed_keys`: `tick_s`, `rate_bytes_s`, `arrival_rate_packets_s`, `traffic_end_s`, `observation_end_s` (5), а для нативной сводки добавляются `failure_probability` при оси `"n"` (итого 6) либо `n` и `planes` при оси `"failure_probability"` (итого 7; ручной расчёт). Различие в любой группе — `ValueError("plot would silently mix rate/tick/load/window controls")`. Вывод: у обычной сводки вероятность отказа и размер сети на линии не сверяются (только пять общих полей); у нативной сверяются.

### 7.4. Рисунки корзины

Для каждого показателя из `METRICS[axis]` (порядок кортежа):

- `cost_figure = axis == "n" and metric in COST_METRICS`. Для `cost_figure` в `shown` попадают только политики из `FIG5_POLICIES`, иначе все политики. Порядок — как в `summary["policy_names"]`. Если `shown` пуст — `ValueError("no Fig.5 policy available for a cost plot")`.
- Для каждой политики из `shown`: `stats = [g["policies"][policy]["equal_replicate"][metric] for g in groups]`; линия — словарь `curve`:
  - `policy`, `label` (`_policy_label(policy, native)`), `x` (значения `x` групп), `y` (`stats[i]["mean"]`, может быть `None`), `se` (`se_of_mean`, может быть `None`), `nonnull_repetitions` (`n_nonnull`), `matched_repetitions` (`g["matched_repetitions"]`) — 7 ключей;
  - для нативной сводки ещё `null_repetitions` (`n_null`), `planned_repetitions`, `statistics_source` («policies[policy].equal_replicate; NOT pooled or surviving-policy subsets»), `method_limitations` (= `label`) — всего 11 ключей (ручной расчёт: 7 + 4).
  Вывод: политики, отсутствующие в `g["policies"]`, вызвали бы `KeyError`; для обычной сводки со срезом политик это не исключено (как `summarize_scoped_group` заполняет `policies`, в этом документе не проверялось; `05_EXPERIMENTS_RU_partC4.md`).
- Спецификация рисунка `spec` (базовые 8 ключей): `filename = f"{grid}--{variant}--{metric}.png"`, `grid`, `variant`, `axis`, `metric`, `controls` (копия), `curves`, `partial = summary["complete"] is not True`.
- Для `cost_figure` добавляются `excluded_policies` (политики сводки, не вошедшие в `shown`) и `exclusion_reason = FIG5_EXCLUSION_REASON` (+2 ключа).
- Для нативной сводки добавляются (+8 ключей): `input_summary_schema`, `plot_consumer` (копия `PLOT_CONSUMER`), `ylabel = NATIVE_LABELS[metric]`, `error_bars = ERROR_BARS`, `display_label` (`LABEL`, при неполной сводке `LABEL + " / PARTIAL"`), `controls_by_x` (`controls` каждой группы), `count_provenance` (для каждой группы `x`, `control_sha256`, `planned_repetitions`, `matched_repetitions`, `included_seed_tuples`, `excluded_seed_tuples`), `native_safety_limits` (`max_nodes`, `max_expansions`, `budget_scope` из справочника).

Ручной расчёт: на корзину приходится 3 спецификации (по `len(METRICS[axis]) = 3`); при двух корзинах получаем 6 файлов PNG. Число линий: при оси `"n"` и показателях `route_seconds_per_call`, `simulation_seconds` у обычной сводки с четырьмя политиками — 3 линии (без `TSR_source_dijkstra`), у остальных — 4; у нативной сводки `with_trained_GLR` — 4 из 5 (без TSR) и 5; при `baselines_only` — 3 из 4 и 4.

### 7.5. Имена файлов и коллизии

Имя файла рисунка: `<grid>--<variant>--<metric>.png`. Для нативной сводки после построения проверяется уникальность имён: повтор — `ValueError("native summary colliding plot filenames")`. Вывод: коллизия возможна лишь при одинаковых `(grid, variant)` с разными осями, что `experiments.py` не создаёт (имена сеток уникальны, у сетки одна ось); у обычной сводки проверки нет. Имя строится из `grid` и `variant` сводки, при обычной сводке без проверки символов: подделанное имя с разделителями пути изменило бы место записи в `plot_summary` (`root / spec["filename"]`); для плана, созданного `experiments.py`, имена ограничены `name()` (`[a-z][a-z0-9_-]{0,39}`, часть A2).

## 8. Основные функции: `prepare_plot_data(summary, summary_sha256=None, allow_partial=False)`

Docstring: «New data-only export helper. Caller supplies file hash, not a measurement.» Вызывает `prepare_plots(summary, allow_partial)` и возвращает документ (словарь), который `plot_summary` записывает как `plot_data.json`. Файлов не читает и не пишет.

Ключи документа:

- общие (3): `summary_sha256` (как передано; может быть `None`), `plots` (список спецификаций), `error_bars = ERROR_BARS`;
- для нативной сводки добавляются ещё 6 (итого 9; ручной расчёт): `input_summary_schema`; `plot_consumer` (копия); `label` (`LABEL`, при неполной сводке `LABEL + " / PARTIAL"`); `partial = not summary["complete"]`; `input_layers` (5 ключей: `producer_plan_schema`, `producer_native_reference`, `producer_single_run_reference`, `scientific_consumer`, `transport_completion_marker`, копии); `summary_provenance` (12 ключей: `plan_sha256`, `declared_checkout_revision`, `source_sha256`, `reference_policy`, `scientifically_verified_cells`, `planned_cells`, `missing_or_failed_cells`, `excluded_cells`, `artifact_evidence`, `statistics`, `timing_warning`, `authentication_limit`, копии).
- Для нативной сводки при `summary_sha256 is not None` значение проверяется `_hash` (64 hex, `"native summary invalid hash/revision"`); для обычной сводки не проверяется (вывод).

Вывод из чтения: порядок такой: сначала вся проверка и подготовка в `prepare_plots`, затем проверка хеша; ошибка хеша не оставляет следов на диске. Документ содержит достаточно данных для повторного построения рисунков без сводки: линии (`x`, `y`, `se`, счётчики), элементы управления и (у нативной) происхождение и ограничения. Результатов в экспорте нет, поэтому значений `y` в этом документе нет.
