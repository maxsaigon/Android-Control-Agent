"""AI metadata service — analyze video keyframes with GPT-4o-mini vision.

Pipeline:
    1. Check cache for existing metadata (same video × language × platform)
    2. If cached → return immediately (0 tokens!)
    3. If not cached → FFmpeg extract keyframes → GPT-4o-mini Vision analyze
    4. Save to cache table + update Video record
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
from sqlmodel import Session, select

from app.config import settings
from app.models import Video, VideoAIMetadata

logger = logging.getLogger(__name__)

# Supported languages for metadata generation
SUPPORTED_LANGUAGES = {
    "vi": "Tiếng Việt",
    "en": "English",
    "ja": "日本語 (Japanese)",
    "ko": "한국어 (Korean)",
    "zh": "中文 (Chinese)",
    "th": "ภาษาไทย (Thai)",
    "id": "Bahasa Indonesia",
    "auto": "Tự động phát hiện từ nội dung video",
}

# System prompt for metadata generation — language-aware
_METADATA_SYSTEM_PROMPT = """Bạn là chuyên gia SEO cho mạng xã hội. Phân tích các keyframes từ video và tạo metadata tối ưu.

Yêu cầu:
- title: Ngắn gọn, gây tò mò, có keyword chính (max 100 ký tự). KHÔNG dùng emoji trong title.
- tags: 8-15 hashtags phù hợp, mix trending + niche. Dạng mảng string, mỗi tag có # phía trước.
- description: 2-3 câu mô tả nội dung video + call-to-action. Có thể dùng emoji.
- thumbnail_index: Chọn index (0-based) của keyframe phù hợp nhất làm thumbnail.

Platform target: {platform}
Ngôn ngữ output: {language}

