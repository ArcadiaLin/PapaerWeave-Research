"""一次运行的配置：先导配置加上这次运行的覆盖。运行框架与测量层读同一份。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def run_config(run: Path, config: dict[str, Any]) -> dict[str, Any]:
    """配置加上这次运行的覆盖（``run.yml`` 的 ``overrides``）：A3 图库、各组的模型服务决定在哪里跑，不改协议；
    ``composition`` 选择这条时间线的写者构成（配置中 ``compositions`` 的一项）。测量（health、grade）与读者
    读同一份。"""
    path = run / "run.yml"
    overrides = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("overrides") or {} if path.exists() else {}
    config = {**config, "arms": {**config["arms"]}, "runner": {**config["runner"]}}
    if overrides.get("neo4j"):
        config["arms"]["A3"] = {**config["arms"]["A3"], "neo4j": overrides["neo4j"]}
    if overrides.get("endpoints"):
        config["runner"]["endpoints"] = overrides["endpoints"]
    if overrides.get("composition"):
        config["composition"] = overrides["composition"]
    if "assignment" in config and config.get("composition") not in config.get("compositions", {}):
        raise ValueError(f"{path} names no writer composition of {sorted(config.get('compositions', {}))}")
    return config


__all__ = ["run_config"]
