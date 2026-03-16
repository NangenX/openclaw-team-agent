# Example: Building a Login Flow

This example walks through a complete 6-agent workflow for implementing a login feature.

## Overview

**Goal**: Add email/password login to a web application.

---

## Step 1 — Initialize the Project

```bash
python3 scripts/task_manager.py init login-flow \
  -g "Add email/password login to web app" \
  --source manual \
  --requester alice
```

## Step 2 — Assign Tasks to Each Stage

```bash
# Product Planner defines the requirement card
python3 scripts/task_manager.py assign login-flow product-planner \
  "Produce REQ-001: email/password login with JWT session"

# Orchestration creates the execution plan
python3 scripts/task_manager.py assign login-flow orchestration \
  "Produce PLAN-001: route tasks to Architecture → Implementation → QA → Docs"

# Architecture designs the solution
python3 scripts/task_manager.py assign login-flow architecture \
  "Produce ADR-001: JWT-based auth, bcrypt password hashing, /api/login endpoint"

# Implementation writes the code
python3 scripts/task_manager.py assign login-flow implementation \
  "Implement /api/login, JWT issuance, and integration tests"

# QA verifies the change
python3 scripts/task_manager.py assign login-flow qa \
  "Verify login happy path, wrong password, account lockout edge cases"

# Documentation updates the docs
python3 scripts/task_manager.py assign login-flow documentation \
  "Update API reference and README with login endpoint details"
```

## Step 3 — Advance Each Stage

```bash
# Mark product-planner done with its output
python3 scripts/task_manager.py update login-flow product-planner in-progress
python3 scripts/task_manager.py result login-flow product-planner \
  "REQ-001: login feature, P0, acceptance: can log in with valid creds, error on invalid"
python3 scripts/task_manager.py update login-flow product-planner done

# Advance orchestration
python3 scripts/task_manager.py update login-flow orchestration in-progress
python3 scripts/task_manager.py result login-flow orchestration \
  "PLAN-001: sequential, arch→impl→qa→docs, no parallel stages needed"
python3 scripts/task_manager.py update login-flow orchestration done

# Architecture and implementation follow the same pattern ...
python3 scripts/task_manager.py update login-flow architecture done
python3 scripts/task_manager.py update login-flow implementation done

# QA gate must pass before documentation can advance
python3 scripts/task_manager.py update login-flow qa in-progress
python3 scripts/task_manager.py result login-flow qa \
  "QA-001: 12/12 tests passed, 0 defects, gate_decision: pass"
python3 scripts/task_manager.py update login-flow qa done

# Documentation can now advance (QA gate is satisfied)
python3 scripts/task_manager.py update login-flow documentation in-progress
python3 scripts/task_manager.py update login-flow documentation done
```

## Step 4 — Check Delivery Gate

```bash
python3 scripts/task_manager.py gate login-flow
# Status: READY
```

## Step 5 — Create the PR

```bash
# Dry-run first to preview
python3 scripts/task_manager.py create-pr login-flow --dry-run

# Then create for real
python3 scripts/task_manager.py create-pr login-flow \
  --title "feat: add email/password login with JWT" \
  --base main
```

## Step 6 — Export Report

```bash
python3 scripts/task_manager.py export login-flow -f md -o ./login-flow-report.md
```

---

## Handling Failures

If a stage fails, use `retry` to reset it while preserving logs:

```bash
python3 scripts/task_manager.py update login-flow implementation failed
python3 scripts/task_manager.py log login-flow implementation "Tests failing: JWT secret env var missing"
python3 scripts/task_manager.py retry login-flow implementation
```

## Setting Deadlines

```bash
python3 scripts/task_manager.py set-deadline login-flow implementation "2026-03-20T18:00:00Z"
python3 scripts/task_manager.py check-timeout login-flow
```

---

## DAG Mode: Parallel Architecture + Design Spike

For features that allow parallel work, use DAG mode:

```bash
python3 scripts/task_manager.py init login-flow-dag -m dag -g "Add login flow"

# No dependencies — these can run in parallel
python3 scripts/task_manager.py add login-flow-dag spec -a product-planner --desc "Write requirement card"
python3 scripts/task_manager.py add login-flow-dag db-schema -a architecture --desc "Design auth schema"

# Both spec and db-schema must be done before implementation
python3 scripts/task_manager.py add login-flow-dag impl -a implementation \
  -d spec,db-schema --desc "Implement login endpoint"

python3 scripts/task_manager.py add login-flow-dag qa-check -a qa \
  -d impl --desc "Verify login tests" \
  --deadline "2026-03-21T12:00:00Z"

python3 scripts/task_manager.py add login-flow-dag docs -a documentation \
  -d qa-check --desc "Update API docs"

# See which tasks are ready to run in parallel
python3 scripts/task_manager.py ready login-flow-dag --json

# Visualize the dependency graph
python3 scripts/task_manager.py graph login-flow-dag
```
