---
type: CompareSettings
title: <what is compared, e.g. DLinear on ETTh1-96 in PatchTST vs TiDE>
abs: <one sentence on whether the two results are comparable, and why>
items: [<art id>#<row key>, <art id>#<row key>]   # the two things compared: leaderboard rows or experiment ids
verdict: U        # T: comparable, F: not comparable, U: cannot tell
relation: unknown # when two papers report the same cell: same_source, independent, incomparable or unknown
---
## Settings

One row per dimension. same is T, F or U; for T and F, basis cites where each side states it, in square
brackets ([<paper id>::<start>:<end>], [exp_0003]); for U, basis says what is missing.

| dimension | left | right | same | basis |
| --- | --- | --- | --- | --- |
| lookback | 336 | 96 | F | [<paper id>::<start>:<end>] [<paper id>::<start>:<end>] |
| split |  |  | U | <what is missing> |
| normalization |  |  | U |  |
| training_data |  |  | U |  |
| protocol |  |  | U |  |
