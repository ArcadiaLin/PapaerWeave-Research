# 数据模型 V3

> **状态：** 草案（2026-10-16），待用户审阅；未实现。V3 依据冒烟与先导运行（smoke-p3-1、pilot3-multi、pilot3-single）中写者与读者的实际用法修订 [Graph Model V2](../v2/graph_model_v2.md)，基础设计不变：图存轻度提炼、原文锚点与关联，不转录原文；有据层与解释层分开；产物是有版本的文档。本文只覆盖数据模型，工具见 [工具](./tools.md)；其余 V2 文档暂不迁移，与本文冲突处以本文为准。
>
> 标 **〔待确认〕** 的是本稿提出、尚未与用户确认的改动。

## 总览：三类证据节点

每类给出一组基础字段（元模型），各 kind 在此之上只加自己的属性。三类按身份怎样确定来划分：

| 类别 | 是什么 | 身份 |
| --- | --- | --- |
| Entity | 有外部标识的资源 | 外部标识（DOI、arXiv、仓库地址）加名称 |
| Concept | 许多论文共同指向、没有外部标识的概念 | 只有名称与描述，最容易误合并 |
| Content | 某篇论文在某处说的话 | 附锚点；内容相似也不合并 |

带 `[]` 的是列表字段。所有节点另有写者在新建时给出的 `kind`，以及系统字段：

- `id`：无语义标识，如 `paper_0012`
- `formed_by`：创建者，入图时按写者的认证身份自动生成
- `formed_at`：创建时间

`formed_by`、`formed_at` 只在新建时写入，以后不变；补全桩不改变它们。谁在什么时候修改过节点，由提交记录推算。

- **Entity**：资源对象
  - `name` 必填
  - `alias[]`
  - `identities[]`
  - `description`
  - `extra`
- **Concept**：共享概念
  - `name` 必填
  - `alias[]`
  - `description` 必填
  - `extra`
- **Content**：来源化内容
  - `paper` 必填
  - `anchor[]` 必填
  - `description` 必填
  - `extra`

## 各 kind

每个 kind 继承所属类别的字段，下面只列它的含义和自己多出的属性。

- **Entity**
  - `Paper`：论文的书目对象
    - `year`：发表年份
    - `material`：论文 Markdown 文件；换成新文件即为论文的新版本
  - `Dataset`：数据本身
  - `Code`：代码仓库
  - `Model`：权重、checkpoint 或经 API 调用的模型
  - `Tool`：不是模型的软件、库或服务
  - V2 的 `Benchmark` 并入 `Dataset`：常见的 benchmark 就是"数据集加任务"；有名称的评测套件记为一个 Dataset 集合节点（见 Dataset）
  - 所有 Entity 都可以建桩：`stub: true`，被引用但尚未入库，只要求 `name`
- **Concept**
  - `Method`：方法方案或方法类别；变体与配置不建节点；可以建桩
  - `Task`：研究任务；可以建桩
  - `Issue`：研究问题，`name` 写问题的短标题；当前论文表单不写
- **Content**
  - `Experiment`：论文报告的一组实验（一个研究问题）
    - `figures[]`：涉及的表和图，如 `[S4.T3, A1.T8]`，第一个是主表图，参与查重（V2 的 `anchors`）
  - `Claim`：论文作者的一条主张，补齐必要上下文
  - `Contribution`：论文自述的一项贡献
  - Content 全部属于有据层：都来自论文、都带锚点。agent 自己的判断不写成证据节点，写进产物

### Entity

这一章节记录每个kind 具体的结构，就比如 extra_metadata 可能以什么样的方式表现

公共字段的写法（各 kind 下不再重复，只写例子）：

- `name`：主称呼，一个值
- `alias[]`：其他称呼；与 `name` 一起作精确查找与查重
- `identities[]`：外部标识，写作 `<命名空间>:<值>`
  - 命名空间：`arxiv`、`doi`、`s2`、`url`
  - `arxiv`、`doi`、`s2` 全库唯一，撞上已有节点即为同一对象
  - `url` 不要求唯一：同一仓库可以同时发布数据集、代码与模型
