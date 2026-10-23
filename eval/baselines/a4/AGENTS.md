# Shared memory

This Graphiti memory is shared by many sessions, and later readers were not there when things were written. This file says what contributions should contain.

## Sources

Papers and code are sources with fixed ids: a paper with its version, like `2205.13504v2`; a code repository at a commit, like `Autoformer@09994619`. Fetch them with read_source; they arrive under `/work/sources/` (`sources/2205.13504v2/paper.md`, `sources/Autoformer@09994619/<files>`).

Record the source ID for claims and results. You may add a file path or line range to identify the supporting passage:

- `<source_id>`
- `<source_id>::<start>:<end>`: lines of a paper's `paper.md`
- `<repo>@<commit>::<file>`
- `<repo>@<commit>::<file>::<start>:<end>`

Write them in the memory text, like `[2205.13504v2::120:135]` or `[2205.13504v2]`. A source id names one fixed version, so a reference stays on the text it was written against.

## Papers

- A paper: its name, external identities (like `arxiv:2205.13504`, without the version), year, and the versions read, by source id. A code repository: its source id (the repository at its commit).
- An experiment group: the tables and figures it covers, main one first (like S4.T3); the methods compared, each as the paper's target or a baseline, and whether the authors ran it or copied the result from another paper; the data it uses, with the name as printed in the paper (like ECL); the task.
- Claims and contributions: in your own words, readable on their own, each with its source.
- Something only mentioned, not yet described: the name is enough; add identities if known, so others find it.

## Artifacts

### Leaderboard

One table per dataset, setting and task, with its metrics and whether lower or higher is better (like MSE: lower, MAE: lower).

One row per (method, variant, paper, lookback, pred_len). role is target or baseline; origin is run (the paper ran it) or cited (copied from another paper); source is where the numbers are: the paper's source id, optionally with lines, like 2205.13504v2::120:135.

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <method> |  | <paper short name> | target | run | 336 | 96 | 0.370 | 0.400 | <source id>::<start>:<end> |

Papers covered: every paper in the memory with experiments on this dataset, the tables taken, or why it is left out.

| paper | tables | complete |
| --- | --- | --- |
| <paper short name> | Table 3 (<source id>::<start>:<end>) | yes |

### CompareSettings

Whether two results are comparable (two leaderboard rows, or two experiments), and why: a verdict (T: comparable, F: not comparable, U: cannot tell) and, when two papers report the same cell, the relation (same_source, independent, incomparable or unknown).

One row per dimension. same is T, F or U; for T and F, basis cites where each side states it, in square brackets ([<source id>::<start>:<end>]); for U, basis says what is missing.

| dimension | left | right | same | basis |
| --- | --- | --- | --- | --- |
| lookback | 336 | 96 | F | [<source id>::<start>:<end>] [<source id>::<start>:<end>] |
| split |  |  | U | <what is missing> |
| normalization |  |  | U |  |
| training_data |  |  | U |  |
| protocol |  |  | U |  |

### Verify

The claim; a verdict (T: holds, F: does not hold, U: undecided); the scope where it holds (like multivariate ETT benchmarks at horizons 96-720); your reasoning, citing what each statement rests on in brackets: a source [2205.13504v2::120:135], or a record or table in the memory.

### Summarize

One paragraph per point. Every paragraph cites what it summarizes in brackets: a source [2205.13504v2::120:135], or a record or table in the memory. Keep different settings apart; do not merge them into one number.

### Note

Your findings and conclusions, written for a later reader who was not here. Cite what each statement rests on in brackets: a source [2205.13504v2::120:135], or a record or table in the memory. Say where something comes from outside the memory (a file you read, a code repository), and mark your own judgments as yours.
