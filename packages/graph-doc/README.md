# graph-doc

graph-doc 是对图的一组改动，借用 Cypher 的动词写成 YAML：`create`、`set`、`delete`。读取结果的节点与 `set` 下的节点同形，原样贴回不产生改动。本包负责与数据模型无关的两层：

1. **语法**（`graph_doc.document`）：把文本解析成 `Document`，检查顶层结构、字段拼写、取值类型与文档内引用。
2. **求差**（`graph_doc.fragment`）：把上层翻译出的物理目标状态与库中现状比对，得到 [graph-vc](../graph-vc) 的变更集。

`kind`、`alias`、`paper`、`extra`、端点规则、查重等属于数据模型，由上层（PaperWeave）把 `Document` 翻译成物理目标状态时处理。格式设计见 `docs/designs/v3/tools.md`。

## 语法

```python
from graph_doc import parse

doc = parse(text)  # 不合法时抛 DocError，problems 列出全部问题及位置
doc.create["$patchtst"].props["name"]
doc.create["$exp"].rels["EVALUATES"]["method_0021"].props   # {"role": "baseline"}
doc.set["exp_0042"].props, doc.delete["exp_0042"]           # 删除：None 是整个节点，否则 {类型: [终点]}
```

| 顶层键 | 含义 |
| --- | --- |
| `graph-doc` | 格式版本，必填，`v0.2` |
| `create` | 新建：键是 `$` 名（新节点：字段与出边），或已有 id（只写要新建的出边） |
| `set` | 修改：键是已有 id；只改写到的字段与边属性，`null` 清除，没写的不动 |
| `delete` | 删除：键是已有 id；值为空删除节点及其全部边，值为 `{类型: [终点]}` 只删这些边 |
| `confirm` | 写入时的确认，内容由上层解释 |

字段类别看拼写：小写是属性，全大写是出边，`_` 开头是只读字段（写入时忽略）。关系键下是 `{终点: 边属性}` 的映射，边没有属性时可写成终点的列表。属性值可以是标量、标量的列表或一层映射（如 `extra`）。

文档内检查：`$` 名只在 `create` 中定义；`set`、`delete` 的键不能是 `$` 名；`create` 中的已有 id 不能带字段；被整体删除的节点不能出现在别处；同一条边只能出现在一节中。动词与库中现状是否相符（`create` 的边不能已存在，`set` 的节点与边必须存在）由上层检查。

YAML 按 1.2 核心模式解析标量，并禁止重复键：只有 `null`、`true` / `false`、十进制整数与有限浮点数会转换类型，`2026-10-04T15:30:00Z`、`yes`、`on`、`52:58` 等都保持为字符串。

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
        "method_0016": FragmentNode(props={"note": None}, edge_deletes=frozenset({("BROADER", "method_0002")})),
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
- 关系：`rels` 中列出的边，不存在的新建、已存在的更新边属性；没列出的不动。要删的边列在 `edge_deletes` 中。
- `new=True` 的节点必须给 Label，且 id 尚未被占用；其余节点必须已存在。关系的终点必须已存在或在本次新建，且不能是本次删除的节点。
- 删除节点时自动删除它的全部入边与出边。
- 求差在事务之外。若读取现状之后库被改动，提交时 graph-vc 核对改前状态，抛出 `ConflictError`。

## 测试

```bash
uv run pytest packages/graph-doc     # 数据库往返测试在未配置时跳过
GRAPH_VC_TEST_NEO4J_URI=bolt://localhost:7688 uv run pytest packages/graph-doc   # 要求测试库为空，见 graph-vc 的 README
```
