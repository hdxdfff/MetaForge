# MetaForge 项目详细报告

生成时间：2026-03-27

## 1. 项目定位

MetaForge 是一个本地化的 AI 软件工厂与研究组织，核心目标不是单纯“生成代码”，而是围绕可验证交付、持续运行、自我改进和受控自治形成一套完整操作系统。

从现有文档看，它的定位包含四层含义：

1. 它是一个控制平面，OpenCode 被设计为主要交互入口。
2. 它是一个持久运行系统，状态、策略、任务和审计信息都要落盘。
3. 它是一个分层自治系统，轻量模型负责廉价重复工作，控制层负责调度和安全。
4. 它是一个持续演化的平台，目标是让“发现问题 -> 生成补丁 -> 验证 -> 合并”成为闭环。

## 2. 核心理念

MetaForge 的最关键原则可以概括为一句话：

`chat != state`

也就是说，聊天记录只是意图入口，不是事实来源；真正的系统事实来自控制器和持久化状态。

围绕这个原则，项目形成了几条稳定的治理逻辑：

- 控制层是唯一可信的变更入口。
- 低成本、本地化、可重复的工作优先交给便宜 worker。
- 高风险动作、架构冲突、重复失败和不可逆动作需要升级处理。
- 输出必须和证据绑定，不能只依赖口头结论。

## 3. 架构概览

根据 [MetaForge OS Architecture](/D:/codex/METAFORGE_OS_ARCHITECTURE.md)，系统大致分为五层：

### 3.1 控制面

控制面由 OpenCode 和控制器脚本组成，负责把操作意图转成可调度的控制动作。

相关入口：

- `D:\codex\orchestrator-mvp\tools\codex_control.py`
- `D:\codex\factoryctl.ps1`（文档中的首选入口）

在当前工作区里，实际可见的包装器是：

- `D:\codex\factoryctl.cmd`
- `D:\codex\factoryctl.py`

### 3.2 控制与规划层

这一层负责：

- 任务分发
- 项目记忆检索
- 能力路由
- 认知安全检查
- 许可与升级决策
- 自我改进治理
- 工具、工作区和升级策略约束

它的作用不是执行任务本身，而是决定“该做什么、谁来做、何时停、何时升级”。

### 3.3 执行层

执行层由 worker、脚本、WSL、PowerShell、容器和沙箱边界构成，负责真正的产出和验证。

这里强调的是“可替换性”：执行层可以换人、换 worker、换工具，但控制与策略层必须保持稳定。

### 3.4 持久状态层

状态层保存任务、审计、审批、热上下文和控制层摘要等信息，典型文件包括：

- `D:\codex\orchestrator-mvp\data\context_kernel.json`
- `D:\codex\orchestrator-mvp\data\hot_context.json`
- `D:\codex\orchestrator-mvp\data\tasks.json`
- `D:\codex\orchestrator-mvp\data\escalation_inbox.json`
- `D:\codex\orchestrator-mvp\data\approval_policy.json`
- `D:\codex\orchestrator-mvp\data\audit_log.json`
- `D:\codex\orchestrator-mvp\data\guard_policy.json`

### 3.5 安全子系统

安全不是附属约定，而是第一等公民。系统把安全分为四个平面：

- cognitive security
- runtime security
- system security
- evolution security

这意味着 MetaForge 不是“先做功能，再补安全”，而是把安全嵌入调度与演化路径中。

## 4. 身份与目标

根据系统身份文件 [METAFORGE_OS_SYSTEM_IDENTITY.json](/D:/codex/METAFORGE_OS_SYSTEM_IDENTITY.json)，项目的身份可以概括为：

- 名称：MetaForge OS
- 类型：AI Software Factory and Research Organization
- 使命：在受控风险下持续演化、交付可验证软件、维持自治运行
- 主要操作面：Codex / OpenCode
- 入口：控制器优先，状态持久化优先

身份文件还明确了几个关键回答：

- `who_am_i`：本地 AI 软件工厂，具备规划、执行、验证和自我改进循环。
- `what_am_i_doing`：在 KPI 与安全策略约束下做边界明确的软件交付、验证和升级。
- `why_am_i_doing_it`：提高可验证交付吞吐、扩大能力覆盖、保持系统健康。
- `what_if_core_model_is_unavailable`：继续依赖控制器状态、本地 workers、cheap-first 策略和受控降级流程。

