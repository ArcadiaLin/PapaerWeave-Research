# E09 测试的运行方法

> **记录日期：** 2026-10-08。本文面向执行测试的 Agent，也供人工参考。它说明怎样运行 `packages/graph-vc`、`packages/graph-doc` 与 `system` 的测试，以及怎样让默认配置的 pi 经 MCP 实际使用 E09 的工具。命令都从仓库根目录执行，除非另行说明。

## 0. 先读这一节

测试分三层，越往后越接近真实使用，副作用也越大：

| 层 | 内容 | 需要 | 副作用 |
| --- | --- | --- | --- |
| A | 不连库的单元测试与 ruff（第 3 节） | 仓库的 `.venv` | 无 |
| B | 连库测试（第 4 节） | 一个**空的**一次性 Neo4j 实例 | 清空所连的库 |
| C | pi 实际运行（第 6 节） | 7688 上的试跑数据、模型服务、向量服务 | pi 的每次运行都会向 7688 写入 |

执行测试的 Agent 必须遵守：

1. **不要让任何东西写入 neo4j-e09（bolt 7687）。** 连库测试的环境变量不要指向它；生成 pi 实验目录时必须显式写 `--neo4j-uri bolt://localhost:7688`，因为默认值是 7687。
2. **不要清空 7688，也不要对它执行 `docker compose down`。** 它没有挂载数据卷，删除容器会丢失试跑数据。
3. **pi 的实验目录放在仓库之外**（`~/e09-runs/` 下）。会话记录不进 git，运行结束后也不要删除实验目录。
4. **不改 pi 的配置。** 不替换系统提示，不限制工具，不加 `--no-context-files` 之类的选项。实验只控制工作目录（AGENTS.md 中"general agent via MCP"一段）。
5. **改动知识本身的运行要先征得用户同意。** 这类运行用 `--enable-commit`，Agent 会调用 `Commit`。
6. **只报告结果，不写文档。** 结果写进回复；不要新建 `docs/experiments/` 下的记录，不改 `docs/progress.md`。
7. **`pi` 后面的参数如果不是它认识的子命令，会被当作提示词。** 例如 `pi --approve mcp list` 会启动模型去回答"mcp list"。只有第 6.4 节列出的写法可以用。

## 1. 测试的组成

| 测试集 | 不连库，随时可跑 | 连库，需要空的测试实例 |
| --- | --- | --- |
| `packages/graph-vc` | 45 个：变更集、内存状态 | 15 个：`tests/test_store.py`（提交、回滚、重放、可逆、`state_at` 等） |
| `packages/graph-doc` | 54 个 | 2 个：`tests/test_roundtrip.py` |
| `system` | 105 个：写入管线的内存场景、MCP 装配、工具接口、参数修复、读取接口（`tests/interfaces/`，用内存中的版本历史） | 101 个：`tests/commit/` 的往返与命令行、`tests/operators/db/`、`tests/operators/agent/` |

数量是 2026-10-08 不设置测试实例时的结果（通过与跳过）。

连库测试只在设置了环境变量 `GRAPH_VC_TEST_NEO4J_URI` 时运行，没有设置时跳过。用户名与密码默认为 `neo4j` / `password`，可用 `GRAPH_VC_TEST_NEO4J_USER`、`GRAPH_VC_TEST_NEO4J_PASSWORD` 改。连库测试不需要向量服务：查询向量关闭，写入后也不补算。

以下连库测试是 2026-10-07 至 10-08 新增的，**还没有在 Neo4j 上运行过**。第一次运行就是对它们的检验：

- graph-vc `test_state_at_is_the_state_after_each_commit`：逆向重放求出的每个提交时的状态，等于从空状态正向重放的结果；
- system `test_db_evidence.py::test_at_resolves_references_in_a_past_state`：ReadEvidence 的 `at`；
- system `test_db_traverse.py::test_snapshot_is_the_head_the_view_was_read_at` 与 `test_db_search.py::test_snapshot_is_the_head_the_results_were_read_at`：读取前后核对头提交。

## 2. 安全约定

