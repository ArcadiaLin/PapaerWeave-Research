"""从种子论文主表的原文行汇出 7 张多变量种子 Leaderboard（只用标准库）。

数字取自所引的原文行，并断言表头与预测长度；输出写到 ../leaderboards/，同一份原文重复运行结果逐字节相同。

    python3 eval/seeds/scripts/boards.py
"""

# ruff: noqa: E501 -- the note strings keep the line breaks of the generated documents

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "data/raw/t1-pilot-corpus/papers"
OUT = Path(__file__).resolve().parents[1] / "leaderboards"
INF = (ROOT / "2012.07436v3/paper.md").read_text().split("\n")
SCI = (ROOT / "2106.09305v3/paper.md").read_text().split("\n")


def cells(lines, n):
    return [c.strip() for c in lines[n - 1].strip().strip("|").split("|")]


I_PAPER, S_PAPER = "paper_0001 Informer", "paper_0002 SCINet"
INFORMER, LOGTRANS, REFORMER, LSTMA, LSTNET = (
    "method_0001 Informer", "method_0005 LogTrans", "method_0006 Reformer", "method_0007 LSTMa", "method_0008 LSTNet")
SCINET, AUTOFORMER, PYRAFORMER, TRANSFORMER, TCN = (
    "method_0012 SCINet", "method_0014 Autoformer", "method_0015 Pyraformer", "method_0016 Transformer",
    "method_0017 TCN")

# ── Informer 表 2（第 265 行起），各数据集的起始行与预测长度；look-back 按附录 E.3 的搜索范围
I_BLOCKS = {"ETTh1": (269, [24, 48, 168, 336, 720]), "ETTh2": (274, [24, 48, 168, 336, 720]),
            "ETTm1": (279, [24, 48, 96, 288, 672]), "Weather": (284, [24, 48, 168, 336, 720]),
            "ECL": (289, [48, 168, 336, 720, 960])}
I_COLS = [(INFORMER, "", "target"), (INFORMER, "Informer†", "target"), (LOGTRANS, "", "baseline"),
          (REFORMER, "", "baseline"), (LSTMA, "", "baseline"), (LSTNET, "", "baseline")]
assert cells(INF, 266)[2::2] == ["Informer", "Informer^†", "LogTrans", "Reformer", "LSTMa", "LSTnet"]


def informer_rows(block):
    start, horizons = I_BLOCKS[block]
    ettm = block == "ETTm1"
    own = "searched in {24, 48, 96, 192, 288, 480, 672}" if ettm else "searched in {24, 48, 96, 168, 336, 480, 720}"
    other = "searched in {24, 48, 96, 192, 288, 672}" if ettm else "searched in {24, 48, 96, 168, 336, 720}"
    assert cells(INF, start)[0] == block
    rows = []
    for j, (method, variant, role) in enumerate(I_COLS):
        for i, h in enumerate(horizons):
            n = start + i
            c = cells(INF, n)
            assert int(c[1]) == h, (block, n)
            rows.append((method, variant, I_PAPER, role, "run", own if method == INFORMER else other, h,
                         c[2 + 2 * j], c[3 + 2 * j], f"paper_0001::Datasets::{n}"))
    return rows


# ── SCINet 表 4（第 289 行起）：每个方法两行（MSE、MAE）；SCINet 自己的 look-back 见附录表 11（第 937 行）
S4_COLS = {"ETTh1": (2, [24, 48, 168, 336, 720]), "ETTh2": (7, [24, 48, 168, 336, 720]),
           "ETTm1": (12, [24, 48, 96, 288, 672])}
S4_METHODS = [(LOGTRANS, 294, ""), (REFORMER, 296, ""), (LSTMA, 298, ""), (LSTNET, 300, ""), (INFORMER, 302, ""),
              (TCN, 304, "run"), (PYRAFORMER, 306, "run"), (AUTOFORMER, 308, ""), (SCINET, 310, "run")]
assert cells(SCI, 934)[2] == "ETTh1" and cells(SCI, 937)[1] == "Look-back window"


def scinet_t4_rows(block):
    col, horizons = S4_COLS[block]
    assert [int(x) for x in cells(SCI, 293)[col:col + 5]] == horizons
    assert [int(x) for x in cells(SCI, 936)[col:col + 5]] == horizons
    lookbacks = cells(SCI, 937)[col:col + 5]
    rows = []
    for method, n, origin in S4_METHODS:
        mse, mae = cells(SCI, n), cells(SCI, n + 1)
        assert mse[1] == "MSE" and mae[1] == "MAE", n
        for i, h in enumerate(horizons):
            m1, m2 = mse[col + i], mae[col + i]
            if m2 == "L1700":  # 转换错误，见 Notes
                m2 = ""
            own = method == SCINET
            rows.append((method, "", S_PAPER, "target" if own else "baseline", origin,
                         lookbacks[i] if own else "same as Informer", h, m1, m2,
                         f"paper_0002::4.2 Results and Analyses::{n}:{n + 1}"
                         + ("; paper_0002::Appendix C Reproducibility::937" if own else "")))
    return rows


