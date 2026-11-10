# experiment_results.py: описание, часть C4 из пяти

Продолжение `05_EXPERIMENTS_RU_partC3.md`. В этом документе: `summarize_group`, `summarize_scoped_group`, `native_completion_marker`, `scoped_declarations`. Источник: `src/ssn_hops/experiment_results.py`. Все числа в примерах — иллюстрации формул, не результаты запусков.

## summarize_group(matched, policies, reference)

Строка документации (в коде написано): «Only complete policy-matched repetitions enter ANY group estimate».

Аргументы:

- `matched` — список словарей, по одному на сценарий группы: `{policy: проверенная запись ячейки}` (запись из `_verify_cell`, см. C3);
- `policies` — список имён политик (в `aggregate_plan` это `body["policies"]`);
- `reference` — имя эталонной политики.

Возврат: пара `(results, differences)`.

### results

Для каждой политики `policy` из `policies`: `runs = [item[policy] for item in matched]` (при отсутствии политики в элементе `KeyError`), далее два блока (в коде написано).

1. `equal_replicate`: для каждого из 7 ключей `FIELDS` вызывается `describe([r["values"][key] for r in runs])` (C1). Это средние по повторениям с равным весом каждого повторения: каждый сценарий (повторение) даёт одно число на показатель, и выборка для оценок состоит из этих чисел. Значение `None` (например, `delivered_mean_delay_s` при отсутствии доставок или `route_seconds_per_call` при нуле вызовов) исключается из `n_nonnull` и учитывается в `n_null`.
2. `pooled_packet_and_call`: суммы по повторениям восьми величин `generated`, `delivered`, `failed`, `pending`, `delay_sum_s`, `route_calls`, `route_seconds`, `delivered_bytes` (по полю `totals` записи) плюс пять производных (обозначения: `g = generated`, `d = delivered`, `calls = route_calls`):
   - `delivered_mean_delay_s = delay_sum_s / d`, при `d == 0` значение `None`;
   - `failure_fraction = failed / g`; `pending_fraction = pending / g`; `nondelivery_fraction = (failed + pending) / g`; при `g == 0` значение `None`;
   - `route_seconds_per_call = route_seconds / calls`, при `calls == 0` значение `None`.
   Всего 8 + 5 = 13 ключей (ручной расчёт). В пулованный блок не входят `goodput_bits_s` и `simulation_seconds`; стандартная ошибка для пулованных значений не вычисляется (вывод из чтения: нет вызова `describe`).

Различие двух блоков: в `equal_replicate` доля — среднее долей по повторениям, в `pooled_packet_and_call` доля — отношение сумм (взвешивание числом пакетов или вызовов). Ручной расчёт: два повторения, `generated` 10 и 30, `failed` 1 и 15. Равновесное среднее: (1/10 + 15/30) / 2 = (0.1 + 0.5) / 2 = 0.3. Пулованная доля: (1 + 15) / (10 + 30) = 16 / 40 = 0.4.

Задержка считается только по доставленным пакетам: `delay_sum_s` — сумма задержек доставленных пакетов (C2), делитель — число доставленных. Пакеты `pending` не считаются доставленными с нулевой задержкой; строка `statistics` итогового документа называет их «right-censored» (цензурированными справа).

### differences

Для каждой политики, кроме `reference` (в коде написано): для каждого ключа `FIELDS` и каждого `item` из `matched`: `left = item[policy]["values"][key]`, `right = item[reference]["values"][key]`; значение разности `left - right`, если оба не `None`, иначе `None`. Далее `describe(values)`. Итог: `differences[policy][key]` — статистика парных разностей «политика минус эталон» по сценариям группы; пары с `None` исключаются, их число видно в `n_null`.

Ручной расчёт: у политики P `failure_fraction` по двум сценариям 0.25 и 0.75, у эталона R: 0.5 и 0.5. Разности: −0.25 и +0.25; mean = 0.0; дисперсия = (0.0625 + 0.0625) / (2 − 1) = 0.125; SD = √0.125 ≈ 0.35355; SE = SD / √2 = 0.25.

Если `matched` пуст: `describe([])` даёт `n_total = 0`, `n_nonnull = 0`, `n_null = 0`, остальное `None`; суммы в `pooled_packet_and_call` равны 0 (сумма пустого списка), а производные `None`. Нулевые значения вместо `None` не подставляются. Если `reference` отсутствует в элементе `matched` при `policy != reference`, возникнет `KeyError` (вывод из чтения; в `aggregate_plan` для обычных планов эталон входит в `body["policies"]`, и сопоставленные элементы содержат все политики).