- **连库测试会清空所连的库。** 每个连库测试模块开始时要求库为空，结束时删除全部节点；e09 的模块还会删掉全部约束与索引。
- **库不空时拒绝运行。** 开始时库中有节点，测试就跳过，原因是 `refusing to run: test database at … is not empty`，不会删除数据。误连到有数据的库只会全部跳过，不会造成损失；但"全部跳过"也不代表通过，要用 `-rs` 查看跳过原因。
- **不要连 neo4j-e09（bolt 7687）。** 它是实验用的库。测试不会主动连它，环境变量也不要指向它。
- **infra/neo4j-test（bolt 7688）不是空库。** 里面是 MCP 试跑写入的数据。2026-10-08 时它有 370 个节点、32 个提交，头提交为 `commit_000032`；2026-10-07 的备份在 `~/e09-runs/2026-10-06-commit-trial/neo4j-7688-after-trials.json`。连库测试连它只会全部跳过。只停止它（`docker stop neo4j-test`）不会丢数据；`docker compose down` 会。

## 3. 层 A：不连库的检查

不需要 Neo4j，随时可以运行：

```bash
.venv/bin/python -m pytest packages/graph-vc packages/graph-doc -q
(cd system && ../.venv/bin/python -m pytest tests -q)
(cd system && uvx ruff check src tests && uvx ruff format --check src tests)
uvx ruff check packages/graph-vc && uvx ruff format --check packages/graph-vc
```

期望结果：graph-vc 与 graph-doc 共 99 个通过、17 个跳过；system 105 个通过、101 个跳过；ruff 无报告。`.venv` 不存在时在仓库根目录运行 `make setup`；不要在成员目录里运行 `uv sync`（见 AGENTS.md）。

## 4. 层 B：在一次性实例上运行连库测试

用与 infra/neo4j-test 相同的镜像，另起一个端口不冲突的容器（bolt 7689，浏览器 7476）。它用完即删，不影响 7687 与 7688。

```bash
# 1. 启动；--rm 表示停止后容器连同数据一起删除
docker run -d --rm --name neo4j-test-run \
  -p 7476:7474 -p 7689:7687 -e NEO4J_AUTH=neo4j/password neo4j:ubi10

# 2. 等到 Neo4j 启动完成（日志出现 Started.）
until docker logs neo4j-test-run 2>&1 | grep -q "Started."; do sleep 2; done

# 3. 依次运行三个测试集；-rs 列出跳过的测试及原因
export GRAPH_VC_TEST_NEO4J_URI=bolt://localhost:7689
.venv/bin/python -m pytest packages/graph-vc -q -rs
.venv/bin/python -m pytest packages/graph-doc -q -rs
(cd system && ../.venv/bin/python -m pytest tests -q -rs)

# 4. 停止，容器与数据一并删除
docker stop neo4j-test-run
```

当前用户不在 docker 组时，把 `docker` 换成 `sudo docker`。system 的第 3 步也可以写成 `make -C system test`，它执行 `uv run pytest tests -q`，不加 `-rs`。

**期望结果：** 三个测试集都没有跳过，全部通过：graph-vc 60 个，graph-doc 56 个，system 206 个。

**各测试集依次运行，不要并行。** 每个模块都要求开始时库为空，并行运行会互相看到对方的数据。一个模块中途失败、没有清空时，之后的模块会因库不空而跳过。这时停止容器，重新执行第 1 步，再从失败的测试集重跑。

## 5. 用 7688 运行连库测试（暂不推荐）

只有 7688 可用时，要先备份其中的试跑数据，清空后运行测试，再恢复。2026-10-06 做过这样一轮，但所用的导出、清空与恢复脚本只是临时脚本，不在仓库中。若要这样做，先与用户商定把备份脚本放进仓库（例如放在 `infra/neo4j-test/`），恢复后用摘要核对与备份一致。在此之前请用第 4 节的方式。

## 6. 层 C：用 pi 实际运行

这一层检查默认配置的 pi 能否只靠 MCP 工具说明，用 E09 的工具完成任务：

- 工具能否被发现、调用；
- 参数能否通过核对；
- 结果是否在 pi 的 20 KB 上限内；
- 写入是否留下可追溯的提交。

它是功能检查，不是评测。基准任务与质量标准尚未商定（AGENTS.md），这里的任务不能当作评测结论。

