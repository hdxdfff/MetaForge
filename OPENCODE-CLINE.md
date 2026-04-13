# OpenCode 与 Cline 配置

这个工作区已经补好了以下文件：

- `D:\codex\opencode.jsonc`
- `D:\codex\.vscode\extensions.json`
- `D:\codex\.vscode\settings.json`
- `D:\codex\opencode.cmd`
- `D:\codex\opencode.ps1`
- `D:\codex\opencode-fast.cmd`
- `D:\codex\codex-session-bootstrap.ps1`
- `D:\codex\metaforge-memory-snapshot.ps1`
- `D:\codex\metaforge-dialogue-assetize.ps1`
- `D:\codex\metaforge-dialogue-compact.ps1`
- `D:\codex\metaforge-dialogue-rescue.ps1`
- `D:\codex\METAFORGE_OS_EXECUTOR_DIVISION.md`

## 1. OpenCode

当前已经改成火山引擎 Coding Plan 配置，编辑 `D:\codex\opencode.jsonc`：

- `baseURL` 使用 `https://ark.cn-beijing.volces.com/api/coding/v3`
- 供应商使用 `volcengine-plan`
- 主模型是 `volcengine-plan/minimax-m2.5`
- 小模型也是 `volcengine-plan/minimax-m2.5`，优先保证对话速度
- `kimi-k2.5` 仍保留为更重分析时的可选模型
- OpenCode 默认是交互层，不直接跑 shell 或改文件；执行必须走控制层分配到后台执行器
- 执行器分工已经拆开：
  - `OpenCode` 只负责交互和提意图，不直接执行
  - `Goose` 负责控制、派发、注册表/脚本/配置维护
  - `Aider` 负责短交互编辑
  - `OpenHands` 负责长链路实现
  - `Plandex` 负责长链路重建和验证
  - `Continue` 负责审查、检查和独立核验

启动方式：

- CMD: `D:\codex\opencode.cmd`
- Fast CMD: `D:\codex\opencode-fast.cmd`
- PowerShell: `D:\codex\opencode.ps1`
- 快速主入口: `D:\codex\opencode-factory.ps1`
  - 默认不再先跑整套状态汇总，启动更快
  - 传 `--fast` 时会切到轻量工作区
  - 如需启动前状态摘要，显式传 `--status`

新对话开箱即用入口：

- `D:\codex\codex-session-bootstrap.ps1`
- `D:\codex\METAFORGE_OS_CODEX_MULTI_SESSION_BOOTSTRAP.md`
- `D:\codex\metaforge-memory-snapshot.ps1`

长对话资产化入口：

- `D:\codex\metaforge-dialogue-assetize.ps1`
- `D:\codex\metaforge-dialogue-compact.ps1`

卡顿或无法关闭的对话恢复入口：

- `D:\codex\metaforge-dialogue-rescue.ps1`

## 2. Cline

这台机器已经安装 `Cline` 扩展。现在在 VS Code 中打开 Cline，按下面填：

- API Provider: `OpenAI Compatible`
- Base URL: `https://ark.cn-beijing.volces.com/api/coding/v3`
- API Key: 你的火山引擎 Coding Plan Key
- Model ID: `minimax-m2.5` 或 `kimi-k2.5`
如果你想让 Cline 更省钱或响应更快，可以在火山方舟控制台把 `minimax-m2.5` 或 `kimi-k2.5` 切到你需要的具体模型。

## 3. 当前状态

- OpenCode CLI 已安装到 `D:\codex\tools\opencode-home`
- OpenCode 现在默认使用独立的交互工作区：
  - `D:\codex\opencode-workspace`
  - `D:\codex\opencode-workspace-fast`
- OpenCode 本地状态已改为独立的：
  - `D:\codex\oi-state-opencode`
  - `D:\codex\oi-state-opencode-fast`
- 旧的 `D:\codex\oi-state\xdg\opencode` 大对象库已不再作为默认状态根
- Cline 扩展已安装，版本 `3.71.0`
- OpenCode 已通过 `--help` 启动验证
- MetaForge OS 多会话 bootstrap 已接入工作区入口
- 长对话现在可以被资产化并压缩换线，而不是只能继续堆长
- 卡顿或无法关闭的线程现在可以通过 rescue 脚本转成可接管的 handoff 包
- 当前执行器职责冻结在 `D:\codex\METAFORGE_OS_EXECUTOR_DIVISION.md`