这说明 MetaForge 的设计不是依赖单一模型能力，而是依赖体系化的降级与恢复能力。

## 5. 当前运行态

我读取到的最新控制层与守护进程状态表明，系统整体处于“运行中但仍需提升”的阶段。

### 5.1 守护进程

从 `factoryctl.cmd daemon-status` 的结果看：

- 守护进程状态：`running`
- 启动时间：2026-03-27T07:12:58Z
- 当前 cycle：1395
- 最近 tick：2026-03-27T09:14:53Z
- tool health：`pass`
- self_model：`healthy`
- goal：`restore_toyos_delivery`
- mode：`toyos_priority_mode`
- blocker_count：0
- control_layer：`signal-only`
- autonomy_score：`stage4_beta`，约 `0.7768`

### 5.2 控制层摘要

从 `factoryctl.cmd control-layer-status` 的结果看：

- control policy：`weak_control`
- execution：`signal_only`
- verification：`delayed`
- release：`advisory_signal`
- quality_system：`candidate`
- overall_score：`0.6945`
- engineering_os：`attention`
- ai_testing：`degraded`
- release_operations：`pass`
- autonomy_score：`0.8468`
- verdict：系统“部分正常”，但还不足以确认稳定自治

### 5.3 运行态解读

这组数据说明项目已经具备持续运行能力，但仍存在两个层面的未完成：

1. 控制层不是完全闭环，仍是 signal-only / weak-control 风格。
2. AI 测试和验证链路存在降级，说明系统还没有达到完全稳定的自证能力。

换句话说，MetaForge 当前更像一个“可运行的自治工厂原型”，而不是一个完全成熟的自治平台。

## 6. 工作空间结构

工作区清单显示，项目已经按职能分成多个方向：

- `ai-agent-factory`
- `ai-research-factory`
- `ai-web-platform-factory`
- `build-ai-video-factory`
- `meta-factory-demo`
- `metaforge-ai-factory`
- `ship-deployable-release-artifact-bundle`
- `strengthen-agent-orchestration-capability`
- `strengthen-webapp-generation-capability`
- `support-mainline-branch-delivery`
- 多个 ToyOS 相关工作区

这说明项目不是单点实验，而是一个以工作区为单位组织的多线并行系统。

同时，`generated` 目录下也已经存在多个结果区：

- `D:\codex\generated\metaforge-ai-factory`
- `D:\codex\generated\metaforge-network-layer`
- `D:\codex\generated\toy-os-demo`

这符合“输出必须落在可追踪产物目录中”的治理思路。

## 7. Stage-4 叙事与主线约束

当前最重要的路线图来自 [MetaForge Stage-4 Execution Guide](/D:/codex/orchestrator-mvp/workspace/METAFORGE_STAGE4_EXECUTION_GUIDE.md)。

这个文档给出的约束非常明确：

1. 只有一条主线是激活的：Self-Improvement Engine。
2. Research Engine 与 Evolution System 处于冻结或只读状态。
3. Safety Guardrail 是支撑性前提，但不是并行主项目。
4. 不允许三条架构线同时推进。

Stage-4 的决定性指标不是“功能数量”，而是是否真的能自动完成：

- 找出 bug
- 生成补丁
- 通过测试
- 合并代码

这意味着 MetaForge 的成熟度标准是闭环能力，不是文档规模。

## 8. 自我改进主线

根据 [MetaForge Self-Improvement Engine Branch Goal](/D:/codex/orchestrator-mvp/workspace/METAFORGE_SELF_IMPROVEMENT_ENGINE_BRANCH_GOAL.md)，当前主线要补的是完整闭环：

1. 把故障、质量问题和工具健康问题统一归入 backlog。
2. 从 backlog 自动生成 bounded patch candidate。
3. 给每个候选项绑定自动测试或验证方式。
4. 形成 merge-ready 记录。
5. 只通过 approved gate 合并。

这一设计有一个很重要的判断：它承认“能生成方案”不等于“能交付”，而真正的交付必须带着验证结果和回滚说明。

## 9. 安全与冻结策略

