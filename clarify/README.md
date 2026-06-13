# clarify

动手之前系统性收集需求细节，确保需求毫无模糊空间。

## 它做了什么

通过多轮结构化提问（使用 AskUserQuestion 工具），把所有有歧义、有二义性、不确定的地方全部问清楚。不仅澄清用户说出来的需求，还会主动设想边界 case 并抛出来对齐。

澄清完毕后只输出需求摘要，不做计划、不写代码——严格只管"问清楚"这一件事。

## 安装

将 `clarify/SKILL.md` 复制到 `~/.claude/commands/clarify.md` 或 `~/.claude/skills/clarify/SKILL.md`：

```bash
# 方式一：作为 command
cp clarify/SKILL.md ~/.claude/commands/clarify.md

# 方式二：作为 skill
mkdir -p ~/.claude/skills/clarify
cp clarify/SKILL.md ~/.claude/skills/clarify/SKILL.md
```

## 用法

```
/clarify 实现一个耦合检测结果的列表页面
```

它会自动分析你的需求描述，从范围、优先级、约束、验收标准、影响范围、风格偏好、边界场景等维度发起提问。

## 特点

- **不限问题数量**：有疑问就问，单轮超过 4 个自动分多轮
- **主动设想边界 case**：输入边界、状态边界、并发边界、依赖边界、数据边界、权限边界
- **严格只做澄清**：不给方案、不写代码、不做计划
- **澄清后引导下一步**：通过选择器让你决定"进入计划模式"还是"直接实施"

## 被依赖

`sync-frontend` skill 生成的前端提示词中，如果用户选择"先澄清"模式，会要求前端 session 使用 `/clarify` 来确认理解无误。