- `description`：这个资源是什么、做什么用；不写某篇论文怎样用它
- `extra`：有就写、方便知道才写的附加信息，键值对，键可以自由扩展
  - 例（写成块格式，不写成行内 `{...}`：pilot3 的格式错误多出在行内映射里的文字上）：

    ```yaml
    extra:
      venue: ICLR 2024
      authors: [Yong Liu, Tengge Hu]
      cited_as: "[38] Wu, Xu, Wang and Long"
    ```
  - 按键合并：只改写到的键，某个键写 `null` 即删除
  - 不进检索，不作过滤条件；只在查看节点完整信息时全部返回
  - 存为一个 JSON 字符串属性
- `stub: true`：桩，只要求 `name`；以后补全时只填空字段并去掉 `stub`

- **Paper**
  - `name`：论文标题，例 `iTransformer: Inverted Transformers are Effective for Time Series Forecasting`
  - `alias[]`：一般不写
  - `identities[]`：例 `[arxiv:2310.06625, url:https://openreview.net/forum?id=JePfAI8fah]`
  - `description`：论文摘要；桩不写
  - `year`：发表年份，例 `2024`；用于过滤与排序，所以不放进 `extra`
  - `material`：论文 Markdown 文件的路径；换成新文件即为论文的新版本；桩没有
  - `extra` 常用键：`venue`（例 `ICLR 2024`）、`authors`（按论文顺序）、`cited_as`（桩在参考文献中的写法）
- **Dataset**
  - `name`：例 `ETT`；子集单独建节点（如 `ETTh1`），用 `PART_OF` 指向 `ETT`
  - `alias[]`：例 `[ETDataset, Electricity Transformer Temperature]`
  - `identities[]`：例 `[url:https://github.com/zhouhaoyi/ETDataset]`
  - `description`：数据是什么、来源、时间范围、变量；例 "Electricity transformer data from July 2016 to July 2018 … 7 variables …"
  - `extra` 常用键：`domain`（例 `energy`）、`frequency`（采样间隔，例 `1h`、`15min`）
  - 有名称的评测套件（V2 的 Benchmark，如 `TFB`）也是 Dataset：`identities[]` 例 `[arxiv:2403.20150]`；成员数据集用 `PART_OF` 指向它；发布者规定的评测流程写进 `description`
- **Code**
  - `name`：仓库名，例 `Time-Series-Library`
  - `identities[]`：例 `[url:https://github.com/thuml/Time-Series-Library]`
  - `description`：仓库实现了什么
  - 无独有属性；不记代码版本
  - 论文表单记下论文发布的代码仓库：按论文给出的地址建节点，用 `IMPLEMENTS` 指向论文的方法；不读仓库内容。pilot3 中没有 Code 节点
- **Model**
  - `name`：例 `TimesFM-1.0-200M`
  - `identities[]`：例 `[url:https://huggingface.co/google/timesfm-1.0-200m]`
  - `description`：哪个方法的哪份权重、怎样获取
  - 无独有属性；方案本身是 Method，模型用 `IMPLEMENTS` 指向它
- **Tool**
  - `name`：例 `Optuna`
  - `identities[]`：例 `[url:https://github.com/optuna/optuna]`
  - `description`：做什么用
  - 无独有属性
### Concept

公共字段的写法：`name`、`alias[]`、`extra`、`stub` 同 Entity，只列不同处。

- `name`：方法名、任务名，或问题的短标题
- `description` 必填：它是什么（V2 的 `definition`）；不写某篇论文怎样用它；桩不写
- 没有 `identities[]`：身份只靠 `name` 与 `alias[]` 的精确匹配；`description` 相似的已有节点只列给写者判断，不自动合并
- `stub: true`：只有 Method、Task 可以建桩

