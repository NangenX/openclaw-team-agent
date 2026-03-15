#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


FEISHU_API = "https://open.feishu.cn/open-apis"


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"http error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"network error: {exc}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid json response: {raw}") from exc


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    url = f"{FEISHU_API}/auth/v3/tenant_access_token/internal"
    resp = post_json(url, {"app_id": app_id, "app_secret": app_secret})
    if resp.get("code") != 0:
        raise SystemExit(f"failed to get tenant token: {resp}")
    token = resp.get("tenant_access_token", "")
    if not token:
        raise SystemExit("empty tenant_access_token in feishu response")
    return token


def send_text_message(token: str, receive_id_type: str, receive_id: str, text: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"receive_id_type": receive_id_type})
    url = f"{FEISHU_API}/im/v1/messages?{query}"
    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    headers = {"Authorization": f"Bearer {token}"}
    return post_json(url, payload, headers=headers)


def cmd_send_text(args: argparse.Namespace) -> int:
    app_id = args.app_id or os.environ.get("FEISHU_APP_ID", "")
    app_secret = args.app_secret or os.environ.get("FEISHU_APP_SECRET", "")

    if args.dry_run:
        print(
            json.dumps(
                {
                    "receiveIdType": args.receive_id_type,
                    "receiveId": args.receive_id,
                    "text": args.text,
                    "appIdProvided": bool(app_id),
                    "appSecretProvided": bool(app_secret),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not app_id or not app_secret:
        raise SystemExit("missing credentials: set FEISHU_APP_ID and FEISHU_APP_SECRET or pass --app-id/--app-secret")

    token = get_tenant_access_token(app_id, app_secret)
    resp = send_text_message(token, args.receive_id_type, args.receive_id, args.text)

    if resp.get("code") != 0:
        raise SystemExit(f"failed to send message: {resp}")

    print(json.dumps(resp, ensure_ascii=False, indent=2))
    return 0


def load_project_report_text(project: str, limit: int) -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    task_manager = os.path.join(script_dir, "task_manager.py")
    cmd = [
        sys.executable,
        task_manager,
        "leader-report",
        project,
        "--json",
        "--limit",
        str(limit),
    ]

    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        detail = stderr or stdout or f"exit code {proc.returncode}"
        raise SystemExit(f"failed to load project report from task_manager: {detail}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid leader-report json output: {proc.stdout}") from exc

    message = payload.get("message", "")
    if not message:
        raise SystemExit("leader-report returned empty message")
    return message


def cmd_send_project_report(args: argparse.Namespace) -> int:
    text = load_project_report_text(args.project, args.limit)

    send_args = argparse.Namespace(
        receive_id_type=args.receive_id_type,
        receive_id=args.receive_id,
        text=text,
        app_id=args.app_id,
        app_secret=args.app_secret,
        dry_run=args.dry_run,
    )
    return cmd_send_text(send_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Feishu OpenAPI adapter for OpenClaw leader notifications")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_text = subparsers.add_parser("send-text", help="Send plain text message")
    send_text.add_argument("--receive-id-type", choices=["chat_id", "open_id", "user_id", "union_id"], default="chat_id")
    send_text.add_argument("--receive-id", required=True, help="Feishu target id according to receive-id-type")
    send_text.add_argument("--text", required=True, help="Message body")
    send_text.add_argument("--app-id", help="Feishu app id")
    send_text.add_argument("--app-secret", help="Feishu app secret")
    send_text.add_argument("--dry-run", action="store_true", help="Print payload without API calls")
    send_text.set_defaults(func=cmd_send_text)

    send_project_report = subparsers.add_parser(
        "send-project-report",
        help="Generate leader report from task_manager and send to Feishu",
    )
    send_project_report.add_argument("project", help="Project id managed by task_manager")
    send_project_report.add_argument(
        "--receive-id-type",
        choices=["chat_id", "open_id", "user_id", "union_id"],
        default="chat_id",
    )
    send_project_report.add_argument("--receive-id", required=True, help="Feishu target id")
    send_project_report.add_argument("--limit", type=int, default=10, help="Recent event count in report")
    send_project_report.add_argument("--app-id", help="Feishu app id")
    send_project_report.add_argument("--app-secret", help="Feishu app secret")
    send_project_report.add_argument("--dry-run", action="store_true", help="Print payload without API calls")
    send_project_report.set_defaults(func=cmd_send_project_report)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
