from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tiktok_controller import TikTokController, UIElement


class TikTokMetricsPrimitivesTest(unittest.IsolatedAsyncioTestCase):
    def _controller(self) -> TikTokController:
        return TikTokController(adb_agent=Mock())

    def _el(
        self,
        *,
        text: str = "",
        desc: str = "",
        cls: str = "android.widget.TextView",
        bounds: tuple[int, int, int, int] = (0, 0, 100, 100),
        clickable: bool = False,
    ) -> UIElement:
        return UIElement(
            resource_id="",
            content_desc=desc,
            text=text,
            cls=cls,
            bounds=bounds,
            clickable=clickable,
        )

    def test_parse_metric_text_cases(self):
        controller = self._controller()
        cases = {
            "12.4K": 12400,
            "3.5M": 3500000,
            "1.2B": 1200000000,
            "123": 123,
            "0": 0,
            "1,234": 1234,
            "  7.2K  ": 7200,
            "": None,
            "abc": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(controller._parse_metric_text(raw), expected)

    def test_detect_profile_screen_requires_multiple_signals(self):
        controller = self._controller()
        elements = [
            self._el(text="Following", bounds=(100, 220, 300, 260)),
            self._el(text="Followers", bounds=(320, 220, 520, 260)),
            self._el(text="Videos", bounds=(90, 520, 210, 560)),
        ]
        self.assertTrue(controller.detect_profile_screen(elements))

    def test_detect_profile_screen_rejects_feed_controls(self):
        controller = self._controller()
        elements = [
            self._el(text="Following", bounds=(100, 220, 300, 260)),
            self._el(desc="Like video. 120 likes", bounds=(900, 1100, 1050, 1250)),
            self._el(desc="Share video. 3 shares", bounds=(900, 1600, 1050, 1750)),
        ]
        self.assertFalse(controller.detect_profile_screen(elements))

    def test_find_grid_items_ignores_profile_header_wrappers(self):
        controller = self._controller()
        elements = [
            self._el(text="Following", bounds=(100, 220, 300, 260)),
            self._el(text="Followers", bounds=(320, 220, 520, 260)),
            self._el(text="Videos", bounds=(90, 520, 210, 560)),
            self._el(
                cls="android.widget.FrameLayout",
                bounds=(0, 120, 1080, 260),
                clickable=False,
            ),
            self._el(
                cls="android.widget.FrameLayout",
                bounds=(0, 280, 1080, 420),
                clickable=False,
            ),
            self._el(
                cls="android.widget.FrameLayout",
                bounds=(0, 720, 360, 1080),
                clickable=True,
            ),
        ]

        items = controller._find_grid_items(elements)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].bounds, (0, 720, 360, 1080))

    def test_extract_grid_view_counts_ignores_header_stats(self):
        controller = self._controller()
        elements = [
            self._el(text="Following", bounds=(100, 220, 300, 260)),
            self._el(text="Followers", bounds=(320, 220, 520, 260)),
            self._el(text="Videos", bounds=(90, 520, 210, 560)),
            self._el(text="123", bounds=(120, 220, 200, 260)),
            self._el(text="456", bounds=(320, 220, 400, 260)),
            self._el(
                cls="android.widget.FrameLayout",
                bounds=(0, 720, 360, 1080),
                clickable=True,
            ),
            self._el(
                cls="android.widget.FrameLayout",
                bounds=(360, 720, 720, 1080),
                clickable=True,
            ),
            self._el(text="12.4K", bounds=(40, 1000, 120, 1040)),
            self._el(text="3.5M", bounds=(400, 1000, 480, 1040)),
        ]

        metrics = controller._extract_grid_view_counts(elements)

        self.assertEqual(len(metrics), 2)
        self.assertEqual([item["views_int"] for item in metrics], [12400, 3500000])

    async def test_navigate_to_videos_tab_verifies_after_fallback_tap(self):
        controller = self._controller()
        controller._get_screen_size = AsyncMock(return_value=(1080, 2280))
        controller._realistic_tap = AsyncMock()
        controller.dump_ui = AsyncMock(
            side_effect=[
                [self._el(text="Videos", bounds=(100, 500, 220, 560))],
                [self._el(text="Videos", bounds=(100, 500, 220, 560))],
            ]
        )

        ok = await controller.navigate_to_videos_tab("cloud:1")

        self.assertFalse(ok)
        controller._realistic_tap.assert_awaited_once()

    async def test_navigate_to_videos_tab_succeeds_when_grid_appears(self):
        controller = self._controller()
        controller._realistic_tap = AsyncMock()
        controller._get_screen_size = AsyncMock(return_value=(1080, 2280))
        controller.dump_ui = AsyncMock(
            side_effect=[
                [
                    self._el(text="Following", bounds=(100, 220, 300, 260)),
                    self._el(text="Followers", bounds=(320, 220, 520, 260)),
                    self._el(text="Videos", bounds=(90, 520, 210, 560)),
                ],
                [
                    self._el(text="Following", bounds=(100, 220, 300, 260)),
                    self._el(text="Followers", bounds=(320, 220, 520, 260)),
                    self._el(text="Videos", bounds=(90, 520, 210, 560)),
                    self._el(
                        cls="android.widget.FrameLayout",
                        bounds=(0, 720, 360, 1080),
                        clickable=True,
                    ),
                ],
            ]
        )

        ok = await controller.navigate_to_videos_tab("cloud:1")

        self.assertTrue(ok)

    def test_detect_post_detail_screen_requires_multiple_engagement_signals(self):
        controller = self._controller()
        self.assertTrue(
            controller._detect_post_detail_screen(
                [
                    self._el(desc="Like video. 100 likes"),
                    self._el(desc="Read or add comments. 3"),
                    self._el(desc="Share video. 1 shares"),
                ]
            )
        )
        self.assertFalse(
            controller._detect_post_detail_screen(
                [self._el(desc="Like video. 100 likes")]
            )
        )

    def test_build_post_locator_captures_tokens_and_version(self):
        controller = self._controller()

        locator = controller.build_post_locator(
            caption_text="Mix đồ đi biển cực cháy #VungTau #Outfit",
            account_name="@demo",
            grid_position_hint=1,
            upload_timestamp="2026-04-06T10:00:00+00:00",
        )

        self.assertEqual(locator["locator_version"], 2)
        self.assertEqual(locator["grid_position_hint"], 1)
        self.assertEqual(locator["account_name"], "@demo")
        self.assertIn("#vungtau", locator["caption_tokens"])
        self.assertIn("#outfit", locator["caption_tokens"])
        self.assertTrue(locator["caption_fingerprint"])

    def test_match_post_locator_accepts_token_overlap_match(self):
        controller = self._controller()
        locator = controller.build_post_locator(
            caption_text="Mix đồ đi biển cực cháy #VungTau #Outfit",
            account_name="@demo",
        )
        signals = {
            "author": "demo",
            "description": "mix do di bien cuc chay #vungtau #outfit",
            "signature_texts": ["mix do di bien cuc chay", "#vungtau #outfit"],
            "caption_preview": "mix do di bien cuc chay #vungtau #outfit",
            "caption_tokens": ["mix", "bien", "chay", "#vungtau", "#outfit"],
            "caption_fingerprint": controller.build_post_locator(
                caption_text="mix do di bien cuc chay #vungtau #outfit",
                account_name="@demo",
            )["caption_fingerprint"],
        }

        match = controller.match_post_locator(locator, signals)

        self.assertTrue(match["matched"])
        self.assertGreaterEqual(match["token_overlap"], 2)
        self.assertTrue(match["fingerprint_match"])

    def test_match_post_locator_rejects_unrelated_post(self):
        controller = self._controller()
        locator = controller.build_post_locator(
            caption_text="Mix đồ đi biển cực cháy #VungTau #Outfit",
            account_name="@demo",
        )
        signals = {
            "author": "demo",
            "description": "cach nau pho bo tai nha #amthuc",
            "signature_texts": ["cach nau pho bo tai nha", "#amthuc"],
            "caption_preview": "cach nau pho bo tai nha #amthuc",
            "caption_tokens": ["cach", "nau", "pho", "#amthuc"],
            "caption_fingerprint": controller.build_post_locator(
                caption_text="cach nau pho bo tai nha #amthuc",
                account_name="@demo",
            )["caption_fingerprint"],
        }

        match = controller.match_post_locator(locator, signals)

        self.assertFalse(match["matched"])
        self.assertEqual(match["token_overlap"], 0)