- **Method**
  - `name`：例 `Informer`
  - `alias[]`：例 `[vanilla Transformer]`（对 `Transformer`）
  - `description`：例 "A Transformer-based encoder-decoder model for long sequence time-series forecasting that replaces canonical self-attention with ProbSparse self-attention …"
  - 粒度：方法方案或方法类别；组件需要单独建节点时（如 `ProbSparse self-attention`），用 `RELATES_TO` 相连并说明；变体与配置（如 `PatchTST/64`）不建节点，写在实验的 `description` 中
  - 桩：论文中的基线方法多是桩，只写 `name`
  - `extra` 常用键：`cited_as`（桩在参考文献中的写法）
- **Task**
  - `name`：例 `Long-term time series forecasting`
  - `alias[]`：例 `[LTSF]`
  - `description`：例 "Time series forecasting with a long forecast horizon (T much larger than 1, typically tens to hundreds of steps)."
  - 更细的任务单独建节点，用 `BROADER` 指向更宽的任务
- **Issue**
  - `name`：问题的短标题，例 `Error accumulation in long-horizon forecasting`
  - `alias[]`：一般不写
  - `description`：问题的陈述，措辞中立，保留范围限定
  - 不建桩；当前论文表单不写

### Content

公共字段的写法：`extra` 同 Entity，只列不同处。

- `paper` 必填：所属论文的 id，一个值
  - 系统存成指向该论文的 `FROM` 边，不存属性
  - 边上记下写入时论文的当前材料版本；论文以后出了新版本，旧锚点仍指向原来那份材料
- `anchor[]` 必填：原文锚点，只写论文 Markdown 的行号范围 `<起始行>:<结束行>`，例 `[120:135, 210:214]`
  - 行号取自 `read_evidence` 或读原文时看到的行号，从 1 起
  - 系统按 Markdown 标题自动生成每个范围所在的章节，读取时一并返回，例 `4.1 Baselines::120:135`
  - 写入时检查行号不越界
- `description` 必填：内容本身，可独立读懂；不写数值，数值按锚点读原文
- 不查重：内容相似的 Content 可以并存，重复在评测中统计
- 不建桩

- **Experiment**
  - `paper`：例 `paper_0012`
  - `anchor[]`：这组实验在原文中的全部行范围，含正文，例 `[318:342, 655:690]`
  - `figures[]`：例 `[S4.T3, A1.T8]`；第一个是主表图
  - `description`：目的、设计和论文声称的结论，不写数值
  - 查重：`<论文 id>::<主表图>`，同一组实验不会被建两次
  - `extra` 常用键：`caveat`（原文中的问题，如数值照搬自另一篇论文、只有图没有表、印刷错误）
- **Claim**
  - `paper`、`anchor[]`：主张所在的位置
  - `description`：**只写一条主张**，补齐必要上下文，例 "TiDE is more than 10x faster in training than the best Transformer-based baseline on the long-term forecasting benchmarks."
  - 一段原文里有几条主张，就写几个 Claim
- **Contribution**
  - `paper`、`anchor[]`：论文自述贡献的位置，通常在引言末尾
  - `description`：一项贡献，例 "Proposes TiDE, an MLP-based encoder-decoder for long-term forecasting."
  - 提出了哪个方法、数据集等，用 `ABOUT` 指向它们

## 关系

词表由工作负载推出：研究意图 I1–I6 与存储层的机制要用到的语义，才开具名类型；其余语义用 `RELATES_TO` 加说明。每个类型后面写它的依据，写不出依据的不开。

所有边共有的字段，与节点对齐：

- **边**
  - 具名类型，如 `EVALUATES`
  - 身份：（起点, 类型, 终点），不另设 id
  - `anchor[]`：有原文依据的边带
  - `description`：都可以写；`RELATES_TO`、`CITES` 必填
  - `extra`
  - 系统字段：`formed_by`、`formed_at`；带锚点的边另记写入时论文的材料版本

## 各关系

写法 `起点 → 终点`；每个类型继承上面的字段，下面只列它的端点、依据和自己多出的属性。

- **来源**
  - `FROM`：Content → Paper；系统由 `paper` 生成，写者不写
    - 依据：有据层的锚点；论文出新版本后的过时判断
