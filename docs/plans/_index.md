# Android Control — Plans & Progress

> **Quy tắc**: Mọi kế hoạch và task đều được lưu tại `docs/plans/`. File được đặt tên theo nội dung, có status rõ ràng.
> Agent phải đọc file `_index.md` này trước khi bắt đầu bất kì task nào.
> **Deploy rule**: Trước khi deploy server để test, phải commit + push branch hiện tại lên `origin` để backup; chỉ deploy khi remote branch đã chứa đúng `HEAD` local.

## Plan Index

| # | Plan File | Status | Summary |
|---|-----------|--------|---------|
| 1 | [cloud-device-integration.md](cloud-device-integration.md) | ✅ COMPLETE | Phase 1A–1E hoàn thành. Cloud infra, APK, deploy, E2E testing done |
| 2 | [saas_website_plan.md](saas_website_plan.md) | 📋 PLANNED | SaaS marketing website (Next.js). Chưa bắt đầu |
| 3 | [video-management-system.md](video-management-system.md) | ✅ COMPLETE | Video library management, device assignment, adb push, duplicate prevention |
| 4 | [proxy-antidetect-management.md](proxy-antidetect-management.md) | 📋 PLANNED | Proxy per-device, antidetect fingerprint spoofing, bypass platform detection, proxy pool management |
| 5 | [auth-protection.md](auth-protection.md) | ✅ COMPLETE | Session-based auth middleware — bảo vệ toàn bộ dashboard và API khỏi truy cập public |
| 6 | [ai-video-metadata.md](ai-video-metadata.md) | 🔄 IN PROGRESS | AI auto-suggest Title/Tags/Description cho video — GPT-4o-mini Vision + keyframe analysis |
| 7 | [dashboard-tiktok-first-redesign.md](dashboard-tiktok-first-redesign.md) | 🔄 IN PROGRESS | Dashboard TikTok-first, template metadata, live run composer, parity với runtime thật |
| 8 | [tiktok-comment-hardening.md](tiktok-comment-hardening.md) | 🔄 IN PROGRESS | Helper APK release/version pipeline, comment send telemetry, regression gates cho `/set` + TikTok comment |
| 9 | [open-issues-tracker.md](open-issues-tracker.md) | 🔄 IN PROGRESS | Single source of truth cho các vấn đề còn mở trên production: TikTok comment runtime, helper stability, verification, schema drift, dashboard E2E |
| 10 | [tiktok-video-performance-tracking.md](tiktok-video-performance-tracking.md) | 🔄 IN PROGRESS | Phase A (schema/API) + Phase B (UI skeleton) complete. Theo dõi views và tương tác của video TikTok theo từng assignment |
| 11 | [tiktok-metrics-locator-matching-checklist.md](tiktok-metrics-locator-matching-checklist.md) | 🔄 IN PROGRESS | Regression + device checklist cho locator-based matching trong TikTok metrics sync |
| 12 | [android-helper-stability-hardening.md](android-helper-stability-hardening.md) | 🔄 IN PROGRESS | Plan + task tracker cho Android Helper APK stability, cloud reconnect safety, credential handling, LAN auth, protocol hardening |
| 13 | [workflow-karpathy-alignment.md](workflow-karpathy-alignment.md) | ✅ COMPLETE | Rà soát workflow/skill docs và đưa assumptions, non-goals, surgical scope, verification của karpathy-guidelines vào quy trình chuẩn |
| 14 | [android-device-approval-linking.md](android-device-approval-linking.md) | 🔄 IN PROGRESS | Username-only Android linking: device requests access, WebApp/admin accepts or rejects, then server issues device token |
| 15 | [cloud-websocket-stability.md](cloud-websocket-stability.md) | 🔄 IN PROGRESS | Fix cloud WS persistent connection: server keepalive ping, stale detection, client timeout tuning, dual-client conflict |
| 16 | [android-live-control-livekit.md](android-live-control-livekit.md) | 🔄 IN PROGRESS | LiveKit screen stream + existing DeviceHub/Accessibility control; MVP built, awaiting physical-device verification |

## Completed Features (No Separate Plan Files)

| Feature | Version | Mô tả |
|---------|---------|-------|
| TikTok Agent | v0.5 | Browse, like, comment, follow, upload scripts |
| Task History UI | v0.6 | Redesigned tab với step-level detail logs |
| Bot PAUSED Mode | v0.6 | Tạm dừng bot từ dashboard |
| AI Comment Quality | v0.6 | DeepSeek reads existing comments before generating |
| Task Communication Fix | v0.6 | Fixed dual-toast bug, WebSocket status, REST polling fallback |

## Status Legend
- ✅ COMPLETE — Đã hoàn thành
- 🔄 IN PROGRESS — Đang thực hiện
- 📋 PLANNED — Đã lên kế hoạch, chưa bắt đầu
- ❌ CANCELLED — Đã huỷ
