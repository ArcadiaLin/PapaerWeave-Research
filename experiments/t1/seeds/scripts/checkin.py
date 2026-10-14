"""在一次性 Neo4j 上种入锚点与两篇种子论文，再检入种子产物（只用标准库）：先是 ../leaderboards/ 的全部 Leaderboard
（一个提交，id 按文件名顺序为 art_0001…），再是 ../skills/*/SKILL.md（另一个提交）。

按 evaluation_draft §10.1，这里不 import e09：种库用 e09 的命令行（``python -m e09 <文档> --source ... --apply``），
检入用 MCP 入口（``python -m e09.mcp``，子进程，stdio 上逐行 JSON-RPC），写者工作目录（``E09_WORKDIR``）是 ``seeds/``，
登录身份 ``E09_USER=seed``。论文材料复制到临时目录，作为 ``E09_DATA``。

    E09_NEO4J_URI=bolt://localhost:7692 .venv/bin/python experiments/t1/seeds/scripts/checkin.py [--check-only]

库必须是空的一次性库：长期使用的库（7687 neo4j-e09、7688、7689 neo4j-t1）一律拒绝。需要向量服务（``EMBED_URL``），
关闭向量时只按词面去重，会给出错误的候选。MCP 的完整回复写到 ``--out``（默认临时目录），这里只打印摘要。
退出码：0 检入成功（或 ``--check-only`` 时检查通过）；1 种库或检入失败。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[4]
CORPUS = REPO / "data/raw/t1-pilot-corpus"
SEEDS = Path(__file__).resolve().parents[1]
PAPERS = ["2012.07436v3", "2106.09305v3"]
SEED_DOCS = [  # (入库文档, 来源标签, 额外参数)；与先导配置的检查点 0 相同
    ("00-anchors.yml", "seed:t1-anchors", ["--no-dedup"]),
    ("01-2020-Informer.yml", "paper:2020-Informer", []),
    ("02-2021-SCINet.yml", "paper:2021-SCINet", []),
]
LONG_LIVED_PORTS = {7687, 7688, 7689}
BATCHES = [  # (文档的 glob，update_abstract)；按顺序各检入一次
    ("leaderboards/*.md", "Seed leaderboards from the seed papers' main tables."),
    ("skills/*/SKILL.md", "Seed skills for the Leaderboard and Generate types."),
]


def main() -> int:
    args = _parser().parse_args()
    uri = os.environ.get("E09_NEO4J_URI", "")
    port = urlparse(uri).port
    if not uri or port in LONG_LIVED_PORTS:
        refused = sorted(LONG_LIVED_PORTS)
        print(f"error: set E09_NEO4J_URI to a throwaway Neo4j (got {uri or 'nothing'}; {refused} refused)")
        return 1
    data = Path(tempfile.mkdtemp(prefix="t1-seed-data-"))
    for paper in PAPERS:
        shutil.copytree(CORPUS / "papers" / paper, data / "papers" / paper)
    env = {**os.environ, "E09_DATA": str(data)}

    for doc, source, extra in SEED_DOCS:
        run = subprocess.run(
            [sys.executable, "-m", "e09", str(CORPUS / "docs" / doc), "--source", source, "--apply", *extra],
            env=env, capture_output=True, text=True,
        )
        status = re.search(r"^status: (\w+)", run.stdout, re.M)
        print(f"seed {doc}: rc={run.returncode} status={status[1] if status else '?'}")
        if run.returncode != 0:
            print(run.stdout[-2000:], run.stderr[-2000:], sep="\n")
            return 1

    mcp_env = {**env, "E09_WORKDIR": str(SEEDS), "E09_USER": "seed", "E09_AGENT": "seed-script"}
    replies = []
    ok = True
    with Client([sys.executable, "-m", "e09.mcp"], mcp_env) as client:
        for pattern, abstract in BATCHES:
            docs = sorted(p.relative_to(SEEDS).as_posix() for p in SEEDS.glob(pattern))
            request = {"artifact_doc": docs, "update_abstract": abstract}
            replies.append((f"check {pattern}", client.call("CheckIn", request)))
            ok = _status(replies[-1][1]) == "checked"
            if ok and not args.check_only:
                replies.append((f"confirm {pattern}", client.call("CheckIn", {**request, "confirm": True})))
                ok = _status(replies[-1][1]) == "committed"
            if not ok:
                break
    out = args.out or data / "checkin.txt"
    out.write_text("".join(f"## {phase}\n\n{text}\n\n" for phase, text in replies), encoding="utf-8")
    for phase, text in replies:
        print(f"{phase}: status={_status(text)} {_commit(text)}")
        for line in _summary(text):
            print("  " + line)
    print(f"full replies: {out}")
    return 0 if ok else 1


class Client:
    """最小的 MCP stdio 客户端：初始化后逐个调用工具，回复是工具结果的文本。"""

    def __init__(self, cmd: list[str], env: dict[str, str]) -> None:
        self.cmd, self.env, self.next_id = cmd, env, 0

    def __enter__(self) -> Client:
        self.proc = subprocess.Popen(
            self.cmd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        self._request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t1-seed-checkin", "version": "1"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def __exit__(self, *exc: object) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=60)

    def call(self, tool: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        return "\n".join(c.get("text", "") for c in result.get("content", []))

    def _request(self, method: str, params: dict) -> dict:
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP server exited during {method}")
            msg = json.loads(line)
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]

    def _send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()


def _status(text: str) -> str | None:
    m = re.search(r"^status: (\w+)", text, re.M)
    return m[1] if m else None


def _commit(text: str) -> str:
    m = re.search(r"^commit: (\S+)", text, re.M)
    return m[1] if m else ""


def _summary(text: str) -> list[str]:
    """每份文档的动作与产物 id，以及错误与按规则计数的警告；从回复文本中按行取，不解析 YAML。"""
    out, doc = [], None
    counts: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        if m := re.match(r"^\s*-?\s*doc: (\S+)", line):
            doc = m[1]
            counts[doc] = {}
            out.append(doc)
        elif doc and (m := re.match(r"^\s*(action|artifact|version): (\S+)", line)):
            out[-1] += f" {m[1]}={m[2]}"
        elif doc and (m := re.match(r"^\s*-?\s*rule: (\S+)", line)):
            counts[doc][m[1]] = counts[doc].get(m[1], 0) + 1
        elif re.match(r"^errors:", line):
            out.append("errors present; see the full reply")
    return [f"{o} rules={counts.get(o.split()[0], {})}" if o.split()[0] in counts else o for o in out]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check-only", action="store_true", help="only check; write no artifact")
    p.add_argument("--out", type=Path, help="file for the full MCP replies")
    return p


if __name__ == "__main__":
    sys.exit(main())
