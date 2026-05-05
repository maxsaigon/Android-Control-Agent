# TikTok Metrics Locator Matching — Test & Device Checklist

**Status**: 🔄 IN PROGRESS  
**Scope**: Verify Phase C2 locator-based matching for TikTok metrics sync.

## Mục tiêu

Đảm bảo metrics sync không còn chỉ đọc `position 0`, mà thực sự:
- dùng `post_locator` được capture sau upload
- scan candidate quanh `grid_position_hint`
- match đúng bài theo caption tokens/preview
- fallback an toàn về `needs_review` nếu không match được

## Regression Tests

### P0 Unit

- `build_post_locator()` lưu `locator_version`, `caption_tokens`, `caption_fingerprint`, `caption_preview`
- `match_post_locator()` match đúng khi token overlap + fingerprint/preview khớp
- `match_post_locator()` reject post không liên quan dù cùng account
- candidate ordering ưu tiên `grid_position_hint`, rồi `+1/-1`, rồi visible positions

### P0 Runner / DB

- hint sai nhưng candidate kế bên match đúng → sync thành công, metrics lưu đúng
- candidate đầu mismatch → runner phải `BACK` về grid rồi thử candidate tiếp theo
- không match candidate nào → assignment chuyển `NEEDS_REVIEW`, có artifact + `metrics_error`
- bài cũ không có `locator_version/caption_tokens` → flow vẫn fallback theo `grid_position_hint`
- match thành công ở candidate khác hint cũ → `post_locator.grid_position_hint` được cập nhật

## Device Checklist

### Preconditions

- Device đã login đúng TikTok account
- Assignment có `upload_status=UPLOADED`
- Assignment có `post_locator` mới (`locator_version=2`)
- Account có ít nhất 2 post gần nhau để test case hint drift

### Case 1: Exact Match At Hint

- Upload 1 video mới
- Trigger `sync-metrics`
- Kỳ vọng:
  - mở đúng post đầu tiên quanh hint
  - `metrics_status=SYNCED`
  - `latest_views/likes/comments/shares` được cập nhật
  - artifact có `locator_match_*`

### Case 2: Hint Drift +1

- Upload video A
- Upload thêm 1 video B sau đó, để A không còn ở `position 0`
- Sync assignment của A
- Kỳ vọng:
  - runner thử `position 0` trước, reject
  - quay lại grid, mở `position 1`
  - match đúng A theo caption tokens/preview
  - `post_locator.grid_position_hint` của A được cập nhật thành `1`

### Case 3: Similar Hashtags, Different Caption

- Tạo 2 bài cùng hashtag nhưng khác nội dung chính
- Sync assignment bài cũ hơn
- Kỳ vọng:
  - không match sai chỉ vì hashtag chung
  - token overlap phải đủ mạnh mới pass

### Case 4: Old Locator Backward Compatibility

- Dùng assignment cũ chỉ có `caption_fingerprint` legacy hoặc chỉ có `grid_position_hint`
- Sync metrics
- Kỳ vọng:
  - flow không crash
  - vẫn thử theo hint
  - nếu sai post thì về `NEEDS_REVIEW`, không ghi metrics nhầm

### Case 5: No Match / Needs Review

- Sửa locator trong DB thành caption không liên quan
- Trigger `sync-metrics`
- Kỳ vọng:
  - runner thử hết candidate window visible
  - không lưu nhầm metrics của bài khác
  - assignment về `NEEDS_REVIEW`
  - `metrics_error` nêu rõ không match được locator

### Case 6: Empty / Sparse Grid Signals

- Account có tile không hiện view count overlay hoặc UI dump thiếu một số text
- Trigger sync
- Kỳ vọng:
  - candidate ordering vẫn hoạt động
  - match vẫn có thể dùng preview/tokens ở post detail
  - nếu không đủ signal thì fail an toàn

## Artifacts Cần Kiểm

- `grid_metrics`
- `locator_miss_*`
- `locator_match_*`
- `locator_match_fail`
- `post_detail_metrics`
- `back_to_profile_fail` nếu có

## Exit Criteria

- Unit + regression tests pass
- 6 case device trên pass ít nhất 1 lần với account thật
- Không còn assignment nào bị gán nhầm metrics khi hint drift trong top visible grid
