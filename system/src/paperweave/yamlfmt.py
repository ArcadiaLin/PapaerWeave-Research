"""读视图、算子结果与 Artifact 文档共用的 YAML 写法：长文本折行，短的标量列表写在一行。"""

from __future__ import annotations

from typing import Any

import yaml


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    tag = "tag:yaml.org,2002:str"
    if "\n" in value:
        return dumper.represent_scalar(tag, value, style="|")
    if len(value) > 100:
        return dumper.represent_scalar(tag, value, style=">")
    return dumper.represent_scalar(tag, value)


def _represent_list(dumper: yaml.SafeDumper, value: list[Any]) -> yaml.SequenceNode:
    scalars = all(isinstance(v, str | int | float | bool) for v in value)
    flow = scalars and sum(len(str(v)) + 2 for v in value) < 80
    return dumper.represent_sequence("tag:yaml.org,2002:seq", value, flow_style=flow)


_Dumper.add_representer(str, _represent_str)
_Dumper.add_representer(list, _represent_list)


def dump(data: Any) -> str:
    """读视图与返回结果的 YAML：长文本折行，短的标量列表写在一行。"""
    return yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=120)


__all__ = ["dump"]
