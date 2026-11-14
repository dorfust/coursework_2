# ERRATA_RU, часть 2: разделы B и C

Начало и индекс — в `docs/ERRATA_RU.md`. Ничего не запускалось. Код не менялся.

## Раздел B. Наблюдения при чтении (не дефекты)

Это нейтральный перечень того, что при чтении замечено по модулям. Слово «ошибка» не используется: ни одно наблюдение не проверено запуском, и определённой логической ошибки чтением не установлено (исключение — несоответствия текста самому себе, они названы прямо: B80, B52). Формулировки сохранены из прежнего чтения; код при составлении этого файла заново сверялся только для `contacts.py` и `geometry.py` (B6, B7, B8, B9). Метка [д] — наблюдение есть в указанной части описания; [э] — в описании соответствующего модуля оно не подтверждено повторным чтением и зафиксировано здесь.

### Модули группы 02 (`config`, `sim_config`, `geometry`, `contacts`, `graph`, `traffic`; [д] `docs/02` часть 8, §8, части 4-5)
- B1. `DataConfig` объявлен `frozen=True`, но списки сидов внутри остаются изменяемыми.
- B2. `Trajectory` (`frozen`) хранит массивы NumPy; сравнение и хеширование по полям к массивам, вероятно, неприменимо; в коде не используется.
- B3. `sim_config.ticks` не проверяет `dt`: при `dt = 0` вызов мимо `validate` даёт `ZeroDivisionError`.
- B4. Два независимых поля `light_speed_km_s`: у `SimulationConfig` проверяется только `> 0`, у `ModelConfig` оно обязано равняться константе.
- B5. `SimulationConfig.validate` не требует `packet_bytes <= buffer_bytes`.
- B6. `graph_from_positions`: две ветви проверки видимости (для C-непрерывного входа — только по парам, прошедшим дальность; иначе полная форма). Комментарий называет «Bitwise-equality argument» в документе вне экспорта; ветви в экспорте не сравниваются.
- B7. `ContactPlan._edge_arrival`: docstring утверждает равенство прежней функции (эталон `tests/reference/contacts_ref.py`, вне экспорта) и обосновывает отсечение `break` рассуждением о монотонности `service_ticks`; единственное названное отличие: на пропущенных отправлениях `distance_at` и `service_ticks` не вызываются, и недопустимые расстояния там исключения не дают.
- B8. В docstring `graph_from_positions` стоит «unresolved 50.4 deg»; в чём неоднозначность, код не раскрывает.
- B9. `GeometryNetwork.snapshot` не проверяет верхнюю границу `tick`; `ContactPlan.earliest_hop` считает ожидание в узле бесплатным (занятость узлов и буферы не моделируются, вывод из чтения).
- B10. `make_trajectory`: при умолчании `independent_plane_offsets` член с `walker_f` перекрывается независимыми случайными смещениями плоскостей, но на значения при фиксированном сиде влияет.
- B11. Внутренние словари `ContactPlan` изменяемы, хотя мутаторов нет.

### Модули группы 03 (`data`, `training`, `cli`, `provenance`, `loss`; [д] `docs/03` часть 3, §§7, 10)
- B12. `data.generate_dataset` создаёт каталог до проверки манифеста: при сбое остаётся каталог без `manifest.json`.
- B13. `training.evaluate` требует побайтового равенства `manifest.json` набора и манифеста обучения; заново сгенерированный набор той же конфигурации отличается полем `provenance`.
- B14. `training.train` импортирует `canonical_json` внутри блока `with` (стиль).
- B15. `cli.py`: `environment` требует `torch_geometric` (через `training` → `model`); `generate` печатает манифест целиком; `main` исключений не перехватывает.
- B16. `provenance.py` делает `import torch` на уровне модуля: поэтому и `simulate trace` требует `torch`.
- B17. `loss.parameter_l2`: производная неквадратичной нормы при нулевом векторе параметров не обработана.