Рандомизации и побочных эффектов нет; входные структуры не изменяются.

## summarize_scoped_group(present, policies, reference)

Строка документации (в коде написано): для планов, где у сценариев есть поле `policies` (`policy_scope`); для планов без него функция «NEVER used». Сопоставление идёт по каждой политике отдельно.

Аргументы: `present` — список словарей, по одному на сценарий группы, `{policy: проверенная запись}`; в нём присутствуют только заявленные и проверенные ячейки (незаявленные или непроверенные политики отсутствуют). `policies`, `reference` — как выше.

Возврат: `(results, differences)`. Для каждой политики:

- `own = [item for item in present if policy in item]`; `results[policy] = summarize_group(own, [policy], policy)[0][policy]`. Передача `reference = policy` отключает расчёт разностей внутри этого вызова. Оценки политики строятся по сценариям, где она проверена.
- Если `policy != reference`: `both = [item for item in own if reference in item]`; `differences[policy] = summarize_group(both, [policy], reference)[1][policy]`. Парные разности строятся только по сценариям, где проверены обе политики.

Арифметика — та же, что в `summarize_group`, применённая к полным подспискам. Политика без единой проверенной ячейки получает `n_total = 0` и пустые оценки (`None`), не нули (строка документации). Вывод из чтения: для политики-эталона разности не формируются; вызов `summarize_group(both, ...)` попутно вычисляет и блок `results`, который отбрасывается.

## native_completion_marker(plan)

Назначение: прочитать и проверить файл `execution_complete.json` нативного плана. Возврат: пара `(finished, marker)`.

В коде написано:

1. `path = Path(plan["body"]["root"]) / "execution_complete.json"`. Если файла нет, возврат `(False, None)`.
2. `marker = read(path)`. Эталонный словарь из 7 ключей: `schema = "ssn-native-experiment-transport-complete-v1"`, `transport_finished = True`, `runs = len(plan["body"]["cells"])`, `plan_sha256 = plan["sha256"]`, `aggregation_supported = False`, `plots_supported = False`, `scope = "all planned child artifacts transported; scientific verification/aggregation NOT performed"` (ручной расчёт: 7 ключей). Те же ключи и значения записываются `execute_suite` в `experiments.py` для нативных планов (вывод из сопоставления текстов).
3. `marker` должен быть словарём с полем `transport_finished` ровно типа `bool`: иначе `ValueError("native transport completion marker malformed")`.
4. Флаг из файла подставляется в эталон (комментарий кода: явный `false` означает неполноту, а не успех); остальные поля должны совпасть: `content_hash(marker) == content_hash(expected)`, иначе `ValueError("native transport completion marker differs from plan/scope")`.
5. Возврат `(marker["transport_finished"], marker)`.

Вывод: маркер подтверждает только транспорт (завершение всех дочерних запусков), а не научную проверку; научную проверку делает `_verify_cell`.

## scoped_declarations(body, scenarios)

Аргументы: `body` — тело плана; `scenarios` — словарь `{id сценария: сценарий}`. Возврат: `None` (ни у одного сценария нет ключа `policies`; поведение обычного плана, ничего не проверяется) либо словарь `{id сценария: список заявленных политик}`.

В коде написано:

1. Если ключ `policies` есть у части сценариев: `ValueError("mixed scoped/unscoped scenarios in plan")` (план «всё или ничего»).
2. Для каждого сценария список должен быть непустым списком строк без повторов, каждая из которых входит в `body["policies"]`: иначе `ValueError("invalid scenario policy declaration")`. Канонический порядок политик здесь не проверяется (он проверяется в `experiment_io.py`, `check_scoped_plan`; вывод из чтения).
3. Пары `(cell["scenario"], cell["policy"])` по `body["cells"]` должны совпадать как множества с парами `(id, политика)` из заявленных списков, и их число должно совпасть (обнаруживает повторы): иначе `ValueError("plan cells differ from declared scenario policies")`. Причина дублирования проверки — в строке документации: прямые вызывающие `aggregate_plan` пропускают `validate_plan`.

Побочных эффектов нет.
