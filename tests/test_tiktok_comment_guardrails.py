from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.script_runner import ScriptRunner


class TikTokCommentGuardrailsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runner = ScriptRunner()
        self.runner._device = "cloud:99"
        self.runner._step = AsyncMock()
        self.runner._wait = AsyncMock()
        self.runner._comment_checkpoint = AsyncMock()

    async def test_does_not_send_when_send_button_inactive(self):
        tiktok = AsyncMock()
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

    async def test_send_comment_forces_no_blind_fallback(self):
        tiktok = AsyncMock()
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


if __name__ == "__main__":
    unittest.main()
