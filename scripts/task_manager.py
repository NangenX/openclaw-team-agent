#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PIPELINE = [
    "product-planner",
    "orchestration",
    "architecture",
    "implementation",
    "qa",
    "documentation",
]
VALID_STATUSES = {"pending", "in-progress", "done", "failed", "skipped"}
DELIVERY_GATE_STAGES = ["qa", "documentation"]
# Stages that must have qa done before they can be advanced to in-progress or done
QA_REQUIRED_BEFORE = {"documentation"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def data_dir() -> Path:
    root = os.environ.get("OPENCLAW_TEAM_TASKS_DIR")
    if root:
        return Path(root).expanduser()
    return Path.cwd() / ".openclaw" / "team-tasks"


def project_file(project: str) -> Path:
    return data_dir() / f"{project}.json"


def ensure_store() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)


def ensure_stage_defaults(stage: dict[str, Any]) -> None:
    stage.setdefault("agent", stage.get("id", ""))
    stage.setdefault("deps", [])
    stage.setdefault("task", "")
    stage.setdefault("result", "")
    stage.setdefault("logs", [])
    stage.setdefault("history", [])
    stage.setdefault("updatedAt", utc_now())
    stage.setdefault("deadline", None)
    stage.setdefault("tokenBudget", None)


def ensure_payload_defaults(payload: dict[str, Any]) -> None:
    payload.setdefault("events", [])
    payload.setdefault("mode", "linear")
    payload.setdefault("status", "active")
    payload.setdefault("goal", "")
    payload.setdefault("intake", {})
    payload.setdefault("createdAt", utc_now())
    payload.setdefault("updatedAt", utc_now())
    payload.setdefault("stages", [])
    for stage in payload["stages"]:
        ensure_stage_defaults(stage)


