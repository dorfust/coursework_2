# REPORT_T160 — independent static review of the 2026-11-14 run-status sentences

- Reviewer: Repo_Review_2 (independent verification role; same-model review is role separation, not empirical verification).
- Task / attempt / step: T160 / A01 / S28.
- Repository binding: `dorfust` / `coursework_2`, branch `main`, head commit `e1fa354729cfe9a20d281abf3fd0612032205053` (commit date 2026-11-14T06:05:44Z).
- Requirement revision reviewed: the user's S28 instruction in this invocation (17-file sentence review, checks A–D, non-goals). No separate task-contract file was available in the bound repository; see L01.
- Method: static reading of the delivered bytes at the head commit. Nothing executed, no run, no parser, no test, no network claim. No claim in this report rests on execution.

## 1. Target revisions (all 17 confirmed against a directory listing before reading)

All blob SHAs reported by the user match the listing exactly; no difference to report.

| Path | Blob (prefix) | Size reported | Size in listing |
|---|---|---|---|
| README.md | 484a7e0d | 25794 | 25794 |
| START_HERE_RU.md | 0f797a38 | 19705 | 19705 |
| docs/STATUS_INDEX_RU.md | 874569f0 | 20991 | 20991 |
| docs/08_VSCODE_SETUP_RU.md | b9bb7c8d | 14383 | 14383 |
| docs/06_CONFIGS_SUITES_RU.md | 4663ba7a | 40100 | 40100 |
| docs/ERRATA_RU_part6.md | b47bb9c7 | 32528 | 32528 |
| docs/10_ALGORITHMS_RU.md | c15c2afc | 14003 | 14003 |
| docs/10_ALGORITHMS_RU_partA.md | 6f9987c2 | 16719 | 16719 |
| docs/10_ALGORITHMS_RU_partB.md | 66e07321 | 14639 | 14639 |
| docs/10_ALGORITHMS_RU_partC.md | b04b89d0 | 12968 | 12968 |
| docs/11_START_AND_PLOTS_RU.md | b385c222 | not stated | 12736 |
| docs/11_START_AND_PLOTS_RU_partA.md | f2add5c0 | not stated | 19834 |
| docs/11_START_AND_PLOTS_RU_partB.md | c609da10 | not stated | 17422 |
| docs/11_START_AND_PLOTS_RU_partC.md | f13bb22c | not stated | 16772 |
| docs/11_START_AND_PLOTS_RU_partD.md | 01269cc2 | 17876 | 17876 |
| docs/11_START_AND_PLOTS_RU_partD2.md | e5d05fe7 | 15225 | 15225 |
| docs/11_START_AND_PLOTS_RU_partE.md | c884beff | 18341 | 18341 |

## 2. What was established for this review (only permitted facts)