# ── SCINet 表 3（第 269 行起）：每个数据集 4 行，列是方法 × (MSE, MAE)
S3_BLOCKS = {"Exchange": 273, "Electricity": 277, "Traffic": 281}
S3_COLS = [(SCINET, "run"), (AUTOFORMER, ""), (PYRAFORMER, "run"), (INFORMER, ""), (TRANSFORMER, ""),
           (LOGTRANS, ""), (REFORMER, "")]
assert [c.split()[0].removeprefix("$*$") for c in cells(SCI, 270)[2:16:2]] == [
    "SCINet", "Autoformer", "Pyraformer", "Informer", "Transformer", "LogTrans", "Reformer"]


def scinet_t3_rows(block):
    start = S3_BLOCKS[block]
    label = cells(SCI, start + 3)[0].replace("<br>", " ")
    assert label.startswith(block), label
    rows = []
    for j, (method, origin) in enumerate(S3_COLS):
        for i, h in enumerate([96, 192, 336, 720]):
            n = start + i
            c = cells(SCI, n)
            assert int(c[1]) == h, (block, n)
            rows.append((method, "", S_PAPER, "target" if method == SCINET else "baseline", origin, "not stated", h,
                         c[2 + 2 * j], c[3 + 2 * j], f"paper_0002::4.2 Results and Analyses::{n}"))
    return rows


# ── 说明（Notes）中的段落，各张按需取用
N_INFORMER_LB = """- Informer chooses input lengths by grid search and does not print the chosen value per row: {own} for Informer
  [paper_0001::The hyperparameter tuning range::773], and {other} for "the recurrent component" of all methods
  [paper_0001::The hyperparameter tuning range::770]; which range applies to LogTrans and Reformer is not spelled out."""
N_SCINET_T4 = """- SCINet says it keeps all input lengths the same as Informer [paper_0002::4.2 Results and Analyses::317], but
  its hyperparameter table lists SCINet's own look-back for each horizon [paper_0002::Appendix C Reproducibility::937],
  including 736 at horizon 720, outside Informer's search range. The SCINet rows use those numbers; the other rows
  of SCINet's table keep "same as Informer".
- SCINet's values for LogTrans, Reformer, LSTMa, LSTNet and Informer equal those in Informer's Table 2, but SCINet does
  not say where they come from, so origin is left empty; it marks TCN and Pyraformer as re-implemented
  [paper_0002::4.2 Results and Analyses::315] and does not state the source of Autoformer's values."""
N_SCINET_T3 = """- SCINet's long-term table does not state the look-back window, and only Pyraformer is marked as re-implemented
  [paper_0002::4.2 Results and Analyses::287]; the source of the other baseline values is not stated, so their origin
  is left empty."""

