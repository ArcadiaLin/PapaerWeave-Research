"""T1 的调度与任务文本：由配置确定，不依赖运行环境。"""

from __future__ import annotations

import yaml
from e09.config import REPO
from t1.run import prompt, schedule

CONFIG = yaml.safe_load((REPO / "experiments/t1/config/pilot-ltsf.yml").read_text(encoding="utf-8"))


def test_writers_alternate_and_checkpoints_follow_every_second_paper() -> None:
    slots = schedule(CONFIG)
    assert len(slots) == 16
    assert [s.writer["id"] for s in slots[:4]] == ["writer-i3", "writer-i2", "writer-i2", "writer-i3"]
    assert [s.paper["short"] for s in slots[:4]] == ["Autoformer", "Autoformer", "Query Selector", "Query Selector"]
    assert [(s.index, s.checkpoint) for s in slots if s.checkpoint] == [(4, 1), (8, 2), (12, 3), (16, 4)]


def test_prompts_differ_between_arms_only_in_the_store_sentence() -> None:
    slot = schedule(CONFIG)[0]
    titles = {"2106.13008": "Autoformer: Decomposition Transformers"}
    a3, a0 = prompt(CONFIG, "A3", slot, titles), prompt(CONFIG, "A0", slot, titles)
    assert "papers/2106.13008v5/paper.md" in a3 and "Autoformer: Decomposition Transformers" in a3
    assert a3.replace(CONFIG["arms"]["A3"]["store"], "") == a0.replace(CONFIG["arms"]["A0"]["store"], "")
    assert "{" not in a3
