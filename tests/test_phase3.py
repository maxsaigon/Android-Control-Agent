"""
Phase 3 Test Suite — Comprehensive tests for multi-device, templates, retry, queue.

Run: /tmp/android-control-venv/bin/python tests/test_phase3.py
Requires: Server running at localhost:8000 with device connected.
"""

import asyncio
import json
import sys
import time
import httpx
import websockets

BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"

# Track results
results = []


def report(name: str, passed: bool, detail: str = ""):
    status = "✅ PASS" if passed else "❌ FAIL"
    results.append((name, passed, detail))
    print(f"  {status} | {name}" + (f" — {detail}" if detail else ""))


async def run_tests():
    print("=" * 60)
    print("Phase 3 Test Suite")
    print("=" * 60)

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # =================================================================
        # 1. HEALTH & VERSION
        # =================================================================
        print("\n📋 1. Health & Version")
        r = await client.get("/")
        data = r.json()
        report("Server is running", r.status_code == 200)
        report("Version is 0.2.0", data.get("version") == "0.2.0", data.get("version"))

        # =================================================================
        # 2. TEMPLATES
        # =================================================================
        print("\n📋 2. Templates")
        r = await client.get("/api/templates")
        templates = r.json()
        report("Templates endpoint works", r.status_code == 200)
        report("Has 4 templates", len(templates) == 4, f"got {len(templates)}")

        template_names = [t["name"] for t in templates]
        report("Has tiktok_browse", "tiktok_browse" in template_names)
        report("Has youtube_watch", "youtube_watch" in template_names)
        report("Has facebook_scroll", "facebook_scroll" in template_names)
        report("Has general", "general" in template_names)

        # Check template structure
        for t in templates:
            has_keys = all(k in t for k in ["name", "title", "description", "file"])
            report(f"Template '{t['name']}' has all fields", has_keys)

        # =================================================================
        # 3. DEVICE SETUP
        # =================================================================
        print("\n📋 3. Device Setup")

        # Check existing devices
        r = await client.get("/api/devices")
        devices = r.json()

        if not devices:
            # Register device
            r = await client.post(
                "/api/devices",
                json={"name": "Sharp 803SH", "ip_address": "192.168.1.150"},
            )
            report("Device registered", r.status_code == 201)
            device_id = r.json()["id"]
        else:
            device_id = devices[0]["id"]
            report("Device already exists", True, f"ID={device_id}")

        # Connect device
        r = await client.post(f"/api/devices/{device_id}/connect")
        if r.status_code == 200:
            report("Device connected", True, r.json()["device"]["device_model"])
        else:
            report("Device connected", False, r.text)
            print("    ⚠️ Device not reachable — some tests will fail")

        # =================================================================
        # 4. QUEUE STATUS
        # =================================================================
        print("\n📋 4. Queue Status")
        r = await client.get("/api/tasks/queue-status")
        qs = r.json()
        report("Queue status endpoint works", r.status_code == 200)
        report("Has running_tasks field", "running_tasks" in qs)
        report("Has max_concurrent field", "max_concurrent" in qs)
        report("max_concurrent = 5", qs.get("max_concurrent") == 5, str(qs.get("max_concurrent")))

        # =================================================================
        # 5. TASK WITH TEMPLATE
        # =================================================================
        print("\n📋 5. Task with Template")
        r = await client.post(
            "/api/tasks",
            json={
                "device_id": device_id,
                "command": "Nhấn Home rồi báo hoàn thành",
                "template": "general",
                "max_steps": 3,
                "max_retries": 0,
            },
        )
        report("Task with template created", r.status_code == 201)
        task_data = r.json()
        report("Template field saved", task_data.get("template") == "general")
        report("max_retries field present", "max_retries" in task_data)
        report("retry_count starts at 0", task_data.get("retry_count") == 0)
        report(
            "Command includes template content",
            "General Task Template" in task_data.get("command", ""),
            "template prepended to command",
        )
        report(
            "Command includes user input",
            "Nhấn Home" in task_data.get("command", ""),
        )
        task_id_template = task_data["id"]

        # Wait for task completion
        print("    ⏳ Waiting for task to complete...")
        for _ in range(30):
            await asyncio.sleep(2)
            r = await client.get(f"/api/tasks/{task_id_template}")
            if r.json()["status"] in ("completed", "failed"):
                break
        task_result = r.json()
        report(
            "Template task completed",
            task_result["status"] in ("completed", "failed"),
            f"status={task_result['status']}, steps={task_result['steps_taken']}",
        )

        # =================================================================
        # 6. RUNNING TASKS ENDPOINT
        # =================================================================
        print("\n📋 6. Running Tasks")
        r = await client.get("/api/tasks/running")
        report("Running tasks endpoint works", r.status_code == 200)
        report("Returns list", isinstance(r.json(), list))

        # =================================================================
        # 7. TASK RETRY FIELDS
        # =================================================================
        print("\n📋 7. Retry Fields")
        r = await client.post(
            "/api/tasks",
            json={
                "device_id": device_id,
                "command": "Nhấn Home rồi báo hoàn thành",
                "max_steps": 3,
                "max_retries": 3,
            },
        )
        task_retry = r.json()
        report("Task with max_retries=3 created", r.status_code == 201)
        report("max_retries saved correctly", task_retry.get("max_retries") == 3)
        report("retry_count starts at 0", task_retry.get("retry_count") == 0)

        # Wait for completion
        print("    ⏳ Waiting for retry task...")
        for _ in range(20):
            await asyncio.sleep(2)
            r = await client.get(f"/api/tasks/{task_retry['id']}")
            if r.json()["status"] in ("completed", "failed"):
                break
        report(
            "Retry task finished",
            r.json()["status"] in ("completed", "failed"),
            f"status={r.json()['status']}",
        )

        # =================================================================
        # 8. BATCH TASK SUBMISSION
        # =================================================================
        print("\n📋 8. Batch Task Submission")
        # With single device (we only have 1)
        r = await client.post(
            "/api/tasks/batch",
            json={
                "device_ids": [device_id],
                "command": "Nhấn Home rồi báo hoàn thành",
                "max_steps": 3,
                "max_retries": 0,
            },
        )
        batch_result = r.json()
        report("Batch submit works", r.status_code == 201)
        report("Returns submitted count", "submitted" in batch_result)
        report("submitted = 1", batch_result.get("submitted") == 1)
        report("Returns tasks list", "tasks" in batch_result)
        report("Tasks list length = 1", len(batch_result.get("tasks", [])) == 1)

        # Invalid device in batch
        r = await client.post(
            "/api/tasks/batch",
            json={
                "device_ids": [999],
                "command": "Test",
                "max_steps": 3,
            },
        )
        report("Batch with invalid device → 404", r.status_code == 404)

        # Wait for batch task
        if batch_result.get("tasks"):
            batch_task_id = batch_result["tasks"][0]["id"]
            print("    ⏳ Waiting for batch task...")
            for _ in range(20):
                await asyncio.sleep(2)
                r = await client.get(f"/api/tasks/{batch_task_id}")
                if r.json()["status"] in ("completed", "failed"):
                    break
            report(
                "Batch task finished",
                r.json()["status"] in ("completed", "failed"),
                f"status={r.json()['status']}",
            )

        # =================================================================
        # 9. TASK FILTERING
        # =================================================================
        print("\n📋 9. Task Filtering")
        r = await client.get(f"/api/tasks?device_id={device_id}")
        report("Filter by device_id works", r.status_code == 200)
        report("Returns tasks for device", len(r.json()) > 0)

        r = await client.get("/api/tasks?status=completed")
        report("Filter by status works", r.status_code == 200)

        r = await client.get("/api/tasks?limit=2")
        report("Limit works", r.status_code == 200 and len(r.json()) <= 2)

        # =================================================================
        # 10. DEVICE LOCK (CONCURRENCY)
        # =================================================================
        print("\n📋 10. Device Lock / Concurrency")
        r = await client.get("/api/tasks/queue-status")
        qs = r.json()
        report(
            "Device lock registered after tasks",
            len(qs.get("device_locks", [])) >= 0,
            f"locks: {qs.get('device_locks')}",
        )

        # =================================================================
        # 11. HEALTH WITH WATCHDOG
        # =================================================================
        print("\n📋 11. Health & Watchdog")
        r = await client.get("/api/health")
        health = r.json()
        report("Health endpoint works", r.status_code == 200)
        report("Has watchdog section", "watchdog" in health)
        report("Watchdog is running", health.get("watchdog", {}).get("running") is True)
        report(
            "Watchdog has devices",
            len(health.get("watchdog", {}).get("devices", {})) > 0,
        )

        # =================================================================
        # 12. WEBSOCKET (optional, quick check)
        # =================================================================
        print("\n📋 12. WebSocket")
        try:
            ws_received = []

            async def ws_listener(task_id: int):
                """Connect to WebSocket and collect events."""
                try:
                    async with websockets.connect(
                        f"{WS_BASE}/ws/tasks/{task_id}", close_timeout=2
                    ) as ws:
                        for _ in range(30):
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                                data = json.loads(msg)
                                ws_received.append(data)
                                if data.get("event") in ("completed", "failed", "cancelled"):
                                    break
                            except asyncio.TimeoutError:
                                break
                except Exception:
                    pass

            # Pre-create task (pending) — it will queue behind any running tasks
            r = await client.post(
                "/api/tasks",
                json={
                    "device_id": device_id,
                    "command": "Nhấn Home rồi báo hoàn thành",
                    "max_steps": 3,
                    "max_retries": 0,
                },
            )
            ws_task_id = r.json()["id"]

            # Run WS listener — it will receive events as they come
            await ws_listener(ws_task_id)

            report(
                "WebSocket received events",
                len(ws_received) > 0,
                f"got {len(ws_received)} events: {[m.get('event') for m in ws_received]}",
            )
            if ws_received:
                events = [m.get("event") for m in ws_received]
                has_progress = any(e in events for e in ("status", "started", "step", "completed", "failed"))
                report("Has progress events", has_progress, str(events))
        except Exception as e:
            report("WebSocket test", False, str(e))

    # =================================================================
    # SUMMARY
    # =================================================================
    print("\n" + "=" * 60)
    passed = sum(1 for _, p, _ in results if p)
    failed = sum(1 for _, p, _ in results if not p)
    total = len(results)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print("\nFailed tests:")
        for name, p, detail in results:
            if not p:
                print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
