"""在一次性 Neo4j 上种入锚点与两篇种子论文，再检入种子产物（只用标准库与 t1）：先是 ../leaderboards/ 的全部 Leaderboard
（一个提交，id 按文件名顺序为 art_0001…），再是 ../skills/*/SKILL.md（另一个提交）。

按 evaluation_draft §10.1，这里不 import paperweave：种库用系统的命令行
（``python -m paperweave <文档> --source ... --apply``），检入用 MCP 入口（``python -m paperweave.mcp``，子进程；
批次与身份见 :mod:`pweval.harness.seeding`，与运行框架的 A3 起点相同）。论文材料复制到临时目录，作为
``PAPERWEAVE_DATA``。

    PAPERWEAVE_NEO4J_URI=bolt://localhost:7692 .venv/bin/python eval/seeds/scripts/checkin.py [--check-only]

库必须是空的一次性库：长期使用的库（7687 neo4j-e09、7688、7689 neo4j-t1）一律拒绝。需要向量服务（``EMBED_URL``），
关闭向量时只按词面去重，会给出错误的候选。MCP 的完整回复写到 ``--out``（默认临时目录），这里只打印摘要。
退出码：0 检入成功（或 ``--check-only`` 时检查通过）；1 种库或检入失败。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from pweval.harness.mcp_client import field, status
from pweval.harness.seeding import check_in

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "data/raw/t1-pilot-corpus"
PAPERS = ["2012.07436v3", "2106.09305v3"]
SEED_DOCS = [  # (入库文档, 来源标签, 额外参数)；与先导配置的检查点 0 相同
    ("00-anchors.yml", "seed:t1-anchors", ["--no-dedup"]),
    ("01-2020-Informer.yml", "paper:2020-Informer", []),
    ("02-2021-SCINet.yml", "paper:2021-SCINet", []),
]
LONG_LIVED_PORTS = {7687, 7688, 7689}


def main() -> int:
    args = _parser().parse_args()
    uri = os.environ.get("PAPERWEAVE_NEO4J_URI", "")
    port = urlparse(uri).port
    if not uri or port in LONG_LIVED_PORTS:
        refused = sorted(LONG_LIVED_PORTS)
        print(f"error: set PAPERWEAVE_NEO4J_URI to a throwaway Neo4j (got {uri or 'nothing'}; {refused} refused)")
        return 1
    data = Path(tempfile.mkdtemp(prefix="t1-seed-data-"))
    for paper in PAPERS:
        shutil.copytree(CORPUS / "papers" / paper, data / "papers" / paper)
    env = {**os.environ, "PAPERWEAVE_DATA": str(data)}

    for doc, source, extra in SEED_DOCS:
        run = subprocess.run(
            [sys.executable, "-m", "paperweave", str(CORPUS / "docs" / doc), "--source", source, "--apply", *extra],
            env=env, capture_output=True, text=True,
        )
        print(f"seed {doc}: rc={run.returncode} status={status(run.stdout) or '?'}")
        if run.returncode != 0:
            print(run.stdout[-2000:], run.stderr[-2000:], sep="\n")
            return 1

    ok, replies = check_in(env, confirm=not args.check_only)
    out = args.out or data / "checkin.txt"
    out.write_text("".join(f"## {phase}\n\n{text}\n\n" for phase, text in replies), encoding="utf-8")
    for phase, text in replies:
        print(f"{phase}: status={status(text)} {field(text, "commit") or ""}")
        for line in _summary(text):
            print("  " + line)
    print(f"full replies: {out}")
    return 0 if ok else 1


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