BOARDS = {
    "etth1-multivariate": dict(
        title="ETTh1 multivariate long-term forecasting", dataset="dataset_0002", name="ETTh1",
        abs="MSE and MAE reported on ETTh1 in the multivariate setting (all seven variables predicted)",
        rows=lambda: informer_rows("ETTh1") + scinet_t4_rows("ETTh1"),
        notes=[N_INFORMER_LB.format(own="{24, 48, 96, 168, 336, 480, 720}", other="{24, 48, 96, 168, 336, 720}"),
               N_SCINET_T4],
        covered=[(I_PAPER, "Table 2 (paper_0001::Datasets::265:273)"),
                 (S_PAPER, "Table 4 (paper_0002::4.2 Results and Analyses::289:311)")]),
    "etth2-multivariate": dict(
        title="ETTh2 multivariate long-term forecasting", dataset="dataset_0003", name="ETTh2",
        abs="MSE and MAE reported on ETTh2 in the multivariate setting (all seven variables predicted)",
        rows=lambda: informer_rows("ETTh2") + scinet_t4_rows("ETTh2"),
        notes=[N_INFORMER_LB.format(own="{24, 48, 96, 168, 336, 480, 720}", other="{24, 48, 96, 168, 336, 720}"),
               N_SCINET_T4],
        covered=[(I_PAPER, "Table 2 (paper_0001::Datasets::265:278)"),
                 (S_PAPER, "Table 4 (paper_0002::4.2 Results and Analyses::289:311)")]),
    "ettm1-multivariate": dict(
        title="ETTm1 multivariate long-term forecasting", dataset="dataset_0004", name="ETTm1",
        abs="MSE and MAE reported on ETTm1 (15-minute) in the multivariate setting (all seven variables predicted)",
        rows=lambda: informer_rows("ETTm1") + scinet_t4_rows("ETTm1"),
        notes=[N_INFORMER_LB.format(own="{24, 48, 96, 192, 288, 480, 672}", other="{24, 48, 96, 192, 288, 672}"),
               N_SCINET_T4,
               """- SCINet prints LSTNet's MAE at horizon 24 as "L1700" [paper_0002::4.2 Results and Analyses::301], a conversion
  error (Informer's table has 1.170 [paper_0001::Datasets::279]); that cell is left empty in SCINet's row."""],
        covered=[(I_PAPER, "Table 2 (paper_0001::Datasets::265:283)"),
                 (S_PAPER, "Table 4 (paper_0002::4.2 Results and Analyses::289:311)")]),
    "weather-noaa-multivariate": dict(
        title="Weather (NOAA) multivariate long-term forecasting", dataset="dataset_0011",
        name="Weather (NOAA local climatological data)",
        abs="MSE and MAE reported on Informer's Weather dataset (NOAA local climatological data) in the multivariate setting",
        rows=lambda: informer_rows("Weather"),
        notes=[N_INFORMER_LB.format(own="{24, 48, 96, 168, 336, 480, 720}", other="{24, 48, 96, 168, 336, 720}"),
               """- Informer's "Weather" is local climatological data for nearly 1,600 U.S. locations from NOAA
  [paper_0001::Datasets::263]. It is not the Weather dataset that many later papers use under the same name."""],
        covered=[(I_PAPER, "Table 2 (paper_0001::Datasets::265:288)")]),
    "electricity-multivariate": dict(
        title="Electricity multivariate long-term forecasting", dataset="dataset_0006", name="Electricity",
        abs="MSE and MAE reported on Electricity (ECL) in the multivariate setting",
        rows=lambda: informer_rows("ECL") + scinet_t3_rows("Electricity"),
        notes=[N_INFORMER_LB.format(own="{24, 48, 96, 168, 336, 480, 720}", other="{24, 48, 96, 168, 336, 720}"),
               """- Informer prints the dataset as ECL and converts it to hourly consumption over two years
  [paper_0001::Datasets::261]; its horizons are 48 to 960, SCINet's are 96 to 720.""",
               N_SCINET_T3,
               """- SCINet prints the same number for Informer's MSE and MAE at horizon 192 (0.296)
  [paper_0002::4.2 Results and Analyses::278]."""],
        covered=[(I_PAPER, "Table 2 (paper_0001::Datasets::265:293)"),
                 (S_PAPER, "Table 3 (paper_0002::4.2 Results and Analyses::269:284)")]),
    "exchange-rate-multivariate": dict(
        title="Exchange-Rate multivariate long-term forecasting", dataset="dataset_0010", name="Exchange-Rate",
        abs="MSE and MAE reported on Exchange-Rate in the multivariate setting",
        rows=lambda: scinet_t3_rows("Exchange"),
        notes=[N_SCINET_T3,
               """- SCINet prints the same number for Informer's MSE and MAE at horizon 720 (2.478)
  [paper_0002::4.2 Results and Analyses::276]."""],
        covered=[(S_PAPER, "Table 3 (paper_0002::4.2 Results and Analyses::269:284)")]),
    "traffic-multivariate": dict(
        title="Traffic multivariate long-term forecasting", dataset="dataset_0007", name="Traffic",
        abs="MSE and MAE reported on Traffic in the multivariate setting",
        rows=lambda: scinet_t3_rows("Traffic"),
        notes=[N_SCINET_T3],
        covered=[(S_PAPER, "Table 3 (paper_0002::4.2 Results and Analyses::269:284)")]),
}

for stem, b in BOARDS.items():
    rows = b["rows"]()
    text = f"""---
type: Leaderboard
title: {b['title']}
abs: >-
  {b['abs']}, by method, paper, look-back and horizon, with the source line of every number.
task: task_0002          # Long-term time series forecasting
dataset: {b['dataset']}    # {b['name']}
setting: {{variate: multivariate}}
metrics: {{MSE: lower, MAE: lower}}
---
## Results

| method | variant | paper | role | origin | lookback | pred_len | MSE | MAE | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""
    text += "".join("| " + " | ".join(str(x) for x in r) + " |\n" for r in rows)
    text += "\n## Notes\n\n" + "\n".join(b["notes"]) + "\n"
    text += "\n## Papers covered\n\n| paper | tables | complete |\n| --- | --- | --- |\n"
    text += "".join(f"| {p} | {t} | yes |\n" for p, t in b["covered"])
    (OUT / f"{stem}.md").write_text(text, encoding="utf-8")
    print(f"{stem}: {len(rows)} rows")
