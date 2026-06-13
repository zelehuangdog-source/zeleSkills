# sync-frontend

后端设计完 API 后，一键生成结构化前端提示词，消除跨 session 信息传递的损耗。

## 解决的痛点

当你用两个 Claude Code session 分别做后端和前端时，后端设计完 API 后需要把方案传递给前端 session。常见问题：

1. **信息丢失**：手动总结时遗漏枚举值、错误码、边界条件等细节，前端实现时只能靠猜
2. **格式不统一**：每次口头描述的粒度不一样，前端 session 收到的信息质量参差不齐
3. **上下文断裂**：后端对话中讨论过"为什么不用 GET"、"空值返回什么"等决策，但这些隐性知识不会自动传递
4. **重复劳动**：每次都要人肉整理接口文档，浪费时间且容易出错

## 它做了什么

从当前后端对话中自动提取完整 API 契约（URL、Method、Request/Response 结构、枚举、错误码、边界说明），组装为一段可直接驱动前端 session 工作的结构化提示词，保存到 Obsidian 并复制到剪贴板。

## 安装

将 `sync-frontend/` 目录复制到 `~/.claude/skills/` 下：

```bash
cp -r sync-frontend ~/.claude/skills/
```

## 正确用法

在后端 Claude Code session 中，API 设计讨论完毕后：

```
/fork /sync-frontend
```

- `/fork` — 派生一个继承完整对话上下文的后台子 agent
- `/sync-frontend` — 子 agent 执行的指令：提取 API 信息 → 询问前端行为模式 → 组装提示词 → 保存文件 → pbcopy

执行完后：
- 浏览器自动打开预览页面，你可以 review 完整内容
- 剪贴板已就绪，切到前端 session 粘贴即可

### 前端行为模式（执行时会询问你）

| 模式 | 说明 |
|------|------|
| 先澄清 | 前端先用 /clarify 确认理解无误再动手 |
| 设计示例 HTML UI 界面 | 前端先出一个纯 HTML 页面骨架，你确认后再写正式代码 |
| 直接实现 | 跳过澄清和设计，直接写 TypeScript 类型 + API hook + 页面组件 |

支持多选（如"先澄清 + 设计 UI"），按顺序串联执行。

### 产出物

- **Obsidian 文件**：`~/Documents/obsidian_repo/工程迭代/{工程名}/{需求名}/sync-frontend-{日期}.md`
- **预览 HTML**：同目录下 `sync-frontend-preview.html`
- **剪贴板**：一句 `读取 {文件路径} 并按其中的任务要求执行`

## 用户故事

> 我在后端 session 里花了 20 分钟设计耦合检测的 3 个 API——列表查询、详情查询、触发检测。讨论过程中决定了 detectId 为空时自动查最近一次、couplingLevel 用英文枚举而非数字、空列表返回空数组不返回 null。
>
> 设计完了，我输入 `/fork /sync-frontend`。
>
> 1 分钟后浏览器弹出预览页面，我快速扫了一眼：3 个接口的 Request/Response 结构完整，枚举值齐全，边界说明也在。我选了"先澄清 + 设计 UI"模式。
>
> 切到前端 session，Cmd+V 回车。前端 agent 先用 /clarify 问了两个问题（分页组件用哪个、状态筛选是否需要多选），我回答后它出了一个 HTML 原型。我确认布局没问题，它就开始写正式代码了。
>
> 全程没手动写过一行接口文档，也没有"那个枚举值到底是啥来着"的反复确认。

## 依赖

- Claude Code v2.1.32+（需要 `/fork` 命令支持）
- macOS（使用 `pbcopy` 和 `open`）
