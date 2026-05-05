"""Script Runner — executes hard-coded task scripts at zero AI cost."""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.behavior import human_behavior

logger = logging.getLogger(__name__)


@dataclass
class ScriptResult:
    """Result from a script execution."""

    success: bool
    reason: str
    steps: int
    step_log: list = field(default_factory=list)
    error: Optional[str] = None
    verified_actions: int = 0    # Actions confirmed via UI verification
    failed_actions: int = 0      # Actions that failed verification


# --- Package hints for common apps ---
APP_PACKAGES = {
    "tiktok": ["tiktok", "musically", "trill", "ugc"],
    "youtube": ["youtube"],
    "facebook": ["facebook.katana", "facebook.lite"],
    "instagram": ["instagram"],
    "twitter": ["twitter", "android.twitter"],
    "zalo": ["zing.zalo"],
    "shopee": ["shopee"],
}

# Known package fallbacks for apps that may be hard to discover via generic hints.
KNOWN_PACKAGES = {
    "tiktok": [
        "com.ss.android.ugc.trill",
        "com.zhiliaoapp.musically",
    ],
}


class ScriptRunner:
    """Executes deterministic task scripts — zero AI cost.

    Each script follows the pattern:
    1. force-stop app (clean start)
    2. launch app
    3. wait for load
    4. repeat: view content → swipe/scroll
    5. press HOME (cleanup)
    """

    # Registry of available scripts
    AVAILABLE_SCRIPTS = {
        "tiktok_browse",
        "tiktok_warmup",
        "tiktok_like",
        "tiktok_comment",
        "tiktok_follow",
        "tiktok_upload",
        "tiktok_metrics_sync",
        "youtube_watch",
        "facebook_scroll",
        "instagram_scroll",
        "generic_scroll",
    }

    # Comment pool for TikTok engagement scripts
    TIKTOK_COMMENTS = [
        ":))", "hay quá", "tuyệt vời!", "😂😂", "ủa gì đây",
        "real", "🔥", "nhìn ngon quá", "cười xỉu", "đỉnh",
        "save lại coi tiếp", "cho xin nhạc", "follow rồi nha",
        "quá hay", "hhh", ":3", "💀💀", "giỏi quá",
        # ASCII-safe comments (work as fallback without Unicode support)
        "love this", "so good", "nice one", "lol", "omg",
        "hahaha", "wow", "amazing", "cool", "best",
    ]

    def __init__(self):
        self._package_cache: dict[str, dict[str, str]] = {}
        self._tiktok: "TikTokController | None" = None
        self._upload_debug: dict | None = None
        self._comment_debug: dict | None = None

    def _get_tiktok_controller(self):
        """Lazy-init TikTok controller."""
        if self._tiktok is None:
            from app.services.tiktok_controller import TikTokController
            self._tiktok = TikTokController(
                self._adb,
                backend=self._backend,
                device_hint=self._device,
            )
        else:
            self._tiktok._backend = self._backend
            self._tiktok._device_hint = self._device
        return self._tiktok

    async def run(
        self,
        device: str,
        script_name: str,
        params: dict | None = None,
        adb_agent=None,
        on_step=None,
    ) -> ScriptResult:
        """Execute a named script on a device.

        Args:
            device: ADB device target (ip:port)
            script_name: Name of the script to run
            params: Script parameters (count, view_time, etc.)
            adb_agent: ADBAgent instance for ADB commands
            on_step: Callback for step progress
        """
        if not adb_agent:
            from app.services.adb_agent import adb_agent as _agent
            adb_agent = _agent

        params = params or {}
        self._adb = adb_agent
        self._device = device
        self._params = params
        self._on_step = on_step
        self._step_num = 0
        self._step_log = []
        self._backend = None  # will be initialized async
        self._upload_debug = None
        self._comment_debug = None

        scripts = {
            "tiktok_browse": self._tiktok_browse,
            "tiktok_warmup": self._tiktok_warmup,
            "tiktok_like": self._tiktok_like,
            "tiktok_comment": self._tiktok_comment,
            "tiktok_follow": self._tiktok_follow,
            "tiktok_upload": self._tiktok_upload,
            "tiktok_metrics_sync": self._tiktok_metrics_sync,
            "youtube_watch": self._youtube_watch,
            "facebook_scroll": self._facebook_scroll,
            "instagram_scroll": self._instagram_scroll,
            "generic_scroll": self._generic_scroll,
        }

        handler = scripts.get(script_name)
        if not handler:
            return ScriptResult(
                success=False,
                reason=f"Unknown script: {script_name}",
                steps=0,
                error=f"Available: {', '.join(scripts.keys())}",
            )

        try:
            logger.info(f"🔧 Script '{script_name}' starting on {device}")
            # Initialize backend for this run
            from app.services.backend_manager import backend_manager
            if script_name in ("tiktok_upload", "tiktok_metrics_sync"):
                # UI automation flows are more stable with raw ADB.
                backend_manager.set_backend(device, "adb")
            self._backend = await backend_manager.get_backend(device)
            result = await handler(**params)
            # Always go HOME after script
            await self._safe_key_event("HOME")
            logger.info(
                f"🔧 Script '{script_name}' done: "
                f"{'✅' if result.success else '❌'} {result.reason} → HOME"
            )
            return result
        except Exception as e:
            logger.exception(f"Script '{script_name}' error on {device}")
            try:
                await self._safe_key_event("HOME")
            except Exception:
                pass
            return ScriptResult(
                success=False,
                reason="Script error",
                steps=self._step_num,
                step_log=self._step_log,
                error=str(e),
            )

    # --- Helper methods ---

    async def _backend_call(self, method_name: str, *args, **kwargs):
        """Call backend method with auto-fallback to ADB on Accessibility failure."""
        if self._backend:
            try:
                method = getattr(self._backend, method_name)
                return await method(self._device, *args, **kwargs)
            except RuntimeError as e:
                err_msg = str(e)
                if "Service not running" in err_msg or "not connected" in err_msg.lower():
                    logger.warning(
                        f"⚠️ Accessibility failed ({err_msg}), falling back to ADB"
                    )
                    await self._fallback_to_adb()
                    method = getattr(self._backend, method_name)
                    return await method(self._device, *args, **kwargs)
                raise
        # No backend — use ADB agent directly
        method = getattr(self._adb, method_name)
        return await method(self._device, *args, **kwargs)

    async def _fallback_to_adb(self):
        """Switch backend from Accessibility to ADB for this run."""
        from app.services.backend_manager import backend_manager
        backend_manager.set_backend(self._device, "adb")
        self._backend = backend_manager.adb
        logger.info(f"🔄 Switched {self._device} to ADB backend")

    async def _safe_key_event(self, key: str):
        """Send key event with backend fallback."""
        try:
            await self._backend_call("key_event", key)
        except Exception:
            # Last resort: ADB directly
            try:
                key_map = {"HOME": "3", "BACK": "4", "ENTER": "66"}
                keycode = key_map.get(key.upper(), key)
                await self._adb._run_adb("-s", self._device, "shell", "input", "keyevent", keycode)
            except Exception:
                pass

    async def _adb_cmd(self, *args: str) -> str:
        """Run an ADB command via backend raw_shell or direct _run_adb."""
        if self._backend:
            try:
                _, stdout, _ = await self._backend.raw_shell(self._device, *args)
                return stdout
            except (NotImplementedError, RuntimeError):
                pass
        # Fallback to direct adb
        _, stdout, _ = await self._adb._run_adb(self._device, *args)
        return stdout

    async def _step(self, action: str, detail: str = ""):
        """Log a step and notify callback."""
        self._step_num += 1
        log_entry = {"step": self._step_num, "action": action, "detail": detail}
        self._step_log.append(log_entry)
        logger.info(f"  📍 Step {self._step_num}: {action} {detail}")
        if self._on_step:
            from app.services.adb_agent import AgentStep
            step = AgentStep(step_num=self._step_num, action=action, detail=detail)
            if asyncio.iscoroutinefunction(self._on_step):
                await self._on_step(step)
            else:
                self._on_step(step)

    async def _comment_checkpoint(self, checkpoint: str, ok: bool, detail: str = ""):
        """Structured comment-flow checkpoint logging for regression/debugging."""
        action = f"comment_checkpoint:{checkpoint}"
        suffix = f" | {detail}" if detail else ""
        status_text = "ok" if ok else "fail"
        await self._step(action, f"{status_text}{suffix}")

    async def _open_app(self, app_name: str) -> str:
        """Force-stop and launch an app by name. Returns package name."""
        package = await self._resolve_package(app_name)
        if not package:
            raise RuntimeError(f"App not found: {app_name}")

        try:
            await self._backend_call("force_stop", package)
            await asyncio.sleep(0.5)
            await self._backend_call("launch_app", package)
        except Exception:
            await self._adb_cmd("shell", "am", "force-stop", package)
            await asyncio.sleep(0.5)
            await self._adb_cmd(
                "shell", "monkey", "-p", package,
                "-c", "android.intent.category.LAUNCHER", "1"
            )
        await self._step("open_app", f"{app_name} ({package})")
        return package

    async def _resolve_package(self, name: str) -> str:
        """Find package name for an app."""
        name_lower = name.lower().strip()

        # Check cache
        if self._device in self._package_cache:
            cached = self._package_cache.get(self._device, {}).get(name_lower)
            if cached:
                return cached

        # Get installed packages — use backend for cloud devices
        packages = set()
        if self._device.startswith("cloud:"):
            # Cloud device: use list_packages via backend
            try:
                pkg_list = await self._backend_call("list_packages", True)
                packages = set(pkg_list) if isinstance(pkg_list, list) else set()
            except Exception as e:
                logger.warning(f"Cloud list_packages failed: {e}")
        else:
            # ADB device: use shell command
            result = await self._adb_cmd("shell", "pm", "list", "packages")
            for line in result.strip().split("\n"):
                if line.startswith("package:"):
                    packages.add(line.split(":", 1)[1].strip())

        # Search with hints
        hints = APP_PACKAGES.get(name_lower, [name_lower])
        for pkg in packages:
            for hint in hints:
                if hint in pkg.lower():
                    # Cache it
                    if self._device not in self._package_cache:
                        self._package_cache[self._device] = {}
                    self._package_cache[self._device][name_lower] = pkg
                    return pkg

        # Fallback: probe well-known package IDs directly.
        for candidate in KNOWN_PACKAGES.get(name_lower, []):
            try:
                out = await self._adb_cmd("shell", "pm", "path", candidate)
                if "package:" in out:
                    if self._device not in self._package_cache:
                        self._package_cache[self._device] = {}
                    self._package_cache[self._device][name_lower] = candidate
                    logger.info(f"📦 Resolved {name_lower} via known package: {candidate}")
                    return candidate
            except Exception:
                continue

        # Last-resort fallback for TikTok to avoid hard-fail on package discovery.
        if name_lower == "tiktok":
            fallback_pkg = "com.ss.android.ugc.trill"
            if self._device not in self._package_cache:
                self._package_cache[self._device] = {}
            self._package_cache[self._device][name_lower] = fallback_pkg
            logger.warning(
                "⚠️ Package discovery failed for tiktok on %s; using fallback %s",
                self._device,
                fallback_pkg,
            )
            return fallback_pkg

        return ""

    async def _adb_screencap(self) -> bytes:
        """Capture screenshot via ADB directly (bypasses backend)."""
        proc = await asyncio.create_subprocess_exec(
            self._adb.adb_path, "-s", self._device,
            "shell", "screencap", "-p",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if not stdout:
            raise RuntimeError("ADB screencap returned empty data")
        return stdout

    async def _wait(self, lo: float, hi: float, label: str = "viewing"):
        """Wait a randomized duration."""
        duration = random.uniform(lo, hi)
        await self._step("wait", f"{duration:.1f}s ({label})")
        await asyncio.sleep(duration)

    def _safe_name(self, value: str) -> str:
        """Normalize text for filesystem-safe artifact names."""
        cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._")
        return cleaned or "item"

    def _write_upload_debug_manifest(self):
        """Persist the current upload debug manifest to disk."""
        if not self._upload_debug:
            return
        manifest_path: Path = self._upload_debug["manifest_path"]
        manifest = self._upload_debug["manifest"]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_comment_debug_manifest(self):
        """Persist the current TikTok comment debug manifest to disk."""
        if not self._comment_debug:
            return
        manifest_path: Path = self._comment_debug["manifest_path"]
        manifest = self._comment_debug["manifest"]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _start_comment_debug_session(
        self,
        *,
        record_enabled: bool,
        count: int,
        use_ai: bool,
    ):
        """Initialize debug artifact storage for TikTok comment runs."""
        if not record_enabled or self._device.startswith("cloud:"):
            self._comment_debug = None
            return

        started_at = datetime.now(timezone.utc)
        session_name = (
            f"{started_at.strftime('%Y%m%dT%H%M%SZ')}_"
            f"{self._safe_name(self._device)}"
        )
        artifact_dir = Path(settings.screenshots_dir) / "tiktok_comment_debug" / session_name
        artifact_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "script": "tiktok_comment",
            "device": self._device,
            "started_at": started_at.isoformat(),
            "target_count": count,
            "use_ai": use_ai,
            "record_enabled": record_enabled,
            "cycles": [],
        }
        self._comment_debug = {
            "enabled": True,
            "record": record_enabled,
            "dir": artifact_dir,
            "manifest": manifest,
            "manifest_path": artifact_dir / "manifest.json",
            "active_cycle": None,
        }
        self._write_comment_debug_manifest()

    async def _start_comment_cycle_record(self, label: str):
        """Start ADB screenrecord for a single comment cycle."""
        if (
            not self._comment_debug
            or not self._comment_debug.get("record")
            or self._device.startswith("cloud:")
        ):
            return

        safe_label = self._safe_name(label)
        remote_path = f"/sdcard/_{safe_label}.mp4"
        local_path = self._comment_debug["dir"] / f"{safe_label}.mp4"
        cmd = [
            self._adb.adb_path,
            "-s",
            self._device,
            "shell",
            "screenrecord",
            "--time-limit",
            "150",
            remote_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        cycle = {
            "label": label,
            "remote_path": remote_path,
            "local_path": str(local_path),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "step_started": self._step_num,
        }
        self._comment_debug["active_cycle"] = {
            "proc": proc,
            "meta": cycle,
        }
        self._comment_debug["manifest"]["cycles"].append(cycle)
        self._write_comment_debug_manifest()

    async def _stop_comment_cycle_record(self, status: str):
        """Stop the active comment-cycle recording and pull it locally."""
        if not self._comment_debug:
            return

        active = self._comment_debug.get("active_cycle")
        if not active:
            return

        proc = active.get("proc")
        cycle = active.get("meta", {})
        remote_path = cycle.get("remote_path")
        local_path = cycle.get("local_path")
        cycle["status"] = status
        cycle["step_finished"] = self._step_num
        cycle["stopped_at"] = datetime.now(timezone.utc).isoformat()

        try:
            await self._adb._run_adb(
                self._device,
                "shell",
                "sh",
                "-c",
                "pkill -INT screenrecord || killall -INT screenrecord || true",
            )
        except Exception:
            pass

        if proc:
            try:
                await asyncio.wait_for(proc.communicate(), timeout=8)
            except Exception:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass

        if remote_path and local_path:
            code, _, err = await self._adb._run_adb(
                self._device,
                "pull",
                remote_path,
                local_path,
            )
            if code == 0:
                cycle["pulled_at"] = datetime.now(timezone.utc).isoformat()
                logger.info("  🎥 [comment_debug] Saved cycle recording: %s", local_path)
            else:
                cycle["pull_error"] = err
            await self._adb._run_adb(self._device, "shell", "rm", "-f", remote_path)

        self._comment_debug["active_cycle"] = None
        self._write_comment_debug_manifest()

    def _start_upload_debug_session(
        self,
        *,
        assignment_id: int | None,
        video_id: int | None,
        capture_enabled: bool,
        record_enabled: bool,
        title: str,
        description: str,
    ):
        """Initialize upload artifact storage."""
        enabled = capture_enabled or record_enabled
        if not enabled:
            self._upload_debug = None
            return

        started_at = datetime.now(timezone.utc)
        session_name = (
            f"{started_at.strftime('%Y%m%dT%H%M%SZ')}_"
            f"{self._safe_name(self._device)}"
        )
        artifact_dir = Path(settings.screenshots_dir) / "tiktok_upload_debug" / session_name
        artifact_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "script": "tiktok_upload",
            "device": self._device,
            "started_at": started_at.isoformat(),
            "assignment_id": assignment_id,
            "video_id": video_id,
            "debug_capture": capture_enabled,
            "debug_record": record_enabled,
            "title_preview": title[:120],
            "description_preview": description[:240],
            "snapshots": [],
            "screenrecord": {},
        }
        self._upload_debug = {
            "enabled": True,
            "capture": capture_enabled,
            "record": record_enabled,
            "dir": artifact_dir,
            "manifest": manifest,
            "manifest_path": artifact_dir / "manifest.json",
            "screenrecord_proc": None,
        }
        self._write_upload_debug_manifest()

    async def _capture_upload_debug(
        self,
        tiktok,
        label: str,
        note: str = "",
    ) -> dict | None:
        """Capture and register a debug snapshot for the upload flow."""
        if not self._upload_debug or not self._upload_debug.get("capture") or not tiktok:
            return None

        step_prefix = f"{self._step_num:02d}"
        snapshot = await tiktok.capture_debug_snapshot(
            self._device,
            str(self._upload_debug["dir"]),
            f"{step_prefix}_{label}",
            note,
        )
        snapshot["step_num"] = self._step_num
        self._upload_debug["manifest"]["snapshots"].append(snapshot)
        self._write_upload_debug_manifest()
        return snapshot

    async def _start_upload_screenrecord(self):
        """Start optional ADB screen recording for the upload run."""
        if (
            not self._upload_debug
            or not self._upload_debug.get("record")
            or self._device.startswith("cloud:")
        ):
            return

        remote_path = "/sdcard/_tiktok_upload_record.mp4"
        local_path = self._upload_debug["dir"] / "screenrecord.mp4"
        cmd = [
            self._adb.adb_path,
            "-s",
            self._device,
            "shell",
            "screenrecord",
            "--time-limit",
            "180",
            remote_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._upload_debug["screenrecord_proc"] = proc
        self._upload_debug["manifest"]["screenrecord"] = {
            "remote_path": remote_path,
            "local_path": str(local_path),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_upload_debug_manifest()

    async def _stop_upload_screenrecord(self):
        """Stop optional screen recording and pull the file locally."""
        if not self._upload_debug or not self._upload_debug.get("record"):
            return

        record_meta = self._upload_debug["manifest"].get("screenrecord", {})
        remote_path = record_meta.get("remote_path")
        local_path = record_meta.get("local_path")
        proc = self._upload_debug.get("screenrecord_proc")

        if not remote_path or not local_path:
            return

        try:
            await self._adb._run_adb(
                self._device,
                "shell",
                "sh",
                "-c",
                "pkill -INT screenrecord || killall -INT screenrecord || true",
            )
        except Exception:
            pass

        if proc:
            try:
                await asyncio.wait_for(proc.communicate(), timeout=8)
            except Exception:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass

        code, _, err = await self._adb._run_adb(
            self._device, "pull", remote_path, local_path
        )
        if code == 0:
            record_meta["pulled_at"] = datetime.now(timezone.utc).isoformat()
        else:
            record_meta["pull_error"] = err

        await self._adb._run_adb(self._device, "shell", "rm", "-f", remote_path)
        self._upload_debug["screenrecord_proc"] = None
        self._write_upload_debug_manifest()

    async def _swipe_up(self):
        """Swipe up to next content."""
        w, h = await self._backend_call("get_screen_size")
        x = w // 2 + random.randint(-30, 30)
        y1 = int(h * 0.75) + random.randint(-20, 20)
        y2 = int(h * 0.25) + random.randint(-20, 20)
        dur = random.randint(250, 450)
        try:
            await self._backend_call("swipe", x, y1, x, y2, dur)
        except Exception:
            await self._adb_cmd(
                "shell", "input", "swipe",
                str(x), str(y1), str(x), str(y2), str(dur)
            )
        await self._step("swipe_up", "next content")
        await human_behavior.random_delay("swipe")

    async def _advance_tiktok_feed(
        self,
        tiktok,
        previous_fingerprint: str | None,
        *,
        max_swipes: int = 3,
    ) -> str | None:
        """Advance TikTok feed and verify that the visible video changed."""
        baseline = previous_fingerprint or ""
        for attempt in range(max_swipes):
            await self._swipe_up()
            if not baseline:
                return None

            next_fingerprint = await tiktok.wait_for_new_video(
                self._device,
                baseline,
                timeout=2.8,
                poll_interval=0.45,
            )
            if next_fingerprint and next_fingerprint != baseline:
                if attempt:
                    await self._step(
                        "swipe_recovered",
                        f"feed advanced after extra swipe {attempt + 1}/{max_swipes}",
                    )
                return next_fingerprint

            await self._step(
                "swipe_retry",
                f"video fingerprint unchanged after swipe {attempt + 1}/{max_swipes}",
            )

        await self._step("swipe_stuck", "video fingerprint unchanged after repeated swipes")
        return baseline or None

    async def _scroll_down(self):
        """Scroll down (shorter swipe than full page)."""
        w, h = await self._backend_call("get_screen_size")
        x = w // 2 + random.randint(-30, 30)
        y1 = int(h * 0.65) + random.randint(-20, 20)
        y2 = int(h * 0.35) + random.randint(-20, 20)
        dur = random.randint(300, 500)
        try:
            await self._backend_call("swipe", x, y1, x, y2, dur)
        except Exception:
            await self._adb_cmd(
                "shell", "input", "swipe",
                str(x), str(y1), str(x), str(y2), str(dur)
            )
        await self._step("scroll_down", "scroll feed")
        await human_behavior.random_delay("scroll_down")

    async def _tap_random_like(self, chance: float = 0.3):
        """Randomly double-tap to like (TikTok style)."""
        if random.random() > chance:
            return
        w, h = await self._backend_call("get_screen_size")
        x = w // 2 + random.randint(-50, 50)
        y = h // 2 + random.randint(-50, 50)
        try:
            await self._backend_call("tap", x, y)
            await asyncio.sleep(0.15)
            await self._backend_call("tap", x, y)
        except Exception:
            await self._adb_cmd("shell", "input", "tap", str(x), str(y))
            await asyncio.sleep(0.15)
            await self._adb_cmd("shell", "input", "tap", str(x), str(y))
        await self._step("double_tap", "liked")

    # --- Built-in scripts ---

    async def _tiktok_browse(
        self,
        count: int = 5,
        view_time_min: float = 5.0,
        view_time_max: float = 15.0,
        like_chance: float = 0.3,
        **_,
    ) -> ScriptResult:
        """Browse TikTok: open → view videos → swipe."""
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        # Dismiss popups and ensure on feed
        tiktok = self._get_tiktok_controller()
        await tiktok.ensure_on_feed(self._device)
        await self._step("ensure_feed", "dismissed popups, on For You feed")

        for i in range(count):
            # View current video
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}/{count}")
            # Maybe like
            await self._tap_random_like(like_chance)
            # Swipe to next
            await self._swipe_up()

        return ScriptResult(
            success=True,
            reason=f"Browsed {count} TikTok videos",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _tiktok_warmup(
        self,
        count: int = 8,
        view_time_min: float = 10.0,
        view_time_max: float = 30.0,
        **_,
    ) -> ScriptResult:
        """Warm-up TikTok account: open → view videos passively → no interactions."""
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        # Dismiss popups and ensure on feed
        tiktok = self._get_tiktok_controller()
        await tiktok.ensure_on_feed(self._device)
        await self._step("ensure_feed", "dismissed popups, on For You feed")

        for i in range(count):
            # View current video — longer than normal browsing
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}/{count}")

            # Occasionally pause extra long (20% chance) — simulate watching full video
            if random.random() < 0.2:
                extra = random.uniform(15, 45)
                await self._step("wait", f"{extra:.1f}s (watching full video)")
                await asyncio.sleep(extra)

            # Occasionally view creator profile (15% chance)
            if random.random() < 0.15:
                w, h = await self._adb.get_screen_size(self._device)
                # Tap avatar area (right side, middle)
                avatar_x = int(w * 0.93) + random.randint(-10, 10)
                avatar_y = int(h * 0.45) + random.randint(-15, 15)
                await self._adb_cmd("shell", "input", "tap", str(avatar_x), str(avatar_y))
                await self._step("tap", "view creator profile")
                await self._wait(3, 8, "browsing profile")
                # Go back to feed
                await self._adb_cmd("shell", "input", "keyevent", "4")
                await self._step("key", "back to feed")
                await self._wait(1, 2, "returning")

            # Swipe to next video
            await self._swipe_up()

        return ScriptResult(
            success=True,
            reason=f"Warmed up TikTok: viewed {count} videos passively",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _tiktok_like(
        self,
        count: int = 10,
        view_time_min: float = 5.0,
        view_time_max: float = 15.0,
        like_chance: float = 0.3,
        **_,
    ) -> ScriptResult:
        """Like TikTok videos: browse feed + double-tap or tap heart."""
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        # Dismiss popups and ensure on feed
        tiktok = self._get_tiktok_controller()
        await tiktok.ensure_on_feed(self._device)
        await self._step("ensure_feed", "dismissed popups, on For You feed")

        likes_done = 0
        consecutive_likes = 0

        for i in range(count * 3):  # Browse more videos than target likes
            if likes_done >= count:
                break

            # View current video
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}")

            # Decide to like
            should_like = random.random() < like_chance and consecutive_likes < 5

            if should_like:
                w, h = await self._adb.get_screen_size(self._device)
                verified = 0
                failed = 0

                if random.random() < 0.7:
                    # Double-tap to like (70% — most natural)
                    x = w // 2 + random.randint(-50, 50)
                    y = h // 2 + random.randint(-50, 50)
                    await self._adb_cmd("shell", "input", "tap", str(x), str(y))
                    await asyncio.sleep(random.uniform(0.1, 0.2))
                    await self._adb_cmd("shell", "input", "tap", str(x), str(y))
                    like_method = "double-tap"
                else:
                    # Tap heart icon (30%)
                    heart_x = int(w * 0.93) + random.randint(-8, 8)
                    heart_y = int(h * 0.38) + random.randint(-8, 8)
                    await self._adb_cmd("shell", "input", "tap", str(heart_x), str(heart_y))
                    like_method = "heart icon"

                # [Verify] Check if like actually registered
                like_ok = await tiktok.verify_like_state(self._device, expected_liked=True)
                if like_ok:
                    likes_done += 1
                    verified += 1
                    await self._step("like_verified", f"✅ liked ({like_method}) [{likes_done}/{count}]")
                else:
                    failed += 1
                    await self._step("like_failed", f"❌ like NOT verified ({like_method})")
                    # Capture debug screenshot on failure
                    await tiktok.capture_verification_screenshot(self._device, "like")

                consecutive_likes += 1
                await self._wait(0.5, 1.5, "post-like pause")

                # Occasionally view profile after liking (10% chance)
                if random.random() < 0.1:
                    avatar_x = int(w * 0.93) + random.randint(-10, 10)
                    avatar_y = int(h * 0.45) + random.randint(-15, 15)
                    await self._adb_cmd("shell", "input", "tap", str(avatar_x), str(avatar_y))
                    await self._step("tap", "view creator profile")
                    await self._wait(2, 5, "browsing profile")
                    await self._adb_cmd("shell", "input", "keyevent", "4")
                    await self._step("key", "back to feed")
                    await self._wait(1, 2, "returning")
            else:
                consecutive_likes = 0

            # Swipe to next
            await self._swipe_up()

            # Anti-detection: occasional long pause
            if random.random() < 0.1:
                await self._wait(8, 20, "natural pause")

        return ScriptResult(
            success=likes_done > 0,
            reason=f"Liked {likes_done}/{count} TikTok videos (verified: {likes_done})",
            steps=self._step_num,
            step_log=self._step_log,
            verified_actions=likes_done,
            failed_actions=count - likes_done if likes_done < count else 0,
        )

    # Shared prompt for AI comment generation
    _COMMENT_SYSTEM_PROMPT = (
        "Bạn là người Việt Nam đang lướt TikTok. "
        "Viết MỘT comment CỤ THỂ cho video này.\n\n"
        "BẮT BUỘC:\n"
        "- Comment PHẢI đề cập MỘT chi tiết CỤ THỂ trong video "
        "(người, hành động, cảnh, nhạc, lời nói, outfit, kỹ năng...)\n"
        "- PHẢI có GÓC NHÌN/QUAN ĐIỂM rõ ràng — đồng ý, không đồng ý, "
        "bất ngờ, hỏi thêm, so sánh, chia sẻ kinh nghiệm\n"
        "- KHÔNG viết comment chung chung như 'hay quá', 'tuyệt vời', 'đỉnh'\n"
        "- KHÔNG khen suông — phải nói RÕ khen CÁI GÌ\n\n"
        "Ví dụ TỐT: 'đoạn chuyển nhạc ở giây 5 smooth quá', 'outfit hôm nay match ghê', "
        "'kỹ năng tay trái ảo thật', 'nhạc này là bài gì nhỉ nghe hoài ko chán'\n"
        "Ví dụ XẤU: 'hay quá', 'tuyệt vời!', 'đỉnh nóc', ':))', 'quá đẹp'\n\n"
        "Quy tắc phong cách:\n"
        "- Ngắn gọn 4-12 từ\n"
        "- Tự nhiên, giống gen Z Việt thật sự\n"
        "- Có thể dùng emoji 1-2 cái, viết tắt, slang\n"
        "- Nếu có comment của người khác, có thể đồng ý/phản bác 1 ý kiến cụ thể\n"
        "- KHÔNG hashtag, KHÔNG formal, KHÔNG tag ai\n"
        "Chỉ trả về comment text, không giải thích."
    )

    async def _ai_generate_comment(
        self,
        fallback_pool: list[str] = None,
        existing_comments: list[dict] = None,
        video_info: dict = None,
    ) -> str:
        """Hybrid: AI generates contextual, opinionated comment.

        Priority (cost-optimized):
        1. DeepSeek (primary) — text-only with video info + existing comments
        2. GPT-4o (fallback) — vision + screenshot
        3. Random pool (last resort)

        Args:
            existing_comments: list of {"user": ..., "text": ...} scraped from panel
            video_info: dict from get_video_info (author, description, sound, etc.)
        """
        from app.config import settings
        import openai

        # If video_info not provided, get it now
        if not video_info:
            tiktok = self._get_tiktok_controller()
            try:
                video_info = await tiktok.get_video_info(self._device)
            except Exception:
                video_info = {}

        # --- Build rich context ---
        context_parts = []
        if video_info.get("author"):
            context_parts.append(f"Creator: {video_info['author']}")
        if video_info.get("description"):
            context_parts.append(f"Mô tả video: {video_info['description']}")
        if video_info.get("sound"):
            context_parts.append(f"Nhạc nền: {video_info['sound']}")
        if video_info.get("likes"):
            context_parts.append(f"Likes: {video_info['likes']}")
        if video_info.get("comments"):
            context_parts.append(f"Số comment: {video_info['comments']}")

        # Add existing comments for context
        if existing_comments:
            context_parts.append("\n--- Comment nổi bật (người khác đã viết) ---")
            for c in existing_comments[:8]:
                user = c.get('user', '?')
                text = c.get('text', '')
                if text:
                    context_parts.append(f"  @{user}: {text}")

        context = "\n".join(context_parts) if context_parts else "Video TikTok bất kỳ"

        # --- Try DeepSeek (primary — text-only, ~$0.00006/comment) ---
        if settings.deepseek_api_key:
            try:
                client = openai.AsyncOpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url="https://api.deepseek.com",
                )

                user_msg = (
                    f"Video info:\n{context}\n\n"
                    "Viết 1 comment CỤ THỂ, có quan điểm rõ ràng, "
                    "đề cập chi tiết trong video hoặc phản hồi ý kiến người khác:"
                )

                response = await client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": self._COMMENT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=60,
                    temperature=1.0,
                )

                comment = response.choices[0].message.content.strip().strip('"\'')
                logger.info(f"  🧠 [deepseek] comment: {comment}")
                await self._step("ai_comment", f"[deepseek] {comment}")
                return comment

            except Exception as e:
                logger.warning(f"DeepSeek failed: {e}")

        # --- Try GPT-4o (fallback — vision, ~$0.003/comment) ---
        if settings.openai_api_key:
            try:
                import base64
                # Capture screenshot via ADB directly (Accessibility may not support it)
                screenshot_bytes = await self._adb_screencap()
                await self._step("screenshot", "captured for GPT-4o fallback")

                client = openai.AsyncOpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.llm_base_url or None,
                )
                img_b64 = base64.b64encode(screenshot_bytes).decode()
                mime = "image/jpeg" if screenshot_bytes[:2] == b'\xff\xd8' else "image/png"

                response = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": self._COMMENT_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Viết comment cho video TikTok này:"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime};base64,{img_b64}",
                                        "detail": "low",
                                    },
                                },
                            ],
                        },
                    ],
                    max_tokens=30,
                    temperature=0.8,
                )

                comment = response.choices[0].message.content.strip().strip('"\'')
                usage = response.usage
                if usage:
                    logger.info(
                        f"  🧠 [gpt-4o-fallback] comment: in={usage.prompt_tokens} "
                        f"out={usage.completion_tokens}"
                    )
                await self._step("ai_comment", f"[gpt-4o] {comment}")
                return comment

            except Exception as e:
                logger.warning(f"GPT-4o fallback failed: {e}")

        # --- Last resort: random pool ---
        await self._step("ai_fallback", "Both AI providers unavailable")
        pool = fallback_pool or self.TIKTOK_COMMENTS
        return random.choice(pool)

    async def _tiktok_comment(
        self,
        count: int = 5,
        view_time_min: float = 5.0,
        view_time_max: float = 15.0,
        like_after_comment: float = 0.5,
        use_ai: bool = True,
        debug_record: bool = True,
        **_,
    ) -> ScriptResult:
        """Hybrid comment: script navigates, AI generates contextual comments.

        Flow:
        1. [Script] Open TikTok, browse feed
        2. [Script] Decide when to comment (random chance)
        3. [AI]     Capture screenshot → AI analyzes → generates relevant comment
        4. [Script] Open comment panel, type AI comment, send
        5. [Verify] Check comment was posted (input cleared / text visible)
        6. [Retry]  On failure: retry once with ASCII comment
        7. [Script] Swipe to next video

        Cost: ~1 AI call per comment (not per step). 5 comments = ~5 API calls.
        """
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        # Dismiss popups and ensure on feed
        tiktok = self._get_tiktok_controller()
        await tiktok.ensure_on_feed(self._device)
        await self._step("ensure_feed", "dismissed popups, on For You feed")
        self._start_comment_debug_session(
            record_enabled=debug_record,
            count=count,
            use_ai=use_ai,
        )

        comments_done = 0
        comments_verified = 0
        comments_failed = 0
        used_comments = set()
        handled_video_fingerprints = set()
        videos_since_last_comment = 0

        for i in range(count * 4):  # Browse many more videos than comments
            if comments_done >= count:
                break
            # Safety: prevent runaway loops (each comment ~20 steps with verification)
            if self._step_num > 100:
                logger.warning(f"⚠️ Step limit reached ({self._step_num}), ending script")
                break

            # [Script] View current video
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}")

            current_video_fingerprint = ""
            try:
                current_video_fingerprint = await tiktok.get_video_fingerprint(self._device)
            except Exception as e:
                logger.warning("Failed to fingerprint current TikTok video: %s", e)

            # [Script] Only comment if skipped at least 2 videos since last comment
            should_comment = (
                videos_since_last_comment >= 2
                and random.random() < 0.4
            )

            if should_comment:
                tiktok = self._get_tiktok_controller()
                cycle_index = comments_done + comments_failed + 1
                cycle_status = "failed"
                await self._start_comment_cycle_record(
                    f"{cycle_index:02d}_video_{i+1}"
                )

                try:
                    if not current_video_fingerprint:
                        cycle_status = "skipped_unfingerprinted"
                        await self._step(
                            "skip_unfingerprinted_video",
                            "current video fingerprint unavailable; skip to avoid duplicate comment risk",
                        )
                        videos_since_last_comment = 0
                        await self._advance_tiktok_feed(tiktok, None)
                        continue

                    if current_video_fingerprint in handled_video_fingerprints:
                        cycle_status = "skipped_duplicate_video"
                        await self._step(
                            "skip_duplicate_video",
                            f"video already handled in this session ({current_video_fingerprint[:8]})",
                        )
                        videos_since_last_comment = 0
                        await self._advance_tiktok_feed(tiktok, current_video_fingerprint)
                        continue

                    handled_video_fingerprints.add(current_video_fingerprint)
                    await self._step(
                        "video_lock",
                        f"single-attempt lock for video {current_video_fingerprint[:8]}",
                    )

                    # [Step 1] Get video info from feed (before opening panel)
                    video_info = {}
                    try:
                        video_info = await tiktok.get_video_info(self._device)
                        await self._step("info", f"video: {video_info.get('author', '?')} | {video_info.get('description', '')[:40]}")
                    except Exception:
                        pass

                    # [Step 2] Open comment panel to read existing comments
                    if await tiktok.is_live_session(self._device):
                        cycle_status = "skipped_live"
                        await self._step("skip_live", "LIVE session detected; skip because template targets video comments")
                        videos_since_last_comment = 0
                        await self._advance_tiktok_feed(tiktok, current_video_fingerprint)
                        continue

                    tapped = await tiktok.tap_comment_icon(self._device)
                    await self._step("tap", f"open comments ({'ui' if tapped else 'failed'})")
                    if not tapped:
                        videos_since_last_comment = 0
                        await self._advance_tiktok_feed(tiktok, current_video_fingerprint)
                        cycle_status = "tap_failed"
                        continue
                    await self._wait(1.5, 3, "comments loading")

                    if await tiktok.is_live_session(self._device):
                        cycle_status = "skipped_live"
                        await self._step("skip_live", "LIVE chat UI detected after opening comments; skip this session")
                        videos_since_last_comment = 0
                        await self._advance_tiktok_feed(tiktok, current_video_fingerprint)
                        continue

                    # [Step 3] Read existing comments for AI context
                    existing_comments = []
                    try:
                        existing_comments = await tiktok.read_comments(self._device)
                        if existing_comments:
                            preview = existing_comments[0].get('text', '')[:30]
                            await self._step("read_comments", f"read {len(existing_comments)} comments (top: {preview}...)")
                    except Exception as e:
                        logger.warning(f"Failed to read comments: {e}")

                    # [Step 4] Generate AI comment WITH full context
                    if use_ai:
                        comment_text = await self._ai_generate_comment(
                            self.TIKTOK_COMMENTS,
                            existing_comments=existing_comments,
                            video_info=video_info,
                        )
                    else:
                        # Prefer ASCII-safe comments (avoids mangled diacritics in fallback)
                        ascii_safe = [c for c in self.TIKTOK_COMMENTS
                                      if all(ord(ch) < 128 for ch in c)
                                      and c not in used_comments]
                        if ascii_safe:
                            comment_text = random.choice(ascii_safe)
                        else:
                            available = [c for c in self.TIKTOK_COMMENTS if c not in used_comments]
                            if not available:
                                available = list(self.TIKTOK_COMMENTS)
                                used_comments.clear()
                            comment_text = random.choice(available)
                        used_comments.add(comment_text)

                    # --- Attempt to post (panel already open, skip re-opening) ---
                    comment_posted = await self._attempt_comment(
                        tiktok, comment_text, comments_done, count,
                        panel_already_open=True,
                        baseline_comments=existing_comments,
                    )

                    retry_panel_open = True
                    retry_used = False
                    if not comment_posted and tiktok.has_helper_service_issue(self._device):
                        await self._step(
                            "helper_recover",
                            "accessibility service dropped during comment flow; recovering before retry",
                        )
                        recovered = await tiktok.recover_helper_service(self._device)
                        await self._comment_checkpoint("helper_recovered", recovered, "before_retry")
                        retry_panel_open = False
                        if recovered:
                            try:
                                retry_panel_open = await tiktok.is_comment_panel_open(self._device)
                            except Exception:
                                retry_panel_open = False
                        if not recovered:
                            comment_posted = False

                    # --- Retry once on failure with ASCII comment ---
                    if not comment_posted:
                        retry_used = True
                        await self._step("comment_retry", "retrying with ASCII comment")
                        retry_text = random.choice(["nice", "love this", "wow", "lol", "so good", ":)"])
                        comment_posted = await self._attempt_comment(
                            tiktok,
                            retry_text,
                            comments_done,
                            count,
                            is_retry=True,
                            panel_already_open=retry_panel_open,
                            baseline_comments=existing_comments,
                        )

                    if comment_posted:
                        comments_done += 1
                        comments_verified += 1
                        cycle_status = "verified"
                        if retry_used:
                            await self._step("comment_recovered", f"✅ comment verified after retry [{comments_done}/{count}]")
                        await self._step("comment_verified", f"✅ comment verified [{comments_done}/{count}]")
                    else:
                        comments_failed += 1
                        cycle_status = "failed"
                        await self._step("comment_failed", f"❌ comment NOT verified (both attempts failed)")
                        # Capture screenshot for debugging
                        await tiktok.capture_verification_screenshot(self._device, "comment")

                    # [Script] Maybe like the video too
                    if comment_posted and random.random() < like_after_comment:
                        await tiktok.double_tap_like(self._device)
                        await self._step("double_tap", "liked")
                finally:
                    # [Controller] Close comments (in case panel is still open)
                    try:
                        await tiktok.close_panel(self._device)
                        await self._step("key", "close comments")
                        await self._wait(1, 2, "panel closing animation")
                    except Exception as e:
                        logger.warning("Failed to close comment panel cleanly: %s", e)
                        await self._step("key_warn", f"close comments degraded: {e}")
                    await self._stop_comment_cycle_record(cycle_status)

                videos_since_last_comment = 0
            else:
                videos_since_last_comment += 1

            # [Script] Swipe to next
            await self._advance_tiktok_feed(tiktok, current_video_fingerprint)

        mode_label = "hybrid AI+script" if use_ai else "script-only"
        return ScriptResult(
            success=comments_verified > 0,
            reason=(
                f"Commented on {comments_done}/{count} TikTok videos ({mode_label}) "
                f"— verified: {comments_verified}, failed: {comments_failed}"
            ),
            steps=self._step_num,
            step_log=self._step_log,
            verified_actions=comments_verified,
            failed_actions=comments_failed,
        )

    async def _attempt_comment(
        self,
        tiktok,
        comment_text: str,
        comments_done: int,
        count: int,
        is_retry: bool = False,
        panel_already_open: bool = False,
        baseline_comments: list[dict] | None = None,
    ) -> bool:
        """Attempt to post a single comment. Returns True if verified.

        Steps: open panel → tap input → type → send → verify
        If panel_already_open=True, skips opening the panel (caller did it).
        """
        retry_label = " (retry)" if is_retry else ""

        # [Controller] Tap comment icon (UI-hierarchy-based)
        # Skip if panel was already opened by caller (for reading comments)
        if not panel_already_open:
            tapped = await tiktok.tap_comment_icon(self._device)
            if not tapped and await tiktok.is_comment_panel_open(self._device):
                await self._step("tap", f"open comments{retry_label} (already open)")
                tapped = True
            else:
                await self._step("tap", f"open comments{retry_label} ({'ui' if tapped else 'failed'})")
            if not tapped:
                return False
            await self._wait(1.5, 3, "comments loading")

            # [Script] Sometimes read others' comments first (40% chance)
            if random.random() < 0.4:
                await self._wait(2, 5, "reading comments")

        # [Controller] Tap comment input field
        await tiktok.tap_comment_input(self._device)
        await self._step("tap", f"comment input{retry_label}")
        await self._wait(0.8, 1.5, "keyboard opening")

        input_cleared = await tiktok.clear_comment_input(self._device)
        if not input_cleared:
            await self._step("verify_fail", f"comment input not cleared{retry_label}")
            await tiktok.capture_verification_screenshot(
                self._device,
                "comment_input_not_cleared_retry" if is_retry else "comment_input_not_cleared",
            )
            return False

        helper_issue_before_type = tiktok.has_helper_service_issue(self._device)
        if helper_issue_before_type:
            await self._step("helper_warn", f"helper degraded before typing{retry_label}")
            await tiktok.capture_verification_screenshot(
                self._device,
                "comment_helper_degraded_before_type_retry" if is_retry else "comment_helper_degraded_before_type",
            )

        # [Controller] Type the comment
        await tiktok.type_text(self._device, comment_text)
        await self._step("type", f"typed{retry_label}: {comment_text}")
        await self._wait(0.5, 1, "text settling")

        helper_issue_after_type = tiktok.has_helper_service_issue(self._device)
        if helper_issue_after_type:
            await self._step("helper_warn", f"helper degraded during typing{retry_label}")
            await tiktok.capture_verification_screenshot(
                self._device,
                "comment_helper_degraded_during_type_retry" if is_retry else "comment_helper_degraded_during_type",
            )

        # [Verify] Check if text was actually typed (excludes placeholder)
        strict_verify = is_retry or len(comment_text.strip()) <= 4
        text_ok = await tiktok._verify_text_entered(
            self._device,
            comment_text,
            strict=strict_verify,
        )
        await self._comment_checkpoint(
            "text_entered_ok",
            text_ok,
            "retry" if is_retry else "primary",
        )
        if text_ok:
            await self._step("verify", f"text confirmed in field{retry_label}")
        else:
            fail_detail = (
                f"text NOT in field after helper degradation{retry_label}"
                if (helper_issue_before_type or helper_issue_after_type)
                else f"text NOT in field{retry_label}"
            )
            await self._step("verify_fail", fail_detail)
            # Try one more time with plain ASCII
            if not is_retry:
                await tiktok.capture_verification_screenshot(self._device, "comment_text_missing_primary")
                return False
            # On retry, force type again
            await tiktok.tap_comment_input(self._device)
            await self._wait(0.5, 1, "re-focusing")
            re_cleared = await tiktok.clear_comment_input(self._device)
            if not re_cleared:
                await self._step("verify_fail", "comment input not cleared before retry retype")
                await tiktok.capture_verification_screenshot(self._device, "comment_input_not_cleared_retry")
                return False
            await tiktok.type_text(self._device, comment_text)
            await self._wait(0.5, 1, "re-typing")
            retry_text_ok = await tiktok._verify_text_entered(
                self._device,
                comment_text,
                strict=True,
            )
            await self._comment_checkpoint("text_reentered_ok", retry_text_ok, "retry")
            if not retry_text_ok:
                await self._step("verify_fail", "text still NOT in field after retry retype")
                await tiktok.capture_verification_screenshot(self._device, "comment_text_missing_retry")
                return False
            await self._step("verify", "text confirmed after retry retype")

        # [Verify] TikTok sometimes shows text but leaves Send disabled.
        send_ready = await tiktok.ensure_comment_send_ready(self._device, comment_text)
        await self._comment_checkpoint(
            "send_ready_ok",
            send_ready,
            "retry" if is_retry else "primary",
        )
        if send_ready:
            await self._step("verify", f"send button active{retry_label}")
        else:
            await self._step("verify_fail", f"send button inactive{retry_label}")
            return False

        # [Controller] Send comment only when an active target was detected.
        sent = await tiktok.send_comment(self._device, allow_blind_fallback=False)
        await self._comment_checkpoint(
            "send_tap_ok",
            sent,
            "retry" if is_retry else "primary",
        )
        if not sent:
            await self._step("verify_fail", f"send target missing{retry_label}")
            return False
        await self._step("send", f"sent comment{retry_label} [{comments_done+1}/{count}]")

        # [Verify] Check if comment was actually posted
        posted = await tiktok.verify_comment_posted(
            self._device,
            comment_text,
            timeout=3.0,
            baseline_comments=baseline_comments,
        )
        await self._comment_checkpoint(
            "posted_ok",
            posted,
            "retry" if is_retry else "primary",
        )
        if not posted:
            await tiktok.capture_verification_screenshot(
                self._device,
                "comment_post_failed_retry" if is_retry else "comment_post_failed",
            )
        return posted

    async def _tiktok_follow(
        self,
        count: int = 5,
        view_time_min: float = 5.0,
        view_time_max: float = 12.0,
        follow_chance: float = 0.3,
        **_,
    ) -> ScriptResult:
        """Follow TikTok accounts from feed: browse → tap avatar → follow."""
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        # Dismiss popups and ensure on feed
        tiktok = self._get_tiktok_controller()
        await tiktok.ensure_on_feed(self._device)
        await self._step("ensure_feed", "dismissed popups, on For You feed")

        follows_done = 0
        follows_verified = 0
        follows_failed = 0
        videos_since_last_follow = 0

        for i in range(count * 5):  # Browse many videos per follow
            if follows_done >= count:
                break

            # View current video
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}")

            # Only follow if skipped some videos
            should_follow = (
                videos_since_last_follow >= 3
                and random.random() < follow_chance
            )

            if should_follow:
                tiktok = self._get_tiktok_controller()
                w, h = await self._adb.get_screen_size(self._device)

                # [Controller] Tap avatar to go to profile
                tapped = await tiktok.tap_avatar(self._device)
                await self._step("tap", f"open creator profile ({'ui' if tapped else 'fallback'})")
                if not tapped:
                    videos_since_last_follow += 1
                    await self._swipe_up()
                    continue
                await self._wait(2, 4, "profile loading")

                # Sometimes watch a video on profile (40% chance)
                if random.random() < 0.4:
                    vid_x = int(w * 0.2) + random.randint(-10, 10)
                    vid_y = int(h * 0.65) + random.randint(-10, 10)
                    await self._adb_cmd("shell", "input", "tap", str(vid_x), str(vid_y))
                    await self._step("tap", "watch profile video")
                    await self._wait(3, 8, "watching profile video")
                    await tiktok.close_panel(self._device)
                    await self._step("key", "back to profile")
                    await self._wait(1, 2, "returning to profile")

                # Sometimes decide NOT to follow (30% chance — natural)
                if random.random() < 0.3:
                    await self._step("skip", "decided not to follow")
                else:
                    # [Controller] Tap Follow button
                    followed = await tiktok.tap_follow(self._device)
                    if followed:
                        # [Verify] Check if follow actually registered
                        follow_ok = await tiktok.verify_follow_state(self._device)
                        if follow_ok:
                            follows_done += 1
                            follows_verified += 1
                            await self._step("follow_verified", f"✅ followed [{follows_done}/{count}]")
                        else:
                            follows_failed += 1
                            await self._step("follow_failed", f"❌ follow NOT verified")
                            await tiktok.capture_verification_screenshot(self._device, "follow")
                    else:
                        await self._step("skip", "follow button not found")
                    await self._wait(1, 2, "post-follow pause")

                # Go back to feed
                await tiktok.close_panel(self._device)
                await self._step("key", "back to feed")
                await self._wait(1, 3, "returning to feed")
                videos_since_last_follow = 0
            else:
                videos_since_last_follow += 1

            # Swipe to next
            await self._swipe_up()

        return ScriptResult(
            success=follows_done > 0,
            reason=(
                f"Followed {follows_done}/{count} TikTok accounts "
                f"— verified: {follows_verified}, failed: {follows_failed}"
            ),
            steps=self._step_num,
            step_log=self._step_log,
            verified_actions=follows_verified,
            failed_actions=follows_failed,
        )

    async def _tiktok_upload(
        self,
        assignment_id: int | None = None,
        video_id: int | None = None,
        title: str | None = None,
        description: str | None = None,
        debug_capture: bool = True,
        debug_record: bool = False,
        **_,
    ) -> ScriptResult:
        """Upload a video to TikTok using assigned metadata."""
        if not assignment_id and not video_id:
            return ScriptResult(
                success=False,
                reason="Missing assignment_id or video_id",
                steps=self._step_num,
                error="Missing required parameters",
            )

        # Database lookup
        from sqlmodel import Session
        from app.database import engine
        from app.models import VideoAssignment, Video, PushStatus, UploadStatus
        from datetime import datetime, timezone

        use_title = title or ""
        use_desc = description or ""
        thumbnail_path = ""

        with Session(engine) as session:
            video = None
            assignment = None
            
            if assignment_id:
                assignment = session.get(VideoAssignment, assignment_id)
                if assignment:
                    video = session.get(Video, assignment.video_id)
            elif video_id:
                video = session.get(Video, video_id)
                
            if not video:
                return ScriptResult(
                    success=False,
                    reason="Video not found in DB",
                    steps=self._step_num,
                )
                
            # If not provided via params, fall back to DB metadata
            if not use_title:
                use_title = video.ai_title or video.title or ""
            if not use_desc:
                use_desc = video.ai_description or video.description or ""
            thumbnail_path = video.thumbnail or ""
                
            # Add hashtags
            tags = video.ai_tags or video.tags
            if tags:
                tag_str = " ".join([t if t.startswith("#") else f"#{t}" for t in tags.replace(",", " ").split() if t.strip()])
                if tag_str:
                    use_desc = f"{use_desc}\n\n{tag_str}".strip()

        tiktok = self._get_tiktok_controller()
        self._start_upload_debug_session(
            assignment_id=assignment_id,
            video_id=video_id,
            capture_enabled=debug_capture,
            record_enabled=debug_record,
            title=use_title,
            description=use_desc,
        )

        result: ScriptResult | None = None
        await self._start_upload_screenrecord()

        try:
            await self._capture_upload_debug(
                tiktok, "start", "Before launching TikTok upload flow"
            )

            # [Script 1] Open App & Ensure Feed
            await self._open_app("tiktok")
            await self._wait(3, 5, "app loading")
            await self._capture_upload_debug(tiktok, "app_open", "TikTok launched")

            if not await tiktok.ensure_on_feed(self._device):
                result = ScriptResult(
                    False,
                    "Could not confirm TikTok feed before upload",
                    self._step_num,
                )
                return result
            await self._step("ensure_feed", "on For You feed")
            await self._capture_upload_debug(tiktok, "feed_ready", "Feed ready")

            # [Script 2] Enter camera/gallery from Create.
            create_state = await tiktok.open_create_entry(self._device, timeout=10.0)
            if not create_state:
                result = ScriptResult(
                    False,
                    "Create did not open camera/gallery",
                    self._step_num,
                )
                return result
            await self._step("tap", f"Create entry ({create_state})")
            await self._capture_upload_debug(
                tiktok,
                "after_create",
                f"Create opened state: {create_state}",
            )

            gallery_state = create_state if create_state == "gallery_picker" else None

            # [Script 3] Some builds open camera first and require Next to enter gallery.
            if create_state == "camera_create":
                # Strategy A: tap Upload thumbnail directly from camera screen.
                if await tiktok.tap_upload_gallery(self._device):
                    await self._step("tap", "Upload (Camera -> Gallery)")
                    await self._capture_upload_debug(
                        tiktok, "gallery_entry", "Tapped Upload thumbnail"
                    )
                    gallery_state = await tiktok.wait_for_upload_state(
                        self._device, {"gallery_picker"}, timeout=8.0
                    )

                # Strategy B fallback: some builds use Next to enter gallery.
                if not gallery_state:
                    if not await tiktok.tap_next(self._device):
                        result = ScriptResult(
                            False,
                            "Failed to open gallery from camera screen",
                            self._step_num,
                        )
                        return result
                    await self._step("tap", "Next (Camera -> Gallery)")
                    await self._capture_upload_debug(
                        tiktok, "gallery_entry", "Entered gallery picker via Next"
                    )
                    gallery_state = await tiktok.wait_for_upload_state(
                        self._device, {"gallery_picker"}, timeout=8.0
                    )

                if not gallery_state:
                    current_state = await tiktok.detect_upload_state(self._device)
                    result = ScriptResult(
                        False,
                        f"Gallery picker did not appear (current_state={current_state})",
                        self._step_num,
                    )
                    return result
            else:
                await self._capture_upload_debug(
                    tiktok,
                    "gallery_entry",
                    "Create opened gallery directly",
                )

            if not gallery_state:
                result = ScriptResult(False, "Gallery picker did not appear", self._step_num)
                return result

            # [Script 4] Select the correct video
            await self._capture_upload_debug(
                tiktok,
                "gallery_ready",
                f"Gallery state ready: {gallery_state}",
            )

            # When launched via run-upload, device_filename tells us exactly which
            # file to select. Without it, fallback to the first video in gallery.
            device_filename = (self._params or {}).get("device_filename")
            if not device_filename and assignment:
                # Try to extract from assignment.device_path via DB
                if assignment.device_path:
                    from pathlib import PurePosixPath
                    device_filename = PurePosixPath(assignment.device_path).name

            async def _select_gallery_video() -> bool:
                return await tiktok.select_video_for_upload(
                    self._device,
                    filename=device_filename,
                    device_path=assignment.device_path if assignment else None,
                    thumbnail_path=thumbnail_path,
                )

            selected = await _select_gallery_video()

            if not selected:
                result = ScriptResult(False, "Failed to select a gallery video", self._step_num)
                return result

            await self._step("tap", "Select video from gallery")
            await self._capture_upload_debug(
                tiktok, "video_selected", "Selected target gallery video"
            )

            if await tiktok.detect_invalid_gallery_preview(self._device):
                await self._step(
                    "warn",
                    "Broken gallery preview detected; backing out to reselect",
                )
                await self._capture_upload_debug(
                    tiktok,
                    "preview_invalid",
                    "Detected broken preview before tapping Next",
                )
                if not await tiktok.recover_invalid_gallery_preview(self._device):
                    result = ScriptResult(
                        False,
                        "Broken gallery preview and failed to return to gallery",
                        self._step_num,
                    )
                    return result
                await self._capture_upload_debug(
                    tiktok,
                    "gallery_recovered",
                    "Returned to gallery after broken preview",
                )

                selected = await _select_gallery_video()
                if not selected:
                    result = ScriptResult(
                        False,
                        "Failed to reselect a gallery video after broken preview",
                        self._step_num,
                    )
                    return result

                await self._step("tap", "Reselect video from gallery")
                await self._capture_upload_debug(
                    tiktok,
                    "video_reselected",
                    "Reselected target video after broken preview recovery",
                )

                if await tiktok.detect_invalid_gallery_preview(self._device):
                    result = ScriptResult(
                        False,
                        "Gallery preview invalid after reselect",
                        self._step_num,
                    )
                    return result

            # [Script 5] Tap Next (Gallery/Preview -> Editor or Post)
            if not await tiktok.tap_next(self._device):
                result = ScriptResult(False, "Failed to tap Next after selecting video", self._step_num)
                return result
            await self._step("tap", "Next (Gallery -> Editor)")
            await self._capture_upload_debug(
                tiktok, "after_next_gallery", "Gallery selection to editor transition"
            )
            await self._wait(2, 4, "video processing")

            current_state = await tiktok.wait_for_upload_state(
                self._device, {"video_editor", "post_form"}, timeout=10.0
            )
            if not current_state:
                result = ScriptResult(False, "Did not reach editor or post form after gallery Next", self._step_num)
                return result

            # [Script 6] Tap Next (Edit -> Post) when editor is present.
            if current_state == "video_editor":
                if not await tiktok.tap_next(self._device):
                    result = ScriptResult(False, "Failed to tap Next on editor screen", self._step_num)
                    return result
                await self._step("tap", "Next (Edit -> Post)")
                await self._wait(2, 3, "opening post form")
                current_state = await tiktok.wait_for_upload_state(
                    self._device, {"post_form"}, timeout=10.0
                )
                if not current_state:
                    result = ScriptResult(False, "Post form did not appear after editor Next", self._step_num)
                    return result

            await self._capture_upload_debug(
                tiktok, "post_form", "Reached post form"
            )

            # [Script 7] Fill Metadata
            if not await tiktok.fill_post_metadata(self._device, use_title, use_desc):
                result = ScriptResult(False, "Failed to fill caption/title metadata", self._step_num)
                return result
            await self._step("type", "Caption & Hashtags")
            await self._capture_upload_debug(
                tiktok, "metadata_filled", "Caption/title/hashtags attempted"
            )

            await tiktok.dismiss_keyboard(self._device)
            await self._capture_upload_debug(
                tiktok, "post_ready", "Keyboard dismissed before Post"
            )

            # [Script 8] Tap Post
            if not await tiktok.tap_post(self._device):
                result = ScriptResult(False, "Failed to tap Post", self._step_num)
                return result
            await self._step("tap", "Post button")
            await self._capture_upload_debug(
                tiktok, "after_post", "Tapped Post; waiting for upload state"
            )

            # Guard: if we remain on post form immediately after tapping Post,
            # try one extra submit tap (some TikTok builds ignore first tap).
            await asyncio.sleep(2.0)
            post_submit_state = await tiktok.detect_post_publish_state(self._device)
            if post_submit_state in {"post_form", "unknown"}:
                await self._step(
                    "tap",
                    f"Post retry (state after submit: {post_submit_state})",
                )
                if not await tiktok.tap_post(self._device):
                    result = ScriptResult(False, "Post retry failed", self._step_num)
                    return result
                await self._capture_upload_debug(
                    tiktok,
                    "after_post_retry",
                    "Retried Post because post form remained visible",
                )

            # [Verify 9] Wait for reliable post completion instead of fixed sleep.
            post_completion_state = await tiktok.wait_for_post_completion(
                self._device, timeout=45.0, poll_interval=1.0
            )
            if not post_completion_state:
                result = ScriptResult(
                    False,
                    "No reliable post completion signal after tapping Post",
                    self._step_num,
                )
                return result
            await self._step("verify", f"Post completion signal: {post_completion_state}")
            await self._capture_upload_debug(
                tiktok,
                "upload_wait_complete",
                f"Post completion signal: {post_completion_state}",
            )

            try:
                await tiktok.dismiss_post_publish_obstacles(self._device)
                # Avoid hard failure if TikTok redirects unexpectedly after posting.
                await tiktok.ensure_on_feed(self._device)
            except Exception:
                pass

            # [Script 10] Update DB + capture post_locator
            if assignment:
                with Session(engine) as session:
                    from sqlmodel import select as sql_select
                    from app.models import DeviceAccount

                    a = session.get(VideoAssignment, assignment.id)
                    if a:
                        a.push_status = PushStatus.UPLOADED  # Legacy compat
                        a.upload_status = UploadStatus.UPLOADED
                        a.uploaded_at = datetime.now(timezone.utc)
                        a.last_error = None

                        # Capture post_locator fingerprint for metrics sync
                        try:
                            acct = session.exec(
                                sql_select(DeviceAccount).where(
                                    DeviceAccount.device_id == a.device_id,
                                    DeviceAccount.platform == a.platform,
                                )
                            ).first()
                            locator = tiktok.build_post_locator(
                                caption_text=f"{use_title}\n\n{use_desc}".strip(),
                                account_name=(acct.account_name if acct else None),
                                grid_position_hint=0,
                                upload_timestamp=datetime.now(timezone.utc).isoformat(),
                            )
                            a.post_locator = json.dumps(locator)
                            logger.info(
                                "  📍 post_locator captured: %s",
                                a.post_locator,
                            )
                        except Exception as loc_err:
                            logger.warning(
                                "  ⚠️ post_locator capture failed: %s",
                                loc_err,
                            )

                        session.commit()
                        await self._step("db", f"assignment {a.id} upload_status -> UPLOADED")

            result = ScriptResult(
                success=True,
                reason="Video successfully uploaded to TikTok",
                steps=self._step_num,
                step_log=self._step_log,
            )
            return result
        finally:
            if self._upload_debug and tiktok:
                final_label = "final_success" if result and result.success else "final_state"
                final_note = result.reason if result else "Upload flow exited without success result"
                try:
                    await self._capture_upload_debug(tiktok, final_label, final_note)
                except Exception as e:
                    logger.warning(f"  ⚠️ Failed to capture final upload snapshot: {e}")

            await self._stop_upload_screenrecord()

            if self._upload_debug:
                self._upload_debug["manifest"]["finished_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                if result:
                    self._upload_debug["manifest"]["result"] = {
                        "success": result.success,
                        "reason": result.reason,
                        "steps": result.steps,
                        "error": result.error,
                    }
                self._write_upload_debug_manifest()

    def _build_metrics_candidate_positions(
        self,
        locator: dict,
        grid_data: list[dict],
        *,
        max_candidates: int = 6,
    ) -> list[int]:
        """Build candidate grid positions for locator matching."""
        try:
            hint = int(locator.get("grid_position_hint", 0) or 0)
        except Exception:
            hint = 0

        visible_positions = []
        for idx, item in enumerate(grid_data):
            try:
                visible_positions.append(int(item.get("position", idx)))
            except Exception:
                visible_positions.append(idx)

        candidates: list[int] = []
        for offset in (0, 1, -1, 2, -2, 3, -3):
            pos = hint + offset
            if pos >= 0:
                candidates.append(pos)
        candidates.extend(sorted(set(visible_positions)))

        fallback_limit = max(max_candidates, hint + 3, (max(visible_positions) + 1) if visible_positions else 0)
        candidates.extend(range(fallback_limit))

        deduped: list[int] = []
        seen = set()
        for pos in candidates:
            if pos < 0 or pos in seen:
                continue
            seen.add(pos)
            deduped.append(pos)
            if len(deduped) >= max_candidates:
                break
        return deduped or [0]

    # === TIKTOK METRICS SYNC ===

    async def _tiktok_metrics_sync(
        self,
        assignment_id: int | None = None,
        **_,
    ) -> ScriptResult:
        """Sync performance metrics for a TikTok assignment.

        Flow:
        1. Open TikTok → ensure on feed
        2. Navigate to own profile
        3. Open Videos tab → read grid metrics
        4. Open target post from locator/grid hint → read full metrics
        5. Save metrics to DB (latest state + snapshot)
        """
        if not assignment_id:
            return ScriptResult(
                success=False,
                reason="Missing assignment_id",
                steps=self._step_num,
                error="assignment_id is required",
            )

        # --- DB lookup ---
        from sqlmodel import Session
        from app.database import engine
        from app.models import (
            VideoAssignment, Video, MetricsStatus, UploadStatus,
        )

        locator: dict = {}
        with Session(engine) as session:
            assignment = session.get(VideoAssignment, assignment_id)
            if not assignment:
                return ScriptResult(
                    False, f"Assignment {assignment_id} not found",
                    self._step_num,
                )
            if assignment.upload_status != UploadStatus.UPLOADED:
                return ScriptResult(
                    False,
                    f"Assignment {assignment_id} not uploaded "
                    f"(status={assignment.upload_status})",
                    self._step_num,
                )
            if assignment.post_locator:
                try:
                    locator = json.loads(assignment.post_locator)
                except Exception:
                    locator = {}

        tiktok = self._get_tiktok_controller()

        # Artifact directory for debug snapshots
        session_name = (
            f"metrics_{assignment_id}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        artifact_dir = str(
            Path(settings.screenshots_dir)
            / "tiktok_metrics_debug"
            / session_name
        )

        sync_error: str | None = None
        metrics_data: dict = {}
        grid_data: list[dict] = []
        locator_signals: dict = {}
        locator_match_result: dict | None = None
        selected_position: int | None = None
        candidate_positions: list[int] = []
        save_result_dict: dict | None = None
        save_error: str | None = None
        final_success = False
        final_reason = ""
        final_error: str | None = None

        try:
            # [Step 1] Open TikTok & ensure on feed
            await self._open_app("tiktok")
            await self._wait(3, 5, "app loading")

            if not await tiktok.ensure_on_feed(self._device):
                sync_error = "Could not get to TikTok feed"
                await tiktok.capture_debug_snapshot(
                    self._device, artifact_dir, "feed_fail", sync_error
                )
            else:
                await self._step("ensure_feed", "on For You feed")

            if sync_error is None:
                # [Step 2] Navigate to own profile
                if not await tiktok.ensure_on_profile(self._device):
                    sync_error = "Could not navigate to profile"
                    await tiktok.capture_debug_snapshot(
                        self._device, artifact_dir, "profile_fail", sync_error
                    )
                else:
                    await self._step("navigate", "on own profile")

            if sync_error is None:
                # [Step 3] Navigate to Videos tab
                if not await tiktok.navigate_to_videos_tab(self._device):
                    sync_error = "Could not navigate to Videos tab"
                    await tiktok.capture_debug_snapshot(
                        self._device, artifact_dir, "videos_tab_fail", sync_error
                    )
                else:
                    await self._step("navigate", "on Videos tab")

            target_position = 0
            try:
                target_position = int(locator.get("grid_position_hint", 0) or 0)
            except Exception:
                target_position = 0
            has_strong_locator = bool(
                locator.get("locator_version")
                or locator.get("caption_tokens")
                or locator.get("caption_preview")
            )

            if sync_error is None:
                # [Step 4] Read grid metrics (quick view counts)
                grid_data = await tiktok.read_profile_grid_metrics(self._device)
                await self._step(
                    "read_grid",
                    f"grid: {len(grid_data)} items with view counts",
                )
                await tiktok.capture_debug_snapshot(
                    self._device, artifact_dir, "grid_metrics",
                    f"Grid items: {len(grid_data)}",
                )

                if not grid_data:
                    logger.info("  ℹ️ No grid view counts found, trying locator/grid hint fallback")

            if sync_error is None:
                # [Step 5] Match target video from profile grid
                candidate_positions = self._build_metrics_candidate_positions(
                    locator,
                    grid_data,
                )
                await self._step(
                    "match_candidates",
                    f"candidate positions={candidate_positions}",
                )

                if has_strong_locator:
                    for candidate_position in candidate_positions:
                        await self._wait(0.5, 1.0, "before opening candidate post")
                        if not await tiktok.open_profile_video_at_position(
                            self._device, position=candidate_position
                        ):
                            logger.info(
                                "  ℹ️ Could not open candidate at position %s",
                                candidate_position,
                            )
                            continue

                        await self._step(
                            "open_post",
                            f"opened candidate at grid position {candidate_position}",
                        )
                        await self._wait(0.8, 1.4, "candidate detail loading")
                        locator_signals = await tiktok.read_post_detail_locator_signals(
                            self._device
                        )
                        locator_match_result = tiktok.match_post_locator(
                            locator,
                            locator_signals,
                        )
                        await self._step(
                            "match_post",
                            f"position={candidate_position} "
                            f"matched={locator_match_result.get('matched')} "
                            f"score={locator_match_result.get('score')} "
                            f"overlap={locator_match_result.get('token_overlap')}",
                        )
                        if locator_match_result.get("matched"):
                            selected_position = candidate_position
                            target_position = candidate_position
                            await tiktok.capture_debug_snapshot(
                                self._device,
                                artifact_dir,
                                f"locator_match_{candidate_position}",
                                json.dumps(locator_match_result, default=str),
                            )
                            break

                        await tiktok.capture_debug_snapshot(
                            self._device,
                            artifact_dir,
                            f"locator_miss_{candidate_position}",
                            json.dumps(
                                {
                                    "match_result": locator_match_result,
                                    "signals": locator_signals,
                                },
                                default=str,
                            ),
                        )
                        if not await tiktok.navigate_back_from_post_detail(self._device):
                            sync_error = (
                                "Could not return to profile after locator mismatch"
                            )
                            await tiktok.capture_debug_snapshot(
                                self._device,
                                artifact_dir,
                                "locator_back_fail",
                                sync_error,
                            )
                            break

                    if sync_error is None and selected_position is None:
                        sync_error = (
                            "Could not match uploaded post from locator "
                            f"across positions {candidate_positions}"
                        )
                        await tiktok.capture_debug_snapshot(
                            self._device,
                            artifact_dir,
                            "locator_match_fail",
                            sync_error,
                        )
                else:
                    await self._wait(0.5, 1.0, "before opening post")
                    if not await tiktok.open_profile_video_at_position(
                        self._device, position=target_position
                    ):
                        sync_error = f"Could not open post at position {target_position}"
                        await tiktok.capture_debug_snapshot(
                            self._device, artifact_dir, "open_post_fail", sync_error
                        )
                    else:
                        selected_position = target_position
                        await self._step(
                            "open_post",
                            f"opened post at grid position {target_position}",
                        )

            if sync_error is None:
                # [Step 6] Read full metrics from post detail
                await self._wait(1.0, 2.0, "post detail loading")
                metrics_data = await tiktok.read_post_detail_metrics(self._device)
                await self._step(
                    "read_metrics",
                    f"views={metrics_data.get('views')} "
                    f"likes={metrics_data.get('likes')} "
                    f"comments={metrics_data.get('comments')} "
                    f"shares={metrics_data.get('shares')}",
                )
                await tiktok.capture_debug_snapshot(
                    self._device, artifact_dir, "post_detail_metrics",
                    json.dumps(metrics_data, default=str),
                )

                if metrics_data.get("views") is None and grid_data:
                    fallback_position = min(
                        max(target_position, 0),
                        len(grid_data) - 1,
                    )
                    metrics_data["views"] = grid_data[fallback_position].get("views_int")
                    logger.info(
                        "  📊 Using grid views fallback: %s",
                        metrics_data["views"],
                    )

                # [Step 7] Navigate back
                if not await tiktok.navigate_back_from_post_detail(self._device):
                    sync_error = "Could not return to profile after reading post detail"
                    await tiktok.capture_debug_snapshot(
                        self._device, artifact_dir, "back_to_profile_fail", sync_error
                    )
                else:
                    await self._step("navigate", "back to profile grid")

        except Exception as e:
            sync_error = f"Metrics sync exception: {e}"
            logger.exception("Metrics sync failed: %s", e)
            try:
                await tiktok.capture_debug_snapshot(
                    self._device, artifact_dir, "exception", sync_error
                )
            except Exception:
                pass
            final_reason = sync_error
            final_error = str(e)
        else:
            final_success = sync_error is None and any(
                metrics_data.get(key) is not None
                for key in ("views", "likes", "comments", "shares")
            )
            final_reason = (
                f"Metrics synced: views={metrics_data.get('views')} "
                f"likes={metrics_data.get('likes')} "
                f"comments={metrics_data.get('comments')} "
                f"shares={metrics_data.get('shares')}"
                if final_success
                else (sync_error or "No metrics could be read")
            )
            final_error = sync_error

        # [Step 8] Save to DB
        try:
            from app.services.video_service import video_service

            with Session(engine) as session:
                raw_payload_str = json.dumps(
                    {
                        "post_detail": metrics_data,
                        "grid": grid_data[:6],
                        "locator": locator,
                        "locator_signals": locator_signals,
                        "locator_match": locator_match_result,
                        "selected_position": selected_position,
                        "candidate_positions": candidate_positions,
                    },
                    default=str,
                )
                assignment = session.get(VideoAssignment, assignment_id)
                if assignment and locator:
                    updated_locator = dict(locator)
                    if selected_position is not None:
                        updated_locator["grid_position_hint"] = selected_position
                    assignment.post_locator = json.dumps(updated_locator)
                    session.add(assignment)
                save_result_dict, save_error = video_service.save_automated_metrics(
                    session,
                    assignment_id,
                    views=metrics_data.get("views"),
                    likes=metrics_data.get("likes"),
                    comments=metrics_data.get("comments"),
                    shares=metrics_data.get("shares"),
                    source="post_detail",
                    raw_payload=raw_payload_str,
                    artifact_dir=artifact_dir,
                    error=sync_error,
                )
                if save_error:
                    return ScriptResult(
                        False, f"DB save failed: {save_error}",
                        self._step_num,
                    )

            await self._step("db", "metrics saved to DB")
        except Exception as e:
            return ScriptResult(
                False, f"DB save exception: {e}",
                self._step_num, error=str(e),
            )

        return ScriptResult(
            success=final_success,
            reason=final_reason,
            steps=self._step_num,
            step_log=self._step_log,
            error=final_error,
        )

    # === OTHER PLATFORM SCRIPTS ===

    async def _youtube_watch(
        self,
        count: int = 3,
        view_time_min: float = 10.0,
        view_time_max: float = 30.0,
        **_,
    ) -> ScriptResult:
        """Watch YouTube: open → watch shorts/videos → swipe."""
        await self._open_app("youtube")
        await self._wait(3, 6, "app loading")

        # Tap on first video or Shorts tab
        w, h = await self._adb.get_screen_size(self._device)
        await self._adb_cmd(
            "shell", "input", "tap",
            str(w // 2), str(int(h * 0.4))
        )
        await self._step("tap", "first video/shorts")
        await self._wait(2, 4, "video loading")

        for i in range(count):
            await self._wait(view_time_min, view_time_max, f"watching {i+1}/{count}")
            await self._swipe_up()

        return ScriptResult(
            success=True,
            reason=f"Watched {count} YouTube videos",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _facebook_scroll(
        self,
        count: int = 5,
        view_time_min: float = 3.0,
        view_time_max: float = 10.0,
        like_chance: float = 0.2,
        **_,
    ) -> ScriptResult:
        """Scroll Facebook feed."""
        await self._open_app("facebook")
        await self._wait(4, 7, "app loading")

        for i in range(count):
            await self._wait(view_time_min, view_time_max, f"reading post {i+1}/{count}")
            # Randomly like a post
            if random.random() < like_chance:
                # Facebook like button is usually on bottom-left area of post
                w, h = await self._adb.get_screen_size(self._device)
                await self._adb_cmd(
                    "shell", "input", "tap",
                    str(int(w * 0.15)), str(int(h * 0.55))
                )
                await self._step("tap", "liked post")
                await asyncio.sleep(random.uniform(0.5, 1.5))
            await self._scroll_down()

        return ScriptResult(
            success=True,
            reason=f"Scrolled {count} Facebook posts",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _instagram_scroll(
        self,
        count: int = 5,
        view_time_min: float = 3.0,
        view_time_max: float = 8.0,
        **_,
    ) -> ScriptResult:
        """Scroll Instagram feed."""
        return await self._generic_scroll(
            app_name="instagram",
            count=count,
            view_time_min=view_time_min,
            view_time_max=view_time_max,
        )

    async def _generic_scroll(
        self,
        app_name: str = "tiktok",
        count: int = 5,
        view_time_min: float = 3.0,
        view_time_max: float = 8.0,
        **_,
    ) -> ScriptResult:
        """Generic app scroll: open → scroll N times → home."""
        await self._open_app(app_name)
        await self._wait(3, 6, "app loading")

        for i in range(count):
            await self._wait(view_time_min, view_time_max, f"viewing {i+1}/{count}")
            await self._scroll_down()

        return ScriptResult(
            success=True,
            reason=f"Scrolled {count} items in {app_name}",
            steps=self._step_num,
            step_log=self._step_log,
        )


# Singleton
script_runner = ScriptRunner()
