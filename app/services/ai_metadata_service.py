"""AI metadata service — analyze video keyframes with GPT-4o-mini vision.

Pipeline:
    1. FFmpeg: extract N keyframes from video → base64 images
    2. GPT-4o-mini Vision: analyze frames → generate title, tags, description
    3. Save suggestions to Video record
"""

import base64
import json
import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import openai
from sqlmodel import Session

from app.config import settings
from app.models import Video

logger = logging.getLogger(__name__)

# System prompt for metadata generation
_METADATA_SYSTEM_PROMPT = """Bạn là chuyên gia SEO cho mạng xã hội. Phân tích các keyframes từ video và tạo metadata tối ưu.

Yêu cầu:
- title: Ngắn gọn, gây tò mò, có keyword chính (max 100 ký tự). KHÔNG dùng emoji trong title.
- tags: 8-15 hashtags phù hợp, mix trending + niche. Dạng mảng string, mỗi tag có # phía trước.
- description: 2-3 câu mô tả nội dung video + call-to-action. Có thể dùng emoji.

Platform target: {platform}
Ngôn ngữ: Tiếng Việt (trừ khi nội dung rõ ràng là tiếng Anh)

Trả lời ĐÚNG JSON format sau, KHÔNG có text khác:
{{
  "title": "...",
  "tags": ["#tag1", "#tag2", "#tag3"],
  "description": "..."
}}"""


