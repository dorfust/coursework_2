# 05. Эксперименты: индекс описания четырёх модулей конвейера экспериментов

Документ перечисляет файлы описания группы 05, порядок чтения, условные обозначения, зависимости модулей, точку входа и сводный перечень того, что чтением не установлено. Сами описания лежат в файлах `05_EXPERIMENTS_RU_part*.md` этой же папки.

## 1. Модули группы 05 (папка `src/ssn_hops/`)

| Модуль | Роль (вывод из чтения) | Файлы описания |
|---|---|---|
| `experiments.py` | планирование серии, обучение, последовательное выполнение, разбор команд | `partA1`-`partA3` |
| `experiment_io.py` | чтение и запись JSON, хеши, проверка плана, охрана запуска, запуск процесса, проверка нативной ячейки | `partB1`-`partB3` |
| `experiment_results.py` | проверка сохранённых артефактов ячеек и агрегирование в сводку | `partC1`-`partC5` |
| `experiment_plots.py` | проверка сводки и построение рисунков (PNG) и данных рисунков | `partD1`-`partD4` |

Всего файлов описания: 16 (3 + 3 + 5 + 4 + 1; ручной расчёт). Файлов с префиксом `05_EXPERIMENTS_RU_part` в списке ниже 16, плюс этот индекс.

## 2. Список файлов и функций

Состав разделов взят из перечней разделов каждой части; точное размещение мелких вспомогательных функций внутри `partA1`/`partA2` в индексе не проверялось.

**`experiments.py`**
- `05_EXPERIMENTS_RU_partA1.md`: назначение, термины, команды `plan`/`train`/`execute`/`aggregate`/`plot`, создаваемые файлы, константы модуля.
- `05_EXPERIMENTS_RU_partA2.md`: проверка набора параметров (suite), зёрна, перечисление сценариев, обучающие единицы, `policy_scope`, ячейки и команды, документ плана (`validate_suite`, `validate_policy_scope`, `scope_policies`, `resolve_suite`, `resolve_plan_inputs`, `plan_commands`, `make_plan`).
- `05_EXPERIMENTS_RU_partA3.md`: `check_model`, `preflight_models`, `train_suite`, `execute_suite`, ветки `aggregate` и `plot` в `main`; условия отказа, связи, побочные эффекты, допущения, не установленное, наблюдения.

**`experiment_io.py`**
- `partB1`: разделы 1-2 (назначение, документы, хеши, строки схем), `NATIVE_CONTRACT`, `positive_budget`, `native_options`, `single_run_native_reference`, `read`, `write`, `digest`, `revision`, `source_hashes`, `inside`.
- `partB2`: `schema_guard`, `validate_native_plan`, `check_scoped_plan`, `validate_plan`, `load_plan`, `execution_guard`.
- `partB3`: `native_transport_check`, `job`; значения по умолчанию, связи, побочные эффекты, допущения, не установленное, наблюдения.

**`experiment_results.py`**
- `partC1`: назначение, константы (`SUMMARY_SCHEMA`, `NATIVE_SUMMARY_SCHEMA`, `SCIENTIFIC_CONTRACT`, `NATIVE_COUNTERS`, `FIELDS`), `close`, `count`, `describe`.
- `partC2`: `verify_accounting`, `scientific_plan_guard`, `verify_native_counters`.
- `partC3`: `verify_cell`, `_verify_cell`, `verify_models`.
- `partC4`: `summarize_group`, `summarize_scoped_group`, `native_completion_marker`, `scoped_declarations`.
- `partC5`: `aggregate_plan`, схемы выходных документов, значения по умолчанию, связи, побочные эффекты, допущения, не установленное.

**`experiment_plots.py`**
- `partD1`: назначение, входы и выходы, константы, `_same`, `_hash`, `_number`, `_stats`, `_seed_list`.
- `partD2`: `_validate_native`.
- `partD3`: `_policy_label`, `prepare_plots`, `prepare_plot_data`, состав спецификаций рисунков.
- `partD4`: `plot_summary`, рисунки, `complete.json`, значения по умолчанию, связи, побочные эффекты, допущения, не установленное, наблюдения.

**обзор группы (не модуль)**
- `05_EXPERIMENTS_RU_partE.md`: сводный обзор редакции 5 — пять стадий конвейера, наборы, опции плана, политики, рисунки; раздел F — 28 нумерованных исправлений к прежнему тексту группы.

## 3. Порядок чтения

Если нужен контекст, сначала `02_ENVIRONMENT_RU.md` (конфигурации, трафик), `03_LEARNING_RU.md` (обучение), `04_SIMULATION_POLICIES_RU.md` (симулятор, политики). Затем: этот индекс; `partA1`-`partA3` (план и запуск); `partB1`-`partB3` (форматы, хеши, проверка плана); `partC1`-`partC5` (агрегирование); `partD1`-`partD4` (рисунки); в конце `partE` (сводный обзор редакции 5). Чтение `B` перед `C` полезно: `experiment_results.py` использует функции `experiment_io.py`.

## 4. Условные обозначения

