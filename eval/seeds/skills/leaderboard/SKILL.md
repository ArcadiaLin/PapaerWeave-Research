---
name: leaderboard
description: How to find, read, add to and create a shared Leaderboard, the results table for one task, dataset and setting across papers. Use it when you need results (MSE, MAE, ...) of methods on a dataset, or when a paper you read reports such results.
metadata:
  type: Skill
---
# Leaderboard

A Leaderboard is a shared Markdown document in the store: one results table for one (task, dataset, setting), such as
"ETTh1, long-term forecasting, multivariate", across papers and horizons. Every number in it carries the paper lines
it came from. Other sessions read and edit the same document; the store keeps every version and who wrote each row.

## 1. Find the one that exists

There is at most one Leaderboard per (task, dataset, setting). Before creating one, look for it:

1. Turn names into ids with `Resolve` (the task, the dataset).
2. `Search` with `type: Artifact` and `where: {key: {type: Leaderboard, task: <task id>, dataset: <dataset id>, setting: {variate: multivariate}}}`.
   Or list them: `where: {op: Leaderboard, used: <dataset id>}`.
3. After a `Commit`, `related_artifacts` lists the Leaderboards on the datasets of the Experiments you wrote, and the
   datasets that have none yet.

If one exists, check it out with `FetchArtifact` (it goes to `artifacts/<title>.md`) and edit that file. If you create
a second one with the same task, dataset and setting, `CheckIn` rejects it and gives the id of the existing one.

Look at how the existing rows are written before adding yours, and write yours the same way.

## 2. The document

```markdown
---
type: Leaderboard
title: ETTh1 multivariate long-term forecasting
abs: >-
  MSE and MAE reported on ETTh1 in the multivariate setting, by method, paper, look-back and horizon,
  with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0002    # ETTh1
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 24 | 0.577 | 0.549 | paper_0001::Datasets::269 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 48 | 24 | 0.300 | 0.342 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.577 | 0.549 | paper_0002::4.2 Results and Analyses::302:303 |

## Notes

- SCINet's values for Informer equal those in Informer's own table, but SCINet does not say where they come from,
  so origin is left empty [paper_0002::4.2 Results and Analyses::315].

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0001 Informer | Table 2 (paper_0001::Datasets::265:273) | yes |
```

**Header.** `title` and `abs` are the text that `Search` matches. `task` and `dataset` are ids (a name or comment may
follow); `setting` says which variant of the benchmark this is. `metrics` lists the metric columns and whether lower or
higher is better.

**Results table.** One row per (method, variant, paper, pred_len, lookback); this is the row key, and two rows with the
same key are rejected.

| column | what to write |
| --- | --- |
| `method` | the method's id, then its name |
| `variant` | a variant or configuration the paper reports separately (e.g. `Informer†`); empty otherwise |
| `paper` | the paper whose table you read, not the paper that proposed the method |
| `role` | `target` for the method the paper proposes, `baseline` for the others |
| `origin` | `run` if the paper says it ran the method, `cited` if it says it copied the value; empty if it does not say |
| `lookback` | the input length as a number; if the paper gives no number per row, its own words (see §3) |
| `pred_len` | the forecasting horizon |
| metric columns | the number as printed, or empty |
| `source` | the paper lines that print this row: `<paper id>::<section heading>::<start>:<end>`; several refs separated by `;` |

The section heading and line numbers are the ones `ReadEvidence` shows for the paper.

**Notes** is free text. Put what a later reader needs to trust the rows there, with references in square brackets.

**Papers covered** lists the tables you transcribed from each paper and whether you took all their rows (`yes` or
`no`). It tells a reader the difference between "the paper did not report this cell" and "nobody transcribed it".

## 3. Judgments while writing rows

- **Copy, do not compute.** Write the number exactly as printed. Do not round it, convert units or average runs.
- **Read the table itself.** Use `ReadEvidence` on the table lines before writing numbers.
- **Look-back.** If the paper states the input length for each row, write the number. If it states a search range, a rule ("same as Informer") or nothing, write that ("searched in {24, 48, 96}", "same as Informer", "not stated"). Do not guess a number. A paper may state it in an appendix; cite that line too.
- **Origin.** Fill it only from what the paper says (e.g. "results are taken from", "we re-implement"). Matching numbers in two papers are not a statement; mention them in Notes instead.
- **Baselines in a paper's table** are rows of that paper, with `role: baseline`, even when the values are copied from another paper.
- **Different papers, same cell.** If two papers report different values for the same method and horizon, both rows stay. Do not merge them or pick one. The store reports such cells when the document is read.
- **Unreadable or misprinted cells.** Leave the cell empty and say why in Notes, citing the line.
- **Other variants of the benchmark.** A different setting (e.g. univariate) is a different Leaderboard. So is a different dataset that shares the name (check the dataset's description with `Traverse`).

## 4. Check in

1. Edit the file, then call `CheckIn` with `artifact_doc: [artifacts/<title>.md]` and an `update_abstract` saying what you added and from where. Without `confirm` it only checks.
2. Read the reply:
   - `errors` (status `rejected`): fix those lines and check again. A row without `source`, or with a source outside that row's paper, is an error.
   - `warnings`: the rows pass but may be wrong. "does not appear in the cited lines" means re-read the cited lines; usually a typo or the wrong line range. "is not a number; fine if the paper states it so" is expected for a look-back written in words.
   - `others`: lines you changed that someone else wrote. Change them only if the cited lines show they are wrong, and give `reason`.
3. Call again with `confirm: true` to write.

Counts and notes that the store computes when the document is read (rows by contributor, rows citing a paper that
has a newer version, cells with several values) are not part of the document. Do not write them into it.

## 5. Use it in an answer

Cite rows rather than retyping numbers from memory. A row is cited as `[<board id>#<row key>]`, where `<board id>` is the
Leaderboard's id (such as art_0002) and the row key joins method, variant, paper, pred_len and lookback with `+` (an
empty variant leaves `++`): `[<board id>#method_0012++paper_0002+24+48]`. Check the rows' `lookback`
and `paper` before comparing two numbers: values from different papers or look-backs may not be comparable.
