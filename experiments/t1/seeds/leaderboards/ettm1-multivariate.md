---
type: Leaderboard
title: ETTm1 multivariate long-term forecasting
abs: >-
  MSE and MAE reported on ETTm1 (15-minute) in the multivariate setting (all seven variables predicted), by method, paper, look-back and horizon, with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0004    # ETTm1
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 24 | 0.323 | 0.369 | paper_0001::Datasets::279 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 48 | 0.494 | 0.503 | paper_0001::Datasets::280 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 96 | 0.678 | 0.614 | paper_0001::Datasets::281 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 288 | 1.056 | 0.786 | paper_0001::Datasets::282 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 672 | 1.192 | 0.926 | paper_0001::Datasets::283 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 24 | 0.306 | 0.371 | paper_0001::Datasets::279 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 48 | 0.465 | 0.470 | paper_0001::Datasets::280 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 96 | 0.681 | 0.612 | paper_0001::Datasets::281 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 288 | 1.162 | 0.879 | paper_0001::Datasets::282 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 192, 288, 480, 672} | 672 | 1.231 | 1.103 | paper_0001::Datasets::283 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 24 | 0.419 | 0.412 | paper_0001::Datasets::279 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 48 | 0.507 | 0.583 | paper_0001::Datasets::280 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 96 | 0.768 | 0.792 | paper_0001::Datasets::281 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 288 | 1.462 | 1.320 | paper_0001::Datasets::282 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 672 | 1.669 | 1.461 | paper_0001::Datasets::283 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 24 | 0.724 | 0.607 | paper_0001::Datasets::279 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 48 | 1.098 | 0.777 | paper_0001::Datasets::280 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 96 | 1.433 | 0.945 | paper_0001::Datasets::281 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 288 | 1.820 | 1.094 | paper_0001::Datasets::282 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 672 | 2.187 | 1.232 | paper_0001::Datasets::283 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 24 | 0.621 | 0.629 | paper_0001::Datasets::279 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 48 | 1.392 | 0.939 | paper_0001::Datasets::280 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 96 | 1.339 | 0.913 | paper_0001::Datasets::281 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 288 | 1.740 | 1.124 | paper_0001::Datasets::282 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 672 | 2.736 | 1.555 | paper_0001::Datasets::283 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 24 | 1.968 | 1.170 | paper_0001::Datasets::279 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 48 | 1.999 | 1.215 | paper_0001::Datasets::280 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 96 | 2.762 | 1.542 | paper_0001::Datasets::281 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 288 | 1.257 | 2.076 | paper_0001::Datasets::282 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 192, 288, 672} | 672 | 1.917 | 2.941 | paper_0001::Datasets::283 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.419 | 0.412 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 0.507 | 0.583 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 96 | 0.768 | 0.792 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 288 | 1.462 | 1.320 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | same as Informer | 672 | 1.669 | 1.461 | paper_0002::4.2 Results and Analyses::294:295 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.724 | 0.607 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.098 | 0.777 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 96 | 1.433 | 0.945 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 288 | 1.820 | 1.094 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | same as Informer | 672 | 2.187 | 1.232 | paper_0002::4.2 Results and Analyses::296:297 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.621 | 0.629 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.392 | 0.939 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 96 | 1.339 | 0.913 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 288 | 1.740 | 1.124 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0007 LSTMa |  | paper_0002 SCINet | baseline |  | same as Informer | 672 | 2.736 | 1.555 | paper_0002::4.2 Results and Analyses::298:299 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 1.968 |  | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 1.999 | 1.215 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 96 | 2.762 | 1.542 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 288 | 1.257 | 2.076 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0008 LSTNet |  | paper_0002 SCINet | baseline |  | same as Informer | 672 | 1.917 | 2.941 | paper_0002::4.2 Results and Analyses::300:301 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.323 | 0.369 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 0.494 | 0.503 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 96 | 0.678 | 0.614 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 288 | 1.056 | 0.786 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | same as Informer | 672 | 1.192 | 0.926 | paper_0002::4.2 Results and Analyses::302:303 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 24 | 0.229 | 0.282 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 48 | 0.239 | 0.360 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 96 | 0.260 | 0.363 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 288 | 0.768 | 0.646 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0017 TCN |  | paper_0002 SCINet | baseline | run | same as Informer | 672 | 2.732 | 1.371 | paper_0002::4.2 Results and Analyses::304:305 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 24 | 0.332 | 0.383 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 48 | 0.492 | 0.475 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 96 | 0.543 | 0.510 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 288 | 0.656 | 0.598 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | same as Informer | 672 | 0.901 | 0.720 | paper_0002::4.2 Results and Analyses::306:307 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 24 | 0.408 | 0.424 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 48 | 0.499 | 0.464 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 96 | 0.540 | 0.489 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 288 | 0.636 | 0.533 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | same as Informer | 672 | 0.699 | 0.564 | paper_0002::4.2 Results and Analyses::308:309 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 48 | 24 | 0.106 | 0.202 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 96 | 48 | 0.136 | 0.230 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 384 | 96 | 0.165 | 0.252 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 672 | 288 | 0.253 | 0.315 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | 672 | 672 | 0.346 | 0.376 | paper_0002::4.2 Results and Analyses::310:311; paper_0002::Appendix C Reproducibility::937 |

## Notes

- Informer chooses input lengths by grid search and does not print the chosen value per row: {24, 48, 96, 192, 288, 480, 672} for Informer
  [paper_0001::The hyperparameter tuning range::773], and {24, 48, 96, 192, 288, 672} for "the recurrent component" of all methods
  [paper_0001::The hyperparameter tuning range::770]; which range applies to LogTrans and Reformer is not spelled out.
- SCINet says it keeps all input lengths the same as Informer [paper_0002::4.2 Results and Analyses::317], but
  its hyperparameter table lists SCINet's own look-back for each horizon [paper_0002::Appendix C Reproducibility::937],
  including 736 at horizon 720, outside Informer's search range. The SCINet rows use those numbers; the other rows
  of SCINet's table keep "same as Informer".
- SCINet's values for LogTrans, Reformer, LSTMa, LSTNet and Informer equal those in Informer's Table 2, but SCINet does
  not say where they come from, so origin is left empty; it marks TCN and Pyraformer as re-implemented
  [paper_0002::4.2 Results and Analyses::315] and does not state the source of Autoformer's values.
- SCINet prints LSTNet's MAE at horizon 24 as "L1700" [paper_0002::4.2 Results and Analyses::301], a conversion
  error (Informer's table has 1.170 [paper_0001::Datasets::279]); that cell is left empty in SCINet's row.

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0001 Informer | Table 2 (paper_0001::Datasets::265:283) | yes |
| paper_0002 SCINet | Table 4 (paper_0002::4.2 Results and Analyses::289:311) | yes |