### Модули группы 04 (`simulator`, `policies`, `tbr_policy`, `simulate`; [э])
- B18. `Simulator.run` вызывает `validate_records` с `cfg`, а не `self.cfg` (тот же объект).
- B19. `Simulator.run`, шаг 4: ветка повторной постановки `not_actionable` выглядит недостижимой.
- B20. Список `events` не ограничен по размеру.
- B21. `decision.neighbor` обязан быть именно `int`: целые `numpy` отвергаются.
- B22. `HopOracle` и `ContactRouting` не используют `packet.visited`.
- B23. У `ContactRouting._none_memo` нет вытеснения.
- B24. `TBR_bounded_exhaustive_reference` не входит в `POLICY_NAMES`.
- B25. Испытание отказа передачи привязано к ребру и тику, а не к пакету.
- B26. Схема результата `ssn-simulation-result-v1` в `simulator.py` заменяется в `simulate.run_single` на `ssn-simulation-result-v2` (для нативной политики — `ssn-native-exhaustive-simulation-result-v1`); результат прямого вызова `simulate()` остаётся с `v1`.
- B27. `run_single` создаёт каталог и пишет `config.json`, `traffic.json`, `provenance.json` до проверок чекпойнта GLR (несовпадение орбиты, пересечение сидов): после отказа остаётся каталог без `complete.json`.
- B28. `input_file_sha256` — хеш файла конфигурации; при `--p` или `--rate-bytes-s` действующая конфигурация иная и видна лишь в выходных `config.json` и `config_sha256`.
- B29. `--revision` проверяется только по формату (40 hex), не по checkout.
- B30. Справка `--rate-bytes-s` говорит «bits/bytes», а поле называется `rate_bytes_s`.
- B31. Нативная политика: исключения не перехватываются в `Simulator.run`; умолчание `DEFAULT_MAX_NODES = 12` при `n = 132` ведёт к отказу `simulate run` до создания вывода, пока не задан `--tbr-max-nodes` (проверка `cfg.orbit.n > policy.max_nodes`).
- B32. Регистр ревизии: `cli.revision` и `simulate.revision` принимают верхний регистр и приводят к нижнему; `experiment_io.revision` принимает только строчные.

### `experiments.py` ([д] `docs/05` часть A3, §14)
- B33. `validate_suite` вызывает `name(g["name"])` до проверки структуры: `KeyError`/`TypeError` вместо `ValueError`.
- B34. Единицы обучения и шаги создаются для всех N, даже при `--baselines-only` и для готовых моделей.
- B35. Команды `trace-<id>` в `offline_steps` не используются `execute_suite`.
- B36. `preflight_models` требует чекпойнт каждого N, даже если `policy_scope` убирает GLR для части N.
- B37. `execute_suite`: при отсутствии `result_sha256` в `complete.json` — `KeyError`.
- B38. `aggregate --reference GLR` для плана `--baselines-only` отвергается только в `aggregate_plan`.
- B39. Пути шаблонов `suite_path.parent / ...` не проверяются на выход за папку.

### `experiment_io.py` ([д] `docs/05` часть B3, §9)
- B40. `write` не атомарна: неполный файл блокирует повтор.
- B41. `job`: нет таймаута, `stdin` наследуется, `job_id` не проверяется как имя файла.
- B42. `validate_plan` для `PLAN_SCHEMA` не перевыводит команды; `sha256` плана — самохеш без секрета; `job` исполняет argv из плана.
- B43. `execution_guard` не вызывает `validate_plan` для `PLAN_SCHEMA`; `validate_plan` оборачивает `KeyError`/`TypeError` только для нативной схемы, `OSError` не оборачивает.
- B44. Docstring говорит «Standard-library», но модуль импортирует `config` и `sim_config`.
- B45. `source_hashes` хеширует все `*.py` рядом: посторонний `*.py` отвергнет `execution_guard` (вывод из чтения).

### `experiment_results.py` ([э])
- B46. `PLAN_SCHEMA` импортируется и не используется.
- B47. `scientific_plan_guard` для схемы v2 делает только `schema_guard`; хеши исходников сравниваются только у нативных планов.
- B48. `verify_models` требует `model_preflight.json`, если запланирован GLR, и при `allow_partial`; `digest()` отсутствующего `best.pt` даёт `FileNotFoundError`, а не `ValueError`.
- B49. Для планов v2 `KeyError`/`TypeError`/`OSError` из повреждённых артефактов ячейки не оборачиваются.
- B50. Нативные ячейки без успешного статуса исключаются, даже если артефакты проходят проверку.
- B51. `arrival_rate_packets_s = 1 / arrival_interval_s` и деление на `observation_end_s` не защищены от нуля.
- B52. Ожидаемый `budget_scope` в `verify_native_counters` — строчный `'not author settings'`, тогда как `experiment_io.native_options` пишет `'NOT author settings'` (текстовое расхождение; производитель фактического значения не читался, см. C1).
- B53. `import json` внутри блока `with` в `_verify_cell`.

