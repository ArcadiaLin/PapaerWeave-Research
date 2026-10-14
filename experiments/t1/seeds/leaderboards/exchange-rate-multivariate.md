---
type: Leaderboard
title: Exchange-Rate multivariate long-term forecasting
abs: >-
  MSE and MAE reported on Exchange-Rate in the multivariate setting, by method, paper, look-back and horizon, with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0010    # Exchange-Rate
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 96 | 0.061 | 0.188 | paper_0002::4.2 Results and Analyses::273 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 192 | 0.106 | 0.244 | paper_0002::4.2 Results and Analyses::274 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 336 | 0.181 | 0.323 | paper_0002::4.2 Results and Analyses::275 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 720 | 0.525 | 0.571 | paper_0002::4.2 Results and Analyses::276 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.197 | 0.323 | paper_0002::4.2 Results and Analyses::273 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.300 | 0.369 | paper_0002::4.2 Results and Analyses::274 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.509 | 0.524 | paper_0002::4.2 Results and Analyses::275 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 1.447 | 0.941 | paper_0002::4.2 Results and Analyses::276 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 96 | 1.748 | 1.105 | paper_0002::4.2 Results and Analyses::273 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 192 | 1.874 | 1.151 | paper_0002::4.2 Results and Analyses::274 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 336 | 1.943 | 1.172 | paper_0002::4.2 Results and Analyses::275 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 720 | 2.085 | 1.206 | paper_0002::4.2 Results and Analyses::276 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.847 | 0.752 | paper_0002::4.2 Results and Analyses::273 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 1.204 | 0.895 | paper_0002::4.2 Results and Analyses::274 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 1.672 | 1.036 | paper_0002::4.2 Results and Analyses::275 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 2.478 | 2.478 | paper_0002::4.2 Results and Analyses::276 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.559 | 0.587 | paper_0002::4.2 Results and Analyses::273 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 1.168 | 0.835 | paper_0002::4.2 Results and Analyses::274 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 1.423 | 0.949 | paper_0002::4.2 Results and Analyses::275 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 2.160 | 1.150 | paper_0002::4.2 Results and Analyses::276 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.968 | 0.812 | paper_0002::4.2 Results and Analyses::273 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 192 | 1.040 | 0.851 | paper_0002::4.2 Results and Analyses::274 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 336 | 1.659 | 1.081 | paper_0002::4.2 Results and Analyses::275 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 720 | 1.941 | 1.127 | paper_0002::4.2 Results and Analyses::276 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 1.065 | 0.829 | paper_0002::4.2 Results and Analyses::273 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 1.188 | 0.906 | paper_0002::4.2 Results and Analyses::274 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 1.357 | 0.976 | paper_0002::4.2 Results and Analyses::275 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 1.510 | 1.016 | paper_0002::4.2 Results and Analyses::276 |

## Notes

- SCINet's long-term table does not state the look-back window, and only Pyraformer is marked as re-implemented
  [paper_0002::4.2 Results and Analyses::287]; the source of the other baseline values is not stated, so their origin
  is left empty.
- SCINet prints the same number for Informer's MSE and MAE at horizon 720 (2.478)
  [paper_0002::4.2 Results and Analyses::276].

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0002 SCINet | Table 3 (paper_0002::4.2 Results and Analyses::269:284) | yes |
