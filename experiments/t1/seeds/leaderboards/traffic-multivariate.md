---
type: Leaderboard
title: Traffic multivariate long-term forecasting
abs: >-
  MSE and MAE reported on Traffic in the multivariate setting, by method, paper, look-back and horizon, with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0007    # Traffic
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 96 | 0.613 | 0.395 | paper_0002::4.2 Results and Analyses::281 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 192 | 0.535 | 0.355 | paper_0002::4.2 Results and Analyses::282 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 336 | 0.540 | 0.359 | paper_0002::4.2 Results and Analyses::283 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 720 | 0.620 | 0.394 | paper_0002::4.2 Results and Analyses::284 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.613 | 0.388 | paper_0002::4.2 Results and Analyses::281 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.616 | 0.382 | paper_0002::4.2 Results and Analyses::282 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.622 | 0.337 | paper_0002::4.2 Results and Analyses::283 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.660 | 0.408 | paper_0002::4.2 Results and Analyses::284 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 96 | 0.867 | 0.468 | paper_0002::4.2 Results and Analyses::281 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 192 | 0.869 | 0.467 | paper_0002::4.2 Results and Analyses::282 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 336 | 0.881 | 0.469 | paper_0002::4.2 Results and Analyses::283 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 720 | 0.896 | 0.473 | paper_0002::4.2 Results and Analyses::284 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.719 | 0.391 | paper_0002::4.2 Results and Analyses::281 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.696 | 0.379 | paper_0002::4.2 Results and Analyses::282 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.777 | 0.420 | paper_0002::4.2 Results and Analyses::283 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.864 | 0.472 | paper_0002::4.2 Results and Analyses::284 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.638 | 0.354 | paper_0002::4.2 Results and Analyses::281 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.647 | 0.354 | paper_0002::4.2 Results and Analyses::282 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.669 | 0.364 | paper_0002::4.2 Results and Analyses::283 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.707 | 0.386 | paper_0002::4.2 Results and Analyses::284 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.684 | 0.384 | paper_0002::4.2 Results and Analyses::281 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.685 | 0.390 | paper_0002::4.2 Results and Analyses::282 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.733 | 0.408 | paper_0002::4.2 Results and Analyses::283 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.717 | 0.396 | paper_0002::4.2 Results and Analyses::284 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.732 | 0.423 | paper_0002::4.2 Results and Analyses::281 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.733 | 0.420 | paper_0002::4.2 Results and Analyses::282 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.742 | 0.420 | paper_0002::4.2 Results and Analyses::283 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.755 | 0.423 | paper_0002::4.2 Results and Analyses::284 |

## Notes

- SCINet's long-term table does not state the look-back window, and only Pyraformer is marked as re-implemented
  [paper_0002::4.2 Results and Analyses::287]; the source of the other baseline values is not stated, so their origin
  is left empty.

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0002 SCINet | Table 3 (paper_0002::4.2 Results and Analyses::269:284) | yes |