### 6.1 前提

| 项目 | 2026-10-08 的情况 | 检查方法 |
| --- | --- | --- |
| pi | 1.0.3，在 nvm 的 node 24 下；MCP 由 pi 内置的扩展加载 | `pi --version` |
| 模型 | pi 的默认模型 `sglang/qwen3.8-27b`，thinking 为 `high`（`~/.pi/agent/settings.json`） | `pi --list-models qwen`；模型服务不通时 pi 会直接报错 |
| 数据 | 7688 上 MCP 试跑的数据：114 个对象（Entity 39，含 6 篇论文；Concept 50；Content 25）与 26 个 Artifact，都已有向量 | 见第 6.3 节 |
| 向量服务 | `EMBED_URL`，默认 `http://192.168.163.112:8002/v1/embeddings`；Resolve 的语义阶段与 Search 的语义通道要用 | 服务不通时，这两处在结果中显示为失败的通道（Search 的 `meta.failed`），不影响其余工具 |
| 论文材料 | `data/raw/e09-paper-knowledge/`（ReadEvidence 按 Material 节点登记的路径与哈希读取） | 不需要单独检查 |

向量服务暂时不可用时，可以在生成目录时加 `--no-embed`，关闭查询向量，写入后也不补算。用了这个选项要在报告中注明。不要为补算向量对 7687 执行 `make embed`。

### 6.2 生成实验目录

每一轮用一个新目录，按日期与用途命名。只读的轮次与写入知识的轮次分开：

```bash
# 只读与 Agent 算子（Extract、Generate 等仍会写入 Artifact）
make -C system workspace DIR=~/e09-runs/2026-10-08-history-read \
  ARGS="--neo4j-uri bolt://localhost:7688"

# 写入知识：列出 Commit；先征得用户同意
make -C system workspace DIR=~/e09-runs/2026-10-08-history-commit \
  ARGS="--neo4j-uri bolt://localhost:7688 --enable-commit"
```

目录里只有三样东西：

- `.pi/mcp.json`：登记 `PaperWeave` 服务（`python -m paperweave.mcp`），并写明 `PAPERWEAVE_NEO4J_URI`、`PAPERWEAVE_FORMED_BY` 与日志路径；
- `.pi/settings.json`：把会话存到 `.pi/sessions/`；
- `pi.sh`：在目录中启动 pi。

生成后先确认 `.pi/mcp.json` 中 `PAPERWEAVE_NEO4J_URI` 是 `bolt://localhost:7688`。目录已存在且不空时，生成会拒绝。

**运行时的笔记与输出放在实验目录之外**，例如 `~/e09-runs/2026-10-08-history-read.notes/`。pi 能读写自己的工作目录；以往的试跑中，它用 `ls` 查看过工作目录。放在目录里的东西可能被它读到。

### 6.3 运行前记下库的状态

pi 的每次运行都可能写入。Agent 算子把 Artifact 写成提交，来源记为 `operator:<算子名>`；Commit 写入的来源是 Agent 给出的说明。运行前记下头提交，运行后用读取接口查看这一轮写了什么：

```bash
cd system
PAPERWEAVE_NEO4J_URI=bolt://localhost:7688 ../.venv/bin/python -m paperweave -e '{op: Log, budget: 1}' --no-embed
```

记下输出中的 `meta.at`，即运行前的头提交。这条命令只读。

### 6.4 运行

非交互运行，每个任务一个新会话：

```bash
cd ~/e09-runs/2026-10-08-history-read
timeout 1800 ./pi.sh -p --approve "<任务>" > ../2026-10-08-history-read.notes/T1.out 2>&1
```

- `-p` 处理完提示词即退出。会话按 `.pi/settings.json` 存在 `.pi/sessions/` 中；运行后确认那里多了一个文件。
- `--approve` 本次信任项目目录，`.pi/mcp.json` 才会被加载。不加时 pi 会忽略它，也就没有 PaperWeave 的工具。
- 以往一个任务用时 4 到 18 分钟，`timeout 1800` 足够。可以放在后台运行，等它结束。
- 追问同一会话用 `./pi.sh -p --approve -c "<追问>"`，`-c` 接着最近的会话。
- 人工观察时可以运行 `./pi.sh` 进入交互界面，第一次启动时确认信任目录。

