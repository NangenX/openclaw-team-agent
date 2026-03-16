# openclaw-team-agent

一个 [OpenClaw Skill](https://docs.openclaw.ai/)，为你的项目安装 10-Agent AI 开发团队。

**版本：v0.5**

## 特性

- **完全自包含** — 所有 Agent 提示词已内嵌在 `SKILL.md` 中，安装时无需外部路径依赖
- **10 个专业 Agent** — Product Planner、Orchestration、Architecture、Implementation、QA（通用 + 4 个专项）、Documentation
- **可执行的 system prompt** — 每个 Agent 有明确的人格、行为准则和工作流程
- **任务编排运行层** — 附带轻量级 Python CLI，支持线性与 DAG 两种多 Agent 流程
- **动态 QA 委员会** — Orchestration 根据变更规模和涉及领域自主选择 1–5 个 QA Agent 并行审查
- **QA 门禁强制执行** — 所有选中的 QA Agent 全部通过后，`documentation` 阶段才可推进
- **自动创建 PR** — `create-pr` 命令在门禁通过后通过 GitHub CLI 自动发起 Pull Request
- **截止时间与超时追踪** — `set-deadline` 与 `check-timeout` 命令支持时间感知工作流
- **智能重试** — `retry` 命令在重置失败阶段的同时保留任务描述和日志
- **双语支持** — 中英文文档一致性保障

## 安装

```bash
# 克隆仓库
git clone https://github.com/your-org/openclaw-team-agent.git

# 复制到 skills 目录
cp -r openclaw-team-agent/ /path/to/clawd/skills/openclaw-team-agent/
```

然后在任意项目中运行：
```
/openclaw-setup
```

## Task Manager CLI

仓库现在包含 `scripts/task_manager.py`，用于管理 6-Agent 线性与 DAG 工作流：

```bash
# 线性模式
python3 scripts/task_manager.py init my-feature -g "Build login flow" --source feishu --requester kim --thread-id oc_xxx
python3 scripts/task_manager.py assign my-feature product-planner "Create requirement card"
python3 scripts/task_manager.py next my-feature
python3 scripts/task_manager.py status my-feature

# DAG 模式
python3 scripts/task_manager.py init my-feature-dag -m dag -g "Build login flow"
python3 scripts/task_manager.py add my-feature-dag spec -a product-planner --desc "Write requirement card"
python3 scripts/task_manager.py add my-feature-dag impl -a implementation -d spec --desc "Implement feature" --deadline "2026-03-20T18:00:00Z" --token-budget 16000
python3 scripts/task_manager.py ready my-feature-dag --json
python3 scripts/task_manager.py graph my-feature-dag

# 失败恢复
python3 scripts/task_manager.py log my-feature implementation "build failed at step X"
python3 scripts/task_manager.py history my-feature implementation
python3 scripts/task_manager.py reset my-feature implementation --keep-task
python3 scripts/task_manager.py retry my-feature implementation   # 智能重试：保留任务上下文与日志

# 截止时间与超时追踪
python3 scripts/task_manager.py set-deadline my-feature implementation "2026-03-20T18:00:00Z"
python3 scripts/task_manager.py check-timeout my-feature

# 可观测性
python3 scripts/task_manager.py events my-feature --limit 20
python3 scripts/task_manager.py stats my-feature
python3 scripts/task_manager.py blocked my-feature

# 健康检查与报表导出
python3 scripts/task_manager.py doctor my-feature
python3 scripts/task_manager.py gate my-feature
python3 scripts/task_manager.py leader-report my-feature
python3 scripts/task_manager.py export my-feature -f md -o ./my-feature.report.md
python3 scripts/task_manager.py export my-feature -f json -o ./my-feature.report.json

# 自动创建 PR（需安装 GitHub CLI：https://cli.github.com/）
python3 scripts/task_manager.py create-pr my-feature --dry-run          # 预览模式
python3 scripts/task_manager.py create-pr my-feature --title "feat: ..." --base main
python3 scripts/task_manager.py create-pr my-feature --draft             # 草稿 PR

# 飞书 OpenAPI 发送适配器
python3 scripts/feishu_openapi_adapter.py send-text --receive-id oc_xxx --text "Leader update" --dry-run
python3 scripts/feishu_openapi_adapter.py send-project-report my-feature --receive-id oc_xxx --dry-run

# 飞书入站桥接（事件回调）
export FEISHU_APP_ID="cli_xxx"
export FEISHU_APP_SECRET="xxx"
export FEISHU_VERIFICATION_TOKEN="token_xxx"
python3 scripts/feishu_inbound_bridge.py serve --host 0.0.0.0 --port 8787

# 本地事件模拟
python3 scripts/feishu_inbound_bridge.py handle-file --input ./.tmp_feishu_event.json --dry-run
```

默认线性流水线顺序：

```text
product-planner -> orchestration -> architecture -> implementation -> qa -> documentation
```

支持模式：

- `linear`：通过 `next` 按阶段顺序推进
- `dag`：通过 `ready` 获取可并行派发任务

恢复命令：

- `log`：为阶段记录排障日志
- `history`：查看阶段状态变更与日志历史
- `reset`：将单阶段或全流程重置为 pending 以重试
- `retry`：智能重试——保留任务描述与日志（推荐用于失败阶段）

可观测性命令：

- `events`：查询项目级事件流（支持 kind/stage 过滤）
- `stats`：汇总运行统计（尝试次数、失败次数、重置次数、日志数）
- `blocked`：定位阻塞阶段及依赖阻塞原因

截止时间与超时命令：

- `set-deadline`：为阶段设置 ISO-8601 截止时间
- `check-timeout`：报告已超过截止时间且未完成的阶段

交付命令：

- `doctor`：执行项目状态健康检查
- `gate`：检查交付门禁（必须满足 QA + Documentation）
- `leader-report`：生成面向 Leader 的进展与阻塞摘要
- `export`：导出 Markdown 或 JSON 报告
- `create-pr`：检查交付门禁并通过 `gh pr create` 自动创建 GitHub PR（需安装 [GitHub CLI](https://cli.github.com/)）

飞书适配器：

- `scripts/feishu_openapi_adapter.py`：通过飞书 OpenAPI 发送 Leader 回报（`send-text`、`send-project-report`）
- `scripts/feishu_inbound_bridge.py`：接收飞书回调事件并映射为 Leader 工作流命令

飞书入站 Leader 命令：

- `/new <goal>`：创建新需求/项目
- `/status <project>`：返回 Leader 进展摘要
- `/gate <project>`：返回交付门禁状态
- `/update <project> <stage> <status>`：推进阶段状态
- `/log <project> <stage> <message>`：追加排障日志

## Agent 团队

| Agent | 核心职责 |
|-------|---------|
| Product Planner | 需求分析与任务切片 |
| Orchestration | 任务路由、执行编排、QA 委员会决策 |
| Architecture | 架构设计与技术决策 |
| Implementation | 代码实现与自测 |
| QA | 通用质量验证与代码审查 |
| QA-Security | 安全漏洞、权限、加密审查 |
| QA-Style | 代码风格、规范、可维护性审查 |
| QA-Performance | 性能瓶颈、内存、算法审查 |
| QA-Logic | 业务逻辑、边界条件审查 |
| Documentation | 文档维护与双语一致性 |

## 开发流程

```
用户输入需求
    ↓
Product Planner  → 需求卡片 (REQ-XXX)
    ↓
Orchestration    → 执行路由计划 (PLAN-XXX) + QA 委员会决策
    ↓
Architecture     → ADR + 接口契约
    ↓
Implementation   → 代码 + 自测报告
    ↓
QA 委员会（动态） → 并行：qa + qa-logic + qa-security + qa-performance + qa-style
                   （Orchestration 根据变更规模和领域自主选择）
    ↓
Documentation    → 文档更新
    ↓
交付
```

### QA 委员会决策规则

| 变更规模 | 判断依据 | 基础 QA 配置 |
|---------|---------|------------|
| 小 | 改动 ≤3 个文件，逻辑简单 | `qa` |
| 中 | 改动 4–10 个文件，或含新功能 | `qa` + `qa-logic` |
| 大/复杂 | 改动 >10 个文件，或跨模块重构 | `qa` + `qa-logic` + `qa-style` |
| + 安全相关 | 含认证/加密/权限/敏感数据 | + `qa-security` |
| + 性能相关 | 含热路径/数据库/并发 | + `qa-performance` |

## 项目结构

```
openclaw-team-agent/
├── README.md              # English README
├── README_CN.md           # 本文件
├── SKILL.md               # OpenClaw skill 定义（自包含）
├── agents/                # Agent 提示词源文件
│   ├── product-planner.md
│   ├── orchestration.md
│   ├── architecture.md
│   ├── implementation.md
│   ├── qa.md
│   ├── qa-security.md
│   ├── qa-style.md
│   ├── qa-performance.md
│   ├── qa-logic.md
│   └── documentation.md
├── scripts/               # 工作流运行层
│   ├── task_manager.py
│   ├── feishu_openapi_adapter.py
│   └── feishu_inbound_bridge.py
└── docs/                  # 参考文档
    ├── examples/
    │   └── login-flow.md  # 端到端示例流程
    └── glossary/
        └── terms.zh-en.md
```

## 版本策略

- v0.1: 角色与治理规则落地
- v0.2: 增补场景化流程（需求到发布）
- v0.3: 引入自动化校验脚本（可选）
- v0.4: QA 门禁强制执行、自动创建 PR、截止时间追踪、智能重试、术语表扩充、示例项目
- v0.5: 动态 QA 委员会 — Orchestration 自主决定专项 QA 阵容（qa-security、qa-style、qa-performance、qa-logic）
