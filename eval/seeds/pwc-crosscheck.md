# 种子 Leaderboard 与 PwC 的事后核对

种子取自两篇种子论文的原文表格，不取自 PwC。本文件记录种子写完后与 PwC 归档的只读核对。它不进库：写者看不到 PwC，
种子文档的 Notes 也就不提 PwC。

- PwC 归档：HF `pwc-archive/evaluation-tables`，固定修订见 `data/raw/t1-pilot-corpus/README.md`；任务
  Time Series Forecasting 及其子任务 Multivariate Time Series Forecasting 下，数据集名形如 `ETTh1 (24) Multivariate`。
- 核对范围：PwC 中两篇种子论文的多变量条目，与种子中该论文自己方法（role target、无 variant）的行逐格比较。
- 核对日期：2026-10-14。

## 结果

PwC 只收了两篇论文各自的方法，且只覆盖 ETTh1、ETTh2，共 20 条（每条 MSE、MAE 两格）；基线、Informer†、ETTm1、
Weather（NOAA）、ECL 都没有条目。

| 论文 | 数据集 | 条目 | 与种子一致 |
| --- | --- | --- | --- |
| SCINet（paper_0002） | ETTh1、ETTh2 | 10 | 10 |
| Informer（paper_0001） | ETTh1、ETTh2 | 10 | 0 |

Informer 的 10 条与原文 v3 表 2 都不一致：

| 数据集 | 预测长度 | PwC（MSE / MAE） | 原文 v3（MSE / MAE） | 原文行 |
| --- | --- | --- | --- | --- |
| ETTh1 | 24 | 0.509 / 0.523 | 0.577 / 0.549 | `paper_0001::Datasets::269` |
| ETTh1 | 48 | 0.551 / 0.563 | 0.685 / 0.625 | `paper_0001::Datasets::270` |
| ETTh1 | 168 | 0.878 / 0.722 | 0.931 / 0.752 | `paper_0001::Datasets::271` |
| ETTh1 | 336 | 0.884 / 0.753 | 1.128 / 0.873 | `paper_0001::Datasets::272` |
| ETTh1 | 720 | 0.941 / 0.768 | 1.215 / 0.896 | `paper_0001::Datasets::273` |
| ETTh2 | 24 | 0.446 / 0.523 | 0.720 / 0.665 | `paper_0001::Datasets::274` |
| ETTh2 | 48 | 0.934 / 0.733 | 1.457 / 1.001 | `paper_0001::Datasets::275` |
| ETTh2 | 168 | 1.512 / 0.996 | 3.489 / 1.515 | `paper_0001::Datasets::276` |
| ETTh2 | 336 | 1.665 / 1.035 | 2.723 / 1.340 | `paper_0001::Datasets::277` |
| ETTh2 | 720 | 2.34 / 1.209 | 3.467 / 1.473 | `paper_0001::Datasets::278` |

## 裁决

按原文：种子保留 v3 表 2 的数值。PwC 的这些数值在 v3 全文中都找不到，表中其他列（Informer†、各基线）也没有；
SCINet 转引的 Informer 数值同样与 v3 一致。PwC 的来源未核实，可能是论文的其他版本，语料中只有 v3。

这对评测的含义：evaluation_draft §8.2 预想的“PwC 与原文不一致、回原文裁决”在先导语料中真实出现；审计 DAG 的
“对照 PwC”一步不能把 PwC 当作金标准。
