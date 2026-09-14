# zeleSkills

个人 Claude Code Skills 集合。

## Skills 列表

| Skill | 说明 | 来源 |
|-------|------|------|
| [sync-frontend](./sync-frontend/) | 后端 API 设计完成后，一键生成结构化提示词同步给前端 session | 原创 |
| [claude-session-restore](./claude-session-restore/) | 重启电脑前后，存档/恢复 Warp 里所有 Claude Code 会话（含真实分屏布局） | 原创 |
| [zele-code-review](./zele-code-review/) | 严格对照个人全局代码规范审查当前改动，后台跑 review 不阻塞，完成后逐条确认、可当场修复 | 原创 |
| [test-backend-full](./test-backend-full/) | 写完后端并本地部署后测本次改动：运行时选测试强度（轻/中/重），调本地服务接口走真实链路，缺数据就 INSERT 造数（加标记不删） | 原创 |
| [translate-article](./translate-article/) | 翻译外文文章到中文，自动添加摘要，本地化图片后存入 Obsidian 对应分类，并同步创建学城文档（含图片上传） | 原创 |
| [clarify](./clarify/) | 需求澄清器，分轻量/专业两档。专业档额外设计数据模型并做双向核对（概念 + 物理可行性），把「模型撑不住流程」的问题在评审前就抛出来，压缩 PM/RD 返工 | 原创 |
| [zele-plan](./zele-plan/) | 写需求迭代的技术方案：动笔前先用「穷举闸门」把用例和路径铺满，再用 PlantUML 出用例图/业务序列图/ER 图，产出 Obsidian md + 带目录跳转的离线 HTML | 原创 |

## 安装

每个 skill 是一个文件夹，拷到本地 skills 目录即可：

```bash
cp -r <skill> ~/.claude/skills/
```

> Commands（`/clarify`、`/ultracode`、`/branchnew`）已迁移到独立仓库 [zeleCommands](https://github.com/zelehuangdog-source/zeleCommands)。
