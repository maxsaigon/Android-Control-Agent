#!/usr/bin/env python3
"""Browser-driven smoke test for the public dashboard domain.

This catches stale public assets or JS crashes that internal localhost API
smoke tests cannot see.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--timeout-ms", type=int, default=60000)
    return parser.parse_args()


def _default_out_dir() -> Path:
    return Path(tempfile.gettempdir()) / "android-control-public-smoke"


def _json_dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    args = _parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "base_url": args.base_url,
        "responses": [],
        "console": [],
        "pageerrors": [],
        "checks": [],
    }

    try:
        from playwright.sync_api import Error, sync_playwright
    except Exception:
        print(
            "❌ Playwright Python is not installed.\n"
            "   Install with: pip install playwright\n"
            "   Then install browser binaries: python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Error as exc:
                print(
                    "❌ Playwright Chromium binary is missing.\n"
                    "   Run: python -m playwright install chromium\n"
                    f"   Details: {exc}",
                    file=sys.stderr,
                )
                return 1

            context = browser.new_context(viewport={"width": 1515, "height": 900})
            page = context.new_page()

            page.on(
                "console",
                lambda msg: report["console"].append(
                    {"type": msg.type, "text": msg.text}
                ),
            )
            page.on("pageerror", lambda err: report["pageerrors"].append(str(err)))

            def on_response(resp) -> None:
                if "/api/" not in resp.url and "/auth/" not in resp.url:
                    return
                try:
                    body = resp.text()
                except Exception as exc:  # pragma: no cover - best effort
                    body = f"<unreadable:{exc}>"
                report["responses"].append(
                    {
                        "url": resp.url,
                        "status": resp.status,
                        "body": body[:2000],
                    }
                )

            page.on("response", on_response)

            login_url = f"{args.base_url.rstrip('/')}/login"
            page.goto(login_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            page.locator("#username").fill(args.username)
            page.locator("#password").fill(args.password)
            page.locator("#loginBtn").click()
            page.wait_for_load_state("networkidle", timeout=args.timeout_ms)
            page.wait_for_timeout(3000)

            page.screenshot(path=str(out_dir / "dashboard.png"), full_page=True)

            state = page.evaluate(
                """() => ({
                  url: location.href,
                  pageTitle: document.title,
                  pageHeader: document.getElementById('pageTitle')?.textContent || null,
                  templateCountBadge: document.getElementById('templateCount')?.textContent || null,
                  templateCards: document.querySelectorAll('#templateLibrary .template-library-card').length,
                  selectedTemplate: document.getElementById('selectedTemplate')?.value || null,
                  selectedTemplateNameVar: typeof selectedTemplateName !== 'undefined' ? selectedTemplateName : null,
                  dynamicFieldCount: document.querySelectorAll('#dynamicTemplateFields .form-group').length,
                  submitText: document.getElementById('submitBtn')?.textContent?.trim() || null,
                  submitDisabled: document.getElementById('submitBtn')?.disabled ?? null,
                  estMode: document.getElementById('estMode')?.textContent || null,
                  estCost: document.getElementById('estCost')?.textContent || null,
                  recentOutcomesText: document.getElementById('recentOutcomes')?.innerText || '',
                  templateLibraryText: document.getElementById('templateLibrary')?.innerText || '',
                })"""
            )
            report["state"] = state
            browser.close()

    finally:
        _json_dump(out_dir / "report.json", report)

    responses = report["responses"]
    templates_ok = any(r["url"].endswith("/api/templates") and r["status"] == 200 for r in responses)
    auth_ok = any("/auth/me" in r["url"] and r["status"] == 200 for r in responses)

    checks = [
        ("logged_in", auth_ok and "/dashboard" in report["state"]["url"]),
        ("templates_api_ok", templates_ok),
        ("no_pageerrors", not report["pageerrors"]),
        ("template_library_rendered", report["state"]["templateCards"] > 0),
        ("template_selected", bool(report["state"]["selectedTemplate"])),
        ("template_state_bound", bool(report["state"]["selectedTemplateNameVar"])),
        ("template_controls_rendered", report["state"]["dynamicFieldCount"] > 0),
        ("cost_estimate_ready", report["state"]["estMode"] not in (None, "", "—")),
        ("submit_ready", report["state"]["submitDisabled"] is False),
    ]
    report["checks"] = [{"name": name, "ok": ok} for name, ok in checks]
    _json_dump(out_dir / "report.json", report)

    failed = [name for name, ok in checks if not ok]
    if failed:
        print(f"❌ Public dashboard smoke failed: {', '.join(failed)}", file=sys.stderr)
        print(f"   Report: {out_dir / 'report.json'}", file=sys.stderr)
        print(f"   Screenshot: {out_dir / 'dashboard.png'}", file=sys.stderr)
        if report["pageerrors"]:
            print(f"   Page errors: {report['pageerrors']}", file=sys.stderr)
        return 1

    print("PUBLIC_SMOKE_OK", json.dumps(
        {
            "template_cards": report["state"]["templateCards"],
            "dynamic_fields": report["state"]["dynamicFieldCount"],
            "selected_template": report["state"]["selectedTemplate"],
            "est_mode": report["state"]["estMode"],
        },
        ensure_ascii=False,
    ))
    print(f"PUBLIC_SMOKE_REPORT {out_dir / 'report.json'}")
    print(f"PUBLIC_SMOKE_SCREENSHOT {out_dir / 'dashboard.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