**确认工具已加载：** MCP 服务启动时会在 `.pi/paperweave.log` 写一行：

```text
PaperWeave 0.2.0 (server.yml <摘要>): session mcp-…, formed_by …, bolt://localhost:7688
```

没有这一行，说明服务没有启动或目录没有被信任。工具共 16 个：Search、Resolve、Traverse、ReadEvidence、Extract、Summarize、Generate、Check、Verify、Filter、MatrixConstruct、Log、Show、Diff、AsOf，加 `--enable-commit` 时还有 Commit。不加 `--enable-commit` 时是 15 个。在 pi 中，它们的名字是 `mcp__PaperWeave__<工具名>`。

### 6.5 任务

**任务只描述用户要做的事，不点名工具，也不讲用法。** 怎样使用工具由 MCP 工具说明负责；Agent 选了哪些工具，本身就是要观察的结果。可以说"使用 PaperWeave 知识库"，但不要写"先调用 Log 再调用 Show"。

| 编号 | 任务（原文照用） | 主要检查 | 目录 |
| --- | --- | --- | --- |
| T1 | 请使用 PaperWeave 知识库回答：比较 DLinear 和 PatchTST 在 ETTh1 数据集上预测长度为 96 和 336 时的结果（MSE 与 MAE）。两篇论文报告的这些结果可以直接比较吗？请用表格回答，并注明出处。 | 回归：与 2026-10-06 的 8 次试跑对照（`~/e09-runs/2026-10-06-*`），看工具覆盖与输出大小 | 只读 |
| T2 | PaperWeave 知识库最近几次提交分别做了什么？最近一次提交具体改动了哪些对象、改成了什么？ | Log、Show（`summary` 与 `changes`） | 只读 |
| T3 | PaperWeave 知识库从 commit_000022 到现在有哪些变化？其中新增的 Observation 依据的是什么，原文怎么说？ | Diff、Traverse 或 AsOf、ReadEvidence；结果分页与续取 | 只读 |
| T4 | 在 PaperWeave 知识库中，claim_0001 是哪一次提交写入的、由谁写入、当时依据了什么？在 commit_000031 时，obs_0002 已经存在了吗？ | Log 的 `node` 过滤、Show、AsOf 的 `missing` | 只读 |
| T5 | 请使用 PaperWeave 知识库，为 DLinear 与 PatchTST 在 ETTh1 上的比较补充一条你核实过的记录并写入知识库，然后告诉我这次写入具体改了什么。 | Commit 的 dry_run 与 apply，写入后用 Show 或 Diff 查看自己的提交 | 写入，需同意 |

T2 至 T4 中的提交与对象 id 是 7688 在 2026-10-08 的状态：claim_0001 写于 `commit_000027`，obs_0001 与 obs_0002 写于 `commit_000032`。这段历史里只有新建，没有修改或删除，所以 Diff 中的 `update` 与 `delete` 要等 T5 这样的写入之后才看得到。库变化后，先运行第 6.3 节的 Log 命令，再按需换成实际存在的 id。T1 用中文；以往试跑也用过英文版本，需要对照时可以照用：

> Using the PaperWeave knowledge store: compare DLinear and PatchTST on ETTh1 at prediction lengths 96 and 336 (MSE and MAE). Can the results reported by the two papers be compared directly? Answer with a table and cite your sources.

ReadEvidence 的 `at` 只有在材料后来被删除时才看得出作用，7688 上没有这样的材料。这一项由层 B 的测试覆盖，层 C 中出现了就记下，不专门构造。

### 6.6 运行后核对

**会话记录。** `.pi/sessions/*.jsonl` 每行一条记录：

- `message.role` 为 `assistant` 时，`content` 中 `type: toolCall` 的项是工具调用（`name`、`arguments`）；
- `message.role` 为 `toolResult` 时是工具结果（`toolName`、`content`、`isError`）。

下面的片段按顺序列出调用，并标出错误、超过 20 KB 被截断的结果，以及 MCP 之外的工具调用：

