# 输出格式规范

技术方案 md 的结构、图表管线与文字要求。

---

## 一、md 骨架

````markdown
---
title: "{需求名} - 技术方案"
date: {YYYY-MM-DD}
tags: [{需求相关标签}]
---

# {需求名} - 技术方案

> 需求背景：两三句话说清这次要解决什么问题、为什么现在做。
>
> 图用 PlantUML 绘制，源码在同目录 `diagrams/*.puml`；改图后重跑 `build-html.py` 即可同步 md 与 html。

## 目录

- [[#1. 用例图|1. 用例图]]
- [[#2. 业务序列图|2. 业务序列图]]
- [[#3. 数据模型 ER 图|3. 数据模型 ER 图]]
- [[#4. 用例与数据流|4. 用例与数据流]]

---

## 1. 用例图

![[diagrams/用例图.svg]]

（使用方/功能对照表）

## 2. 业务序列图

### 2.1 {用例名}

![[diagrams/序列图-{用例名}.svg]]

## 3. 数据模型 ER 图

![[diagrams/ER图.svg]]

## 4. 用例与数据流

### 4.1 {用例名}（UC-1）

![[diagrams/序列图-{用例名}.svg]]

| 模型 | 在这条路径上的作用 |
|---|---|
| {中文模型名}（`{table_name}`） | {角色} |

{数据流叙述}
````

**目录必须用 Obsidian wikilink `[[#标题|显示文本]]`** —— 这是 Obsidian 里唯一稳定可靠的同文档标题跳转写法。html 会剥掉这一段，用自己的侧边栏。

---

## 二、图表管线

**图不在 md 里内联，而是**：

1. PlantUML 源码写成 `diagrams/{图名}.puml`
2. md 里用 `![[diagrams/{图名}.svg]]` 引用
3. 构建脚本渲染 `.puml` → `.svg`，再把 SVG 内联进 HTML

这样 md 在 Obsidian 里能直接看到图（Obsidian 原生渲染 SVG 嵌图），HTML 离线自包含，两边同源不漂移。

```
{需求名}/
├── 技术方案.md
├── 技术方案.html
└── diagrams/
    ├── 用例图.puml / 用例图.svg
    ├── 序列图-差异识别.puml / 序列图-差异识别.svg
    └── ER图.puml / ER图.svg
```

**为什么不用 mermaid**：一是 mermaid 表达不了 UML 的 `<<include>>` / `<<extend>>` / 泛化，也没有真正的用例图（只能用 flowchart 近似），PlantUML 原生就是 UML；二是本 skill 的构建管线只支持 PlantUML，混用会让 md 与 html 两边对不上。

---

## 三、PlantUML 写法

每个 `.puml` 文件的开头两行固定：

```plantuml
@startuml
!pragma layout smetana
skinparam shadowing false
skinparam defaultFontName "PingFang SC"
```

- `!pragma layout smetana` **必加** —— 本机没装 graphviz，靠 PlantUML 内置的 Smetana 布局引擎
- `defaultFontName` 指定中文字体，否则中文可能跳到衬线体

### 3.1 用例图

```plantuml
actor "打标人\nSRE / 业务方" as A1
actor "风险处理人" as A2
actor "黄金链路\nGoldLink" as A3

rectangle "系统边界（本次改造范围）" {
  usecase "打强弱依赖标签" as UC1
  usecase "查看风险列表" as UC2
  usecase "同步拓扑识别差异" as UC3
}

A1 --> UC1
A2 --> UC2
A3 --> UC3
```

约定：

- 参与者用 `actor`（渲染成火柴人），放在 `rectangle` **外面**
- 用例用 `usecase`（渲染成椭圆），放在 `rectangle` **里面**
- 标签里可以用 `\n` 换行
- **用例超过 8 个就按参与者拆成多张图**，否则布局会很宽

> ⚠️ **已知布局坑**：用 `..> : <<include>>` 或 `<<extend>>` 时，被指向的用例**会被排到 `rectangle` 外面**，边界就画错了。
> 规避：优先用普通关联边 `-->`；确实要表达 include/extend 时，同时给该用例补一条参与者的关联边，把它拉回框内。

### 3.2 业务序列图

> **一张业务序列图回答的是：谁（人 / 外部系统）在什么时候，对谁做了什么。**
> 它是给业务方看的，不是给 RD 看的。判断标准就一条：**一个不了解这个系统实现的产品经理，看得懂吗？**

#### 🚫 红线一：泳道只能是「我方系统边界之外」的

| ✅ 可以当泳道 | ❌ 不可以当泳道 |
|---|---|
| 人（角色）：运营人员、打标人 | 内部类 / 任务：`MafkaConfigSyncJob`、`XxxService`、`XxxJob`、`XxxHandler` |
| 外部系统：Crane 调度平台、Mafka 开放平台、黄金链路 | 内部存储：数据库、AGE 图库、缓存、MQ |
| **本系统整体 —— 且只占一条泳道**：架构治理平台 | 把本系统拆成多条：标签系统 / 图谱服务 / 风险模块 |

**判据：它在我的系统边界里面还是外面？里面的，一律不画。**

内部存储（图库、DB、MQ）尤其容易漏 —— 它们是本系统的实现细节，业务方根本不关心数据存在哪。

#### 🚫 红线二：消息只能是业务动作，不能是接口细节

| ✅ 业务动作 | ❌ 接口细节 |
|---|---|
| 提交筛选条件 | `/api/topic/config/query?topicName=物理名` |
| 拉取该入口的拓扑 | `[(物理名, environment), ...]` |
| 返回弱依赖判定 | `7,356 + 9,236 = 16,592 个节点` |
| 标记已修复 | `topic 47%，消费组 63%` |

**判据同样是：业务方看得懂吗？** 路径、字段结构、数据量、百分比、表名、方法名、SQL、日志 —— 全都不该出现。

#### 数据、实测值、技术风险放哪

**不放图上。** 图只画交互；数字、字段、实测结论、技术风险写成**图下方的正文段落**，或单独一节「本图暴露的问题」。

图上的 `note` 只写**业务规则或例外** —— 例如"标签组不存在时返回空集，不报错"。**不写量级、不写百分比、不写字段名。**

> 这条最容易被违反：写方案时手边正好有实测数据，顺手就写进 note 了。记住 —— 图的作用是让业务方看懂交互，实测数据放正文，两者不要混。

#### 粒度

- 一张图只讲**一条业务流程**，不要把多个流程塞一张
- 步骤 ≤ 15，超了就拆图

#### 模板

```plantuml
autonumber

actor "风险处理人" as H
participant "架构治理平台" as Plat
participant "黄金链路\nGoldLink" as GL

H -> Plat : 打开风险列表
Plat -> GL : 拉取拓扑
GL --> Plat : 返回强弱依赖判定
note over Plat : 标签组不存在时返回空集，不报错

alt 暂不处理
  H -> Plat : 忽略
else 确认已处理
  H -> Plat : 标记已修复
end
```

#### PlantUML 画法约定

- 人用 `actor`（渲染成火柴人），外部系统用 `participant`（渲染成方块）
- 加 `autonumber`，方便正文引用"第 3 步"
- 分支用 `alt / else / end`
- 失败/降级用 `note over` 标注，不要画成分支箭头把图搞乱

#### 出图自检（逐条过，缺一不可）

- [ ] 每条泳道都在系统边界外？本系统只占一条？
- [ ] 没有类名、任务名、表名、接口路径、字段名？
- [ ] 没有数据量、百分比、统计值？
- [ ] 消息都是业务动作，不是接口调用？
- [ ] 步骤 ≤ 15？

### 3.3 ER 图

```plantuml
hide circle
skinparam linetype ortho

entity "风险记录表\ntag_value_risk" as risk {
  * id : bigint <<PK>>
  --
  * risk_code : varchar(64)
  detected_value : varchar(64)
  is_valid : boolean
}

entity "实体标签关系表\nentity_tag_rel" as rel {
  * id : bigint <<PK>>
  --
  * entity_id : varchar(128)
  is_valid : boolean
}

risk }o..o{ rel : 逻辑关联，无外键
```

约定：

- **模型名用中文 + 换行 + 真实表名**（`entity "风险记录表\ntag_value_risk"`）。只写英文表名可读性差
- 字段名保留英文（那是数据库列名），主键标 `<<PK>>`
- 关系名用中文业务语义（"被标注"、"逻辑关联"），不写 "has_many"
- **只画变更相关的表**；被引用但不改的表可以画成孤立节点并注明"不改动"

> ⚠️ **不要用 mermaid**：本 skill 的构建管线**只认 PlantUML**。mermaid 代码块不会渲染成图 —— HTML 里它只是一段代码，而 Obsidian 里它会正常出图，两边就对不上了。

---

## 四、第 4 节的写法

**每一节开头先复述对应的业务序列图**，再讲模型的数据作用 —— 图文对照着看，比纯文字好懂得多。

```markdown
### 4.1 按在线服务筛选实体（UC-1）

![[diagrams/序列图-按在线服务筛选.svg]]

| 模型 | 在这条路径上的作用 |
|---|---|
| 服务表（`service`） | 提供 appkey → 图节点 id 的映射，是"服务"这个概念的锚点 |
| 实体标签关系表（`entity_tag_rel`） | 判定依据：该服务是否带 `APPKEY_STATUS` 标签 |
| 链路入口节点（`LINK_ENTRY_NODE`） | 最终被过滤和返回的对象 |

数据流：请求带筛选条件进来 → 按 appkey 找到服务节点 → 用节点 id 在实体标签关系表里查标签
→ 命中的服务 id 集合作为 IN 条件 → 过滤链路入口节点 → 返回。

边界：标签组不存在时子查询返回空集，结果是"全部被过滤掉"而非报错 —— 这是刻意的。
```

要点：

- **同一张序列图在第 2 节和第 4 节出现两次**，这是有意的。第 2 节是全局视图，第 4 节是逐用例的图文对照
- 表格里模型名用**中文**（首次出现括注表名），不要只写 `ENTITY_TAG_REL`
- 讲的是**数据怎么流**，不是复述字段含义。字段含义属于 ER 图那一节
- **复杂路径才额外画流程图**（PlantUML `activity`）。简单路径用文字讲，别为了凑图而画图

---

## 五、命名约定

**正文指代数据模型统一用中文名**，英文表名可读性差。规则：

| 场合 | 写法 |
|---|---|
| 首次出现 | `风险记录表（tag_value_risk）` |
| 后续指代 | `风险记录表` |
| ER 图节点 | `entity "风险记录表\ntag_value_risk"` |
| 字段名 | **保留英文**（`detected_value`），那是数据库列名 |
| 枚举值 / 状态码 | 保留英文 code，首次出现括注中文（`suspended`（已挂起）） |

图里的参与者、用例、系统边界名同样用中文业务名，不要写 `UserService` 这类类名。

---

## 六、代码节制

**整个技术方案不应出现大量代码。** 判断标准：

| 该出现 | 不该出现 |
|---|---|
| 接口签名（新增/变更的参数，≤10 行） | 完整方法实现 |
| DDL 变更（只在必须精确表达时） | 建表 SQL 全文 |
| 关键数据结构定义 | Service / Mapper 代码 |
| 有歧义的 SQL 片段（≤15 行） | 大段查询语句 |

数据模型**优先用 ER 图 + 文字表格**表达，而不是甩 DDL。**全文代码块总数控制在个位数**，超了就说明在用代码代替思考。

---

## 七、构建

```bash
python3 ~/.claude/skills/zele-plan/scripts/build-html.py "<目录>/技术方案.md"
```

一条命令做完三件事：

1. 渲染 `diagrams/*.puml` → 同名 `.svg`（一次 java 调用批量跑）
2. 把 md 里的 `![[diagrams/xxx.svg]]` 替换成内联 SVG
3. 生成 `技术方案.html`

其他参数：

- `--open` 生成后用浏览器打开
- `--no-render` 跳过 PlantUML 渲染，直接用已有 svg（改样式重跑时更快）

**md 是唯一事实源，图源 `.puml` 是图的唯一事实源。** 改内容改 md，改图改 `.puml`，然后重跑脚本 —— 不要手改 html 或 svg。

生成后建议用浏览器确认：若某张图位置出现黄色"图未找到"或红色"渲染失败"提示，说明该图的 puml 有问题。