安全主线来自 [MetaForge Safety Guardrail Branch Goal](/D:/codex/orchestrator-mvp/workspace/METAFORGE_SAFETY_GUARDRAIL_BRANCH_GOAL.md)。

这里的核心思想是“核心模块不可被自动突变”：

- control layer
- scheduler and orchestration control path
- state system and persistent state schema
- 相关控制关键工具

如果要修改这些区域，必须走显式审批或 `approved_patch` 语义，而不能靠普通自动写入完成。

这类设计对一个自我改进系统很关键，因为它阻止了系统在没有审查的情况下修改自己的控制骨架。

## 10. 研究主线状态

Research Engine 当前被明确冻结。它的允许模式是：

- 保持状态文件
- 输出 report-only 产物
- 为 Self-Improvement 提供证据

它不应在当前阶段扩展成主构建路线。这个冻结策略是合理的，因为研究如果不能回流到修复和验证闭环，就会变成“知识堆积但无法落地”。

## 11. 当前优势

从现有材料看，MetaForge 已经具备几个明显优势：

1. 体系化程度高，概念、状态、流程、身份和安全都有文档。
2. 运行态不是纸面工程，已经存在守护进程、状态文件和控制层摘要。
3. 有明确的降级路径，知道在 premium reasoning 不可用时怎么继续工作。
4. 有产物目录和 workspace 体系，适合持续交付。
5. 已经把“验证”提升到和“生成”同等重要的位置。

## 12. 当前问题与风险

也有几项需要注意的风险。

### 12.1 控制层仍是弱控制

控制层摘要显示 `signal-only`、`weak_control`、`delayed verification`、`advisory release`。这说明系统还没有进入完全自动闭环状态。

### 12.2 AI 测试降级

`ai_testing` 在最近状态里是 `degraded`，并列出失败 case。即使总体守护进程正常，测试层的稳定性仍然是一个风险点。

### 12.3 文档与入口有轻微不一致

文档里多次提到 `D:\codex\factoryctl.ps1` 作为首选入口，但当前目录清单里实际可见的是：

- `D:\codex\factoryctl.cmd`
- `D:\codex\factoryctl.py`

我直接尝试执行 `D:\codex\factoryctl.ps1` 时，系统返回“找不到脚本”的错误。这说明文档和实际入口存在轻微漂移，后续最好统一。

### 12.4 阶段目标仍未达成

Stage-4 的关键闭环还没有被文档证明已经完全打通，所以项目仍属于“接近成熟但未完全确认”的阶段。

## 13. 综合评估

如果把 MetaForge 看作一个工程系统，而不是单个项目，它目前处于以下状态：

- 已经有清晰的身份定义
- 已经有可运行的控制层和持续状态
- 已经有主线冻结与安全边界
- 已经有多工作区组织能力
- 已经有初步自治评分和健康检查
- 但还没有完全证明自动 patch-test-merge 闭环已经稳定成立

因此，当前最准确的判断是：

MetaForge 不是一个概念原型，而是一个进入实运行阶段的 AI 工厂控制系统；它已经具备自治雏形，但仍处在 Stage-4 的冲刺与验证阶段，而不是完全封顶阶段。

## 14. 建议

如果后续继续推进，建议按这个优先级处理：

1. 先统一控制入口文档与实际脚本，消除 `factoryctl.ps1` / `factoryctl.cmd` 的漂移。
2. 继续强化 Self-Improvement 闭环，让“发现问题 -> 生成补丁 -> 自动验证 -> 合并准备”可被机器证实。
3. 保持 Research 与 Evolution 的冻结状态，直到主闭环真正成立。
4. 继续完善 Safety Guardrail 的审批语义，避免核心控制模块被自动突变。
5. 把状态检查、验证结果和报告产物继续落盘到 `generated` 与 `data` 层，减少只靠对话上下文的风险。

## 15. 结论

MetaForge 的本质不是一个普通开发仓库，而是一套面向自治交付的本地 AI 工厂操作系统。

它已经具备：

- 控制面
- 状态面
- 安全面
- 多工作区组织
- 自我模型
- 运行守护与评分体系

下一阶段真正要证明的，不是“还能不能跑”，而是“能否稳定地自动找出问题、生成补丁、完成验证并走到合并门禁”。那一步完成后，MetaForge 才能从“高成熟原型”进入真正意义上的 Stage-4。
