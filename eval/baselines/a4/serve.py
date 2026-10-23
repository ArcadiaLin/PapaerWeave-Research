"""A4 的 Graphiti MCP 服务（HTTP，127.0.0.1:8765，所有写者共用一个进程）。由先导 tmps/pilot/graphiti/serve.py 移来。

- 发给 sglang 的对话请求都关掉思考（chat_template_kwargs.enable_thinking=false）：Graphiti 的内部 LLM 做抽取，
  要的是受约束的 JSON；开着思考时每次调用多出上千个 token。
- 不列出 clear_graph：共享库中一个写者就能清空全部，任务也用不到它。
- 加 get_episodes_by_uuid：按 UUID 取 episode 原文（f3 设计第 5 节，10-23 定），写者与读者都开放。
- 每次对话请求的 token 用量写一行日志（`llm usage prompt=… completion=…`），按时间记到 A4 的写者头上。
- 服务代码取自 getzep/graphiti 的 mcp_server（commit a107b62，graphiti-core 0.31.1、mcp 2.3.0、neo4j 6.4.1、
  openai 3.33.0），不改动。源码与独立的 Python 环境是外部运行环境，不在仓库中：``GRAPHITI_SRC`` 指向源码目录
  （默认 tmps/pilot/graphiti/src），用那个环境的 python 运行本文件。

用法（运行框架之外，长驻；日志即 eval/config/formal-ltsf.yml 的 ``graphiti_log``，运行框架按它判断处理完）：

    $GRAPHITI_ENV/bin/python -I eval/baselines/a4/serve.py >> ~/pw-lab/runs/graphiti.log 2>&1
"""

import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(os.environ.get("GRAPHITI_SRC", HERE.parents[2] / "tmps/pilot/graphiti/src"))
sys.path.insert(0, str(SRC / "mcp_server" / "src"))
sys.path.insert(0, str(SRC / "mcp_server"))

from openai.resources.chat.completions import AsyncCompletions  # noqa: E402

_create = AsyncCompletions.create
usage_log = logging.getLogger("pilot.usage")


async def create(self, *args, **kwargs):
    body = dict(kwargs.pop("extra_body", None) or {})
    body.setdefault("chat_template_kwargs", {"enable_thinking": False})
    response = await _create(self, *args, extra_body=body, **kwargs)
    usage = getattr(response, "usage", None)
    if usage is not None:
        usage_log.info("llm usage prompt=%d completion=%d", usage.prompt_tokens, usage.completion_tokens)
    return response


AsyncCompletions.create = create

import graphiti_mcp_server as server  # noqa: E402
from graphiti_core.nodes import EpisodicNode  # noqa: E402
from models.response_types import EpisodeSearchResponse, ErrorResponse  # noqa: E402

server.mcp.remove_tool("clear_graph")


@server.mcp.tool()
async def get_episodes_by_uuid(
    episode_uuids: list[str],
    group_id: str | None = None,
) -> EpisodeSearchResponse | ErrorResponse:
    """Get the full stored text of specific episodes.

    Facts from search_memory_facts list the episodes they came from (their `episodes` field, a list of
    episode UUIDs); use this to read those episodes as they were written.

    Args:
        episode_uuids: List of episode UUIDs to read
        group_id: Optional group ID. Falls back to the default group when omitted.
    """
    # f3 设计第 5 节：官方 MCP 没有按 UUID 取 episode 原文的入口；这里开放核心库已有的 EpisodicNode.get_by_uuids，
    # 结果的字段与官方 get_episodes 相同。写者与读者都开放（不在 timeline.A4_WRITE_TOOLS 中）。
    if server.graphiti_service is None:
        return ErrorResponse(error="Graphiti service not initialized")
    if not episode_uuids:
        return ErrorResponse(error="episode_uuids must contain at least one UUID")
    try:
        client = await server.graphiti_service.get_client()
        group = group_id or server.config.graphiti.group_id
        driver = server._driver_for_group(client, group) if group else client.driver
        found = {e.uuid: e for e in await EpisodicNode.get_by_uuids(driver, list(episode_uuids))
                 if not group or e.group_id == group}  # fmt: skip
        episodes = [episode_result(found[u]) for u in dict.fromkeys(episode_uuids) if u in found]
        missing = [u for u in dict.fromkeys(episode_uuids) if u not in found]
        message = f"Retrieved {len(episodes)} of {len(dict.fromkeys(episode_uuids))} episode(s)"
        return EpisodeSearchResponse(message=message + (f"; not found: {', '.join(missing)}" if missing else ""),
                                     episodes=episodes)  # fmt: skip
    except Exception as e:
        server.logger.error(f"Error getting episodes by uuid: {e}")
        return ErrorResponse(error=f"Error getting episodes by uuid: {e}")


def episode_result(episode: EpisodicNode) -> dict:
    """与官方 get_episodes 返回的字段相同。"""
    return {
        "uuid": episode.uuid,
        "name": episode.name,
        "content": episode.content,
        "created_at": episode.created_at.isoformat() if episode.created_at else None,
        "source": episode.source.value if hasattr(episode.source, "value") else str(episode.source),
        "source_description": episode.source_description,
        "group_id": episode.group_id,
    }

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--config", str(HERE / "config.yaml")]
    server.main()
