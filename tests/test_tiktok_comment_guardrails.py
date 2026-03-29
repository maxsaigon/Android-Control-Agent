from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.script_runner import ScriptRunner
from app.services.tiktok_controller import TikTokController, UIElement


class TikTokCommentGuardrailsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runner = ScriptRunner()
        self.runner._device = "cloud:99"
        self.runner._step_num = 0
        self.runner._step_log = []
        self.runner._step = AsyncMock()
        self.runner._wait = AsyncMock()
        self.runner._comment_checkpoint = AsyncMock()

    async def test_does_not_send_when_send_button_inactive(self):
        tiktok = AsyncMock()
        tiktok.has_helper_service_issue = Mock(return_value=False)
        tiktok.tap_comment_input = AsyncMock()
        tiktok.type_text = AsyncMock()
        tiktok._verify_text_entered = AsyncMock(return_value=True)
        tiktok.ensure_comment_send_ready = AsyncMock(return_value=False)
        tiktok.send_comment = AsyncMock(return_value=True)
        tiktok.verify_comment_posted = AsyncMock(return_value=True)

        posted = await self.runner._attempt_comment(
            tiktok=tiktok,
            comment_text="hello world",
            comments_done=0,
            count=1,
            panel_already_open=True,
        )

        self.assertFalse(posted)
        tiktok.send_comment.assert_not_awaited()
        tiktok.verify_comment_posted.assert_not_awaited()

    async def test_retry_success_does_not_count_as_failed_video(self):
        tiktok = AsyncMock()
        tiktok.ensure_on_feed = AsyncMock(return_value=True)
        tiktok.get_video_info = AsyncMock(return_value={"author": "tester", "description": "desc"})
        tiktok.tap_comment_icon = AsyncMock(return_value=True)
        tiktok.read_comments = AsyncMock(return_value=[{"text": "existing"}])
        tiktok.has_helper_service_issue = Mock(return_value=False)
        tiktok.close_panel = AsyncMock(return_value=True)
        tiktok.capture_verification_screenshot = AsyncMock()

        self.runner._open_app = AsyncMock()
        self.runner._swipe_up = AsyncMock()
        self.runner._get_tiktok_controller = Mock(return_value=tiktok)
        self.runner._attempt_comment = AsyncMock(side_effect=[False, True])

        random_values = iter([0.1, 0.9])
        with unittest.mock.patch("app.services.script_runner.random.random", side_effect=lambda: next(random_values)):
            result = await self.runner._tiktok_comment(
                count=1,
                view_time_min=0,
                view_time_max=0,
                like_after_comment=0.0,
                use_ai=False,
            )

        self.assertTrue(result.success)
        self.assertEqual(result.verified_actions, 1)
        self.assertEqual(result.failed_actions, 0)

    async def test_send_comment_forces_no_blind_fallback(self):
        tiktok = AsyncMock()
        tiktok.has_helper_service_issue = Mock(return_value=False)
        tiktok.tap_comment_input = AsyncMock()
        tiktok.type_text = AsyncMock()
        tiktok._verify_text_entered = AsyncMock(return_value=True)
        tiktok.ensure_comment_send_ready = AsyncMock(return_value=True)
        tiktok.send_comment = AsyncMock(return_value=True)
        tiktok.verify_comment_posted = AsyncMock(return_value=True)

        posted = await self.runner._attempt_comment(
            tiktok=tiktok,
            comment_text="hello world",
            comments_done=0,
            count=1,
            panel_already_open=True,
        )

        self.assertTrue(posted)
        tiktok.send_comment.assert_awaited_once_with(
            "cloud:99",
            allow_blind_fallback=False,
        )

    async def test_retry_does_not_send_when_text_still_missing_after_retype(self):
        tiktok = AsyncMock()
        tiktok.tap_comment_input = AsyncMock()
        tiktok.type_text = AsyncMock()
        tiktok.has_helper_service_issue = Mock(return_value=False)
        tiktok._verify_text_entered = AsyncMock(side_effect=[False, False])
        tiktok.capture_verification_screenshot = AsyncMock()
        tiktok.ensure_comment_send_ready = AsyncMock(return_value=True)
        tiktok.send_comment = AsyncMock(return_value=True)
        tiktok.verify_comment_posted = AsyncMock(return_value=True)

        posted = await self.runner._attempt_comment(
            tiktok=tiktok,
            comment_text="lol",
            comments_done=0,
            count=1,
            is_retry=True,
            panel_already_open=True,
        )

        self.assertFalse(posted)
        tiktok.send_comment.assert_not_awaited()
        tiktok.verify_comment_posted.assert_not_awaited()

    async def test_helper_issue_after_typing_does_not_abort_when_text_is_verified(self):
        tiktok = AsyncMock()
        tiktok.tap_comment_input = AsyncMock()
        tiktok.type_text = AsyncMock()
        tiktok.capture_verification_screenshot = AsyncMock()
        issue_states = iter([False, True])
        tiktok.has_helper_service_issue = Mock(side_effect=lambda *_: next(issue_states))
        tiktok._verify_text_entered = AsyncMock(return_value=True)
        tiktok.ensure_comment_send_ready = AsyncMock(return_value=True)
        tiktok.send_comment = AsyncMock(return_value=True)
        tiktok.verify_comment_posted = AsyncMock(return_value=True)

        posted = await self.runner._attempt_comment(
            tiktok=tiktok,
            comment_text="hello world",
            comments_done=0,
            count=1,
            panel_already_open=True,
        )

        self.assertTrue(posted)
        tiktok.send_comment.assert_awaited_once()
        tiktok.verify_comment_posted.assert_awaited_once()

