# ultracode

Ultracode 多智能体编排器。当需要通过多 agent 并行协作来完成复杂任务时，使用本 skill 进行结构化编排。

## 流程

1. **Phase 1 - 需求澄清**：调用 `/clarify` 收集需求细节
2. **Phase 2 - 方案设计**：设计 Workflow 脚本并向用户讲解确认
3. **Phase 3 - 执行**：调用 Workflow 工具执行，呈现最终结果

## 触发词

`ultracode`、多智能体、workflow、并行 agent、编排

## 安装

将 `SKILL.md` 复制到 `~/.claude/commands/ultracode.md`。

## 依赖

- `/clarify` skill（Phase 1 需要）
- Claude Code Workflow 工具
