# zele-plan

写需求迭代的技术方案。输入是需求文档 + 代码仓库，输出「用例图 → 业务序列图 → ER 图 → 逐用例数据流讲解」结构的方案。

## 特性

- **穷举闸门**：动笔前必须先产出「使用方 / 用例 / 路径 / 模型触点」四张表并做反推模拟，避免写到一半推翻设计
- **非必要不问人**：提问前必须先查代码 / 学城 / 历史方案 / 互联网，能查到答案的问题不许问
- **PlantUML 画图**：用例图、业务序列图、ER 图统一用 PlantUML，渲染成 SVG 嵌入，Obsidian 与 HTML 同源不漂移
- **双产物**：`技术方案.md`（Obsidian 原生）+ `技术方案.html`（单文件自包含，侧边目录跳转，离线可看）

## 目录结构

```
zele-plan/
├── SKILL.md                        主流程
├── references/
│   ├── design-protocol.md          穷举闸门细则
│   └── output-format.md            排版规范、PlantUML 写法、命名约定
├── scripts/
│   └── build-html.py               渲染 puml → svg，再生成自包含 HTML
└── assets/
    └── marked.min.js               HTML 端的 markdown 渲染器
```

## 依赖

- **Java 8+**（跑 plantuml.jar）
- **plantuml.jar**：21MB，不入库。首次跑 `build-html.py` 时自动从 Maven Central 下载，之后走本地缓存
- **无需 graphviz**：`.puml` 里用 `!pragma layout smetana` 走 PlantUML 内置布局引擎
- 不需要 python 第三方库，标准库即可

## 使用

```bash
python3 scripts/build-html.py "<需求目录>/技术方案.md"
```

需在方案 md 同级放 `diagrams/*.puml`，md 里用 `![[diagrams/xxx.svg]]` 引用。

## 产出

```
需求迭代/{需求名}/
├── 技术方案.md
├── 技术方案.html
└── diagrams/
    ├── 用例图.puml / 用例图.svg
    └── ...
```
