# 03. Обучение: описание модулей (индекс)

Описание девяти модулей каталога `src/ssn_hops/`, которые строят признаки, набор данных, модель, функцию потерь, обучение и командную строку: `features.py`, `data.py`, `model.py`, `loss.py`, `training.py`, `provenance.py`, `cli.py`, `__main__.py`, `__init__.py`. Файл — индекс; текст разбит на три части в той же папке `docs/`. Среда (`config.py`, `sim_config.py`, `geometry.py`, `contacts.py`, `graph.py`, `traffic.py`) описана в `02_ENVIRONMENT_RU.md` и здесь не повторяется. Документ заканчивается списком «Не установлено чтением» (часть 3, раздел 10).

## Части

| Часть | Файл | Модули (разделы) |
|---|---|---|
| 1 | `03_LEARNING_RU_part1.md` | `features.py` (1), `data.py` (2) |
| 2 | `03_LEARNING_RU_part2.md` | `model.py` (3), `training.py` (4) |
| 3 | `03_LEARNING_RU_part3.md` | `loss.py` (5), `provenance.py` (6), `cli.py` (7), `__main__.py` (8), `__init__.py` (9), сводка «Не установлено чтением» (10) |

## Условные обозначения
- «В коде написано» — цитата или пересказ исходного текста; «вывод из чтения» — заключение без запуска; «ручной расчёт» — арифметика, показанная в тексте.
- Ничего из описанного не запускалось: нет заявлений о том, что код работает, прошёл проверки или даёт результаты. Результаты экспериментов не приводятся.
- Идентификаторы, имена файлов, параметров и команды даны латиницей. Значения по умолчанию указаны с файлом и именем константы или класса.
- Комментарии и строки кода местами называют внутренние документы и метки (например, «R3_FEATURES.md», «T020 C002», «pre-T022», пути в `provenance.SOURCES`). Эти документы не входят в экспорт; они упомянуты только как цитаты кода.

## Зависимости между девятью модулями (по строкам `import`)
```
features.py    <- config
loss.py        <- (torch)
provenance.py  <- (torch)
model.py       <- config, graph
data.py        <- config, geometry, graph, provenance
training.py    <- config, data, features, graph, loss, model, provenance
cli.py         <- config, data, provenance, training
__main__.py    <- cli
__init__.py    <- (нет импортов)
```
`graph.py` (см. `02_ENVIRONMENT_RU.md`, часть 6) импортирует `features.py`. Сторонние пакеты: `numpy`, `torch`, `torch_geometric` (в `model.py`).

## Поток данных (вывод из чтения)
`generate` → `data.generate_dataset` → каталог `train.npz`, `val.npz`, `test.npz`, `manifest.json`; `train` → `training.train` → каталог прогона (`config.json`, `dataset_manifest.json`, `provenance.json`, `history.jsonl`, `best.pt`, `best.json`, `complete.json`); `evaluate` → `training.evaluate` → один JSON-файл метрик.

## Как читать
Сначала часть 2 (модель и обучение), затем часть 3, раздел 5 (потери), затем часть 1 (данные). Каждый модуль описан по схеме: назначение; входы и выходы; функции; значения по умолчанию; связи; побочные эффекты; допущения в коде; что не установлено чтением. Планируемое описание симуляции и политик — `docs/04_SIMULATION_POLICIES_RU.md`.
