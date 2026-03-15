#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

try:
    from feishu_openapi_adapter import get_tenant_access_token, send_text_message
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"failed to import feishu_openapi_adapter: {exc}")


def utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def slug(text: str, fallback: str = "req") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:24] if cleaned else fallback


def task_manager_path() -> Path:
    return Path(__file__).with_name("task_manager.py")


def run_task_manager(args: list[str]) -> tuple[bool, str]:
    cmd = [sys.executable, str(task_manager_path())] + args
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    output = output.strip()
    return proc.returncode == 0, output


def parse_message_text(payload: dict[str, Any]) -> str:
    event = payload.get("event", payload)
    message = event.get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {"text": content}
    elif isinstance(content, dict):
        parsed = content
    else:
        parsed = {}
    text = parsed.get("text", "")
    return text.strip()


def parse_chat_id(payload: dict[str, Any]) -> str:
    event = payload.get("event", payload)
    message = event.get("message", {})
    return str(message.get("chat_id", "")).strip()


def parse_requester(payload: dict[str, Any]) -> str:
    event = payload.get("event", payload)
    sender = event.get("sender", {})
    sender_id = sender.get("sender_id", {})
    return (
        str(sender_id.get("open_id") or sender_id.get("user_id") or sender.get("sender_type") or "unknown")
        .strip()
    )


def parse_event_token(payload: dict[str, Any]) -> str:
    token = payload.get("token")
    if token:
        return str(token)
    header = payload.get("header", {})
    if header.get("token"):
        return str(header.get("token"))
    return ""


def build_help() -> str:
    return "\n".join(
        [
            "Leader command help:",
            "- /new <goal>",
            "- /status <project>",
            "- /gate <project>",
            "- /update <project> <stage> <status>",
            "- /log <project> <stage> <message>",
        ]
    )


def cmd_new(goal: str, requester: str, chat_id: str) -> str:
    project = f"req-{utc_compact()}-{slug(goal, 'new')}"
    ok, out = run_task_manager(
        [
            "init",
            project,
            "-g",
            goal,
            "--source",
            "feishu",
            "--requester",
            requester,
            "--thread-id",
            chat_id,
        ]
    )
    if not ok:
        return f"create failed\n{out}"
    ok2, out2 = run_task_manager(["leader-report", project])
    if not ok2:
        return f"created project={project}\n{out}\nleader-report failed\n{out2}"
    return f"created project={project}\n{out2}"


def dispatch_text(text: str, requester: str, chat_id: str) -> str:
    if not text:
        return build_help()

    if text.startswith("/new "):
        goal = text[5:].strip()
        if not goal:
            return "missing goal\n" + build_help()
        return cmd_new(goal, requester, chat_id)

    if text.startswith("/status "):
        project = text[8:].strip()
        ok, out = run_task_manager(["leader-report", project])
        return out if ok else f"status failed\n{out}"

    if text.startswith("/gate "):
        project = text[6:].strip()
        ok, out = run_task_manager(["gate", project])
        return out if ok else f"gate failed\n{out}"

    if text.startswith("/update "):
        parts = text.split(maxsplit=4)
        if len(parts) < 4:
            return "usage: /update <project> <stage> <status>"
        _, project, stage, status = parts[:4]
        ok, out = run_task_manager(["update", project, stage, status])
        if not ok:
            return f"update failed\n{out}"
        ok2, out2 = run_task_manager(["leader-report", project])
        return out2 if ok2 else f"updated\n{out}\nleader-report failed\n{out2}"

    if text.startswith("/log "):
        parts = text.split(maxsplit=3)
        if len(parts) < 4:
            return "usage: /log <project> <stage> <message>"
        _, project, stage, message = parts
        ok, out = run_task_manager(["log", project, stage, message])
        if not ok:
            return f"log failed\n{out}"
        ok2, out2 = run_task_manager(["leader-report", project])
        return out2 if ok2 else f"logged\n{out}\nleader-report failed\n{out2}"

    return build_help()


def send_text_to_feishu(receive_id_type: str, receive_id: str, text: str, app_id: str, app_secret: str) -> dict[str, Any]:
    token = get_tenant_access_token(app_id, app_secret)
    return send_text_message(token, receive_id_type, receive_id, text)


def handle_event_payload(payload: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    event_type = payload.get("type")
    if event_type == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    expected = os.environ.get("FEISHU_VERIFICATION_TOKEN", "").strip()
    if expected:
        got = parse_event_token(payload).strip()
        if got != expected:
            return {"code": 1, "msg": "invalid verification token"}

    text = parse_message_text(payload)
    chat_id = parse_chat_id(payload)
    requester = parse_requester(payload)

    response_text = dispatch_text(text, requester=requester, chat_id=chat_id)

    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()

    sent = None
    if dry_run:
        sent = {
            "receive_id_type": "chat_id",
            "receive_id": chat_id,
            "text": response_text,
            "app_id_provided": bool(app_id),
            "app_secret_provided": bool(app_secret),
        }
    elif chat_id and app_id and app_secret:
        sent = send_text_to_feishu("chat_id", chat_id, response_text, app_id, app_secret)
    else:
        sent = {
            "skipped": True,
            "reason": "missing chat_id or credentials",
            "chat_id": chat_id,
        }

    return {"code": 0, "msg": "ok", "response": response_text, "send": sent}


class FeishuHandler(BaseHTTPRequestHandler):
    dry_run = False

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"code": 1, "msg": "invalid json"})
            return

        result = handle_event_payload(payload, dry_run=self.dry_run)
        status = 200 if result.get("code") in {0, None} or "challenge" in result else 403
        self._json(status, result)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def cmd_serve(args: argparse.Namespace) -> int:
    FeishuHandler.dry_run = args.dry_run
    server = HTTPServer((args.host, args.port), FeishuHandler)
    print(f"feishu inbound bridge listening on http://{args.host}:{args.port}")
    print("set FEISHU_APP_ID/FEISHU_APP_SECRET for outbound replies")
    print("set FEISHU_VERIFICATION_TOKEN for callback verification")
    server.serve_forever()
    return 0


def cmd_handle_file(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = handle_event_payload(payload, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Feishu inbound bridge for OpenClaw leader workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run HTTP callback server")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--dry-run", action="store_true", help="Do not call Feishu send API")
    serve.set_defaults(func=cmd_serve)

    handle_file = subparsers.add_parser("handle-file", help="Handle a local event payload json")
    handle_file.add_argument("--input", required=True, help="Path to event json file")
    handle_file.add_argument("--dry-run", action="store_true", help="Do not call Feishu send API")
    handle_file.set_defaults(func=cmd_handle_file)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
