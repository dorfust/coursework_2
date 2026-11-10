# 05. Эксперименты: `experiment_plots.py` (часть D4: `plot_summary`, рисунки, значения по умолчанию, связи, побочные эффекты, перечни)

Продолжение `05_EXPERIMENTS_RU_partD3.md`; модуль `src/ssn_hops/experiment_plots.py`. Метки: «в коде написано», «вывод из чтения», «ручной расчёт». Ничего не запускалось; результатов построения в экспорте нет, и в этом документе их нет.

## 9. Основные функции: `plot_summary(summary_path, output, allow_partial=False)`

Единственная функция модуля, которую вызывает другой модуль (`experiments.py`, `main`, команда `plot`). Аргументы: путь к файлу сводки, путь нового каталога вывода, флаг допуска неполной сводки. Возврат: `{"plots": len(specs), "out": str(root), "partial": summary["complete"] is not True}`.

### 9.1. Порядок работы (в коде написано)

1. `input_hash = digest(summary_path)` (SHA-256 файла, `experiment_io.py`), затем `summary = read(summary_path)`, затем `data = prepare_plot_data(summary, input_hash, allow_partial)` (раздел 8; вся проверка и подготовка). Если `digest(summary_path) != input_hash` — `ValueError("summary changed during plot preparation")`.
2. Ленивый импорт; комментарий кода: «Import ONLY after all native validation; missing package creates no output.» Выполняется `import matplotlib`, затем `matplotlib.use("Agg")`, затем `import matplotlib.pyplot as plt`. Бэкенд `Agg` выбран до подключения `pyplot` (в коде написано); `Agg` — растровый бэкенд без окна (знание о библиотеке, не из кода). Если пакета нет, возникает обычное исключение импорта Python (`ImportError`/`ModuleNotFoundError`); собственного сообщения в коде нет, исключение не перехватывается (вывод). Каталог вывода к этому моменту не создан.
3. `root = Path(output)`; `root.mkdir(parents=True, exist_ok=False)`: существующий каталог даёт `FileExistsError`.
4. `write(root / "plot_data.json", data)` (режим `"x"`).
5. Для каждой спецификации: рисунок, сохранение (9.2).
6. После цикла повторная проверка `digest(summary_path) != input_hash` — `ValueError("summary changed during rendering; no completion claim")`.
7. Запись `complete.json` (9.3) и возврат.

Вывод: при отказе на шагах 5-6 в `root` остаются `plot_data.json` и уже сохранённые PNG, а `complete.json` отсутствует; повторный запуск требует нового каталога вывода (`exist_ok=False`). Отказы шагов 1-2 следов не оставляют. Хеш сводки вычисляется три раза (ручной расчёт: шаги 1, 1 после подготовки и 6).

### 9.2. Рисунки (по каждой спецификации; в коде написано)

- Фигура: `plt.subplots(figsize=(10, 6), constrained_layout=True)`; закрывается в `finally` (`plt.close(figure)`). Ручной расчёт размера: 10 x 6 дюймов при `dpi=150` — 1500 x 900 пикселей (при стандартных параметрах сохранения; вывод).
- Линии. Для каждой кривой `curve`: значения `y`, равные `None`, заменяются на `math.nan`; `axes.plot(x, values, marker="o", label=curve["label"])`. Маркер `"o"` одинаков для всех политик; цвет явно не задаётся (используется стандартный цикл цветов `matplotlib`, знание о библиотеке). Вывод: цвет политики зависит от порядка рисования и не фиксирован за политикой; на рисунках стоимости (без TSR) цвета последующих политик сдвигаются относительно рисунков задержки и долей.
- Планки погрешности. Для каждой точки, у которой `y` и `se` не `None`: `axes.errorbar([x], [y], yerr=[se], color=цвет линии, capsize=3)`. Планка равна одной стандартной ошибке среднего с равным весом повторений (`se_of_mean`, формула в части C1: `sd / sqrt(n_nonnull)`); доверительные интервалы не строятся (`ERROR_BARS`, подпись внизу). Вывод: при `n_nonnull = 1` (`se` равно `None`) и при `n_nonnull = 0` планки нет; при `se = 0.0` рисуется планка нулевой длины с засечками.
- Пропуски. `None` в `y` становится `NaN`: точки нет, линия прерывается (знание о библиотеке); пропуск не подменяется нулём и не интерполируется. Подпись внизу: «Null estimates are gaps.»
- Заголовок из трёх строк: `LABEL` (с добавкой `" / PARTIAL"` при неполной сводке); `"<grid> / <variant> / <mode>"` (`mode` — `summary["mode"]`); `"dt=<tick_s> s; rate=<rate_bytes_s> B/s; load=<arrival_rate_packets_s:g> packets/s"`. Поля берутся из `spec["controls"]` (первая группа корзины).
- Подпись X: «Per-active-transfer-tick abort probability p» при оси `"failure_probability"`, иначе «Constellation size N». Подпись Y: `spec.get("ylabel", LABELS[metric])`: у нативных — `NATIVE_LABELS[metric]`, у обычных — `LABELS[metric]`.
- Сетка `axes.grid(True, alpha=0.25)`; легенда `axes.legend(fontsize="small")`; шкалы линейные (логарифмическая шкала и пределы осей не задаются; вывод).
- Подпись внизу: `figure.text(0.01, 0.005, "Equal-replicate means; bars = 1 SE, not CI. Null estimates are gaps. Matched/nonnull counts in plot_data.json.", fontsize=8)`.
- Сохранение: `figure.savefig(root / spec["filename"], dpi=150)`; формат PNG (по расширению).

