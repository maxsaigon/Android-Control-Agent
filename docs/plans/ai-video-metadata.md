# AI Video Metadata Suggestions — 📋 PLANNED

> **Created**: 2026-03-23 | **Updated**: 2026-03-23  
> **Status**: 🔄 IN PROGRESS — Backend implemented, chờ deploy + test với video thật

---

## Tổng quan

Tự động gợi ý Title, Tags, Description cho video sau khi upload, sử dụng GPT-4o-mini Vision phân tích keyframes.

**Pipeline**: FFmpeg extract keyframes → GPT-4o-mini Vision analyze → Generate metadata

---

## Files thay đổi

| Action | File | Mô tả |
|--------|------|-------|
| **NEW** | `app/services/ai_metadata_service.py` | Core AI service (keyframe extract + GPT vision) |
| MODIFY | `app/models.py` | +5 fields: `description`, `ai_title`, `ai_tags`, `ai_description`, `ai_generated_at` |
| MODIFY | `app/config.py` | +`ai_metadata_model`, `ai_metadata_max_frames` |
| MODIFY | `app/routers/videos.py` | +2 endpoints: `/ai-suggest`, `/apply-ai` |
| MODIFY | `app/services/video_service.py` | Updated `_video_to_dict()` |
| MODIFY | `Dockerfile` | +`ffmpeg` |

---

## API Endpoints

| Method | Path | Mô tả |
|--------|------|--------|
| `POST` | `/api/videos/{id}/ai-suggest` | Trigger AI metadata generation |
| `POST` | `/api/videos/{id}/apply-ai` | Apply AI suggestions → actual fields |

---

## Verification

1. Deploy → rebuild Docker image (ffmpeg included)
2. Upload video thật (.mp4 có nội dung)
3. `POST /api/videos/{id}/ai-suggest` → verify title/tags/description
4. `POST /api/videos/{id}/apply-ai` → verify fields updated
