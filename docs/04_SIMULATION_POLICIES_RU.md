# 04. Симуляция и политики: индекс (simulator.py, policies.py, tbr_policy.py, tbr_reference.py, simulate.py)

## Состав и порядок чтения
1. `04_SIMULATION_POLICIES_RU_partA1.md` — `simulator.py`: объекты, состояние, операции, отмена передачи и повторы.
2. `04_SIMULATION_POLICIES_RU_partA2.md` — `simulator.py`: порядок тика, планирование, результаты, умолчания, связи.
3. `04_SIMULATION_POLICIES_RU_partA3.md` — `policies.py`: `HopOracle`, `GLR`, `SourceDijkstra`, `ContactRouting`.
4. `04_SIMULATION_POLICIES_RU_partB1.md` — `tbr_reference.py`, `tbr_policy.py`; раздел 0 различает три похожих имени.
5. `04_SIMULATION_POLICIES_RU_partB2.md` — `simulate.py`: команды `trace`, `run`, сборка прогона, предиктор GLR.

Порядок: A1, A2, A3, B1, B2.

## Соглашения
Метки «в коде написано», «вывод из чтения», «ручной расчёт» — как в частях. Ничего не запускалось: утверждений о работоспособности и результатах нет. Документы из строк кода, не входящие в экспорт, помечены как таковые.

## Зависимости между модулями набора (импорты по коду)
```
tbr_reference <- features
policies      <- config, features
simulator     <- policies (RoutingContext), contacts, sim_config, traffic
tbr_policy    <- policies (Decision), tbr_reference
simulate      <- simulator, policies, tbr_policy, tbr_reference,
                 config, contacts, provenance, sim_config, traffic
```

## Что не установлено чтением (заголовки пунктов)
- Кто импортирует `simulator.py` и `simulate.py`; где ещё используется `POLICY_NAMES`.
- Соответствие политик первоисточникам (заявлена независимая реконструкция).
- Эквивалентность кэшей прежним версиям (тесты не в экспорте).
- Точность предсказаний GLR (построение предиктора и смысл оценки разобраны в части B2).
- Допустимость `use_deterministic_algorithms(True)` для GLR на CPU.
- Доля поисков `TBR_bounded_exhaustive_reference`, укладывающихся в границы, на геометрических графах.
- Содержимое документов, названных в строках кода.
- Работоспособность всех модулей набора.
