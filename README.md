# zeleSkills

个人 Claude Code Skills 集合。

## Skills 列表

| Skill | 说明 | 来源 |
|-------|------|------|
| [sync-frontend](./sync-frontend/) | 后端 API 设计完成后，一键生成结构化提示词同步给前端 session | 原创 |
| [claude-session-restore](./claude-session-restore/) | 重启电脑前后，存档/恢复 Warp 里所有 Claude Code 会话（含真实分屏布局） | 原创 |
| [zele-code-review](./zele-code-review/) | 严格对照个人全局代码规范审查当前改动，后台跑 review 不阻塞，完成后逐条确认、可当场修复 | 原创 |
| [test-backend-full](./test-backend-full/) | 写完后端并本地部署后，对本次改动做全方位测试：穷举分支（含中间字段 null）、调本地服务接口走真实链路，数据取自 test 库不足则 INSERT 造数（加标记不删） | 原创 |

## 安装

每个 skill 是一个文件夹，拷到本地 skills 目录即可：

```bash
cp -r <skill> ~/.claude/skills/
```

> Commands（`/clarify`、`/ultracode`、`/branchnew`）已迁移到独立仓库 [zeleCommands](https://github.com/zelehuangdog-source/zeleCommands)。