2026-11-14, user's own computer, delivered tree: SHORT end-to-end run (`start_quick.py`, `suite_quick`, 3 epochs, N = 132; its numbers are NOT results) ended with exit code 0; `probes/tbr_enum/check_tbr_enum.py` printed PASS with 2000 compared, 0 skipped. No log uploaded or held; the probe's exit code was never reported. Anything beyond this (that something WORKS or is scientifically valid, a FULL run on the user's computer, a probe exit code, a duration, a result number) must not appear.

## 3. Static conclusion per dimension

- Requirements coverage: all 17 named files carry at least one status sentence about the 2026-11-14 events, and all 17 were read in full. Coverage of the named scope is complete.
- Claim truth (check A): the overwhelming majority of the new sentences are accurate and correctly hedged. Overstatement risk did NOT materialise: no file promotes the run to evidence of working software, and every file that mentions the run repeats that its numbers are not results (README §§2,10,14; START_HERE_RU status bullets 1–2; STATUS_INDEX §2; docs/08 status; docs/10 index + A + B + C; docs/11 partA/partB/partC/partD/partD2; docs/06 status; ERRATA_RU_part6 status). One overstatement found (F05), one class of understatement found in five files (F01).
- Internal consistency (check B): date, scope of the short run, absence of a full run on the user's computer and absence of a log are stated consistently in substance; there is no conflicting date and no conflicting claim that a full run happened on the user's machine. Disagreements are in construction/qualification, not in the core fact: F01, F06, F07, F10, and one substantive conflict about `check_comment_only.py` (F03).
- Boundary survival (check C): "no agent executed anything", "journals and results unavailable", "probe not executed by its author", "runner series belongs to the tree before the later edits", and every "What PASS does NOT prove" list survive intact. One boundary item is contradicted from inside the set (F03); one is weakened by missing qualification (F06).
- Forbidden content / verbatim block / mechanical safety (check D): the `docs/06` block is intact and unchanged by its edit, but two additional files now also quote it verbatim (F02); a rule ID appears in delivered text (F04). Two diffs were taken and both show exactly one replaced sentence (mechanical safety good where measurable); for the other files only indirect evidence is available (L03).
- Static syntax/runtime/numerical validation: not applicable and not performed. This review makes no statement about whether the software works.

## 4. Findings — confirmed defects

### F01 — MAJOR — residual "at the time of writing it had not been run" denial, in five files, contradicting the same sentence's own second half

Affected paths and anchors (verbatim):

- `docs/10_ALGORITHMS_RU.md` (index, status paragraph after the intro): "О состоянии проекта: ревизия 5 на компьютере в момент написания не запускалась; по сообщению пользователя от 2026-11-14 на его компьютере прошёл только короткий сквозной прогон (его числа — не результаты), полного прогона на его компьютере нет…"
- `docs/10_ALGORITHMS_RU_partA.md` (header), `_partB.md` (header), `_partC.md` (header): the same sentence, identical wording.
- `docs/11_START_AND_PLOTS_RU_partB.md` (header): "ревизия 5 подготовлена, проверена чтением; в момент написания на компьютере её никто не запускал; по сообщению от 2026-11-14 на нём прошёл только короткий прогон (`--quick`, 3 эпохи, N = 132; его числа — не результаты)".

Why it matters: the sentence cites a report dated 2026-11-14, so it was written after that report; at the moment of writing, revision 5 HAD been run (short). As printed, the leading absolute denial ("не запускалась" / "не запускал никто") contradicts the second half of the same sentence. That is precisely the understatement failure mode S28 exists to remove: a reader who stops at the denial concludes nothing has ever run. Five other files already use the correct, time-resolved construction, so the fix is proven inside the same delivered set: `docs/11 partE` ("в момент написания она не запускалась, **а с тех пор** по сообщению… прошёл только короткий сквозной прогон"), `docs/11 partD` ("…не запускал никто, **а** по сообщению пользователя от 2026-11-14…"), `docs/11 partD2` (same "а" construction), `docs/06` ("Редакцию 5 на вашем компьютере **до 2026-11-14** никто не запускал; по сообщению… прошёл…"), `ERRATA_RU_part6` ("Редакцию 5 … **до 2026-11-14** не запускал никто; по сообщению…").

Recommended correction: in the five files, replace the absolute denial with the `docs/06`/`ERRATA_RU_part6` form ("до 2026-11-14 … никто не запускал") or the `partE` form ("а с тех пор"). Do not add anything else; no exit code, no duration, no number is needed.

Evidence needed to close: re-read the five headers at the new revision and confirm the denial is time-bounded.

### F02 — MAJOR — the mandatory run block is now quoted verbatim in three files, not two

Anchors: (1) `docs/06_CONFIGS_SUITES_RU.md`, "**Обязательная формулировка о прогонах** (закреплённая запись фактов, раздел B, как есть): «По сообщению пользователя, режимы checks, smoke и full …»"; (2) `docs/STATUS_INDEX_RU.md` §2, the same text inside «…» — 438-character body, character-for-character the same as (1) as far as static comparison of the two passages can establish; (3) `docs/ERRATA_RU_part6.md`, "**Обязательная формулировка о запусках на GitHub** (приводится один раз на весь файл, как есть): «По сообщению пользователя, режимы checks, smoke и full …»" — again the same text.

Why it matters: the rule under review allows this block VERBATIM in exactly two files (`docs/05 …partE` section G and `docs/06`). Two additional verbatim copies exist in delivered text. The files also disagree about the count themselves: `STATUS_INDEX_RU.md` §2 says the formulation "приведена здесь один раз; `docs/05_EXPERIMENTS_RU_partE.md` (раздел G) и `docs/06_CONFIGS_SUITES_RU.md` … повторяют её дословно" (i.e. three locations counting itself), while `ERRATA_RU_part6.md` scopes its copy as "один раз на весь файл". `docs/06`'s own copy is intact: the S130 diff shows only the sentence after the closing «» replaced, the quotation lines themselves untouched (same context lines in the patch).

Recommended correction: decide one canonical holder and reduce the other copies to a pointer, or extend the rule deliberately. Both sides are recorded here; the reviewer does not decide which file is right.

Evidence to close: a listing/grep-equivalent check on the final revision showing the block in exactly the permitted files.

### F03 — MAJOR — `check_comment_only.py`: "never run by anyone" vs "passed in the GitHub checks mode"

Two sides, both in delivered text:

- Side 1 (never run): `docs/11 partE` §Статус — "**На момент написания ни один из двух скриптов этой части не запускал никто.** … второй (`check_comment_only.py`) не запускал никто"; `docs/11 partE` §3 — "второй скрипт не запускал никто"; `START_HERE_RU.md` §6 — "второй (`check_comment_only.py`) на вашем ПК не запускался".
- Side 2 (it did run): `START_HERE_RU.md` §6, first sentence — "По сообщению пользователя, сравнение 20 модулей скриптом «только комментарии» прошло в режиме checks на GitHub (журналов у авторов нет)".

Why it matters: this is one of the check-C items that had to survive. As written, one file says the script ran (in the checks mode) and another says nobody ever ran it; the two cannot both hold as printed. The likely intended split — ran in the GitHub checks mode, never on the user's PC — is not what the sentences say.

Recommended correction: scope both sides explicitly ("на компьютере пользователя не запускался никто; в режиме checks рабочего процесса, по сообщению пользователя, сравнение прошло — журналов у авторов нет").

Attribution caveat: whether this START_HERE clause is new in S28 could not be established (no diff taken for this file).

### F04 — MAJOR — rule ID in delivered text (D-DOC-4)

Anchor: `docs/ERRATA_RU_part6.md`, section L-G04, first line: "Отбор для этой группы задан правилом **D-DOC-3**, и оно распространено на весь файл…".

Why it matters: D-DOC-4 forbids rule IDs in delivered text; a rule ID is printed in a file the user reads.

Attribution: the S130 diff of this file proves the line predates this step (single replaced status sentence; this paragraph is context). It is therefore not an S28 regression, but it is a live breach of the rule restated in S28 and blocks final acceptance of the set until the rule owner decides.

Recommended correction: replace with a neutral phrase ("правилом отбора для этой группы") and keep the behaviour described.

## 5. Findings — minor

### F05 — MINOR — unestablished run parameters presented as fact
`docs/11 partE` §1: "По сообщению пользователя, запуск 2026-11-14 **с параметрами по умолчанию (`--seed` 12345)** напечатал `2000 compared, 0 skipped`". Only the output was reported; the command line and seed were not. Correction: "при сообщённом выводе `2000 compared` — число случаев по умолчанию (`--cases` 2000); ключ и seed не сообщались".

### F06 — MINOR — unqualified "полного прогона нет" vs the qualified forms elsewhere
Side 1 (unqualified): `docs/11 partE` §Статус ("полного прогона нет") and §3 ("Полного прогона у него нет"); `docs/ERRATA_RU_part6.md` status ("полного прогона нет"); `docs/11 partD` header ("полного прогона нет"); `docs/11 partB` header ("полного прогона нет").
Side 2 (qualified): `README.md` §14 ("на дереве после этих правок полного прогона нет", plus the runner series on the earlier tree); `docs/06` ("полного прогона **на Windows** не было"); `docs/10 index/A/B/C` ("полного прогона **на его компьютере** нет"); `docs/11 partA/partC` (same scoping). Read alone, side 1 can be taken as "no full run exists anywhere", which contradicts the runner series the same files report. Correction: qualify as "на дереве после правок / на компьютере пользователя".

### F07 — MINOR — two "first start" claims in one file
`START_HERE_RU.md` status bullet 1: "первый старт на вашем компьютере состоялся, но только в КОРОТКОМ объёме…" against bullet 2 of the same file: "**До 2026-11-14** единственный запуск на вашем Windows — редакция 3a…". Correction: "первый старт редакции 5".

### F08 — MINOR — stale byte sizes in `docs/11` index §2 (mechanical by-product of the 17-file edit)
The table says the sizes are "по ответам записи файлов"; six are now smaller than the bytes on disk: partA 19402→19834, partB 17115→17422, partC 16331→16772, partD 17552→17876, partD2 14895→15225, partE 16816→18341. Correction: update or drop the size column (it will go stale again).

### F09 — MINOR — self-referential repository claim contradicted by the repository it is read from
`docs/ERRATA_RU_part6.md`, "Перенос в другой репозиторий": "В `dorfust/coursework_2` из редакций 4 и 5 не перенесено ничего: … корневое дерево того репозитория равно выгрузке редакции 3b". The reviewer read that very repository at `main`: its root carries revision-5 material (`start.py`, `start_quick.py`, `docs/10*`, `docs/11*`, this ERRATA file). Attribution: diff shows the paragraph is context, unchanged by S130. Correction: state the claim conditionally or point at the tree that was actually meant.

### F10 — MINOR — scope ambiguity of "no log held" next to the 3a run
`docs/08_VSCODE_SETUP_RU.md` status: "…известен также запуск редакции 3a (старый объём); полного прогона на его компьютере не было, журнала у авторов этого текста нет". The clause follows the 3a mention, while `README.md` §10 quotes the 3a run "по журналу пользователя". Correction: "журнала этого прогона (2026-11-14) у авторов нет".

## 6. Notes (non-blocking observations)

- N01 — Stale marker: `docs/06` §8 lists `docs/STATUS_INDEX_RU.md` as "(планируется)" although it is delivered; `STATUS_INDEX_RU.md` §3.2 records that defect only for `README.md` §§8,12.
- N02 — Internal-record references in delivered text (reader cannot access them): "закреплённая запись фактов, раздел B" and "по разделу C той же записи фактов" (`docs/06`), "записях шага", "файл фактов, раздел 2" (`ERRATA_RU_part6` L-G04), "запись исследования", "файл внутренних записей" (`docs/11 partD2`), "запись проверки" (`docs/11 partC`). `docs/11` index §6 already discloses this class. Classify against D-DOC-4's "journal or manifest names" wording before acting; not counted as an S28 defect.
- N03 — Generic agent references in delivered text: "агенты рисунка не видели" (`README.md` §7), "второй прочитывающей стороной той же модели, то есть не независимой проверкой" (`docs/11` index §1). No agent or role names; disclosures, not names.
- N04 — Task/step IDs (`T159c`, `T159d S130`) appear in the commit messages of the delivered repository. That is repository metadata, not delivered document text; flagged for the orchestrator's awareness only.
- N05 — `README.md` §13 records that the user ran the probe but omits the PASS / 2000 compared result that five other files state. Omission, not contradiction.
- N06 — Script exit-code documentation ("`PASS` … код 0", "PASS (код 0) / FAIL (1)") sits near the new sentences in `START_HERE_RU.md` §6, `docs/11 partE` §1 and `docs/10` index §7. No observed exit code is claimed anywhere in the set — compliant with the constraint; the `[К]`/"в коде написано" markers should not be dropped when these are next touched.

## 7. The two specific pair checks the user asked for

- `docs/11_START_AND_PLOTS_RU_partE.md`, first paragraph vs its own §1 and §3: no longer self-contradictory. §Статус resolves the timeline explicitly ("в момент написания … не запускалась, **а с тех пор** … прошёл только короткий сквозной прогон"; "На момент написания … не запускал никто" then "По сообщению … запускался … и напечатал `PASS`"). §1 adds the `2000 compared, 0 skipped` detail consistently; §3 ("Первый скрипт запускался один раз … и напечатал `PASS`") agrees. One caveat of substance, F05, is inside §1. Result: PASS on that specific check.
- `docs/10_ALGORITHMS_RU.md` index vs parts A, B, C: the same sentence **was** replaced in all four, and the four copies are word-identical (verified by reading all four). Consistency of the four is satisfied; the sentence itself is F01.

## 8. Check-C boundary result

Preserved: no agent executed anything (README §2 "Авторы текста ничего не запускали"; STATUS_INDEX §1; `docs/06` status; `docs/10 partA` "Ничего не запускалось автором описания — метка метода"; `docs/11 partD2` "Скрипт ни разу не рисовал"); journals/results unavailable to the authors (all 17 files); probe not executed by its author (`docs/10` index §7, `docs/10 partC` §9, `docs/11 partE`); runner series belongs to the pre-edit tree (README §§2,14; STATUS_INDEX §2; `docs/06` §6 with commit `780fd332`; `docs/11 partA/B/C/D`); all "What PASS does NOT prove" lists intact (`START_HERE_RU` §6 both lists, `docs/11 partE` both lists, `docs/10` index §7). Weakened or contradicted: "no FULL-scope run anywhere" now exists in an unqualified form in four files (F06) and `check_comment_only.py`'s never-run boundary is contradicted (F03).

## 9. Check-D result

- `docs/06` block intact and byte-stable across its edit (diff: one sentence after the quotation changed; quotation lines are context).
- Additional verbatim copies: `STATUS_INDEX_RU.md` §2 and `ERRATA_RU_part6.md` (F02).
- No file paraphrases the block in a way that reads as a quotation beyond those copies.
- Forbidden content: one rule ID (F04); internal-record references and generic agent references listed as notes.
- Passages rewritten beyond their subject: none found where a diff was available (`docs/06`, `ERRATA_RU_part6` — one sentence each). For the six `docs/11` parts the byte growth recorded in `docs/11` index §2 against the current listing (+307…+1525 bytes) is consistent with sentence-scale edits, not rewrites; for the other nine files no size baseline exists, so collateral edits there cannot be excluded statically.

## 10. Verdict

REVISE.

- Blocking: 0. Major: 4 (F01–F04). Minor: 6 (F05–F10). Note: 6 (N01–N06).
- Static review conclusion: the new sentences are factually sound in substance and correctly refuse to claim that anything works; the residual defects are one understatement pattern (F01), one verbatim-block overrun (F02), one internal contradiction about a check (F03), and one forbidden rule ID (F04).
- Proof / numerical / runtime conclusions: not applicable, none performed, none claimed by this review. This review does not establish that any part of the software works.
- Scope of the verdict: the 17 files listed in §1 at commit `e1fa354`. It does not cover the code, the suites, `docs/10` C2–E2, the probe script, or `docs/05 partE`.

## 11. Limitations

- L01 — No task contract, global checkpoint, owner checkpoint, prior reviewer checkpoint or review task file was present in `dorfust/coursework_2` at `main`: `Repo_Review_2/` did not exist before this write, and neither did any other `Repo_*` agent directory at repository root. Reviewer state could therefore not be reconciled with an owner's submission, and the requirement revision reviewed is the user's instruction in this invocation only. The orchestrator should confirm the workspace location (see §12).
- L02 — Static reading only. No execution, no parser, no test, no proof assistant. Byte-identity of quoted blocks in three files is established by reading the three passages; a mechanical comparison was not run.
- L03 — Diffs were taken only for the two most recent commits (`a78fb94`, `e1fa354`). For the other 15 files, neither the exact inserted sentences nor collateral-edit freedom is proven.
- L04 — `docs/05_EXPERIMENTS_RU_partE.md` (the second permitted holder of the block, section G) was not read: it is a declared non-goal. Byte-identity of `docs/06`'s block is therefore asserted against itself and the two third copies, not against `docs/05 partE`.
- L05 — Read in full: all 17 files. Not read: `docs/05 partE`, `docs/10` parts C2, D, D2, E, E2, the probe scripts, all code, all configs, `docs/01–07`, `docs/09`, other ERRATA parts.
- L06 — No user log exists; the user's report is the only execution evidence and it is accepted only within its demonstrated scope (revision, command not reported, exit code only for the short run).

## 12. Required next action

1. Owner of the delivered texts corrects F01–F03 and (with the rule owner) F04; F05–F10 optional but cheap.
2. Orchestrator confirms where agent directories belong: this report is written inside the delivered repository, whose root the user reads. If the review workspace is meant to live elsewhere, these three files must be relocated and excluded from the shipped tree.
3. Re-review after correction: re-read the five headers in F01, the three block holders in F02, the `START_HERE_RU` §6 / `docs/11 partE` pair in F03, and the ERRATA L-G04 line in F04, at a new immutable revision.
