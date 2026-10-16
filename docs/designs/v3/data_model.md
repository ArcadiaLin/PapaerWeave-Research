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
| Content | 某个来源在某处说的话，或 agent 形成的理解 | 附锚点；内容相似也不合并 |

带 `[]` 的是列表字段。所有节点另有系统字段 `id`，以及写者在新建时给出的 `kind`。

- **Entity**：资源对象
  - `name` 必填
  - `alias[]`
  - `identities[]`
  - `description`
  - `note`
- **Concept**：共享概念
  - `name` 必填
  - `alias[]`
  - `description` 必填
  - `note`
- **Content**：来源化内容
  - `paper` 必填
  - `anchor[]` 必填
  - `description` 必填
  - `note`

## 各 kind

每个 kind 继承所属类别的字段，下面只列它的含义和自己多出的属性。

- **Entity**
  - `Paper`：论文的书目对象
    - `year`：发表年份
    - `material`：论文 Markdown 文件；换成新文件即为论文的新版本
  - `Dataset`：数据本身
  - `Code`：代码仓库
  - `Model`：权重、checkpoint 或经 API 调用的模型
  - `Benchmark`：有名称的评测资源或套件
  - `Tool`：不是模型的软件、库或服务
  - 所有 Entity 都可以建桩：`stub: true`，被引用但尚未入库，只要求 `name`
- **Concept**
  - `Method`：方法方案或方法类别；变体与配置不建节点；可以建桩
  - `Task`：研究任务；可以建桩
  - `Issue`：研究问题，`name` 写问题的短标题；当前论文表单不写
- **Content**
  - `Experiment`：论文报告的一组实验（一个研究问题），有据层
    - `figures[]`：涉及的表和图，如 `[S4.T3, A1.T8]`，第一个是主表图，参与查重（V2 的 `anchors`）〔待确认〕
  - `Claim`：论文作者的一条主张，补齐必要上下文，有据层
  - `Contribution`：论文的一项贡献
    - `stated_by` 必填：`paper` 为论文自述，属有据层；`agent` 为 agent 的判断，属解释层，系统记 `formed_by`、`formed_at`，只有形成者本人能修改