def load_project(project: str) -> dict[str, Any]:
    path = project_file(project)
    if not path.exists():
        raise SystemExit(f"project not found: {project}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    ensure_payload_defaults(payload)
    return payload


def save_project(project: str, payload: dict[str, Any]) -> None:
    ensure_store()
    ensure_payload_defaults(payload)
    project_file(project).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def stage_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {stage["id"]: stage for stage in payload["stages"]}


def append_event(payload: dict[str, Any], kind: str, message: str, stage_id: str | None = None) -> None:
    payload.setdefault("events", []).append(
        {
            "at": utc_now(),
            "kind": kind,
            "stage": stage_id,
            "message": message,
        }
    )


def append_stage_history(stage: dict[str, Any], action: str, note: str) -> None:
    stage.setdefault("history", []).append(
        {
            "at": utc_now(),
            "action": action,
            "note": note,
        }
    )


def is_done_like(status: str) -> bool:
    return status in {"done", "skipped"}


def sorted_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def has_cycle(stages: list[dict[str, Any]]) -> bool:
    graph = {stage["id"]: sorted_unique(stage.get("deps", [])) for stage in stages}
    visited: set[str] = set()
    visiting: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph and dfs(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(dfs(node) for node in graph)


def deps_satisfied(payload: dict[str, Any], stage: dict[str, Any]) -> bool:
    stages = stage_map(payload)
    for dep in stage.get("deps", []):
        dep_stage = stages.get(dep)
        if dep_stage is None:
            return False
        if not is_done_like(dep_stage["status"]):
            return False
    return True


def next_stage_linear(payload: dict[str, Any]) -> dict[str, Any] | None:
    for stage in payload["stages"]:
        if stage["status"] in {"pending", "in-progress", "failed"}:
            return stage
    return None


def ready_stages_dag(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ready: list[dict[str, Any]] = []
    for stage in payload["stages"]:
        if stage["status"] in {"pending", "failed"} and deps_satisfied(payload, stage):
            ready.append(stage)
    return ready


def recompute_project_status(payload: dict[str, Any]) -> None:
    if all(is_done_like(stage["status"]) for stage in payload["stages"]):
        payload["status"] = "complete"
    elif any(stage["status"] == "failed" for stage in payload["stages"]):
        payload["status"] = "blocked"
    else:
        payload["status"] = "active"


def delivery_gate(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    stages = stage_map(payload)
    blockers: list[str] = []
    for stage_id in DELIVERY_GATE_STAGES:
        stage = stages.get(stage_id)
        if stage is None:
            blockers.append(f"missing required stage: {stage_id}")
            continue
        if stage.get("status") != "done":
            blockers.append(f"{stage_id} not done (current: {stage.get('status', 'unknown')})")
    return len(blockers) == 0, blockers


def qa_gate_satisfied(payload: dict[str, Any]) -> bool:
    """Return True if the QA stage exists and is marked done."""
    stages = stage_map(payload)
    qa_stage = stages.get("qa")
    return qa_stage is not None and qa_stage.get("status") == "done"


def leader_report_message(payload: dict[str, Any], blockers: list[str]) -> str:
    intake = payload.get("intake", {})
    requester = intake.get("requester", "unknown")
    source = intake.get("source", "manual")
    project_status = payload.get("status", "active")
    mode = payload.get("mode", "linear")
    ready, _ = delivery_gate(payload)
    total = len(payload.get("stages", []))
    done = sum(1 for stage in payload.get("stages", []) if stage.get("status") == "done")

    lines = [
        f"[Leader Update] project={payload.get('project', '')}",
        f"goal={payload.get('goal', '')}",
        f"requester={requester} source={source}",
        f"mode={mode} status={project_status} progress={done}/{total}",
    ]
    if ready:
        lines.append("delivery=READY (qa + documentation complete)")
    else:
        lines.append("delivery=NOT_READY")
        for item in blockers:
            lines.append(f"- blocker: {item}")
    return "\n".join(lines)


def render_status(payload: dict[str, Any]) -> str:
    total = len(payload["stages"])
    done = sum(1 for stage in payload["stages"] if stage["status"] == "done")
    mode = payload.get("mode", "linear")
    current = next_stage_linear(payload) if mode == "linear" else None
    ready = ready_stages_dag(payload) if mode == "dag" else []
    lines = [
        f"Project: {payload['project']}",
        f"Goal: {payload['goal']}",
        f"Mode: {mode}",
        f"Status: {payload['status']}",
        (
            f"Current: {current['id'] if current else 'complete'}"
            if mode == "linear"
            else f"Ready: {', '.join(stage['id'] for stage in ready) if ready else 'none'}"
        ),
        "",
    ]
    intake = payload.get("intake", {})
    if intake:
        source = intake.get("source", "manual")
        requester = intake.get("requester", "unknown")
        thread_id = intake.get("threadId", "")
        lines.append(f"Intake: source={source}, requester={requester}, thread={thread_id or '-'}")
        lines.append("")
    for stage in payload["stages"]:
        marker = {
            "pending": "⬜",
            "in-progress": "🔄",
            "done": "✅",
            "failed": "❌",
            "skipped": "⏭️",
        }[stage["status"]]
        lines.append(f"{marker} {stage['id']}: {stage['status']}")
        if stage.get("agent"):
            lines.append(f"   Agent: {stage['agent']}")
        if stage.get("deps"):
            lines.append(f"   Deps: {', '.join(stage['deps'])}")
        if stage["task"]:
            lines.append(f"   Task: {stage['task']}")
        if stage["result"]:
            lines.append(f"   Result: {stage['result']}")
    lines.append("")
    lines.append(f"Progress: {done}/{total}")
    return "\n".join(lines)


def stage_metrics(stage: dict[str, Any]) -> dict[str, Any]:
    history = stage.get("history", [])
    attempts = sum(
        1
        for entry in history
        if entry.get("action") == "status" and "-> in-progress" in entry.get("note", "")
    )
    failures = sum(
        1
        for entry in history
        if entry.get("action") == "status" and "-> failed" in entry.get("note", "")
    )
    resets = sum(1 for entry in history if entry.get("action") == "reset")
    return {
        "id": stage.get("id", ""),
        "agent": stage.get("agent", stage.get("id", "")),
        "status": stage.get("status", "pending"),
        "attempts": attempts,
        "failures": failures,
        "resets": resets,
        "logs": len(stage.get("logs", [])),
    }


def cmd_init(args: argparse.Namespace) -> int:
    ensure_store()
    path = project_file(args.project)
    if path.exists() and not args.force:
        raise SystemExit(f"project already exists: {args.project} (use --force to overwrite)")

    pipeline = (
        sorted_unique([s.strip() for s in args.pipeline.split(",") if s.strip()])
        if args.pipeline
        else DEFAULT_PIPELINE
    )
    if args.mode == "linear":
        stages = [
            {
                "id": stage_id,
                "agent": stage_id,
                "deps": [],
                "status": "pending",
                "task": "",
                "result": "",
                "logs": [],
                "history": [],
                "updatedAt": utc_now(),
            }
            for stage_id in pipeline
        ]
    else:
        stages = []
    payload = {
        "project": args.project,
        "goal": args.goal,
        "intake": {
            "source": args.source,
            "requester": args.requester,
            "threadId": args.thread_id,
        },
        "mode": args.mode,
        "status": "active",
        "createdAt": utc_now(),
        "updatedAt": utc_now(),
        "events": [],
        "stages": stages,
    }
    append_event(payload, "project.init", f"initialized in {args.mode} mode")
    save_project(args.project, payload)
    print(f"initialized project: {args.project}")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    stages = stage_map(payload)
    if args.stage not in stages:
        raise SystemExit(f"unknown stage: {args.stage}")
    stage = stages[args.stage]
    stage["task"] = args.description
    stage["updatedAt"] = utc_now()
    append_stage_history(stage, "assign", f"task assigned: {args.description}")
    append_event(payload, "stage.assign", f"assigned task to {args.stage}", args.stage)
    payload["updatedAt"] = utc_now()
    save_project(args.project, payload)
    print(f"assigned task to {args.stage}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    if args.status not in VALID_STATUSES:
        raise SystemExit(f"invalid status: {args.status}")
    payload = load_project(args.project)
    stages = stage_map(payload)
    if args.stage not in stages:
        raise SystemExit(f"unknown stage: {args.stage}")
    stage = stages[args.stage]
    delivery_ready_before, _ = delivery_gate(payload)
    if payload.get("mode") == "dag" and args.status in {"in-progress", "done"}:
        if not deps_satisfied(payload, stage):
            raise SystemExit(f"cannot set {args.stage} to {args.status}: dependencies not satisfied")
    # Enforce QA gate: stages listed in QA_REQUIRED_BEFORE cannot be advanced
    # past pending unless qa is already done (use --skip-qa-gate only for emergencies)
    if args.stage in QA_REQUIRED_BEFORE and args.status in {"in-progress", "done"}:
        if not getattr(args, "skip_qa_gate", False) and not qa_gate_satisfied(payload):
            raise SystemExit(
                f"cannot advance '{args.stage}' to '{args.status}': "
                "QA stage must be 'done' first. "
                "Use --skip-qa-gate to override (emergency use only)."
            )
    prev_status = stage["status"]
    stage["status"] = args.status
    stage["updatedAt"] = utc_now()
    append_stage_history(stage, "status", f"{prev_status} -> {args.status}")
    append_event(payload, "stage.update", f"{args.stage}: {prev_status} -> {args.status}", args.stage)
    payload["updatedAt"] = utc_now()
    recompute_project_status(payload)
    delivery_ready_after, blockers_after = delivery_gate(payload)
    if not delivery_ready_before and delivery_ready_after:
        append_event(payload, "project.delivery_ready", "qa and documentation gates are satisfied")
    elif args.status == "failed":
        append_event(
            payload,
            "project.delivery_blocked",
            f"delivery gate blocked by {args.stage}: {', '.join(blockers_after) if blockers_after else 'unknown'}",
            args.stage,
        )
    save_project(args.project, payload)
    print(f"updated {args.stage} to {args.status}")
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    stages = stage_map(payload)
    if args.stage not in stages:
        raise SystemExit(f"unknown stage: {args.stage}")
    stage = stages[args.stage]
    stage["result"] = args.output
    stage["updatedAt"] = utc_now()
    append_stage_history(stage, "result", "stage output saved")
    append_event(payload, "stage.result", f"saved result for {args.stage}", args.stage)
    payload["updatedAt"] = utc_now()
    save_project(args.project, payload)
    print(f"saved result for {args.stage}")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    if payload.get("mode", "linear") != "linear":
        raise SystemExit("next is only available in linear mode; use ready for dag mode")
    stage = next_stage_linear(payload)
    if not stage:
        print("all stages complete")
        return 0
    if args.json:
        print(json.dumps(stage, ensure_ascii=False, indent=2))
    else:
        print(stage["id"])
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_status(payload))
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    ensure_store()
    files = sorted(data_dir().glob("*.json"))
    for path in files:
        print(path.stem)
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    events = payload.get("events", [])

    if args.kind:
        events = [evt for evt in events if evt.get("kind") == args.kind]
    if args.stage:
        events = [evt for evt in events if evt.get("stage") == args.stage]
    if args.limit and args.limit > 0:
        events = events[-args.limit :]

    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
        return 0

    if not events:
        print("no events")
        return 0
    for evt in events:
        print(
            f"[{evt.get('at', '')}] {evt.get('kind', '')}"
            f" stage={evt.get('stage', '-')}: {evt.get('message', '')}"
        )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    stages = payload.get("stages", [])
    metrics = [stage_metrics(stage) for stage in stages]

    total = len(metrics)
    done = sum(1 for row in metrics if row["status"] == "done")
    failed = sum(1 for row in metrics if row["status"] == "failed")
    in_progress = sum(1 for row in metrics if row["status"] == "in-progress")
    pending = sum(1 for row in metrics if row["status"] == "pending")
    skipped = sum(1 for row in metrics if row["status"] == "skipped")

    summary = {
        "project": payload.get("project", ""),
        "mode": payload.get("mode", "linear"),
        "status": payload.get("status", "active"),
        "totalStages": total,
        "done": done,
        "failed": failed,
        "inProgress": in_progress,
        "pending": pending,
        "skipped": skipped,
        "events": len(payload.get("events", [])),
        "attempts": sum(row["attempts"] for row in metrics),
        "resets": sum(row["resets"] for row in metrics),
    }

    if args.json:
        print(json.dumps({"summary": summary, "stages": metrics}, ensure_ascii=False, indent=2))
        return 0

    print(f"Project: {summary['project']}")
    print(f"Mode: {summary['mode']}  Status: {summary['status']}")
    print(
        "Counts: "
        f"done={done}, in-progress={in_progress}, pending={pending}, failed={failed}, skipped={skipped}"
    )
    print(
        "Ops: "
        f"events={summary['events']}, attempts={summary['attempts']}, resets={summary['resets']}"
    )
    print("Stage metrics:")
    for row in metrics:
        print(
            f"- {row['id']} [{row['status']}] "
            f"attempts={row['attempts']} failures={row['failures']} resets={row['resets']} logs={row['logs']}"
        )
    return 0


def cmd_blocked(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    stages = stage_map(payload)
    mode = payload.get("mode", "linear")

    blocked_items: list[dict[str, Any]] = []
    failed_stages = [stage for stage in payload.get("stages", []) if stage.get("status") == "failed"]

    for stage in failed_stages:
        blocked_items.append(
            {
                "id": stage.get("id", ""),
                "reason": "stage failed",
                "status": stage.get("status", ""),
                "deps": stage.get("deps", []),
            }
        )

    if mode == "dag":
        for stage in payload.get("stages", []):
            if stage.get("status") != "pending":
                continue
            unmet = [
                dep
                for dep in stage.get("deps", [])
                if dep in stages and not is_done_like(stages[dep].get("status", "pending"))
            ]
            if not unmet:
                continue
            blocked_by_failed = [dep for dep in unmet if stages[dep].get("status") == "failed"]
            blocked_items.append(
                {
                    "id": stage.get("id", ""),
                    "reason": "waiting dependencies",
                    "status": stage.get("status", ""),
                    "deps": stage.get("deps", []),
                    "unmetDeps": unmet,
                    "blockedByFailedDeps": blocked_by_failed,
                }
            )

    if args.json:
        print(json.dumps(blocked_items, ensure_ascii=False, indent=2))
        return 0

    if not blocked_items:
        print("no blocked stages")
        return 0
    for item in blocked_items:
        base = f"- {item.get('id', '')}: {item.get('reason', '')}"
        if item.get("unmetDeps"):
            base += f" (unmet: {', '.join(item['unmetDeps'])})"
        if item.get("blockedByFailedDeps"):
            base += f" (failed deps: {', '.join(item['blockedByFailedDeps'])})"
        print(base)
    return 0


def render_report_markdown(payload: dict[str, Any]) -> str:
    stages = payload.get("stages", [])
    metrics = [stage_metrics(stage) for stage in stages]
    blocked_items: list[dict[str, Any]] = []
    if payload.get("status") == "blocked":
        # Reuse blocked diagnostics in report context.
        stage_lookup = stage_map(payload)
        for stage in stages:
            if stage.get("status") == "failed":
                blocked_items.append({"id": stage.get("id", ""), "reason": "stage failed"})
            if payload.get("mode") == "dag" and stage.get("status") == "pending":
                unmet = [
                    dep
                    for dep in stage.get("deps", [])
                    if dep in stage_lookup and not is_done_like(stage_lookup[dep].get("status", "pending"))
                ]
                if unmet:
                    blocked_items.append(
                        {
                            "id": stage.get("id", ""),
                            "reason": f"waiting dependencies ({', '.join(unmet)})",
                        }
                    )

    lines = [
        f"# Team Task Report: {payload.get('project', '')}",
        "",
        f"- Goal: {payload.get('goal', '')}",
        f"- Mode: {payload.get('mode', 'linear')}",
        f"- Status: {payload.get('status', 'active')}",
        f"- Created: {payload.get('createdAt', '')}",
        f"- Updated: {payload.get('updatedAt', '')}",
        "",
        "## Stage Metrics",
        "",
        "| Stage | Status | Attempts | Failures | Resets | Logs |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in metrics:
        lines.append(
            f"| {row['id']} | {row['status']} | {row['attempts']} | {row['failures']} | {row['resets']} | {row['logs']} |"
        )

    lines.append("")
    lines.append("## Recent Events")
    lines.append("")
    events = payload.get("events", [])[-20:]
    if not events:
        lines.append("- none")
    else:
        for evt in events:
            lines.append(
                f"- [{evt.get('at', '')}] {evt.get('kind', '')}"
                f" stage={evt.get('stage', '-')}: {evt.get('message', '')}"
            )

    lines.append("")
    lines.append("## Blocked Diagnosis")
    lines.append("")
    if not blocked_items:
        lines.append("- no blocked stages")
    else:
        for item in blocked_items:
            lines.append(f"- {item.get('id', '')}: {item.get('reason', '')}")

    return "\n".join(lines) + "\n"


def cmd_export(args: argparse.Namespace) -> int:
    payload = load_project(args.project)

    if args.format == "json":
        output_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        output_text = render_report_markdown(payload)

    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        ext = "json" if args.format == "json" else "md"
        output_path = Path.cwd() / f"{args.project}.report.{ext}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_text, encoding="utf-8")
    print(f"report exported: {output_path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    issues: list[str] = []
    warnings: list[str] = []

    if payload.get("mode") not in {"linear", "dag"}:
        issues.append(f"invalid mode: {payload.get('mode')}")

    stages = payload.get("stages", [])
    stage_ids = [stage.get("id", "") for stage in stages]
    unique_ids = set(stage_ids)
    if len(stage_ids) != len(unique_ids):
        issues.append("duplicate stage ids found")

    stage_lookup = stage_map(payload)
    for stage in stages:
        sid = stage.get("id", "")
        status = stage.get("status", "")
        if status not in VALID_STATUSES:
            issues.append(f"stage {sid}: invalid status {status}")

        for dep in stage.get("deps", []):
            if dep not in stage_lookup:
                issues.append(f"stage {sid}: missing dependency {dep}")

        if status == "done" and not stage.get("result"):
            warnings.append(f"stage {sid}: done without result")

        if status == "failed" and not stage.get("logs"):
            warnings.append(f"stage {sid}: failed without troubleshooting logs")

    if payload.get("mode") == "dag" and has_cycle(stages):
        issues.append("dag cycle detected")

    if payload.get("mode") == "linear" and not stages:
        warnings.append("linear project has no stages")

    ready, blockers = delivery_gate(payload)
    if not ready:
        for blocker in blockers:
            warnings.append(f"delivery gate: {blocker}")

    summary = {
        "project": payload.get("project", ""),
        "ok": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print(f"Doctor: {summary['project']}")
    print("Status: OK" if summary["ok"] else "Status: FAIL")
    if issues:
        print("Issues:")
        for item in issues:
            print(f"- {item}")
    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")
    if not issues and not warnings:
        print("- no issues found")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    stages = stage_map(payload)
    if args.stage not in stages:
        raise SystemExit(f"unknown stage: {args.stage}")
    stage = stages[args.stage]
    stage.setdefault("logs", []).append(
        {
            "at": utc_now(),
            "message": args.message,
        }
    )
    stage["updatedAt"] = utc_now()
    append_stage_history(stage, "log", args.message)
    append_event(payload, "stage.log", f"logged message for {args.stage}", args.stage)
    payload["updatedAt"] = utc_now()
    save_project(args.project, payload)
    print(f"logged message for {args.stage}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    stages = stage_map(payload)
    if args.stage not in stages:
        raise SystemExit(f"unknown stage: {args.stage}")
    stage = stages[args.stage]

    if args.json:
        print(
            json.dumps(
                {
                    "stage": args.stage,
                    "history": stage.get("history", []),
                    "logs": stage.get("logs", []),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"History: {args.stage}")
    for entry in stage.get("history", []):
        print(f"- [{entry.get('at', '')}] {entry.get('action', '')}: {entry.get('note', '')}")
    if stage.get("logs"):
        print("Logs:")
        for entry in stage["logs"]:
            print(f"- [{entry.get('at', '')}] {entry.get('message', '')}")
    return 0


def reset_stage(stage: dict[str, Any], keep_task: bool) -> None:
    old_status = stage.get("status", "pending")
    stage["status"] = "pending"
    if not keep_task:
        stage["task"] = ""
    stage["result"] = ""
    stage["updatedAt"] = utc_now()
    append_stage_history(stage, "reset", f"{old_status} -> pending")


def cmd_reset(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    stages = stage_map(payload)

    if args.all:
        for stage in payload["stages"]:
            reset_stage(stage, keep_task=args.keep_task)
        append_event(payload, "project.reset", "reset all stages")
        payload["updatedAt"] = utc_now()
        recompute_project_status(payload)
        save_project(args.project, payload)
        print("reset all stages")
        return 0

    if not args.stage:
        raise SystemExit("reset requires <stage> or --all")
    if args.stage not in stages:
        raise SystemExit(f"unknown stage: {args.stage}")

    reset_stage(stages[args.stage], keep_task=args.keep_task)
    append_event(payload, "stage.reset", f"reset stage {args.stage}", args.stage)
    payload["updatedAt"] = utc_now()
    recompute_project_status(payload)
    save_project(args.project, payload)
    print(f"reset stage: {args.stage}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    if payload.get("mode") != "dag":
        raise SystemExit("add is only available in dag mode")
    stages = stage_map(payload)
    if args.task_id in stages:
        raise SystemExit(f"task already exists: {args.task_id}")

    deps = sorted_unique([d.strip() for d in (args.deps or "").split(",") if d.strip()])
    for dep in deps:
        if dep not in stages:
            raise SystemExit(f"dependency not found: {dep}")

    new_stage = {
        "id": args.task_id,
        "agent": args.agent,
        "deps": deps,
        "status": "pending",
        "task": args.description or "",
        "result": "",
        "logs": [],
        "history": [],
        "updatedAt": utc_now(),
        "deadline": validate_iso8601(args.deadline) if getattr(args, "deadline", None) else None,
        "tokenBudget": getattr(args, "token_budget", None),
    }
    payload["stages"].append(new_stage)
    if has_cycle(payload["stages"]):
        payload["stages"].pop()
        raise SystemExit("cannot add task: dependency cycle detected")
    payload["updatedAt"] = utc_now()
    recompute_project_status(payload)
    append_event(payload, "dag.add", f"added task {args.task_id}", args.task_id)
    append_stage_history(new_stage, "add", "task added to dag")
    save_project(args.project, payload)
    print(f"added task: {args.task_id}")
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    if payload.get("mode") != "dag":
        raise SystemExit("ready is only available in dag mode")
    ready = ready_stages_dag(payload)
    if args.json:
        stage_by_id = stage_map(payload)
        enriched: list[dict[str, Any]] = []
        for stage in ready:
            dep_outputs = {
                dep: stage_by_id[dep].get("result", "")
                for dep in stage.get("deps", [])
                if dep in stage_by_id
            }
            enriched.append(
                {
                    "id": stage["id"],
                    "agent": stage.get("agent", stage["id"]),
                    "task": stage.get("task", ""),
                    "deps": stage.get("deps", []),
                    "depOutputs": dep_outputs,
                }
            )
        print(json.dumps(enriched, ensure_ascii=False, indent=2))
        return 0

    if not ready:
        print("no ready tasks")
        return 0
    for stage in ready:
        print(stage["id"])
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    if payload.get("mode") != "dag":
        raise SystemExit("graph is only available in dag mode")
    stages = payload["stages"]
    if not stages:
        print("(empty dag)")
        return 0

    children: dict[str, list[str]] = {stage["id"]: [] for stage in stages}
    indeg: dict[str, int] = {stage["id"]: 0 for stage in stages}
    lookup = stage_map(payload)

    for stage in stages:
        for dep in stage.get("deps", []):
            if dep in children:
                children[dep].append(stage["id"])
                indeg[stage["id"]] += 1

    roots = sorted([sid for sid, deg in indeg.items() if deg == 0])

    def marker(status: str) -> str:
        return {
            "pending": "⬜",
            "in-progress": "🔄",
            "done": "✅",
            "failed": "❌",
            "skipped": "⏭️",
        }[status]

    seen: set[str] = set()

    def walk(node: str, prefix: str) -> None:
        if node in seen:
            print(f"{prefix}└─ {node} (↑)")
            return
        seen.add(node)
        st = lookup[node]
        print(f"{prefix}└─ {marker(st['status'])} {node} [{st.get('agent', node)}]")
        for child in sorted(children[node]):
            walk(child, prefix + "   ")

    print(f"Project: {payload['project']} (dag)")
    for root in roots:
        walk(root, "")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    ready, blockers = delivery_gate(payload)
    summary = {
        "project": payload.get("project", ""),
        "ready": ready,
        "requiredStages": DELIVERY_GATE_STAGES,
        "blockers": blockers,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print(f"Gate: {summary['project']}")
    print("Status: READY" if ready else "Status: BLOCKED")
    if blockers:
        print("Blockers:")
        for item in blockers:
            print(f"- {item}")
    return 0


def cmd_leader_report(args: argparse.Namespace) -> int:
    payload = load_project(args.project)
    ready, blockers = delivery_gate(payload)
    message = leader_report_message(payload, blockers)
    events = payload.get("events", [])
    recent = events[-args.limit :] if args.limit and args.limit > 0 else events

    report = {
        "project": payload.get("project", ""),
        "ready": ready,
        "blockers": blockers,
        "message": message,
        "recentEvents": recent,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(message)
    if recent:
        print("Recent events:")
        for evt in recent:
            print(
                f"- [{evt.get('at', '')}] {evt.get('kind', '')}"
                f" stage={evt.get('stage', '-')}: {evt.get('message', '')}"
            )
    return 0


def validate_iso8601(value: str) -> str:
    """Validate that value looks like an ISO-8601 datetime string and return it.

    Accepts the subset used in this tool: YYYY-MM-DDThh:mm:ssZ or +offset.
    Raises SystemExit with a helpful message if invalid.
    """
    import re

    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$"
    if not re.match(pattern, value):
        raise SystemExit(
            f"invalid deadline format: {value!r}. "
            "Expected ISO-8601 datetime, e.g. 2026-03-20T18:00:00Z"
        )
    return value


def cmd_set_deadline(args: argparse.Namespace) -> int:
    """Set or clear the deadline for a stage."""
    payload = load_project(args.project)
    stages = stage_map(payload)
    if args.stage not in stages:
        raise SystemExit(f"unknown stage: {args.stage}")
    stage = stages[args.stage]
    deadline = validate_iso8601(args.deadline) if args.deadline else None
    stage["deadline"] = deadline
    stage["updatedAt"] = utc_now()
    append_stage_history(stage, "deadline", f"deadline set to {deadline or 'none'}")
    append_event(payload, "stage.deadline", f"{args.stage}: deadline={deadline or 'none'}", args.stage)
    payload["updatedAt"] = utc_now()
    save_project(args.project, payload)
    print(f"deadline set for {args.stage}: {deadline or '(cleared)'}")
    return 0


def cmd_check_timeout(args: argparse.Namespace) -> int:
    """Report stages whose deadlines have passed and are not yet done."""
    payload = load_project(args.project)
    now = utc_now()
    overdue: list[dict[str, Any]] = []
    for stage in payload.get("stages", []):
        deadline = stage.get("deadline")
        if not deadline:
            continue
        if is_done_like(stage.get("status", "")):
            continue
        if deadline < now:
            overdue.append(
                {
                    "stage": stage["id"],
                    "status": stage.get("status", "unknown"),
                    "deadline": deadline,
                    "agent": stage.get("agent", stage["id"]),
                }
            )

    if args.json:
        print(json.dumps({"project": payload.get("project", ""), "overdue": overdue}, ensure_ascii=False, indent=2))
        return 0

    if not overdue:
        print("no overdue stages")
        return 0
    print(f"Overdue stages in '{payload.get('project', '')}':")
    for item in overdue:
        print(f"- {item['stage']} [{item['agent']}] status={item['status']} deadline={item['deadline']}")
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    """Reset a failed stage to pending while preserving its task description and logs."""
    payload = load_project(args.project)
    stages = stage_map(payload)
    if args.stage not in stages:
        raise SystemExit(f"unknown stage: {args.stage}")
    stage = stages[args.stage]
    current_status = stage.get("status", "unknown")
    if current_status != "failed":
        raise SystemExit(
            f"cannot retry stage '{args.stage}': status is '{current_status}' (must be 'failed'). "
            "Use 'reset' to reset stages with other statuses."
        )
    old_result = stage.get("result", "")
    stage["status"] = "pending"
    stage["result"] = ""
    stage["updatedAt"] = utc_now()
    append_stage_history(stage, "retry", f"failed -> pending (previous result preserved in log)")
    if old_result:
        stage.setdefault("logs", []).append({"at": utc_now(), "message": f"[retry] previous result: {old_result}"})
    append_event(payload, "stage.retry", f"retrying stage {args.stage}", args.stage)
    payload["updatedAt"] = utc_now()
    recompute_project_status(payload)
    save_project(args.project, payload)
    print(f"retrying stage: {args.stage}")
    return 0


def _build_pr_body(payload: dict[str, Any]) -> str:
    """Build a markdown PR body from project state."""
    goal = payload.get("goal", "")
    project = payload.get("project", "")
    intake = payload.get("intake", {})
    requester = intake.get("requester", "unknown")
    source = intake.get("source", "manual")
    lines = [
        f"## {goal}",
        "",
        f"**Project**: `{project}`  ",
        f"**Requester**: {requester}  ",
        f"**Source**: {source}  ",
        "",
        "## Stages",
        "",
    ]
    for stage in payload.get("stages", []):
        status_icon = {
            "done": "✅",
            "skipped": "⏭️",
            "failed": "❌",
            "in-progress": "🔄",
            "pending": "⬜",
        }.get(stage.get("status", ""), "❓")
        agent = stage.get("agent", stage["id"])
        task = stage.get("task", "")
        result = stage.get("result", "")
        lines.append(f"- {status_icon} **{stage['id']}** ({agent})")
        if task:
            lines.append(f"  - Task: {task}")
        if result:
            lines.append(f"  - Result: {result}")
    lines += ["", "---", "_Generated by OpenClaw task manager_"]
    return "\n".join(lines)


def cmd_create_pr(args: argparse.Namespace) -> int:
    """Check delivery gate and create a GitHub PR via `gh pr create`."""
    import shutil
    import subprocess

    payload = load_project(args.project)
    ready, blockers = delivery_gate(payload)

    if not ready and not getattr(args, "force", False):
        print("Delivery gate is not satisfied. Fix the following before creating a PR:")
        for item in blockers:
            print(f"  - {item}")
        print("\nRun with --force to create the PR anyway (not recommended).")
        return 1

    title = args.title or payload.get("goal") or f"[OpenClaw] {payload.get('project', '')}"
    body = _build_pr_body(payload)

    if args.dry_run:
        print("=== PR Title ===")
        print(title)
        print("\n=== PR Body ===")
        print(body)
        print("\n=== Command (dry-run, body shown above) ===")
        base = args.base or "main"
        draft_flag = " --draft" if args.draft else ""
        print(f"gh pr create --title {title!r} --body '...' --base {base}{draft_flag}")
        return 0

    if not shutil.which("gh"):
        raise SystemExit(
            "GitHub CLI (`gh`) not found. Install it from https://cli.github.com/ "
            "or run with --dry-run to preview the PR."
        )

    cmd: list[str] = ["gh", "pr", "create", "--title", title, "--body", body]
    if args.base:
        cmd += ["--base", args.base]
    if args.draft:
        cmd.append("--draft")

    result = subprocess.run(cmd, capture_output=False)  # noqa: S603
    if result.returncode != 0:
        raise SystemExit(f"gh pr create failed with exit code {result.returncode}")

    append_event(payload, "project.pr_created", f"PR created: {title}")
    payload["updatedAt"] = utc_now()
    save_project(args.project, payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage OpenClaw 6-agent workflows in linear or dag mode."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new project workflow")
    init_parser.add_argument("project")
    init_parser.add_argument("-g", "--goal", required=True)
    init_parser.add_argument("-m", "--mode", choices=["linear", "dag"], default="linear")
    init_parser.add_argument("--source", default="manual", help="Requirement source (manual/feishu/api)")
    init_parser.add_argument("--requester", default="", help="Requester identity")
    init_parser.add_argument("--thread-id", default="", help="External thread/conversation id")
    init_parser.add_argument(
        "-p",
        "--pipeline",
        help="Comma-separated stage order (linear mode only).",
    )
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    add_parser = subparsers.add_parser("add", help="Add a dag task with dependencies")
    add_parser.add_argument("project")
    add_parser.add_argument("task_id")
    add_parser.add_argument("-a", "--agent", required=True)
    add_parser.add_argument("-d", "--deps", help="Comma-separated dependency task IDs")
    add_parser.add_argument("--desc", "--description", dest="description")
    add_parser.add_argument("--deadline", help="ISO-8601 deadline (e.g. 2026-03-20T18:00:00Z)")
    add_parser.add_argument("--token-budget", dest="token_budget", type=int, help="Max tokens for this stage")
    add_parser.set_defaults(func=cmd_add)

    assign_parser = subparsers.add_parser("assign", help="Assign a task to a stage")
    assign_parser.add_argument("project")
    assign_parser.add_argument("stage")
    assign_parser.add_argument("description")
    assign_parser.set_defaults(func=cmd_assign)

    update_parser = subparsers.add_parser("update", help="Update stage status")
    update_parser.add_argument("project")
    update_parser.add_argument("stage")
    update_parser.add_argument("status")
    update_parser.add_argument(
        "--skip-qa-gate",
        action="store_true",
        help="Override QA gate check (emergency use only)",
    )
    update_parser.set_defaults(func=cmd_update)

    result_parser = subparsers.add_parser("result", help="Save stage output")
    result_parser.add_argument("project")
    result_parser.add_argument("stage")
    result_parser.add_argument("output")
    result_parser.set_defaults(func=cmd_result)

    log_parser = subparsers.add_parser("log", help="Add a log entry to a stage")
    log_parser.add_argument("project")
    log_parser.add_argument("stage")
    log_parser.add_argument("message")
    log_parser.set_defaults(func=cmd_log)

    history_parser = subparsers.add_parser("history", help="Show stage history and logs")
    history_parser.add_argument("project")
    history_parser.add_argument("stage")
    history_parser.add_argument("--json", action="store_true")
    history_parser.set_defaults(func=cmd_history)

    reset_parser = subparsers.add_parser("reset", help="Reset one stage or all stages to pending")
    reset_parser.add_argument("project")
    reset_parser.add_argument("stage", nargs="?")
    reset_parser.add_argument("--all", action="store_true")
    reset_parser.add_argument(
        "--keep-task",
        action="store_true",
        help="Keep task description when resetting stage(s)",
    )
    reset_parser.set_defaults(func=cmd_reset)

    next_parser = subparsers.add_parser("next", help="Get next stage to run")
    next_parser.add_argument("project")
    next_parser.add_argument("--json", action="store_true")
    next_parser.set_defaults(func=cmd_next)

    ready_parser = subparsers.add_parser("ready", help="Get all dispatchable tasks in dag mode")
    ready_parser.add_argument("project")
    ready_parser.add_argument("--json", action="store_true")
    ready_parser.set_defaults(func=cmd_ready)

    graph_parser = subparsers.add_parser("graph", help="Show dag dependency graph")
    graph_parser.add_argument("project")
    graph_parser.set_defaults(func=cmd_graph)

    status_parser = subparsers.add_parser("status", help="Show project status")
    status_parser.add_argument("project")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_status)

    list_parser = subparsers.add_parser("list", help="List projects")
    list_parser.set_defaults(func=cmd_list)

    events_parser = subparsers.add_parser("events", help="Query project events")
    events_parser.add_argument("project")
    events_parser.add_argument("--kind", help="Filter by event kind")
    events_parser.add_argument("--stage", help="Filter by stage id")
    events_parser.add_argument("--limit", type=int, default=20, help="Show last N events")
    events_parser.add_argument("--json", action="store_true")
    events_parser.set_defaults(func=cmd_events)

    stats_parser = subparsers.add_parser("stats", help="Show runtime statistics")
    stats_parser.add_argument("project")
    stats_parser.add_argument("--json", action="store_true")
    stats_parser.set_defaults(func=cmd_stats)

    blocked_parser = subparsers.add_parser("blocked", help="Show blocked stages and reasons")
    blocked_parser.add_argument("project")
    blocked_parser.add_argument("--json", action="store_true")
    blocked_parser.set_defaults(func=cmd_blocked)

    export_parser = subparsers.add_parser("export", help="Export project report as json or markdown")
    export_parser.add_argument("project")
    export_parser.add_argument("-f", "--format", choices=["json", "md"], default="md")
    export_parser.add_argument("-o", "--output", help="Output file path")
    export_parser.set_defaults(func=cmd_export)

    doctor_parser = subparsers.add_parser("doctor", help="Run project health checks")
    doctor_parser.add_argument("project")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(func=cmd_doctor)

    gate_parser = subparsers.add_parser("gate", help="Check delivery gate (qa + documentation)")
    gate_parser.add_argument("project")
    gate_parser.add_argument("--json", action="store_true")
    gate_parser.set_defaults(func=cmd_gate)

    leader_report_parser = subparsers.add_parser("leader-report", help="Generate leader progress report")
    leader_report_parser.add_argument("project")
    leader_report_parser.add_argument("--limit", type=int, default=10, help="Show last N events in report")
    leader_report_parser.add_argument("--json", action="store_true")
    leader_report_parser.set_defaults(func=cmd_leader_report)

    set_deadline_parser = subparsers.add_parser("set-deadline", help="Set deadline for a stage")
    set_deadline_parser.add_argument("project")
    set_deadline_parser.add_argument("stage")
    set_deadline_parser.add_argument("deadline", nargs="?", default=None, help="ISO-8601 datetime (omit to clear)")
    set_deadline_parser.set_defaults(func=cmd_set_deadline)

    check_timeout_parser = subparsers.add_parser("check-timeout", help="Report overdue stages")
    check_timeout_parser.add_argument("project")
    check_timeout_parser.add_argument("--json", action="store_true")
    check_timeout_parser.set_defaults(func=cmd_check_timeout)

    retry_parser = subparsers.add_parser("retry", help="Retry a failed stage (keeps task + logs)")
    retry_parser.add_argument("project")
    retry_parser.add_argument("stage")
    retry_parser.set_defaults(func=cmd_retry)

    create_pr_parser = subparsers.add_parser("create-pr", help="Create a GitHub PR after delivery gate passes")
    create_pr_parser.add_argument("project")
    create_pr_parser.add_argument("--title", default="", help="PR title (defaults to project goal)")
    create_pr_parser.add_argument("--base", default="", help="Base branch (default: main)")
    create_pr_parser.add_argument("--draft", action="store_true", help="Create as draft PR")
    create_pr_parser.add_argument("--force", action="store_true", help="Create PR even if gate is not satisfied")
    create_pr_parser.add_argument("--dry-run", action="store_true", help="Preview PR without creating it")
    create_pr_parser.set_defaults(func=cmd_create_pr)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
