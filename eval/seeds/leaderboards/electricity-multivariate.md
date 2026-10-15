---
type: Leaderboard
title: Electricity multivariate long-term forecasting
abs: >-
  MSE and MAE reported on Electricity (ECL) in the multivariate setting, by method, paper, look-back and horizon, with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0006    # Electricity
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 48 | 0.344 | 0.393 | paper_0001::Datasets::289 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 168 | 0.368 | 0.424 | paper_0001::Datasets::290 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 336 | 0.381 | 0.431 | paper_0001::Datasets::291 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 720 | 0.406 | 0.443 | paper_0001::Datasets::292 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 960 | 0.460 | 0.548 | paper_0001::Datasets::293 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 48 | 0.334 | 0.399 | paper_0001::Datasets::289 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 168 | 0.353 | 0.420 | paper_0001::Datasets::290 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 336 | 0.381 | 0.439 | paper_0001::Datasets::291 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 720 | 0.391 | 0.438 | paper_0001::Datasets::292 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 960 | 0.492 | 0.550 | paper_0001::Datasets::293 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.355 | 0.418 | paper_0001::Datasets::289 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 0.368 | 0.432 | paper_0001::Datasets::290 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 0.373 | 0.439 | paper_0001::Datasets::291 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 0.409 | 0.454 | paper_0001::Datasets::292 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 960 | 0.477 | 0.589 | paper_0001::Datasets::293 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 1.404 | 0.999 | paper_0001::Datasets::289 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 1.515 | 1.069 | paper_0001::Datasets::290 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 1.601 | 1.104 | paper_0001::Datasets::291 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 2.009 | 1.170 | paper_0001::Datasets::292 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 960 | 2.141 | 1.387 | paper_0001::Datasets::293 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.486 | 0.572 | paper_0001::Datasets::289 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 0.574 | 0.602 | paper_0001::Datasets::290 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 0.886 | 0.795 | paper_0001::Datasets::291 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 1.676 | 1.095 | paper_0001::Datasets::292 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 960 | 1.591 | 1.128 | paper_0001::Datasets::293 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.369 | 0.445 | paper_0001::Datasets::289 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 0.394 | 0.476 | paper_0001::Datasets::290 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 0.419 | 0.477 | paper_0001::Datasets::291 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 0.556 | 0.565 | paper_0001::Datasets::292 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 960 | 0.605 | 0.599 | paper_0001::Datasets::293 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 96 | 0.168 | 0.253 | paper_0002::4.2 Results and Analyses::277 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 192 | 0.175 | 0.262 | paper_0002::4.2 Results and Analyses::278 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 336 | 0.189 | 0.278 | paper_0002::4.2 Results and Analyses::279 |
| method_0012 SCINet |  | paper_0002 SCINet | target | run | not stated | 720 | 0.231 | 0.316 | paper_0002::4.2 Results and Analyses::280 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.201 | 0.317 | paper_0002::4.2 Results and Analyses::277 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.222 | 0.334 | paper_0002::4.2 Results and Analyses::278 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.231 | 0.338 | paper_0002::4.2 Results and Analyses::279 |
| method_0014 Autoformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.254 | 0.361 | paper_0002::4.2 Results and Analyses::280 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 96 | 0.386 | 0.449 | paper_0002::4.2 Results and Analyses::277 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 192 | 0.378 | 0.443 | paper_0002::4.2 Results and Analyses::278 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 336 | 0.376 | 0.443 | paper_0002::4.2 Results and Analyses::279 |
| method_0015 Pyraformer |  | paper_0002 SCINet | baseline | run | not stated | 720 | 0.376 | 0.445 | paper_0002::4.2 Results and Analyses::280 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.274 | 0.368 | paper_0002::4.2 Results and Analyses::277 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.296 | 0.296 | paper_0002::4.2 Results and Analyses::278 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.300 | 0.394 | paper_0002::4.2 Results and Analyses::279 |
| method_0001 Informer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.373 | 0.439 | paper_0002::4.2 Results and Analyses::280 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.263 | 0.359 | paper_0002::4.2 Results and Analyses::277 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.273 | 0.374 | paper_0002::4.2 Results and Analyses::278 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.277 | 0.373 | paper_0002::4.2 Results and Analyses::279 |
| method_0016 Transformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.290 | 0.378 | paper_0002::4.2 Results and Analyses::280 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.258 | 0.357 | paper_0002::4.2 Results and Analyses::277 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.266 | 0.368 | paper_0002::4.2 Results and Analyses::278 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.280 | 0.380 | paper_0002::4.2 Results and Analyses::279 |
| method_0005 LogTrans |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.283 | 0.376 | paper_0002::4.2 Results and Analyses::280 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 96 | 0.312 | 0.402 | paper_0002::4.2 Results and Analyses::277 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 192 | 0.348 | 0.433 | paper_0002::4.2 Results and Analyses::278 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 336 | 0.350 | 0.433 | paper_0002::4.2 Results and Analyses::279 |
| method_0006 Reformer |  | paper_0002 SCINet | baseline |  | not stated | 720 | 0.340 | 0.420 | paper_0002::4.2 Results and Analyses::280 |

## Notes

- Informer chooses input lengths by grid search and does not print the chosen value per row: {24, 48, 96, 168, 336, 480, 720} for Informer
  [paper_0001::The hyperparameter tuning range::773], and {24, 48, 96, 168, 336, 720} for "the recurrent component" of all methods
  [paper_0001::The hyperparameter tuning range::770]; which range applies to LogTrans and Reformer is not spelled out.
- Informer prints the dataset as ECL and converts it to hourly consumption over two years
  [paper_0001::Datasets::261]; its horizons are 48 to 960, SCINet's are 96 to 720.
- SCINet's long-term table does not state the look-back window, and only Pyraformer is marked as re-implemented
  [paper_0002::4.2 Results and Analyses::287]; the source of the other baseline values is not stated, so their origin
  is left empty.
- SCINet prints the same number for Informer's MSE and MAE at horizon 192 (0.296)
  [paper_0002::4.2 Results and Analyses::278].

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0001 Informer | Table 2 (paper_0001::Datasets::265:293) | yes |
| paper_0002 SCINet | Table 3 (paper_0002::4.2 Results and Analyses::269:284) | yes |
