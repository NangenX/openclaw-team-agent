# 术语对照表 / Glossary

| 中文 | English | 说明 |
|------|---------|------|
| 主责 Agent | Owning Agent | 对任务结果负责的唯一角色 |
| 交接 | Handoff | 上下游 Agent 的输入输出传递 |
| 路由计划 | Routing Plan | 任务分配与执行顺序定义 |
| 上下文边界 | Context Boundary | 主会话与子会话可见性约束 |
| 风险分级 | Risk Tiering | Low/Medium/High 风险分类 |
| 合并门禁 | Merge Gate | 进入可合并状态前的检查条件 |
| 提示词治理 | Prompt Governance | 提示词规则、版本和质量控制 |
| Token 预算 | Token Budget | 每轮上下文成本约束 |
| 长期记忆 | Long-term Memory | 高价值、低频变更规则集合 |
| 检查清单路由 | Checklist Routing | 高风险动作先走清单再执行 |
| 需求卡片 | Requirement Card | 结构化需求描述文档（REQ-XXX） |
| 架构决策记录 | Architecture Decision Record (ADR) | 记录架构决策背景、选项和结论的文档 |
| 执行路由 | Execution Routing | Orchestration Agent 分配任务给各 Agent 的计划 |
| 交付门禁 | Delivery Gate | QA + Documentation 均完成才可交付 |
| 变更说明 | Change Summary | Implementation Agent 完成后输出的变更描述 |
| 测试报告 | Test Report | QA Agent 输出的验证结果（pass/block） |
| 缺陷严重性 | Defect Severity | critical / major / minor 三级分类 |
| 回归范围 | Regression Scope | 本次变更需要重新验证的模块列表 |
| 阻塞项 | Blocker | 阻止当前阶段推进的问题 |
| 并行任务 | Parallel Tasks | 在 DAG 模式下可同时执行的无依赖任务 |
| 串行流水线 | Linear Pipeline | 按固定顺序逐阶段推进的执行方式 |
| 上下文策略 | Context Strategy | 控制哪些文档常驻加载、哪些按需加载 |
| 超时检查 | Timeout Check | 检查阶段是否超过截止时间 |
| 截止时间 | Deadline | 阶段必须完成的 ISO-8601 时间戳 |
| 重试 | Retry | 对失败阶段保留上下文的重新执行 |
| 自动创建 PR | Auto Create PR | 交付门禁通过后通过 CLI 自动发起 Pull Request |
| 交接上下文 | Handoff Context | Agent 间传递的关键信息摘要，防止上下文丢失 |
