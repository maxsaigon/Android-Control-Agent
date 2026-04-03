from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tiktok_controller import TikTokController


class TikTokUploadPreviewGuardrailsTest(unittest.IsolatedAsyncioTestCase):
    def _controller(self) -> TikTokController:
        return TikTokController(adb_agent=Mock())

    def _broken_preview_image(self) -> Image.Image:
        image = Image.new("RGB", (1080, 2280), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((430, 840, 650, 1060), fill=(110, 110, 110))
        draw.rectangle((500, 900, 580, 980), fill=(70, 70, 70))
        return image

    def _healthy_preview_image(self) -> Image.Image:
        image = Image.new("RGB", (1080, 2280), (42, 128, 64))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1080, 1600), fill=(64, 170, 92))
        draw.ellipse((320, 500, 760, 1200), fill=(220, 180, 72))
        return image

    async def test_detect_invalid_gallery_preview_matches_broken_preview(self):
        controller = self._controller()
        controller.detect_upload_state = AsyncMock(return_value="gallery_picker")
        controller._dump_all_ui_nodes = AsyncMock(
            return_value=[
                {"text": "Select", "desc": "", "pkg": "", "cls": "", "clickable": False, "bounds": None},
                {"text": "Next", "desc": "", "pkg": "", "cls": "", "clickable": True, "bounds": None},
                {"text": "AutoCut", "desc": "", "pkg": "", "cls": "", "clickable": False, "bounds": None},
            ]
        )
        controller._capture_analysis_image = AsyncMock(
            return_value=self._broken_preview_image()
        )

        matched = await controller.detect_invalid_gallery_preview("cloud:1")

        self.assertTrue(matched)

    async def test_detect_invalid_gallery_preview_ignores_healthy_preview(self):
        controller = self._controller()
        controller.detect_upload_state = AsyncMock(return_value="gallery_picker")
        controller._dump_all_ui_nodes = AsyncMock(
            return_value=[
                {"text": "Select", "desc": "", "pkg": "", "cls": "", "clickable": False, "bounds": None},
                {"text": "Next", "desc": "", "pkg": "", "cls": "", "clickable": True, "bounds": None},
                {"text": "AutoCut", "desc": "", "pkg": "", "cls": "", "clickable": False, "bounds": None},
            ]
        )
        controller._capture_analysis_image = AsyncMock(
            return_value=self._healthy_preview_image()
        )

        matched = await controller.detect_invalid_gallery_preview("cloud:1")

        self.assertFalse(matched)

    async def test_detect_invalid_gallery_preview_requires_preview_controls(self):
        controller = self._controller()
        controller.detect_upload_state = AsyncMock(return_value="gallery_picker")
        controller._dump_all_ui_nodes = AsyncMock(
            return_value=[
                {"text": "Recents", "desc": "", "pkg": "", "cls": "", "clickable": False, "bounds": None},
                {"text": "Select multiple", "desc": "", "pkg": "", "cls": "", "clickable": True, "bounds": None},
                {"text": "Next", "desc": "", "pkg": "", "cls": "", "clickable": True, "bounds": None},
            ]
        )
        controller._capture_analysis_image = AsyncMock(
            return_value=self._broken_preview_image()
        )

        matched = await controller.detect_invalid_gallery_preview("cloud:1")

        self.assertFalse(matched)
        controller._capture_analysis_image.assert_not_awaited()

    async def test_select_video_for_upload_falls_back_to_visual_match_after_name_fail(self):
        controller = self._controller()
        controller.get_media_store_video = AsyncMock(
            return_value={"_display_name": "clip.mp4", "relative_path": "DCIM/AndroidControl/"}
        )
        controller._load_reference_thumbnail = Mock(return_value=object())
        controller.select_video_by_name = AsyncMock(return_value=False)
        controller.ensure_gallery_video_context = AsyncMock()
        controller._select_gallery_video_by_visual_match = AsyncMock(return_value=True)

        ok = await controller.select_video_for_upload(
            "cloud:1",
            filename="clip.mp4",
            device_path="/sdcard/DCIM/AndroidControl/clip.mp4",
            thumbnail_path="/tmp/thumb.jpg",
        )

        self.assertTrue(ok)
        controller.select_video_by_name.assert_awaited_once_with(
            "cloud:1",
            "clip.mp4",
            allow_scroll=False,
        )
        controller.ensure_gallery_video_context.assert_awaited_once()
        controller._select_gallery_video_by_visual_match.assert_awaited_once()

    async def test_select_video_for_upload_rechecks_preview_after_name_match(self):
        controller = self._controller()
        reference = object()
        controller.get_media_store_video = AsyncMock(
            return_value={"_display_name": "clip.mp4", "relative_path": "DCIM/AndroidControl/"}
        )
        controller._load_reference_thumbnail = Mock(return_value=reference)
        controller.select_video_by_name = AsyncMock(return_value=True)
        controller.verify_selected_gallery_preview = AsyncMock(
            side_effect=[(False, 0.11), (True, 0.73)]
        )
        controller.return_to_gallery_grid = AsyncMock(return_value=True)
        controller.ensure_gallery_video_context = AsyncMock()
        controller._select_gallery_video_by_visual_match = AsyncMock(return_value=True)

        ok = await controller.select_video_for_upload(
            "cloud:1",
            filename="clip.mp4",
            device_path="/sdcard/DCIM/AndroidControl/clip.mp4",
            thumbnail_path="/tmp/thumb.jpg",
        )

        self.assertTrue(ok)
        controller.return_to_gallery_grid.assert_awaited_once_with("cloud:1")
        controller._select_gallery_video_by_visual_match.assert_awaited_once()