- **实验参与**
  - `EVALUATES`：Experiment → Method、Model、Code、Tool；Experiment 必有
    - `role` 必填：`target` 或 `baseline`
    - `result`：`own`（作者自己跑）、`cited`（引自他文）或 `unstated`
    - 依据：Leaderboard 的行；I3 追溯转引的结果
  - `USES`：Experiment → Dataset 等 Entity
    - `role`：如 `evaluation_data`、`training_data`
    - `printed_as`：论文中印的名字，如 `ECL`
    - 依据：Leaderboard 的身份；别名证据，供查重与审计对齐列名
  - `ON_TASK`：Experiment → Task
    - 依据：Leaderboard 的身份
- **论证**
  - `SUPPORTS`、`OPPOSES`：Experiment、Claim → Claim
    - 依据：I5 核查；C3 分歧，包括论文 B 的实验反驳论文 A 的主张
- **讨论**
  - `ABOUT`：Content → Entity、Concept、Content；Contribution 必有
    - 依据：检索时的邻居名称
- **资源结构**
  - `CITES`：Paper → Paper；`description` 必填：引它做什么
    - 依据：I3，`EVALUATES.result` 为 `cited` 时由它找到出处论文
  - `PART_OF`：Dataset → Dataset
    - 依据：子集与评测套件；检索时展开
  - `IMPLEMENTS`：Code、Model → Method
    - 依据：I1，选方法时找可用的实现
  - `FOR_TASK`：Dataset → Task
    - 依据：数据集适用的任务，供检索与遍历；pilot3 中 12 条
- **概念结构**
  - `BROADER`：Concept → 同 kind 的 Concept
    - 依据：检索时展开下位概念
- **兜底**
  - `RELATES_TO`：任意两个节点；`description` 必填
    - 不参与任何机制，只进检索
- **系统关系**（写者不能写）
  - `USED`：Artifact → 任一节点
  - `NAMES`：名称键 → 有名称的节点
  - `MATERIAL_OF`：材料 → Paper、Artifact

### 写法

- 同一对端点之间，同类关系只有一条；需要两个角色时 `role` 写成列表
- `anchor[]` 的论文取起点所在的论文；起点是 Entity 或 Concept 时另写 `paper`
- `description` 是补充，不替代存储层要用的字段：反复出现、被机制用到的信息做成字段
  - pilot3 中 `EVALUATES` 的 305 条说明，约 270 条是"自己跑 / 引自他文 / 未说明"之一，所以改为 `result`
  - `USES` 的说明多是"论文中印作 ECL"，所以改为 `printed_as`
- 检索：`description` 加两端名称进关系全文索引，`description` 进关系向量索引；没有 `description` 的边不进索引
- `RELATES_TO`
  - 写者不能自造类型名，词表外的语义都用它；同一种说明反复出现，是给它开类型的信号
  - 端点恰好符合某个具名类型时（如 Experiment → Dataset），`commit` 提示是否应为该类型
  - 使用比例与集中的端点组合作为评测的观测量（评测草案 §4.3"写入内容装不进类型的次数及去向"）
- 词表的位置：满足本工作负载的最小结构，不是对领域的完整刻画；够不够由 E2 与 `RELATES_TO` 的使用比例检验
  - 对照：Graphiti 的边全是 `RELATES_TO` 加一句 LLM 写的事实，存储层无法据以行事；ORKG、PwC 等固定 schema 要求一切都有类型，装不下的只能丢掉
  - 扩展：其他工作负载按同一结构往词表加具名类型

### 相对 V2 去掉的关系

括号中是 pilot3-multi 的 A3 库中的条数。

- `SUPPORTED_BY`（66）：并入 `SUPPORTS`，方向改为"依据 → 主张"
- `EVALUATED_ON`（0）：Benchmark 并入 Dataset，改用 `USES`
- `DERIVED_FROM`（0）、`HAS_PART`（4）、`ADDRESSES`（2）、`OVERLAPS_WITH`（0）：没有机制用到，需要时用 `RELATES_TO`
