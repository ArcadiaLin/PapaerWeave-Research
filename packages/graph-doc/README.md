# graph-doc

graph-doc 是读写同形的 YAML 子图：Agent 读到的视图是一份 graph-doc，写入时交回的也是 graph-doc。本包负责与数据模型无关的两层：

1. **语法**（`graph_doc.document`）：把文本解析成 `Document`，检查顶层结构、字段拼写、取值类型与文档内引用。
2. **求差**（`graph_doc.fragment`）：把上层翻译出的物理目标状态与库中现状比对，得到 [graph-vc](../graph-vc) 的变更集。

`kind`、`aliases`、`material`、端点规则、查重等属于数据模型，由上层（PaperWeave）把 `Document` 翻译成物理目标状态时处理。格式设计见 `docs/experiments/e09/operators/commit.md` §2–§3。

## 语法

```python
from graph_doc import parse

doc = parse(text)  # 不合法时抛 DocError，problems 列出全部问题及位置
doc.nodes["$patchtst"].props["name"]
doc.nodes["$exp"].rels["EVALUATES"][0].to, doc.nodes["$exp"].rels["EVALUATES"][0].props
doc.deleted(), doc.temp_refs()
```

| 顶层键 | 含义 |
| --- | --- |
| `graph-doc` | 格式版本，必填，目前为 `v0.1` |
| `meta` | 读视图的说明；写入时忽略 |
| `by` | 写入者 |
| `confirm` | 写入时的确认，内容由上层解释 |
| `nodes` | 节点，键是已有 id 或 `$` 开头的临时引用；值为 `null` 表示删除 |

字段类别看拼写：小写是属性，全大写是出边（值为列表，元素是引用或 `{to: 引用, <边属性>…}`），`_` 开头是只读字段（原样保留，交给上层比对）。属性值为 `null` 表示清除；没写的字段不动。

文档内检查：临时引用必须在 `nodes` 中定义；临时引用不能写 `null`；不能向本文档删除的节点连边；同一关系键中同一目标只能出现一次；属性值只能是标量或同类型标量的列表。

YAML 按 1.2 核心模式解析标量，并禁止重复键：只有 `null`、`true` / `false`、十进制整数与有限浮点数会转换类型，`2026-10-04T15:30:00Z`、`yes`、`on`、`12:30` 等都保持为字符串。

## 求差

```python
from graph_doc import Fragment, FragmentNode, diff

fragment = Fragment(
    nodes={
        "$patchtst": FragmentNode(
            labels=frozenset({"Concept", "Method"}),
            props={"name": "PatchTST"},
            rels={"BROADER": {"method_0004": {}}},
            new=True,
        ),
        "method_0016": FragmentNode(props={"note": None}),  # 清除一个属性
        "exp_0001": FragmentNode(rels={"EVALUATES": {"method_0016": {"role": "baseline"}}}),
    },
    deletes=frozenset({"method_0021"}),
)
fragment = fragment.rename({"$patchtst": graph.allocate_ids("method")[0]})
changeset = diff(fragment, graph.local_state(fragment.ids()))  # 目标不可能成立时抛 DiffError
graph.commit(changeset, author="claude", source="commit-tool")
```

- 属性与边属性：写了就设置，`None` 就清除，没写就不动；与现值相同的不算改动。
- Label：给出时整组替换，`None` 表示不动。
- 关系：`rels` 的每个类型是该类型出边的完整集合，多出的新建、缺少的删除；没写的类型不动。
- `new=True` 的节点必须给 Label，且 id 尚未被占用；其余节点必须已存在。关系的终点必须已存在或在本次新建，且不能是本次删除的节点。
- 删除节点时自动删除它的全部入边与出边。
- 求差在事务之外。若读取现状之后库被改动，提交时 graph-vc 核对改前状态，抛出 `ConflictError`。

## 测试

```bash
uv run pytest packages/graph-doc     # 数据库往返测试在未配置时跳过
GRAPH_VC_TEST_NEO4J_URI=bolt://localhost:7688 uv run pytest packages/graph-doc   # 要求测试库为空，见 graph-vc 的 README
```
