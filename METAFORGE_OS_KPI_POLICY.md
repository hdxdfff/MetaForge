# AI 元工厂生产力 KPI 与饱和调度策略（ToyOS 支线）

## 一、核心原则

**生产力 ≠ 代码量**

生产力必须定义为：

> **单位时间内产生的可验证交付单元（Verifiable Delivery Units, VDU）**

一个交付单元必须满足：

1. 有明确落点，例如 patch、PR、文档、测试。
2. 有验证方法，例如 test、QEMU、script。
3. 可以被自动系统验收。

否则一律视为**无效产出**。

## 二、生产单位定义（VDU）

系统的最小生产单位如下。

### Level-1 交付单元

以下任意一种：

- 可运行 patch
- patch proposal
- branch goal
- 自动测试报告
- 风险 / 依赖清单

### Level-2 交付单元（ToyOS 专用）

ToyOS 支线额外允许：

- 新 syscall 实现
- 新 kernel module
- 新测试用例
- 新文档章节
- QEMU 可复现验证脚本

### Level-3 交付单元（重大成果）

例如：

- 新子系统
- scheduler 改进
- memory subsystem patch
- build system upgrade

## 三、核心 KPI 指标

### 1. 有效交付量（核心指标）

单位时间完成：

`VDU / hour`

建议目标：

- `1–3 个 VDU / hour / worker`

系统级目标：

- `10–30 VDU / hour`

具体取决于 worker 数量。

### 2. 质量指标

测试通过率：

`passed_tests / total_tests`

建议：

`>90%`

回归率：

`regression / patch`

建议：

`<5%`

patch 驳回率：

`rejected_patch / patch`

建议：

`<15%`

越界改动率：

`out_of_scope_patch / patch`

建议：

`<10%`

### 3. 周转效率

首次结果时间：

`task -> first result`

目标：

`<20 min`

首稿到验收：

`first patch -> accepted patch`

目标：

`<60 min`

### 4. 自动化利用率

自动完成比例：

`auto_complete / total_tasks`

目标：

`>70%`

人工兜底比例：

`manual_fix / tasks`

目标：

`<20%`

空转率：

`idle_time / total_time`

目标：

`<10%`

## 四、系统饱和度指标

不要看代码量，要看：

### 活跃 worker 数

`active_workers`

### 队列深度

`pending_tasks`

建议：

`3–6 × worker`

### 吞吐量

`tasks_completed / hour`

## 五、强约束饱和生产策略

为了防止系统发呆，执行以下强约束。

### 任务队列规则

系统必须始终保持：

`3–6 个 ToyOS 子任务`

例如：

- syscall
- memory
- scheduler
- filesystem
- driver
- tests
- docs

### Worker 产出规则

每个 worker 每轮必须提交至少一项：

- patch
- patch proposal
- branch goal
- 测试报告
- 风险列表

### 禁止行为

禁止：

- 只写思路
- 只写设计
- 没有落点
- 没有验证

必须附：

- 验证步骤
- 或落点文件

## 六、空转检测

如果：

`15–20 分钟`

无产出，系统自动判定：

`worker idle`

执行：

1. 重新派发任务
2. 降级任务难度
3. 切换 worker

## 七、连续无产出惩罚

如果：

`连续 2 轮`

无有效 VDU，执行：

`降低该 worker 权重`

调度器减少任务派发。

## 八、自动调度策略

调度器采用：

### Priority Queue

优先级：

- critical
- kernel
- core
- feature
- tests
- docs

### 调度规则

调度公式：

`score = priority × success_rate × speed`

高分 worker 优先获得关键任务。

## 九、ToyOS 专项产出指标

每轮开发周期建议产出：

- `1 syscall`
- `3 tests`
- `1 doc`
- `1 qemu verification`

## 十、元工厂生产目标

假设：

`20 workers`

理论产出：

- `20–60 VDU / hour`
- `200–500 VDU / day`

## 十一、最关键的一条

系统必须遵循：

> **没有验证 = 没有产出**

## 十二、最重要的系统能力

MetaForge OS 必须具备：

### 自动验证

`tests`

`qemu`

`build`

### 自动验收

`CI agent`

### 自动重派

`scheduler`

## 十三、高吞吐执行化

This policy is the measurement layer for the operational blueprint in:

- `D:\codex\METAFORGE_OS_HIGH_THROUGHPUT_BLUEPRINT.md`

The blueprint adds the execution contract that the KPI layer measures.

### Admission rule

Tasks that enter the production queues must define:

- `task_type`
- `artifact_spec`
- `verification_level`
- `max_runtime_seconds`
- `retry_limit`
- `rollback_rule`

Tasks without those fields do not count as valid VDU candidates.

### Queue rule

The default execution profile is:

- `fastlane`
- `build_test`
- `regression`
- `incubation`

Queue depth must be managed so that short verified tasks are not blocked by long exploratory work.

### Verification rule

Verification must be chosen before dispatch:

- `L1` for fastlane
- `L2` for build/test and standard evidence work
- `L3` for release candidates and real-artifact promotion

### Dashboard rule

The main throughput dashboard should focus on:

- completed tasks last 24h
- first-result median minutes
- final-verdict median minutes
- queue-wait median minutes
- pass rate by task type
- retry rate
- real artifact conversion rate
- flakiness by harness case

## 执行解释

大部分 agent 系统的问题是只会写代码，不会生产软件。

MetaForge OS 的目标是定义并执行：

- 生产单位
- 生产 KPI
- 生产调度
- 生产质量

并让这些规则约束 ToyOS 支线交付。

## 生效规则

若 KPI 压力与安全、边界、验证冲突：

- 安全优先
- 边界优先
- 验证优先
- 无法安全实现时，退化为 patch proposal 或 branch goal