### `experiment_plots.py` ([д] `docs/05` часть D4, §15)
- B54. Для обычной сводки структура не проверяется: `KeyError`/`TypeError` не переводятся в `ValueError`, имя PNG строится из `grid` и `variant` без фильтра.
- B55. `summary["mode"]` и поля заголовка читаются при рисовании, после создания каталога и `plot_data.json`: сбой оставит неполный каталог.
- B56. Общий перехват `KeyError`/`TypeError` в `_validate_native` скрывает, какой ключ неверен.
- B57. Цвета политик не закреплены за политикой.
- B58. `POLICIES` определена заново, а не импортирована из `experiments.py`.

### `driver/run_cell.py` ([д] `docs/06` часть A5, §14)
- B59. При `python -m driver.run_cell` модуль загружается дважды: как `__main__` и как `driver.run_cell` (через `train_unit`).
- B60. `plan_io.mark_started` вызывается до проверки среза и `--param`: `execution_started.json` остаётся и при отказе.
- B61. В `main` не перехватываются обычный `ValueError` из `load_plan`, `execution_guard`, `view.cell` и `OSError` из `ensure_traces` (в `traces.main` тот же `OSError` перехватывается, код 4).
- B62. Любой отказ возвращает 4 сразу, даже с `--keep-going`; накопленный код теряется.
- B63. `except BaseException` записывает любое исключение как `outcome="interrupted"`, не только сигнал.
- B64. `--cap-minutes` перекрывает лимиты ячеек из файла срезов для всех ячеек среза.
- B65. Список `names` строится через `relative_to(view.root.resolve())`, а пути логов — от `view.root` без `resolve`: опора на каноничность `body["root"]`.
- B66. Создание трасс не ограничено `--cap-minutes`, но входит в «стену» и журнал (`kind="trace"`).
- B67. Исключение при хешировании логов или записи `status.json` в нормальной ветке `_spawn_and_wait` не ловится; `status.json` может отсутствовать.

### `driver/train_unit.py` ([д] `docs/06` часть B4, §12)
- B68. `light_state` определена и не вызывается.
- B69. `mark_started` выполняется до проверки среза и параметров.
- B70. Не перехватываются: `ValueError` из `load_plan`/`execution_guard`, `OSError` вне POSIX, `KeyError` при плане без `steps`, `FileExistsError` при существующих журналах шага.
- B71. Любое исключение внутри `try` называется в журнале `interrupted` (в том числе `FileExistsError`).
- B72. `TrainRefused` возвращает 4 и отбрасывает накопленный код, даже при `--keep-going`.
- B73. `discard_unit` проверяет корень по мере удаления: ранние цели могут быть удалены до отказа на поздней.
- B74. `--slice ""` ложен в `if args.slice_id`: идёт ветка `--n` с `ns = [None]`, итог `refused: N=None is not a planned model` после `mark_started`.
- B75. `run_complete_no_evaluation` не требует каталога `data`; повтор `evaluate` без него завершится сбоем шага.
- B76. `cap_seconds` в `status.json` убитого шага — остаток лимита, а не лимит единицы.
- B77. Текст `check_cap_minutes` «omit the option for no cap» неточен: без опции действует умолчание 120 минут.
- B78. Послепроверка не ограничена лимитом.

### `driver/selector.py` ([э])
- B79. `check_suite_binding` отказывает только если в файле срезов есть ключ `suite` и имя серии плана — строка, отличная от него; сравнение по имени, иначе проверка пропускается.

### `driver/finish.py` ([д] `docs/06` часть D1, §10)
- B80. Docstring называет код 4 и для «usage», но ошибки `argparse` завершают процесс кодом 2 (текст docstring и поведение библиотеки расходятся).
- B81. `check` без `--revision` не использует `--plan-sha256`.
- B82. `verify_models` в `verify_cells` стоит вне `try`: в `check_report` его исключение не перехватывается (в `do_marker` перехватывается).
- B83. `do_preflight` и `models_light` учитывают все записи `body["models"]`, включая подставленные через `--models`.
- B84. `preflight_would_succeed` не учитывает проверку схемы, а `marker_would_succeed` учитывает.

