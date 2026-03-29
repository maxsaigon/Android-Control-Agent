#!/usr/bin/env python3
"""Run repeated TikTok comment audits on one production device overnight.

The runner targets the production app on max.lan via localhost, creates
`tiktok_comment` tasks, waits for completion, stores per-attempt summaries,
and stops once a run reaches the requested verification threshold.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_line(path: Path, line: str) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def parse_verified(result: str | None) -> int:
    if not result:
        return 0
    match = re.search(r"verified:\s*(\d+)", result, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def parse_failed(result: str | None) -> int:
    if not result:
        return 0
    match = re.search(r"failed:\s*(\d+)", result, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def short_detail(detail: str | None, limit: int = 180) -> str:
    if not detail:
        return ""
    text = " ".join(str(detail).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def collect_debug_sessions(root: Path) -> dict[str, float]:
    if not root.exists():
        return {}
    return {
        child.name: child.stat().st_mtime
        for child in root.iterdir()
        if child.is_dir()
    }


def checkpoint_summary(logs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in logs:
        action = str(entry.get("action") or "")
        if not action.startswith("comment_checkpoint:"):
            continue
        name = action.split(":", 1)[1]
        detail = str(entry.get("detail") or "")
        status = "ok" if detail.startswith("ok") else "fail" if detail.startswith("fail") else "unknown"
        result[name] = {
            "status": status,
            "detail": detail,
            "step": entry.get("step"),
            "timestamp": entry.get("timestamp"),
        }
    return result


def summarize_logs(logs: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    screenshots: list[str] = []
    for entry in logs:
        action = str(entry.get("action") or "")
        counts[action] = counts.get(action, 0) + 1
        screenshot_path = entry.get("screenshot_path")
        if screenshot_path:
            screenshots.append(str(screenshot_path))
    tail = [
        {
            "step": entry.get("step"),
            "action": entry.get("action"),
            "detail": short_detail(entry.get("detail")),
            "timestamp": entry.get("timestamp"),
        }
        for entry in logs[-12:]
    ]
    return {
        "counts": counts,
        "checkpoints": checkpoint_summary(logs),
        "tail": tail,
        "screenshots": screenshots[-12:],
    }


@dataclass
class ApiClient:
    base_url: str
    username: str
    password: str

    def __post_init__(self) -> None:
        self._cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )

    def login(self) -> None:
        self.post_json(
            "/auth/login",
            {"username": self.username, "password": self.password},
        )

    def get_json(self, path: str) -> Any:
        req = urllib.request.Request(self.base_url + path)
        with self._opener.open(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with self._opener.open(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}


class OvernightAuditRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out_dir = ensure_dir(Path(args.out_dir).expanduser())
        self.log_path = self.out_dir / "runner.log"
        self.state_path = self.out_dir / "state.json"
        self.summary_path = self.out_dir / "summary.json"
        self.history_path = self.out_dir / "attempts.json"
        self.report_path = self.out_dir / "report.md"
        self.debug_root = Path(args.debug_root).expanduser()
        self.client = ApiClient(args.base_url.rstrip("/"), args.username, args.password)
        self.client.login()
        self.device = self._resolve_device()
        self.required_verified = max(1, args.required_verified)
        self.deadline = utc_now() + timedelta(hours=args.max_hours)
        self._log(
            f"authenticated -> device #{self.device['id']} {self.device['ip_address']}:{self.device['adb_port']} ({self.device['name']})"
        )
        self._write_state({"status": "running", "started_at": iso_now(), "device": self.device})

    def _log(self, message: str) -> None:
        line = f"[{iso_now()}] {message}"
        print(line, flush=True)
        append_line(self.log_path, line)

    def _write_state(self, payload: dict[str, Any]) -> None:
        current = read_json(self.state_path, {})
        current.update(payload)
        write_json(self.state_path, current)

    def _resolve_device(self) -> dict[str, Any]:
        devices = self.client.get_json("/api/devices")
        for device in devices:
            if (
                str(device.get("ip_address")) == self.args.device_ip
                and int(device.get("adb_port") or 0) == self.args.device_port
            ):
                return device
        raise SystemExit(f"Device {self.args.device_ip}:{self.args.device_port} not found")

    def _device_status(self) -> dict[str, Any]:
        devices = self.client.get_json("/api/devices")
        for device in devices:
            if int(device.get("id")) == int(self.device["id"]):
                return device
        raise RuntimeError(f"Device #{self.device['id']} disappeared from /api/devices")

    def _device_running_task(self) -> dict[str, Any] | None:
        running = self.client.get_json("/api/tasks/running")
        for task in running:
            if int(task.get("device_id")) == int(self.device["id"]):
                return task
        return None

    def _wait_for_idle(self) -> None:
        while utc_now() < self.deadline:
            device = self._device_status()
            running = self._device_running_task()
            if running:
                self._log(
                    f"device busy with task #{running.get('id')} ({running.get('status')}); waiting {self.args.poll_interval}s"
                )
                self._write_state(
                    {
                        "status": "waiting_device_busy",
                        "current_running_task": running.get("id"),
                        "last_device_status": device.get("status"),
                    }
                )
                time.sleep(self.args.poll_interval)
                continue
            if device.get("status") == "offline":
                self._log(f"device offline; waiting {self.args.poll_interval}s")
                self._write_state(
                    {"status": "waiting_device_online", "last_device_status": device.get("status")}
                )
                time.sleep(self.args.poll_interval)
                continue
            self.device = device
            return
        raise TimeoutError("deadline reached while waiting for device to become idle")

    def _create_task(self) -> dict[str, Any]:
        payload = {
            "device_id": int(self.device["id"]),
            "command": "TikTok Comment Videos",
            "template": "tiktok_comment",
            "execution_mode": "script",
            "max_steps": int(self.args.max_steps),
            "max_retries": 1,
            "template_vars": {
                "count": int(self.args.target_count),
                "view_time_min": int(self.args.view_time_min),
                "view_time_max": int(self.args.view_time_max),
                "like_after_comment": float(self.args.like_after_comment),
                "use_ai": bool(self.args.use_ai),
                "debug_record": True,
            },
        }
        return self.client.post_json("/api/tasks", payload)

    def _wait_task_complete(self, task_id: int) -> dict[str, Any]:
        while utc_now() < self.deadline:
            task = self.client.get_json(f"/api/tasks/{task_id}")
            status = str(task.get("status") or "").upper()
            if status not in {"PENDING", "RUNNING"}:
                return task
            self._write_state(
                {"status": "task_running", "current_task_id": task_id, "task_status": status}
            )
            time.sleep(self.args.poll_interval)
        raise TimeoutError(f"deadline reached while waiting for task #{task_id}")

    def _build_attempt_record(
        self,
        attempt_no: int,
        task: dict[str, Any],
        logs: list[dict[str, Any]],
        debug_before: dict[str, float],
    ) -> dict[str, Any]:
        debug_after = collect_debug_sessions(self.debug_root)
        new_sessions = sorted(name for name in debug_after if name not in debug_before)
        result_text = str(task.get("result") or "")
        log_summary = summarize_logs(logs)
        verified_from_logs = int(log_summary["counts"].get("comment_verified", 0))
        verified = max(parse_verified(result_text), verified_from_logs)
        failed = max(parse_failed(result_text), int(log_summary["counts"].get("comment_failed", 0)))
        return {
            "attempt": attempt_no,
            "created_at": iso_now(),
            "task_id": task.get("id"),
            "task_status": task.get("status"),
            "task_result": result_text,
            "task_error": task.get("error"),
            "verified": verified,
            "failed": failed,
            "target_count": int(self.args.target_count),
            "threshold": self.required_verified,
            "goal_met": verified >= self.required_verified,
            "new_debug_sessions": new_sessions,
            "log_summary": log_summary,
        }

    def _persist_attempt(self, attempt: dict[str, Any]) -> None:
        attempts = read_json(self.history_path, [])
        attempts.append(attempt)
        write_json(self.history_path, attempts)

        attempt_dir = ensure_dir(self.out_dir / f"attempt-{attempt['attempt']:02d}-task-{attempt['task_id']}")
        write_json(attempt_dir / "summary.json", attempt)
        write_json(attempt_dir / "task-logs.json", attempt["log_summary"])

        report_lines = [
            f"# Overnight TikTok Comment Audit",
            "",
            f"- Updated: {iso_now()}",
            f"- Device: {self.device['ip_address']}:{self.device['adb_port']} ({self.device['name']})",
            f"- Goal: verified >= {self.required_verified}/{self.args.target_count}",
            f"- Latest task: #{attempt['task_id']} ({attempt['task_status']})",
            f"- Latest result: {attempt['task_result'] or '(none)'}",
            f"- Latest verified: {attempt['verified']}",
            f"- Latest failed: {attempt['failed']}",
            f"- Goal met: {'yes' if attempt['goal_met'] else 'no'}",
            "",
            "## Attempts",
        ]
        for item in attempts:
            report_lines.append(
                f"- Attempt {item['attempt']}: task #{item['task_id']} | status={item['task_status']} | verified={item['verified']} | failed={item['failed']} | goal_met={'yes' if item['goal_met'] else 'no'}"
            )
        report_lines.append("")
        report_lines.append("## Latest checkpoints")
        for name, info in attempt["log_summary"]["checkpoints"].items():
            report_lines.append(
                f"- {name}: {info.get('status')} | {short_detail(info.get('detail'))}"
            )
        self.report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        summary = {
            "status": "goal_met" if attempt["goal_met"] else "running",
            "updated_at": iso_now(),
            "latest_attempt": attempt,
            "attempt_count": len(attempts),
            "report_path": str(self.report_path),
        }
        write_json(self.summary_path, summary)
        self._write_state(summary)

    def run(self) -> int:
        self._log(
            f"starting overnight audit | goal verified>={self.required_verified}/{self.args.target_count} | max_attempts={self.args.max_attempts} | deadline={self.deadline.isoformat()}"
        )
        attempts = 0
        while attempts < self.args.max_attempts and utc_now() < self.deadline:
            attempts += 1
            self._wait_for_idle()
            debug_before = collect_debug_sessions(self.debug_root)
            task = self._create_task()
            task_id = int(task["id"])
            self._log(
                f"attempt {attempts}/{self.args.max_attempts}: created task #{task_id} on device #{self.device['id']}"
            )
            self._write_state(
                {
                    "status": "task_submitted",
                    "current_task_id": task_id,
                    "attempt": attempts,
                }
            )
            task = self._wait_task_complete(task_id)
            logs = self.client.get_json(f"/api/tasks/{task_id}/logs")
            attempt_record = self._build_attempt_record(attempts, task, logs, debug_before)
            self._persist_attempt(attempt_record)
            self._log(
                f"task #{task_id} finished status={attempt_record['task_status']} verified={attempt_record['verified']} failed={attempt_record['failed']} goal_met={attempt_record['goal_met']}"
            )
            if attempt_record["new_debug_sessions"]:
                self._log(
                    f"task #{task_id} debug sessions: {', '.join(attempt_record['new_debug_sessions'])}"
                )
            if attempt_record["goal_met"]:
                self._write_state(
                    {
                        "status": "completed",
                        "completed_at": iso_now(),
                        "success_task_id": task_id,
                    }
                )
                self._log(f"goal reached with task #{task_id}")
                return 0
            if attempts < self.args.max_attempts:
                self._log(f"cooldown {self.args.cooldown_seconds}s before next attempt")
                time.sleep(self.args.cooldown_seconds)

        self._write_state({"status": "exhausted", "completed_at": iso_now()})
        self._log("max attempts or deadline reached without meeting goal")
        return 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--device-ip", default="192.168.1.45")
    parser.add_argument("--device-port", type=int, default=5555)
    parser.add_argument("--target-count", type=int, default=3)
    parser.add_argument("--required-verified", type=int, default=2)
    parser.add_argument("--view-time-min", type=int, default=5)
    parser.add_argument("--view-time-max", type=int, default=10)
    parser.add_argument("--like-after-comment", type=float, default=0.0)
    parser.add_argument("--use-ai", action="store_true", default=True)
    parser.add_argument("--no-use-ai", action="store_false", dest="use_ai")
    parser.add_argument("--max-steps", type=int, default=80)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--max-hours", type=float, default=8.0)
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument("--cooldown-seconds", type=int, default=45)
    parser.add_argument(
        "--debug-root",
        default="/home/max/android-control/screenshots/tiktok_comment_debug",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
    )
    args = parser.parse_args(argv)
    if not args.out_dir:
        stamp = datetime.now().strftime("%Y%m%d-night")
        args.out_dir = f"/home/max/android-control/data/overnight-tiktok-audit/{stamp}"
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        runner = OvernightAuditRunner(args)
        return runner.run()
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"HTTP error {exc.code}: {exc.reason}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
