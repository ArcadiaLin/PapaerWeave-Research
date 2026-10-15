---
type: Leaderboard
title: ETTh1 multivariate long-term forecasting
abs: >-
  MSE and MAE reported on ETTh1 in the multivariate setting (all seven variables predicted), by method, paper, look-back and horizon, with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0002    # ETTh1
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 24 | 0.577 | 0.549 | paper_0001::Datasets::269 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 48 | 0.685 | 0.625 | paper_0001::Datasets::270 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 168 | 0.931 | 0.752 | paper_0001::Datasets::271 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 336 | 1.128 | 0.873 | paper_0001::Datasets::272 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 720 | 1.215 | 0.896 | paper_0001::Datasets::273 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 24 | 0.620 | 0.577 | paper_0001::Datasets::269 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 48 | 0.692 | 0.671 | paper_0001::Datasets::270 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 168 | 0.947 | 0.797 | paper_0001::Datasets::271 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 336 | 1.094 | 0.813 | paper_0001::Datasets::272 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 720 | 1.241 | 0.917 | paper_0001::Datasets::273 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 0.686 | 0.604 | paper_0001::Datasets::269 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.766 | 0.757 | paper_0001::Datasets::270 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 1.002 | 0.846 | paper_0001::Datasets::271 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 1.362 | 0.952 | paper_0001::Datasets::272 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 1.397 | 1.291 | paper_0001::Datasets::273 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 0.991 | 0.754 | paper_0001::Datasets::269 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 1.313 | 0.906 | paper_0001::Datasets::270 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 1.824 | 1.138 | paper_0001::Datasets::271 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 2.117 | 1.280 | paper_0001::Datasets::272 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 2.415 | 1.520 | paper_0001::Datasets::273 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 0.650 | 0.624 | paper_0001::Datasets::269 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.702 | 0.675 | paper_0001::Datasets::270 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 1.212 | 0.867 | paper_0001::Datasets::271 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 1.424 | 0.994 | paper_0001::Datasets::272 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 1.960 | 1.322 | paper_0001::Datasets::273 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 1.293 | 0.901 | paper_0001::Datasets::269 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 1.456 | 0.960 | paper_0001::Datasets::270 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 1.997 | 1.214 | paper_0001::Datasets::271 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 2.655 | 1.369 | paper_0001::Datasets::272 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 2.143 | 1.380 | paper_0001::Datasets::273 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.686 | 0.604 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 0.766 | 0.757 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 1.002 | 0.846 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 1.362 | 0.952 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 1.397 | 1.291 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.991 | 0.754 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.313 | 0.906 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 1.824 | 1.138 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 2.117 | 1.280 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 2.415 | 1.520 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.650 | 0.624 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 0.702 | 0.675 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 1.212 | 0.867 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 1.424 | 0.994 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 1.960 | 1.322 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 1.293 | 0.901 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.456 | 0.960 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 1.997 | 1.214 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 2.655 | 1.369 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 2.143 | 1.380 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.577 | 0.549 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 0.685 | 0.625 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 0.931 | 0.752 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 1.128 | 0.873 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 1.215 | 0.896 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 24 | 0.511 | 0.549 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 48 | 0.515 | 0.529 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 168 | 0.694 | 0.617 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 336 | 0.814 | 0.682 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 720 | 0.944 | 0.778 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 24 | 0.479 | 0.499 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 48 | 0.518 | 0.520 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 168 | 0.758 | 0.665 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 336 | 0.891 | 0.738 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 720 | 0.963 | 0.782 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.406 | 0.440 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 0.478 | 0.462 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 168 | 0.493 | 0.481 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 336 | 0.515 | 0.492 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 720 | 0.499 | 0.500 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 48 | 24 | 0.300 | 0.342 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 96 | 48 | 0.361 | 0.388 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 336 | 168 | 0.408 | 0.417 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 336 | 336 | 0.504 | 0.495 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 736 | 720 | 0.544 | 0.527 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |

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
| paper_0001 Informer | Table 2 (paper_0001::Datasets::265:273) | yes |
| paper_0002 SCINet | Table 4 (paper_0002::4.2 Results and Analyses::289:311) | yes |