### `driver/ledger.py` ([д] `docs/06` часть D2, §1.6)
- B85. Несуществующий путь в `sum` тихо даёт нули и код 0.
- B86. Один и тот же файл, переданный дважды, суммируется дважды.
- B87. Строка с корректным JSON, не являющаяся объектом, не отмечается как `_bad_line`; вызов `event.get` даст исключение.
- B88. Поля `extra` могут переписать служебные ключи записи.

### Уровень раскладки экспорта
- B89. Умолчание `--slices` (`Path(__file__).resolve().parents[1] / "slices.json"`) в раскладке экспорта указывает на несуществующий файл; обход — явный `--slices configs/slices_m1b_cgr.json` (нет в поставке; вывод из чтения).
- B90. В драйвере нет константы бюджета «700 минут»; `ledger sum` только суммирует. Строка «360-minute sum» в сообщениях `run_cell` и `train_unit` — текст, не проверка.
- B91. Готового `plan.json` в экспорте нет; план привязан к абсолютному корню и к хешам `*.py` пакета.

Всего в разделе B 91 пункт (ручной счёт): группа 02 — 11, группа 03 — 6, группа 04 — 15, `experiments.py` — 7, `experiment_io.py` — 6, `experiment_results.py` — 8, `experiment_plots.py` — 5, `run_cell.py` — 9, `train_unit.py` — 11, `selector.py` — 1, `finish.py` — 5, `ledger.py` — 4, раскладка — 3.

## Раздел C. Помечено как проверяемое, но не проверено

- C1. Регистр литерала `budget_scope`: `experiment_results.verify_native_counters` ожидает `'not author settings'`, `experiment_io.native_options` записывает `'NOT author settings'`; код, который пишет фактическое значение в результат нативной ячейки (`policy_details`), не читался; пройдёт ли реальная нативная ячейка эту проверку, не установлено.
- C2. Литералы `_validate_native` (`scientific_consumer`, маркер транспорта, `budget_scope`) не сравнивались символ в символ с тем, что пишет `aggregate_plan`.
- C3. Импортёры `simulator.py`, `simulate.py` и мест использования `POLICY_NAMES` не установлены (поиск по коду результатов не дал).
- C4. Берёт ли `data.py` положения в моменты времени выборок; назначение полей `step_s`, `start_s`, `mask_diagonal`, `beta`, `device`, `threads`, `deterministic`, `gcn_width`, `dense_width` в `data.py`, `training.py`, `model.py`, `loss.py`.
- C5. Подгружает ли цепочка `config` → `sim_config` → `traffic` библиотеку `torch`: `sim_config.py` и `traffic.py` прочитаны (в них только стандартная библиотека), `config.py` взят по индексу.
- C6. Равенство двух ветвей `graph_from_positions` и оптимизированного/базового `_edge_arrival`: аргументы лежат в документе и тесте вне экспорта; не проверялось.
- C7. Точный текст `docs/05` `partD2` §5.3 (A1), `docs/06` `partB2` п. 4.1 (A8), `partB3` п. 4.14 (A9), `partC3` §8 (A12) в этом файле не цитируется: части не перечитывались.
- C8. Полный перечень оборотов о ходе работы («в этом шаге», «в этой части», «прочитан для этого раздела») по всем частям `docs/02`-`docs/06`: перечислены только найденные при повторном чтении (A24).
- C9. Импортёры модулей, помеченных в `docs/01` часть 1, §2 как «индекс» (все, кроме 11 сверённых в A25).
- C10. Как `summarize_scoped_group` заполняет `policies` у обычной сводки со срезом политик и пройдёт ли такая сводка `prepare_plots`.
- C11. Вернёт ли `experiment_results.verify_cell` `None` для ячейки, убитой по лимиту (утверждение docstring `run_cell.py` не сверено с `experiment_results.py`).
- C12. Использование `light_state` в файлах `src/ssn_hops` (проверены только файлы драйвера).
- C13. Совпадение текста цитаты в комментарии `_judge` с `experiments.execute_suite`; ключи `result.json`, `provenance.json`, `complete.json` и точный состав `policy_details` нативной политики (их пишет симулятор).
- C14. Содержимое документов, названных строками кода (`SIMULATION_PROTOCOL.md`, `R3_FEATURES.md`, `TBR_NATIVE_ADAPTER.md`, `TBR_NATIVE_SINGLE_RUN.md`, словари `*_CONTRACT`): в экспорт не входят.

Всего в разделе C 14 пунктов.
