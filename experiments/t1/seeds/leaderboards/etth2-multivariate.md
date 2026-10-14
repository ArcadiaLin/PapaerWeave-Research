---
type: Leaderboard
title: ETTh2 multivariate long-term forecasting
abs: >-
  MSE and MAE reported on ETTh2 in the multivariate setting (all seven variables predicted), by method, paper, look-back and horizon, with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0003    # ETTh2
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 24 | 0.720 | 0.665 | paper_0001::Datasets::274 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 48 | 1.457 | 1.001 | paper_0001::Datasets::275 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 168 | 3.489 | 1.515 | paper_0001::Datasets::276 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 336 | 2.723 | 1.340 | paper_0001::Datasets::277 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 720 | 3.467 | 1.473 | paper_0001::Datasets::278 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 24 | 0.753 | 0.727 | paper_0001::Datasets::274 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 48 | 1.461 | 1.077 | paper_0001::Datasets::275 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 168 | 3.485 | 1.612 | paper_0001::Datasets::276 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 336 | 2.626 | 1.285 | paper_0001::Datasets::277 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 720 | 3.548 | 1.495 | paper_0001::Datasets::278 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 0.828 | 0.750 | paper_0001::Datasets::274 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 1.806 | 1.034 | paper_0001::Datasets::275 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 4.070 | 1.681 | paper_0001::Datasets::276 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 3.875 | 1.763 | paper_0001::Datasets::277 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 3.913 | 1.552 | paper_0001::Datasets::278 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 1.531 | 1.613 | paper_0001::Datasets::274 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 1.871 | 1.735 | paper_0001::Datasets::275 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 4.660 | 1.846 | paper_0001::Datasets::276 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 4.028 | 1.688 | paper_0001::Datasets::277 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 5.381 | 2.015 | paper_0001::Datasets::278 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 1.143 | 0.813 | paper_0001::Datasets::274 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 1.671 | 1.221 | paper_0001::Datasets::275 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 4.117 | 1.674 | paper_0001::Datasets::276 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 3.434 | 1.549 | paper_0001::Datasets::277 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 3.963 | 1.788 | paper_0001::Datasets::278 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 2.742 | 1.457 | paper_0001::Datasets::274 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 3.567 | 1.687 | paper_0001::Datasets::275 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 3.242 | 2.513 | paper_0001::Datasets::276 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 2.544 | 2.591 | paper_0001::Datasets::277 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 4.625 | 3.709 | paper_0001::Datasets::278 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.828 | 0.750 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.806 | 1.034 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 4.070 | 1.681 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 3.875 | 1.763 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 3.913 | 1.552 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 1.531 | 1.613 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.871 | 1.735 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 4.660 | 1.846 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 4.028 | 1.688 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 5.381 | 2.015 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 1.143 | 0.813 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.671 | 1.221 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 4.117 | 1.674 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 3.434 | 1.549 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 3.963 | 1.788 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 2.742 | 1.457 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 3.567 | 1.687 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 3.242 | 2.513 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 2.544 | 2.591 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 4.625 | 3.709 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.720 | 0.665 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.457 | 1.001 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 3.489 | 1.515 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 2.723 | 1.340 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 3.467 | 1.473 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 24 | 0.444 | 0.478 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 48 | 0.617 | 0.615 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 168 | 2.405 | 1.266 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 336 | 2.486 | 1.312 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 720 | 2.608 | 1.276 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 24 | 0.477 | 0.537 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 48 | 0.934 | 0.764 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 168 | 3.913 | 1.557 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 336 | 0.907 | 0.747 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 720 | 0.963 | 0.783 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.260 | 0.339 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 0.311 | 0.372 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 0.466 | 0.458 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 0.472 | 0.478 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 0.480 | 0.488 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 48 | 24 | 0.180 | 0.263 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 96 | 48 | 0.230 | 0.303 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 336 | 168 | 0.342 | 0.380 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 336 | 336 | 0.365 | 0.409 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 736 | 720 | 0.475 | 0.488 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |

## Notes

- Informer chooses input lengths by grid search and does not print the chosen value per row: {24, 48, 96, 168, 336, 480, 720} for Informer
  [paper_0001::The hyperparameter tuning range::773], and {24, 48, 96, 168, 336, 720} for "the recurrent component" of all methods
  [paper_0001::The hyperparameter tuning range::770]; which range applies to LogTrans and Reformer is not spelled out.
- SCINet says it keeps all input lengths the same as Informer [paper_0002::4.2 Results and Analyses::317], but
  its hyperparameter table lists SCINet's own look-back for each horizon [paper_0002::Appendix C Reproducibility::937],
  including 736 at horizon 720, outside Informer's search range. The SCINet rows use those numbers; the other rows
  of SCINet's table keep "same as Informer".
- SCINet's values for LogTrans, Reformer, LSTMa, LSTNet and Informer equal those in Informer's Table 2, but SCINet does
  not say where they come from, so origin is left empty; it marks TCN and Pyraformer as re-implemented
  [paper_0002::4.2 Results and Analyses::315] and does not state the source of Autoformer's values.

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0001 Informer | Table 2 (paper_0001::Datasets::265:278) | yes |
| paper_0002 SCINet | Table 4 (paper_0002::4.2 Results and Analyses::289:311) | yes |
