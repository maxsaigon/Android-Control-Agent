# Deploy SOP — max.lan (m.buonme.com)

## Mục tiêu
Deploy code hiện tại lên `max@max.lan:/home/max/android-control` an toàn, có backup DB, và verify nhanh trước khi test device.

## Nguồn chuẩn hiện hành
- Script chuẩn: `deploy/max-lan-smoke.sh`
- Cloud script: `deploy/cloud-setup.sh`
- Rule: `README.md` mục **Deploy Rule**

## Pre-check
1. Xác nhận SSH vào server được:
   - `ssh max@max.lan 'echo ok'`
2. Xác nhận stack production đang chạy file compose nào:
   - `ssh max@max.lan 'cd /home/max/android-control && docker compose ps && docker compose -f docker-compose.cloud.yml ps'`
3. Mặc định production hiện dùng `docker-compose.yml` (bind DB `./data/android_control.db`).

## Quy trình chuẩn (khuyến nghị)
1. Commit + push branch hiện tại lên `origin`.
2. Chạy:
   - `./deploy/max-lan-smoke.sh`
3. Script sẽ:
   - verify backup rule `origin/<branch> == HEAD`
   - rsync code
   - backup DB vào `data/backups/android_control.db.pre_deploy_<timestamp>`
   - `docker compose -f docker-compose.yml up -d --build`
   - chạy smoke local + public domain (`https://m.buonme.com`)

## Quy trình bypass (khẩn cấp, chưa push)
Chỉ dùng khi cần hotfix ngay và chấp nhận bỏ qua git-backup gate:
1. rsync source lên server (giữ nguyên exclude như script chuẩn)
2. backup DB thủ công
3. deploy:
   - `docker compose -f docker-compose.yml up -d --build`
4. verify:
   - `curl -sf http://localhost:8001/api/health`
   - `curl -skSf https://m.buonme.com/api/health`

## Post-deploy verify cho WebSocket stability
1. Đảm bảo Uvicorn có flags:
   - `--ws-ping-interval 25 --ws-ping-timeout 30`
2. Theo dõi logs app:
   - `ssh max@max.lan 'docker logs -f android-control-app-1'`
3. Sau khi device connect, cần thấy:
   - `server_ping sent (count=...)` tăng dần
   - session close summary: `uptime`, `server_pings`, `heartbeat_acks`

## Rollback nhanh
1. Lấy file backup mới nhất trong `data/backups/`.
2. Stop app, restore DB backup, start lại compose.
3. Re-verify `/api/health` local và public.