- «в коде написано» — прямая цитата или пересказ строки кода; «вывод из чтения» — следствие, не заявленное в коде; «ручной расчёт» — арифметика с показом.
- Ничего не запускалось: описания получены только чтением; нигде не утверждается, что код работает, прошёл проверку или даёт определённые результаты. Числовых результатов экспериментов в группе нет.
- Документы, названные в строках кода (например пути к внутренним документам проекта в словарях `CONTRACT`, `FEATURE_CONTRACT`, `NATIVE_CONTRACT`, `SCIENTIFIC_CONTRACT`, `PLOT_CONTRACT`), в экспорт не входят; они цитируются только как строки. Внутренние метки правок в комментариях кода не расшифровываются.

## 5. Зависимости между модулями (по строкам import)

Верхние импорты:
- `experiments.py` -> `config`, `sim_config`, `experiment_io`.
- `experiment_io.py` -> `config`, `sim_config`.
- `experiment_results.py` -> `config`, `sim_config`, `traffic`, `experiment_io`.
- `experiment_plots.py` -> `config`, `experiment_io`, `experiment_results`.

Ленивые импорты (внутри функций):
- `experiments.py` -> `training` (`load_trained_model`), `traffic` (`make_trace`, `trace_document`), `experiment_results` (`aggregate_plan`), `experiment_plots` (`plot_summary`).
- `experiment_io.py` -> `experiments` (`validate_native_plan`, `check_scoped_plan`).
- `experiment_results.py` -> `experiments` (`check_model`).
- `experiment_plots.py` -> `matplotlib`, `matplotlib.pyplot`.

Вывод: при загрузке циклов нет, обратные ссылки на `experiments` ленивые. Дочерние процессы (запускает `job`): `python -m ssn_hops` (`generate`, `train`, `evaluate`) и `python -m ssn_hops.simulate` (`trace`, `run`).

## 6. Точка входа

`python -m ssn_hops.experiments plan | train | execute | aggregate | plot` (`experiments.py`, `parser`, `main`; блок `if __name__ == "__main__"`). Пакет `ssn_hops` должен быть импортируем из текущего каталога или среды (вывод).

| Команда | Аргументы | Функция | Часть |
|---|---|---|---|
| `plan` | `--suite`, `--out`, `--revision` (обязательны); `--models`, `--baselines-only`, `--include-native-tbr`, `--tbr-max-nodes`, `--tbr-max-expansions` | `make_plan` | A2 |
| `train` | `--plan`, `--revision` | `train_suite` | A3 |
| `execute` | `--plan`, `--revision` | `execute_suite` | A3 |
| `aggregate` | `--plan`, `--out`; `--allow-partial`, `--reference` | `aggregate_plan` | C5 |
| `plot` | `--summary`, `--out`; `--allow-partial` | `plot_summary` | D4 |

Поток данных (вывод): `plan` пишет `plan.json` и конфигурации; `train` обучает модели; `execute` пишет трассы, `runs/`, `logs/`, маркеры; `aggregate` читает их и пишет один JSON сводки; `plot` читает только сводку и пишет `plot_data.json`, PNG, `complete.json`. Результат команды печатается как JSON.

## 7. Что не установлено чтением (сводный перечень заголовков)

Подробности — в разделах «Что не установлено чтением» указанных частей.

1. Работоспособность, время работы, вид рисунков и любые числовые результаты: ничего не запускалось (A3, B3, C5, D4).
2. Содержимое документов, названных в строках `CONTRACT`, `FEATURE_CONTRACT`, `NATIVE_CONTRACT`, `SCIENTIFIC_CONTRACT`, `PLOT_CONTRACT`; соответствие строк `*_commit` реальным ревизиям (A3, B3, C5, D4).
3. Формат файла suite на практике (A3).
4. Сигнатура и поведение `training.load_trained_model` вне использованных ключей (A3).
5. Ключи `result.json`, `provenance.json`, `complete.json`, `packets.json`, `events.jsonl` и точный состав `policy_details` нативной политики: их пишет симулятор (B3, C5).
6. Совпадение строки `budget_scope` (регистр "not"/"NOT") и других литералов проверок с тем, что фактически записывают производители (C5, D4).
7. Допустимость нулевых `observation_end_s` и `arrival_interval_s` (деления без защиты) (C5).
8. Версия Python и поведение на Windows (B3).
9. Подгружает ли цепочка `config` / `sim_config` / `traffic` библиотеку `torch` (C5, D4).
10. Установленность и версия `matplotlib`, объявление зависимости, поведение библиотеки (D4).
11. Заполнение `policies` у обычной сводки со срезом политик и прохождение такой сводки через `prepare_plots` (D4).
12. Прочие импортёры модулей группы, кроме перечисленных в разделе 5 (A3, B3, C5, D4).

## 8. Уточнения к частям

- `05_EXPERIMENTS_RU_partD2.md`, раздел 5.3, последний пункт: правило 28 сравнивает с нулём целые знаменатели `delivered`, `route_calls`, `generated`; суммы `delay_sum_s` и `route_seconds` в нём не участвуют. Верна эта формулировка.
- `05_EXPERIMENTS_RU_partD4.md`, раздел 11, абзац «Предусловия»: обозначение в скобках записано неточно. Верно так: для неполной сводки (`complete = false`, получена командой `aggregate --allow-partial`) рисунки строятся только с флагом `--allow-partial` команды `plot`. В разделе 9.1 фраза о трёх хешированиях: шаг 1 (до чтения), проверка после подготовки данных и проверка после рисования.