Trả lời ĐÚNG JSON format sau, KHÔNG có text khác:
{{
  "title": "...",
  "tags": ["#tag1", "#tag2", "#tag3"],
  "description": "...",
  "thumbnail_index": 0
}}"""

# Thumbnail storage directory
THUMBNAIL_DIR = Path(settings.video_storage_dir) / "thumbnails"


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
        language: str = "vi",
        force: bool = False,
    ) -> Optional[dict]:
        """Generate AI metadata suggestions for a video.

        Checks cache first. If cached result exists for this
        video × language × platform combo, returns it without
        calling OpenAI (saving tokens!).

        Args:
            session: Database session
            video_id: Video ID
            platform: Target platform
            language: Output language code
            force: If True, skip cache and regenerate

        Returns:
            Dict with ai_title, ai_tags, ai_description, cached flag.
        """
        video = session.get(Video, video_id)
        if not video:
            logger.error(f"Video {video_id} not found")
            return None

        # --- Check cache first (unless force=True) ---
        if not force:
            cached = self._get_cached(session, video_id, language, platform)
            if cached:
                logger.info(
                    f"Cache HIT for video {video_id} "
                    f"[{language}/{platform}] — 0 tokens used"
                )
                # Also set as active on Video record
                self._set_active(session, video, cached)
                return {
                    "ai_title": cached.ai_title,
                    "ai_tags": cached.ai_tags,
                    "ai_description": cached.ai_description,
                    "ai_generated_at": str(cached.generated_at),
                    "thumbnail": cached.thumbnail,
                    "cached": True,
                    "language": cached.language,
                    "platform": cached.platform,
                }

        # --- Cache MISS — generate fresh ---
        if not Path(video.filepath).exists():
            logger.error(f"Video file not found: {video.filepath}")
            return None

        if not settings.openai_api_key:
            logger.error("OpenAI API key not configured")
            return None

        lang_label = SUPPORTED_LANGUAGES.get(language, SUPPORTED_LANGUAGES["vi"])

        try:
            # Step 1: Extract keyframes
            frames_b64, frame_bytes_list = self._extract_keyframes(
                video.filepath,
                n_frames=settings.ai_metadata_max_frames,
            )
            if not frames_b64:
                logger.error(f"Failed to extract keyframes from video {video_id}")
                return None

            logger.info(
                f"Cache MISS for video {video_id} [{language}/{platform}] "
                f"— extracting {len(frames_b64)} keyframes, calling GPT"
            )

            # Step 2: Analyze with GPT-4o-mini vision
            result = await self._analyze_and_generate(
                frames_b64, platform, lang_label
            )
            if not result:
                logger.error(f"AI analysis failed for video {video_id}")
                return None

            # Step 3: Save thumbnail
            thumb_idx = result.get("thumbnail_index", 0)
            thumb_idx = max(0, min(thumb_idx, len(frame_bytes_list) - 1))
            thumbnail_path = self._save_thumbnail(
                video_id, frame_bytes_list[thumb_idx]
            )

            ai_title = result.get("title", "")
            ai_tags = ",".join(result.get("tags", []))
            ai_description = result.get("description", "")
            now = datetime.now(timezone.utc)

            # Step 4: Save to cache table
            self._save_cache(
                session, video_id, language, platform,
                ai_title, ai_tags, ai_description,
                thumbnail_path, now,
            )

            # Step 5: Update active on Video record
            video.ai_title = ai_title
            video.ai_tags = ai_tags
            video.ai_description = ai_description
            video.ai_generated_at = now
            if thumbnail_path:
                video.thumbnail = thumbnail_path
            session.commit()
            session.refresh(video)

            logger.info(
                f"AI metadata generated + cached for video {video_id} "
                f"[{language}/{platform}]: title='{ai_title}'"
            )
            return {
                "ai_title": ai_title,
                "ai_tags": ai_tags,
                "ai_description": ai_description,
                "ai_generated_at": str(now),
                "thumbnail": thumbnail_path,
                "cached": False,
                "language": language,
                "platform": platform,
            }

        except Exception as e:
            logger.exception(f"AI metadata generation failed for video {video_id}: {e}")
            return None

    def get_all_cached(
        self, session: Session, video_id: int
    ) -> list[dict]:
        """Get all cached AI metadata for a video (all languages/platforms)."""
        stmt = (
            select(VideoAIMetadata)
            .where(VideoAIMetadata.video_id == video_id)
            .order_by(VideoAIMetadata.generated_at.desc())  # type: ignore
        )
        results = session.exec(stmt).all()
        return [
            {
                "id": r.id,
                "language": r.language,
                "platform": r.platform,
                "ai_title": r.ai_title,
                "ai_tags": r.ai_tags,
                "ai_description": r.ai_description,
                "thumbnail": r.thumbnail,
                "generated_at": str(r.generated_at),
            }
            for r in results
        ]

    def apply_suggestions(
        self,
        session: Session,
        video_id: int,
        apply_title: bool = True,
        apply_tags: bool = True,
        apply_description: bool = True,
    ) -> Optional[dict]:
        """Apply AI suggestions to the actual video fields."""
        video = session.get(Video, video_id)
        if not video:
            return None
        if not video.ai_generated_at:
            return None

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
    # Internal: Cache operations
    # ------------------------------------------------------------------

    def _get_cached(
        self, session: Session,
        video_id: int, language: str, platform: str,
    ) -> Optional[VideoAIMetadata]:
        """Find cached metadata for exact video×language×platform."""
        stmt = select(VideoAIMetadata).where(
            VideoAIMetadata.video_id == video_id,
            VideoAIMetadata.language == language,
            VideoAIMetadata.platform == platform,
        )
        return session.exec(stmt).first()

    def _save_cache(
        self, session: Session,
        video_id: int, language: str, platform: str,
        ai_title: str, ai_tags: str, ai_description: str,
        thumbnail: Optional[str], generated_at: datetime,
    ) -> None:
        """Upsert cached metadata — replace if same combo exists."""
        existing = self._get_cached(session, video_id, language, platform)
        if existing:
            existing.ai_title = ai_title
            existing.ai_tags = ai_tags
            existing.ai_description = ai_description
            existing.thumbnail = thumbnail
            existing.generated_at = generated_at
        else:
            entry = VideoAIMetadata(
                video_id=video_id,
                language=language,
                platform=platform,
                ai_title=ai_title,
                ai_tags=ai_tags,
                ai_description=ai_description,
                thumbnail=thumbnail,
                generated_at=generated_at,
            )
            session.add(entry)
        session.commit()

    def _set_active(
        self, session: Session, video: Video, cached: VideoAIMetadata
    ) -> None:
        """Set cached entry as the active AI metadata on the Video."""
        video.ai_title = cached.ai_title
        video.ai_tags = cached.ai_tags
        video.ai_description = cached.ai_description
        video.ai_generated_at = cached.generated_at
        if cached.thumbnail:
            video.thumbnail = cached.thumbnail
        session.commit()
        session.refresh(video)

    # ------------------------------------------------------------------
    # Internal: Frame extraction
    # ------------------------------------------------------------------

    def _extract_keyframes(
        self,
        video_path: str,
        n_frames: int = 5,
    ) -> tuple[list[str], list[bytes]]:
        """Extract N evenly-spaced keyframes using FFmpeg."""
        video_path = str(video_path)
        duration = self._get_duration(video_path)
        if duration is None or duration <= 0:
            logger.warning(f"Could not determine video duration: {video_path}")
            duration = n_frames

        with tempfile.TemporaryDirectory() as tmpdir:
            fps = n_frames / duration if duration > 0 else 1
            fps = max(0.1, min(fps, 2.0))
            output_pattern = str(Path(tmpdir) / "frame_%04d.jpg")

            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-vf", f"fps={fps}",
                "-frames:v", str(n_frames),
                "-q:v", "2",
                "-y",
                output_pattern,
            ]

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60
                )
                if result.returncode != 0:
                    logger.error(f"FFmpeg failed: {result.stderr[:500]}")
                    return [], []
            except subprocess.TimeoutExpired:
                logger.error("FFmpeg timeout (>60s)")
                return [], []
            except FileNotFoundError:
                logger.error("FFmpeg not installed")
                return [], []

            frames_b64 = []
            frames_bytes = []
            for frame_file in sorted(Path(tmpdir).glob("frame_*.jpg")):
                raw = frame_file.read_bytes()
                frames_b64.append(base64.b64encode(raw).decode("utf-8"))
                frames_bytes.append(raw)

            return frames_b64[:n_frames], frames_bytes[:n_frames]

    def _get_duration(self, video_path: str) -> Optional[float]:
        """Get video duration in seconds using FFprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", video_path,
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
    # Internal: Thumbnail
    # ------------------------------------------------------------------

    def _save_thumbnail(self, video_id: int, frame_bytes: bytes) -> Optional[str]:
        """Save keyframe as thumbnail JPEG."""
        try:
            THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
            thumb_path = THUMBNAIL_DIR / f"{video_id}.jpg"
            thumb_path.write_bytes(frame_bytes)
            logger.info(f"Saved thumbnail: {thumb_path}")
            return str(thumb_path)
        except Exception as e:
            logger.error(f"Failed to save thumbnail: {e}")
            return None

    # ------------------------------------------------------------------
    # Internal: GPT-4o-mini Vision analysis
    # ------------------------------------------------------------------

    async def _analyze_and_generate(
        self,
        frames_b64: list[str],
        platform: str,
        language: str = "Tiếng Việt",
    ) -> Optional[dict]:
        """Send keyframes to GPT-4o-mini vision and generate metadata."""
        content = [
            {
                "type": "text",
                "text": (
                    f"Đây là {len(frames_b64)} keyframes từ 1 video sẽ upload lên {platform}. "
                    "Phân tích nội dung hình ảnh và tạo metadata SEO-optimized. "
                    "Cũng hãy chọn keyframe nào phù hợp nhất làm thumbnail."
                ),
            }
        ]

        for i, frame_b64 in enumerate(frames_b64):
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{frame_b64}",
                    "detail": "low",
                },
            })

        try:
            response = await self.client.chat.completions.create(
                model=settings.ai_metadata_model,
                messages=[
                    {
                        "role": "system",
                        "content": _METADATA_SYSTEM_PROMPT.format(
                            platform=platform, language=language
                        ),
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
