---
type: Leaderboard
title: Weather (NOAA) multivariate long-term forecasting
abs: >-
  MSE and MAE reported on Informer's Weather dataset (NOAA local climatological data) in the multivariate setting, by method, paper, look-back and horizon, with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: dataset_0011    # Weather (NOAA local climatological data)
setting: {variate: multivariate}
metrics: {MSE: lower, MAE: lower}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 24 | 0.335 | 0.381 | paper_0001::Datasets::284 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 48 | 0.395 | 0.459 | paper_0001::Datasets::285 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 168 | 0.608 | 0.567 | paper_0001::Datasets::286 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 336 | 0.702 | 0.620 | paper_0001::Datasets::287 |
| method_0001 Informer |  | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 720 | 0.831 | 0.731 | paper_0001::Datasets::288 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 24 | 0.349 | 0.397 | paper_0001::Datasets::284 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 48 | 0.386 | 0.433 | paper_0001::Datasets::285 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 168 | 0.613 | 0.582 | paper_0001::Datasets::286 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 336 | 0.707 | 0.634 | paper_0001::Datasets::287 |
| method_0001 Informer | Informer† | paper_0001 Informer | target | run | searched in {24, 48, 96, 168, 336, 480, 720} | 720 | 0.834 | 0.741 | paper_0001::Datasets::288 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 0.435 | 0.477 | paper_0001::Datasets::284 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.426 | 0.495 | paper_0001::Datasets::285 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 0.727 | 0.671 | paper_0001::Datasets::286 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 0.754 | 0.670 | paper_0001::Datasets::287 |
| method_0005 LogTrans |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 0.885 | 0.773 | paper_0001::Datasets::288 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 0.655 | 0.583 | paper_0001::Datasets::284 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.729 | 0.666 | paper_0001::Datasets::285 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 1.318 | 0.855 | paper_0001::Datasets::286 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 1.930 | 1.167 | paper_0001::Datasets::287 |
| method_0006 Reformer |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 2.726 | 1.575 | paper_0001::Datasets::288 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 0.546 | 0.570 | paper_0001::Datasets::284 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.829 | 0.677 | paper_0001::Datasets::285 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 1.038 | 0.835 | paper_0001::Datasets::286 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 1.657 | 1.059 | paper_0001::Datasets::287 |
| method_0007 LSTMa |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 1.536 | 1.109 | paper_0001::Datasets::288 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 24 | 0.615 | 0.545 | paper_0001::Datasets::284 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 48 | 0.660 | 0.589 | paper_0001::Datasets::285 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 168 | 0.748 | 0.647 | paper_0001::Datasets::286 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 336 | 0.782 | 0.683 | paper_0001::Datasets::287 |
| method_0008 LSTNet |  | paper_0001 Informer | baseline | run | searched in {24, 48, 96, 168, 336, 720} | 720 | 0.851 | 0.757 | paper_0001::Datasets::288 |

## Notes

- Informer chooses input lengths by grid search and does not print the chosen value per row: {24, 48, 96, 168, 336, 480, 720} for Informer
  [paper_0001::The hyperparameter tuning range::773], and {24, 48, 96, 168, 336, 720} for "the recurrent component" of all methods
  [paper_0001::The hyperparameter tuning range::770]; which range applies to LogTrans and Reformer is not spelled out.
- Informer's "Weather" is local climatological data for nearly 1,600 U.S. locations from NOAA
  [paper_0001::Datasets::263]. It is not the Weather dataset that many later papers use under the same name.

## Papers covered

| paper | tables | complete |
| --- | --- | --- |
| paper_0001 Informer | Table 2 (paper_0001::Datasets::265:288) | yes |