class TikTokCommentVerificationTest(unittest.IsolatedAsyncioTestCase):
    def _controller(self) -> TikTokController:
        return TikTokController(adb_agent=Mock())

    def _el(
        self,
        *,
        text: str = "",
        cls: str = "android.widget.TextView",
        bounds: tuple[int, int, int, int] = (100, 400, 900, 520),
        desc: str = "",
    ) -> UIElement:
        return UIElement(
            resource_id="",
            content_desc=desc,
            text=text,
            cls=cls,
            bounds=bounds,
            clickable=False,
        )

    async def test_verify_comment_requires_visible_new_comment(self):
        controller = self._controller()
        controller.dump_ui = AsyncMock(return_value=[
            self._el(
                text="Add comment...",
                cls="android.widget.EditText",
                bounds=(60, 2040, 860, 2140),
            ),
            self._el(text="old comment", bounds=(120, 800, 900, 920)),
        ])

        ok = await controller.verify_comment_posted(
            "cloud:99",
            "brand new thought",
            timeout=0,
            attempts=1,
        )

        self.assertFalse(ok)

    async def test_verify_comment_rejects_baseline_match(self):
        controller = self._controller()
        controller.dump_ui = AsyncMock(return_value=[
            self._el(
                text="Add comment...",
                cls="android.widget.EditText",
                bounds=(60, 2040, 860, 2140),
            ),
            self._el(text="love this", bounds=(120, 800, 900, 920)),
        ])

        ok = await controller.verify_comment_posted(
            "cloud:99",
            "love this",
            timeout=0,
            baseline_comments=[{"text": "love this"}],
            attempts=1,
        )

        self.assertFalse(ok)

    async def test_verify_comment_accepts_new_visible_match(self):
        controller = self._controller()
        controller.dump_ui = AsyncMock(return_value=[
            self._el(
                text="Add comment...",
                cls="android.widget.EditText",
                bounds=(60, 2040, 860, 2140),
            ),
            self._el(text="nhac nen chill ma edit dinh the", bounds=(120, 800, 980, 940)),
        ])

        ok = await controller.verify_comment_posted(
            "cloud:99",
            "nhạc nền chill mà edit đỉnh thế",
            timeout=0,
            baseline_comments=[{"text": "comment khac"}],
            attempts=1,
        )

        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