Набор рисунков (по `METRICS`): оси `"failure_probability"` — `delivered_mean_delay_s`, `failure_fraction`, `pending_fraction`; оси `"n"` — `delivered_mean_delay_s`, `route_seconds_per_call`, `simulation_seconds`. Названия показателей совпадают с ключами `FIELDS` агрегирования (часть C1). Парные разности, объединённые суммы, `nondelivery_fraction`, `goodput_bits_s` не рисуются.

### 9.3. `complete.json` (в коде написано)

Ключи: `plots_finished = True`, `summary_sha256 = input_hash`, `output_sha256 = {имя PNG: digest}`, `plot_data_sha256 = digest(plot_data.json)` (4 ключа); для нативной сводки ещё `input_summary_schema`, `plot_consumer` (копия), `partial = not summary["complete"]` (итого 7; ручной расчёт). Вывод: `plot_data.json` не входит в `output_sha256`; его хеш — отдельное поле.

## 10. Значения по умолчанию (experiment_plots.py)

`plot_summary` и `prepare_plots`: `allow_partial=False`; `prepare_plot_data`: `summary_sha256=None`, `allow_partial=False`. Рисунок: `figsize=(10, 6)`, `constrained_layout=True`, `dpi=150`, маркер `"o"`, `capsize=3`, сетка `alpha=0.25`, легенда `fontsize="small"`, подпись `fontsize=8` в точке (0.01, 0.005); бэкенд `"Agg"`; `mkdir(parents=True, exist_ok=False)`. Ограничения: имена `[a-z][a-z0-9_-]{0,39}`, зёрна `0 <= v < 2**32`, допуск `close` 1e-10 (`experiment_results.py`). Константы — раздел 3 (`D1`). Командная строка `plot` (`experiments.py`, `parser`): `--summary` и `--out` обязательны, `--allow-partial` — флаг, по умолчанию ложь.

## 11. Связи с другими модулями

Импортирует (вверху, в коде написано): `defaultdict` (collections), `deepcopy` (copy), `math`, `Path` (pathlib), `re`; `config.content_hash`; `experiment_io`: `NATIVE_PLAN_SCHEMA`, `NATIVE_POLICY_NAME`, `digest`, `native_options`, `read`, `single_run_native_reference`, `write`; `experiment_results`: `FIELDS`, `SCIENTIFIC_CONTRACT`, `SUMMARY_SCHEMA`, `NATIVE_SUMMARY_SCHEMA`, `count`, `close`, `verify_native_counters`. Лениво (внутри `plot_summary`): `matplotlib`, `matplotlib.pyplot`. Вывод: все импортированные имена в тексте модуля используются. Импорт `experiment_results` подтягивает `sim_config` и `traffic` (часть C1), поэтому утверждение docstring «No matplotlib, simulator or search is imported» относится к собственному коду модуля; подгружает ли эта цепочка `torch`, не установлено.

Импортируется (по чтению экспортированных файлов): `experiments.py`, `main`, ветка `plot`: `from .experiment_plots import plot_summary` (ленивый импорт). Других импортёров чтением не установлено. Циклов при загрузке нет (вывод: `experiment_results` и `experiment_io` не импортируют `experiment_plots`).

