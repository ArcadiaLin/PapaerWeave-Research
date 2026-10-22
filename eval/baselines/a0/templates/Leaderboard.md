---
type: Leaderboard
title: <dataset> <setting> <task>
abs: <one sentence on what the table holds>
task: <task id>                   # <task name>
dataset: <dataset id>             # <dataset name>
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

One row per (method, variant, paper, lookback, pred_len). method and paper cells start with the id; role is
target or baseline; origin is run (the paper ran it) or cited (copied from another paper); source is where the
numbers are: the paper's source id, optionally with lines, like 2205.13504v2::120:135.

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <method id> <name> |  | <paper id> <short name> | target | run | 336 | 96 | 0.370 | 0.400 | <source id>::<start>:<end> |

## Papers covered

Every paper in the store with experiments on this dataset: the tables taken, or why it is left out.

| paper | tables | complete |
| --- | --- | --- |
| <paper id> <short name> | Table 3 (<source id>::<start>:<end>) | yes |
