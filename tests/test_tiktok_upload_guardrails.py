from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import unittest.mock

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
            return_value={
                "_display_name": "clip.mp4",
                "relative_path": "DCIM/AndroidControl/",
                "duration": "60767",
            }
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
        controller._select_gallery_video_by_visual_match.assert_awaited_once_with(
            "cloud:1",
            reference_image=unittest.mock.ANY,
            expected_duration_seconds=61,
        )

    async def test_select_video_for_upload_rechecks_preview_after_name_match(self):
        controller = self._controller()
        reference = object()
        controller.get_media_store_video = AsyncMock(
            return_value={
                "_display_name": "clip.mp4",
                "relative_path": "DCIM/AndroidControl/",
                "duration": "60767",
            }
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
        controller._select_gallery_video_by_visual_match.assert_awaited_once_with(
            "cloud:1",
            reference_image=reference,
            expected_duration_seconds=61,
        )

    def test_rank_gallery_candidates_prefers_duration_match(self):
        controller = self._controller()
        candidates = [
            {
                "bounds": (722, 393, 1074, 749),
                "center": (898, 571),
                "duration": "00:51",
                "tile_similarity": 0.750,
            },
            {
                "bounds": (6, 393, 358, 749),
                "center": (182, 571),
                "duration": "01:01",
                "tile_similarity": 0.658,
            },
            {
                "bounds": (364, 393, 716, 749),
                "center": (540, 571),
                "duration": "01:01",
                "tile_similarity": 0.614,
            },
        ]

        ranked = controller._rank_gallery_video_candidates(
            candidates,
            expected_duration_seconds=61,
        )

        self.assertEqual(ranked[0]["duration"], "01:01")
        self.assertEqual(ranked[0]["duration_delta"], 0)
        self.assertTrue(ranked[-1]["duration_blocked"])
        self.assertEqual(ranked[-1]["duration"], "00:51")

    async def test_dump_all_ui_nodes_falls_back_to_accessibility(self):
        controller = self._controller()
        controller.dump_ui_xml = AsyncMock(return_value="")
        fake_nodes = [
            SimpleNamespace(
                text="Home",
                content_desc="",
                package="com.ss.android.ugc.trill",
                class_name="android.widget.TextView",
                clickable=True,
                bounds=(0, 0, 100, 100),
            ),
            SimpleNamespace(
                text="Add to Home screen",
                content_desc="",
                package="jp.co.sharp.android.launcher3",
                class_name="android.widget.TextView",
                clickable=False,
                bounds=(0, 0, 100, 100),
            ),
        ]

        with unittest.mock.patch("app.services.backend_manager.backend_manager") as backend_manager:
            backend_manager.accessibility.ping = AsyncMock(return_value=True)
            backend_manager.accessibility.get_ui_tree = AsyncMock(return_value=fake_nodes)

            nodes = await controller._dump_all_ui_nodes("cloud:1")

        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["text"], "Home")
        self.assertEqual(nodes[1]["pkg"], "jp.co.sharp.android.launcher3")

    async def test_dump_ui_falls_back_to_accessibility_tree(self):
        controller = self._controller()
        controller._adb._run_adb = AsyncMock(side_effect=[(0, "", ""), (0, "", "")])
        fake_nodes = [
            SimpleNamespace(
                resource_id="id/home",
                content_desc="Home",
                text="",
                class_name="android.widget.TextView",
                bounds=(0, 0, 100, 100),
                clickable=True,
                package="com.ss.android.ugc.trill",
            ),
            SimpleNamespace(
                resource_id="id/other",
                content_desc="Other",
                text="",
                class_name="android.widget.TextView",
                bounds=(0, 0, 100, 100),
                clickable=True,
                package="com.example.other",
            ),
        ]

        with unittest.mock.patch("app.services.backend_manager.backend_manager") as backend_manager:
            backend_manager.accessibility.ping = AsyncMock(return_value=True)
            backend_manager.accessibility.get_ui_tree = AsyncMock(return_value=fake_nodes)

            elements = await controller.dump_ui("cloud:1")

        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0].content_desc, "Home")
