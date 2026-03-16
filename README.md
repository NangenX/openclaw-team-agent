# openclaw-team-agent

An [OpenClaw Skill](https://docs.openclaw.ai/) that installs a 6-agent AI development team into your project.

**Version: v0.4**

## Features

- **Self-contained skill** — all agent prompts are embedded in `SKILL.md`, no external path dependencies
- **6 specialized agents** — Product Planner, Orchestration, Architecture, Implementation, QA, Documentation
- **Executable system prompts** — each agent has a clear persona, behavioral rules, and workflow steps
- **Task manager runtime** — a lightweight Python CLI supports both linear and DAG multi-agent workflows
- **QA gate enforcement** — `documentation` stage is blocked until `qa` is marked done
- **Automatic PR creation** — `create-pr` command generates a PR via GitHub CLI after gate passes
- **Deadline & timeout tracking** — `set-deadline` and `check-timeout` commands for time-aware workflows
- **Smart retry** — `retry` command resets failed stages while preserving task context and logs
- **Bilingual support** — Chinese/English documentation consistency

## Installation

```bash
# Clone the repo
git clone https://github.com/your-org/openclaw-team-agent.git

# Copy to your skills directory
cp -r openclaw-team-agent/ /path/to/clawd/skills/openclaw-team-agent/
```

Then in any project:
```
/openclaw-setup
```

## Task Manager CLI

This repository now includes `scripts/task_manager.py`, a minimal workflow runtime for the 6-agent team.

```bash
# Linear mode
python3 scripts/task_manager.py init my-feature -g "Build login flow" --source feishu --requester kim --thread-id oc_xxx
python3 scripts/task_manager.py assign my-feature product-planner "Create requirement card"
python3 scripts/task_manager.py next my-feature
python3 scripts/task_manager.py status my-feature

# DAG mode
python3 scripts/task_manager.py init my-feature-dag -m dag -g "Build login flow"
python3 scripts/task_manager.py add my-feature-dag spec -a product-planner --desc "Write requirement card"
python3 scripts/task_manager.py add my-feature-dag impl -a implementation -d spec --desc "Implement feature" --deadline "2026-03-20T18:00:00Z" --token-budget 16000
python3 scripts/task_manager.py ready my-feature-dag --json
python3 scripts/task_manager.py graph my-feature-dag

# Failure recovery
python3 scripts/task_manager.py log my-feature implementation "build failed at step X"
python3 scripts/task_manager.py history my-feature implementation
python3 scripts/task_manager.py reset my-feature implementation --keep-task
python3 scripts/task_manager.py retry my-feature implementation   # smart retry: keeps task + logs

# Deadline & timeout tracking
python3 scripts/task_manager.py set-deadline my-feature implementation "2026-03-20T18:00:00Z"
python3 scripts/task_manager.py check-timeout my-feature

# Observability
python3 scripts/task_manager.py events my-feature --limit 20
python3 scripts/task_manager.py stats my-feature
python3 scripts/task_manager.py blocked my-feature

# Health check & report
python3 scripts/task_manager.py doctor my-feature
python3 scripts/task_manager.py gate my-feature
python3 scripts/task_manager.py leader-report my-feature
python3 scripts/task_manager.py export my-feature -f md -o ./my-feature.report.md
python3 scripts/task_manager.py export my-feature -f json -o ./my-feature.report.json

# Auto PR creation (requires GitHub CLI: https://cli.github.com/)
python3 scripts/task_manager.py create-pr my-feature --dry-run        # preview only
python3 scripts/task_manager.py create-pr my-feature --title "feat: ..." --base main
python3 scripts/task_manager.py create-pr my-feature --draft           # open as draft

# Feishu message adapter (OpenAPI)
python3 scripts/feishu_openapi_adapter.py send-text --receive-id oc_xxx --text "Leader update" --dry-run
python3 scripts/feishu_openapi_adapter.py send-project-report my-feature --receive-id oc_xxx --dry-run

# Feishu inbound bridge (event callback)
export FEISHU_APP_ID="cli_xxx"
export FEISHU_APP_SECRET="xxx"
export FEISHU_VERIFICATION_TOKEN="token_xxx"
python3 scripts/feishu_inbound_bridge.py serve --host 0.0.0.0 --port 8787

# Local callback simulation
python3 scripts/feishu_inbound_bridge.py handle-file --input ./.tmp_feishu_event.json --dry-run
```

Default linear pipeline order:

```text
product-planner -> orchestration -> architecture -> implementation -> qa -> documentation
```

Supported modes:

- `linear`: sequential stage flow via `next`
- `dag`: dependency graph with parallel-ready tasks via `ready`

Recovery commands:

- `log`: attach troubleshooting notes to a stage
- `history`: review stage status transitions and logs
- `reset`: reset one stage or all stages to pending for retry
- `retry`: smart reset that preserves task description and logs (recommended for failed stages)

Observability commands:

- `events`: query project-level event stream (supports kind/stage filter)
- `stats`: summarize runtime metrics (attempts, failures, resets, logs)
- `blocked`: show blocked stages and dependency-related blocking reasons

Deadline & timeout commands:

- `set-deadline`: assign an ISO-8601 deadline to a stage
- `check-timeout`: report stages that have passed their deadline without completing

Delivery commands:

- `doctor`: run health checks against project state consistency
- `gate`: check delivery gate readiness (must satisfy QA + Documentation)
- `leader-report`: generate leader-facing progress report text with blockers
- `export`: export project report as Markdown or JSON
- `create-pr`: check delivery gate and create a GitHub PR via `gh pr create` (requires [GitHub CLI](https://cli.github.com/))

Feishu adapter:

- `scripts/feishu_openapi_adapter.py`: send leader updates to Feishu via OpenAPI (`send-text`, `send-project-report`)
- `scripts/feishu_inbound_bridge.py`: accept Feishu callback events and map leader commands to task manager

Feishu inbound leader commands:

- `/new <goal>`: create a new requirement/project
- `/status <project>`: return leader progress summary
- `/gate <project>`: return delivery gate status
- `/update <project> <stage> <status>`: advance stage status
- `/log <project> <stage> <message>`: append troubleshooting log

## Agent Team

| Agent | Role |
|-------|------|
| Product Planner | Requirement analysis and task slicing |
| Orchestration | Task routing and execution scheduling |
| Architecture | Architecture decisions and interface contracts |
| Implementation | Code implementation and self-testing |
| QA | Quality verification and code review |
| Documentation | Documentation maintenance and bilingual consistency |

## Workflow

```
User requirement
    ↓
Product Planner  → Requirement Card (REQ-XXX)
    ↓
Orchestration    → Routing Plan (PLAN-XXX)
    ↓
Architecture     → ADR + Interface Contract
    ↓
Implementation   → Code + Self-test Report
    ↓
QA               → Test Report (pass/block)
    ↓
Documentation    → Doc Update
    ↓
Delivery
```

## Project Structure

```
openclaw-team-agent/
├── README.md              # This file
├── SKILL.md               # OpenClaw skill definition (self-contained)
├── agents/                # Agent prompt source files
│   ├── product-planner.md
│   ├── orchestration.md
│   ├── architecture.md
│   ├── implementation.md
│   ├── qa.md
│   └── documentation.md
├── scripts/               # Workflow runtime
│   ├── task_manager.py
│   ├── feishu_openapi_adapter.py
│   └── feishu_inbound_bridge.py
└── docs/                  # Reference documentation
    ├── examples/
    │   └── login-flow.md  # End-to-end worked example
    └── glossary/
        └── terms.zh-en.md
```

## Versioning

- v0.1: Role and governance baseline
- v0.2: Scenario playbooks (from requirement to release)
- v0.3: Optional automated validation
- v0.4: QA gate enforcement, auto PR creation, deadline/timeout tracking, smart retry, expanded glossary, example project