class AIMetadataService:
    """Generate video metadata suggestions using GPT-4o-mini vision."""

    def __init__(self) -> None:
        self._client: Optional[openai.AsyncOpenAI] = None

    @property
    def client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            self._client = openai.AsyncOpenAI(
                api_key=settings.openai_api_key,
            )
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_suggestions(
        self,
        session: Session,
        video_id: int,
        platform: str = "tiktok",
    ) -> Optional[dict]:
        """Generate AI metadata suggestions for a video.

        Args:
            session: Database session
            video_id: Video ID
            platform: Target platform (tiktok/youtube/instagram/facebook)

        Returns:
            Dict with ai_title, ai_tags, ai_description or None on error.
        """
        video = session.get(Video, video_id)
        if not video:
            logger.error(f"Video {video_id} not found")
            return None

        if not Path(video.filepath).exists():
            logger.error(f"Video file not found: {video.filepath}")
            return None

        if not settings.openai_api_key:
            logger.error("OpenAI API key not configured")
            return None

        try:
            # Step 1: Extract keyframes
            frames_b64 = self._extract_keyframes(
                video.filepath,
                n_frames=settings.ai_metadata_max_frames,
            )
            if not frames_b64:
                logger.error(f"Failed to extract keyframes from video {video_id}")
                return None

            logger.info(
                f"Extracted {len(frames_b64)} keyframes from video {video_id}"
            )

            # Step 2: Analyze with GPT-4o-mini vision
            result = await self._analyze_and_generate(frames_b64, platform)
            if not result:
                logger.error(f"AI analysis failed for video {video_id}")
                return None

            # Step 3: Save to DB
            video.ai_title = result.get("title")
            video.ai_tags = ",".join(result.get("tags", []))
            video.ai_description = result.get("description")
            video.ai_generated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(video)

            logger.info(
                f"AI metadata generated for video {video_id}: "
                f"title='{video.ai_title}'"
            )
            return {
                "ai_title": video.ai_title,
                "ai_tags": video.ai_tags,
                "ai_description": video.ai_description,
                "ai_generated_at": str(video.ai_generated_at),
            }

        except Exception as e:
            logger.exception(f"AI metadata generation failed for video {video_id}: {e}")
            return None

    def apply_suggestions(
        self,
        session: Session,
        video_id: int,
        apply_title: bool = True,
        apply_tags: bool = True,
        apply_description: bool = True,
    ) -> Optional[dict]:
        """Apply AI suggestions to the actual video fields.

        Returns updated video dict or None if not found.
        """
        video = session.get(Video, video_id)
        if not video:
            return None

        if not video.ai_generated_at:
            return None  # No AI suggestions to apply

        if apply_title and video.ai_title:
            video.title = video.ai_title
        if apply_tags and video.ai_tags:
            video.tags = video.ai_tags
        if apply_description and video.ai_description:
            video.description = video.ai_description

        session.commit()
        session.refresh(video)

        logger.info(f"Applied AI suggestions to video {video_id}")
        return {
            "id": video.id,
            "title": video.title,
            "tags": video.tags,
            "description": video.description,
        }

    # ------------------------------------------------------------------
    # Internal: Frame extraction
    # ------------------------------------------------------------------

    def _extract_keyframes(
        self,
        video_path: str,
        n_frames: int = 5,
    ) -> list[str]:
        """Extract N evenly-spaced keyframes from a video using FFmpeg.

        Returns list of base64-encoded JPEG images.
        """
        video_path = str(video_path)

        # Get video duration first
        duration = self._get_duration(video_path)
        if duration is None or duration <= 0:
            logger.warning(f"Could not determine video duration: {video_path}")
            # Fallback: extract first 5 frames at 1fps
            duration = n_frames

        with tempfile.TemporaryDirectory() as tmpdir:
            # Calculate FPS to get exactly n_frames spread across video
            fps = n_frames / duration if duration > 0 else 1
            # Minimum fps of 0.1 (1 frame per 10s), max 2fps
            fps = max(0.1, min(fps, 2.0))

            output_pattern = str(Path(tmpdir) / "frame_%04d.jpg")

            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-vf", f"fps={fps}",
                "-frames:v", str(n_frames),
                "-q:v", "2",  # High quality JPEG
                "-y",         # Overwrite
                output_pattern,
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    logger.error(f"FFmpeg failed: {result.stderr[:500]}")
                    return []
            except subprocess.TimeoutExpired:
                logger.error("FFmpeg timeout (>60s)")
                return []
            except FileNotFoundError:
                logger.error("FFmpeg not installed")
                return []

            # Read frames and encode to base64
            frames = []
            for frame_file in sorted(Path(tmpdir).glob("frame_*.jpg")):
                with open(frame_file, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    frames.append(b64)

            return frames[:n_frames]

    def _get_duration(self, video_path: str) -> Optional[float]:
        """Get video duration in seconds using FFprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            video_path,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return float(data.get("format", {}).get("duration", 0))
        except Exception as e:
            logger.warning(f"FFprobe failed: {e}")
        return None

    # ------------------------------------------------------------------
    # Internal: GPT-4o-mini Vision analysis
    # ------------------------------------------------------------------

    async def _analyze_and_generate(
        self,
        frames_b64: list[str],
        platform: str,
    ) -> Optional[dict]:
        """Send keyframes to GPT-4o-mini vision and generate metadata.

        Returns dict with title, tags, description.
        """
        # Build content with images
        content = [
            {
                "type": "text",
                "text": (
                    f"Đây là {len(frames_b64)} keyframes từ 1 video sẽ upload lên {platform}. "
                    "Phân tích nội dung hình ảnh và tạo metadata SEO-optimized."
                ),
            }
        ]

        for i, frame_b64 in enumerate(frames_b64):
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{frame_b64}",
                    "detail": "low",  # Low detail = fewer tokens, still good enough
                },
            })

        try:
            response = await self.client.chat.completions.create(
                model=settings.ai_metadata_model,
                messages=[
                    {
                        "role": "system",
                        "content": _METADATA_SYSTEM_PROMPT.format(platform=platform),
                    },
                    {
                        "role": "user",
                        "content": content,
                    },
                ],
                max_tokens=500,
                temperature=0.7,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            if not raw:
                logger.error("Empty response from GPT-4o-mini")
                return None

            result = json.loads(raw)

            # Validate required fields
            if not all(k in result for k in ("title", "tags", "description")):
                logger.error(f"Missing fields in AI response: {result.keys()}")
                return None

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI JSON response: {e}")
            return None
        except openai.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            return None


# Singleton
ai_metadata_service = AIMetadataService()