Связь с агрегированием: вход — файл, записанный `aggregate_plan` (часть C5); имена показателей, схемы сводок, `field_units`, `statistics`, `timing_warning`, `authentication_limit`, `source_sha256` и структура групп взяты из того документа. Нативная сводка в слое агрегирования несёт `plots_supported: false`; модуль `experiment_plots.py` принимает её, сверяя именно этот литерал (`_validate_native`, п. 4), и сам заявляет `plots_supported: true` в `PLOT_CONSUMER`. Связь с командой `plot` (`experiments.py`, `main`): `plot_summary(args.summary, args.out, args.allow_partial)`; в отличие от `train`, `execute`, `aggregate`, план не загружается (`load_plan` не вызывается), ревизия не передаётся, `execution_guard` не вызывается (вывод: команде нужен только файл сводки); результат печатается как JSON (`indent=2`, `sort_keys=True`, `allow_nan=False`).

Предусловия (вывод): полный план или неполный? Для полной сводки (`complete = True`) флаг не нужен; для неполной (`allow_aggregate --allow-partial` на этапе агрегирования, `complete = false`) рисунки строятся только с `--allow-partial` и получают `PARTIAL` в заголовке и `partial: true` в документах.

## 12. Побочные эффекты

Чтение файла сводки (один раз `read` и три хеширования); создание каталога и трёх видов файлов (`plot_data.json`, PNG, `complete.json`); существующие пути не перезаписываются. Глобальное состояние: `matplotlib.use("Agg")` меняет бэкенд процесса (вывод); фигуры закрываются. Случайность: модули `random`, `time`, `datetime` не импортируются, генераторов нет. Сеть и подпроцессы не задействованы. Ручной расчёт числа файлов: `len(specs) + 2` (PNG, `plot_data.json`, `complete.json`).

## 13. Что в коде названо допущением или реконструкцией

`LABEL` («RECONSTRUCTION / NOT AUTHORS' RESULTS»); `ERROR_BARS` («NOT confidence intervals»); подписи политик: «BFS practical alternative; NON-COMPARABLE to Fig.5» и «bounded exhaustive; ... NOT pure-core / author Fig.5», «Safety limits ... (NOT author settings)»; `PLOT_CONSUMER`: `validation_limit` (согласованность сводки, без повторного чтения артефактов; хеши не доказывают подлинность), `timing_limit` (только время CPU реализации; единица и обход оригинального рисунка 5 неизвестны); `FIG5_EXCLUSION_REASON` («paper Fig.5 legend: GLR, TBR, CGR only»). Название «Fig.5» относится к рисунку оригинальной статьи; документа-источника в экспорте нет. Комментарии содержат внутренние метки правок; расшифровка не входит в экспорт.

## 14. Что не установлено чтением

- Работоспособность модуля и вид рисунков: ничего не запускалось.
- Установленность и версия `matplotlib`, объявлена ли зависимость в проекте (файлы зависимостей здесь не читались).
- Поведение `matplotlib` (цвета, `NaN`, `Agg`, размер в пикселях) — знание о библиотеке, не проверка.
- Совпадение литералов `_validate_native` (`scientific_consumer`, маркер транспорта, `budget_scope`) с тем, что фактически пишет `aggregate_plan`: сравнение символ в символ не выполнялось; пройдёт ли реальная нативная сводка эту проверку, не установлено.
- Как `summarize_scoped_group` заполняет `policies` у обычной сводки со срезом политик и пройдёт ли она `prepare_plots`.
- Подпись `verify_native_counters` и состав счётчиков (часть C2); содержимое документа из `PLOT_CONTRACT["path"]`.
- Другие импортёры модуля, кроме `experiments.py`.

## 15. Наблюдения о коде (не исправлялись) и группа документов 05

1. Для обычной сводки структура не проверяется: `KeyError`/`TypeError` не переводятся в `ValueError`, имена `grid` и `variant` не фильтруются, а имя PNG строится из них (разделы 6.2, 7.5).
2. `summary["mode"]` и поля заголовка читаются только при рисовании, после создания каталога и `plot_data.json`: отсутствие `mode` или нечисловая нагрузка оставят неполный каталог.
3. В `_validate_native` общий перехват `KeyError`/`TypeError` скрывает, какой ключ неверен.
4. Цвета политик не закреплены (9.2).
5. `POLICIES` определена заново, а не импортируется из `experiments.py`.
6. Уточнение к `05_EXPERIMENTS_RU_partD2.md`, раздел 5.3, последний пункт: правило 28 сравнивает с нулём целые знаменатели `delivered`, `route_calls`, `generated`; суммы `delay_sum_s` и `route_seconds` в правиле не участвуют. Формулировка в том пункте неточна, верна эта.
Однозначной логической ошибки чтением не установлено.

Документы группы 05: индекс `05_EXPERIMENTS_RU.md`; `partA1`-`partA3` (`experiments.py`); `partB1`-`partB3` (`experiment_io.py`); `partC1`-`partC5` (`experiment_results.py`); `partD1`-`partD4` (`experiment_plots.py`; этот набор).