```bash
python3 - ~/e09-runs/2026-10-08-history-read/.pi/sessions/*.jsonl <<'EOF'
import json, sys
for path in sys.argv[1:]:
    print("==", path)
    for line in open(path, encoding="utf-8"):
        m = json.loads(line).get("message") or {}
        if m.get("role") == "assistant":
            for c in m.get("content", []):
                if c.get("type") == "toolCall":
                    name = c["name"].removeprefix("mcp__PaperWeave__")
                    print("call  ", name, json.dumps(c.get("arguments"), ensure_ascii=False)[:160])
        elif m.get("role") == "toolResult":
            text = json.dumps(m.get("content"), ensure_ascii=False)
            flags = ["ERROR"] * bool(m.get("isError")) + ["TRUNCATED"] * ("Warning: truncated output" in text)
            print("result", m.get("toolName", "").removeprefix("mcp__PaperWeave__"), len(text.encode()), *flags)
EOF
```

逐项检查：

- **工具调用。**
  - 调用了哪些工具，有没有该用而没用的（例如 T2 没有调用 Show）？
  - `isError` 的结果是什么错误？是参数写错、工具说明不清，还是实现问题？
- **输出大小。** 出现 `TRUNCATED` 说明结果超过了 pi 的 20 KB 上限：pi 截掉中间部分，完整内容存到临时文件。读取接口、Search 与 Traverse 都按 16 KB 控制，出现截断就是需要报告的问题。ReadEvidence 目前没有容量控制，引用多时可能超过上限，这一项已知。
- **绕过中间件的读取。** `bash`、`read` 等内置工具的调用逐条看。读取 `data/raw/e09-paper-knowledge/` 或仓库中的论文材料就是绕过了中间件。评测不禁止这样做，但要记录（AGENTS.md）。
- **服务日志。** `.pi/paperweave.log`：
  - 每次调用一行 `<会话> <工具> <状态>`，状态为 `ok`、`rejected`、`blocked` 或 `conflict`；
  - `repaired` 行是服务替 Agent 修复的参数格式，例如数组被当作字符串传来；
  - 第一行的 `server.yml` 摘要标明这一轮用的工具说明版本。
- **写入。** 运行后用第 6.3 节的命令，加上 `since: <运行前的头提交>`，列出这一轮的提交：

  ```bash
  cd system
  PAPERWEAVE_NEO4J_URI=bolt://localhost:7688 ../.venv/bin/python -m paperweave \
    -e '{op: Log, since: commit_000032}' --no-embed
  ```

  `by` 是写入者：Agent 算子的提交为 `PAPERWEAVE_FORMED_BY`（如 `sglang/qwen3.8-27b`），Commit 的提交为 Agent 自己填写的名字。需要细看时用 `{op: Show, commit: <id>, part: changes}`。T1 至 T4 不应出现 `source` 不是 `operator:…` 的提交，否则说明没有 Commit 的目录也写入了知识。
- **回答内容。** 回答中的数值与结论要对照它引用的原文核实，可以用 `{op: ReadEvidence, source_refs: [...]}` 读出。回答流畅、引用格式正确，都不说明内容正确。

### 6.7 报告

在回复中给出：

- 实验目录、所用的选项（`--enable-commit`、`--no-embed`），以及服务日志第一行；
- 每个任务的工具调用序列、错误与截断、MCP 之外的调用；
- 运行前后的头提交与这一轮的提交列表；
- 回答内容核实的结果；
- 工具说明或实现中值得改的地方，附会话记录中的位置。

实验目录保留在 `~/e09-runs/`。是否把第 6.6 节的片段整理成仓库中的脚本，待与用户讨论后再定。

## 7. 与真实历史的只读核对

读取接口在 2026-10-07 另做过一次只读核对，用的是 7687 与 7688 的真实历史：

- `AsOf(main)` 与 Traverse 的视图逐对象一致；
- `Show` 的 `input` 分页可以拼回原文；
- `Diff(父提交, 提交)` 等于 `Show(提交, changes)`；
- 所有输出都不超过 16 KB。

核对结果记在提交 `b793426` 的说明中。所用脚本是临时的，不在仓库中；是否把它整理成仓库中的检查脚本，待讨论后再定。
