"""
Video Management System — Integration Test Suite

Tests 6 scenarios from the plan + extras.
Run: python tests/test_video_service.py
Requires: Server running at localhost:8000
"""

import asyncio
import io
import os
import sys
import tempfile

import httpx

BASE = "http://localhost:8000"

results = []


def report(name: str, passed: bool, detail: str = "") -> None:
    status = "✅ PASS" if passed else "❌ FAIL"
    results.append((name, passed, detail))
    print(f"  {status} | {name}" + (f" — {detail}" if detail else ""))


def make_fake_video(size_kb: int = 10) -> bytes:
    """Create a fake MP4-ish file for upload testing."""
    # Minimal MP4 header bytes
    header = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2"
    return header + os.urandom(size_kb * 1024)


async def run_tests() -> bool:
    print("=" * 60)
    print("Video Management System — Test Suite")
    print("=" * 60)

    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:

        # =================================================================
        # 0. PRE-CHECK: Server running
        # =================================================================
        print("\n📋 0. Server Health")
        r = await client.get("/")
        report("Server is running", r.status_code == 200)

        # =================================================================
        # 1. Upload video → verify DB record + SHA-256 hash
        # =================================================================
        print("\n📋 1. Upload Video")
        video_content = make_fake_video(20)
        files = {"file": ("test_video.mp4", io.BytesIO(video_content), "video/mp4")}
        data = {"title": "Test Video", "tags": "test,automation"}

        r = await client.post("/api/videos/upload", files=files, data=data)
        report("Upload responds 201", r.status_code == 201, f"got {r.status_code}")

        if r.status_code == 201:
            v1 = r.json()
            report("Video has id", "id" in v1)
            report("Video has file_hash", "file_hash" in v1 and len(v1.get("file_hash", "")) == 64)
            report("Video title saved", v1.get("title") == "Test Video", v1.get("title"))
            report("Video tags saved", v1.get("tags") == "test,automation")
            video_id = v1["id"]
        else:
            report("Upload succeeded", False, r.text)
            video_id = None

        # =================================================================
        # 2. Upload SAME file → detect duplicate (200, not 201)
        # =================================================================
        print("\n📋 2. Duplicate Detection")
        files2 = {"file": ("test_video_copy.mp4", io.BytesIO(video_content), "video/mp4")}
        r2 = await client.post("/api/videos/upload", files=files2, data={"title": "Duplicate"})
        report("Duplicate returns 200 (not 201)", r2.status_code == 200, f"got {r2.status_code}")
        if r2.status_code == 200:
            dup = r2.json()
            report("Duplicate flag set", dup.get("_duplicate") is True)
            report("Same video ID returned", video_id and dup.get("id") == video_id, f"got {dup.get('id')} vs {video_id}")

        # =================================================================
        # 3. Assign video → TikTok Device A → ✅
        # =================================================================
        print("\n📋 3. Assign Video → TikTok Device A")

        # Get devices
        r = await client.get("/api/devices")
        devices = r.json()

        if not devices or video_id is None:
            report("Devices available for assignment test", False, "No devices registered")
        else:
            device_a_id = devices[0]["id"]
            r3 = await client.post(
                f"/api/videos/{video_id}/assign",
                json={"device_id": device_a_id, "platform": "tiktok"},
            )
            report("Assign TikTok A → 201", r3.status_code == 201, f"got {r3.status_code}")
            if r3.status_code == 201:
                assign_a = r3.json()
                report("Assignment has id", "id" in assign_a)
                report("Push status = pending", assign_a.get("push_status") == "pending")
                assignment_a_id = assign_a["id"]
            else:
                report("Assignment created", False, r3.text)
                assignment_a_id = None

            # =================================================================
            # 4. Assign SAME video → TikTok Device B → ❌ 409
            # =================================================================
            print("\n📋 4. Duplicate Platform Assignment (409)")
            device_b_id = devices[1]["id"] if len(devices) > 1 else device_a_id + 999

            r4 = await client.post(
                f"/api/videos/{video_id}/assign",
                json={"device_id": device_b_id, "platform": "tiktok"},
            )
            report("Same video TikTok B → 409", r4.status_code == 409, f"got {r4.status_code}")
            if r4.status_code == 409:
                report("Error message mentions platform", "tiktok" in r4.json().get("detail", "").lower())

            # =================================================================
            # 5. Assign same video → YouTube → ✅ (different platform OK)
            # =================================================================
            print("\n📋 5. Same Video → YouTube (different platform OK)")
            yt_device_id = devices[0]["id"]
            r5 = await client.post(
                f"/api/videos/{video_id}/assign",
                json={"device_id": yt_device_id, "platform": "youtube"},
            )
            report("Same video YouTube → 201", r5.status_code == 201, f"got {r5.status_code}")

        # =================================================================
        # 6. GET /api/videos?platform=tiktok&unassigned=true
        #    → should NOT include the assigned video
        # =================================================================
        print("\n📋 6. Unassigned Filter")
        if video_id and devices:
            r6 = await client.get("/api/videos?platform=tiktok&unassigned=true")
            report("Unassigned filter endpoint works", r6.status_code == 200)
            unassigned = r6.json()
            assigned_ids = [v["id"] for v in unassigned]
            report("Assigned video NOT in unassigned list", video_id not in assigned_ids, f"ids={assigned_ids}")

        # =================================================================
        # 7. GET /api/videos — list endpoint
        # =================================================================
        print("\n📋 7. Video List Endpoint")
        r7 = await client.get("/api/videos")
        report("GET /api/videos works", r7.status_code == 200)
        vlist = r7.json()
        report("List returns array", isinstance(vlist, list))
        if vlist and video_id:
            found = any(v["id"] == video_id for v in vlist)
            report("Uploaded video in list", found)
            sample = next((v for v in vlist if v["id"] == video_id), None)
            if sample:
                report("Video has assignments field", "assignments" in sample)

        # =================================================================
        # 8. GET /api/videos/assignments
        # =================================================================
        print("\n📋 8. Assignments Endpoint")
        r8 = await client.get("/api/videos/assignments")
        report("GET /api/videos/assignments works", r8.status_code == 200)
        assignments = r8.json()
        report("Assignments is list", isinstance(assignments, list))

        # =================================================================
        # 9. Device Accounts CRUD
        # =================================================================
        print("\n📋 9. Device Accounts CRUD")
        r9_list = await client.get("/api/device-accounts")
        report("GET /api/device-accounts works", r9_list.status_code == 200)

        if devices:
            r9_create = await client.post(
                "/api/device-accounts",
                json={
                    "device_id": devices[0]["id"],
                    "platform": "tiktok",
                    "account_name": "@test_account",
                    "notes": "Test account",
                },
            )
            report("Create device account → 201", r9_create.status_code == 201, f"got {r9_create.status_code}")
            if r9_create.status_code == 201:
                acc = r9_create.json()
                report("Account has id", "id" in acc)
                report("Account name saved", acc.get("account_name") == "@test_account")

                # Upsert (update same device+platform)
                r9_update = await client.post(
                    "/api/device-accounts",
                    json={
                        "device_id": devices[0]["id"],
                        "platform": "tiktok",
                        "account_name": "@updated_account",
                    },
                )
                report("Upsert device account works", r9_update.status_code == 201)

                # Delete
                acc_id = acc["id"]
                r9_del = await client.delete(f"/api/device-accounts/{acc_id}")
                report("Delete device account → 204", r9_del.status_code == 204, f"got {r9_del.status_code}")

        # =================================================================
        # 10. Soft delete
        # =================================================================
        print("\n📋 10. Soft Delete")
        if video_id:
            # Upload a new video to delete
            throwaway = make_fake_video(5)
            r10_up = await client.post(
                "/api/videos/upload",
                files={"file": ("throwaway.mp4", io.BytesIO(throwaway), "video/mp4")},
                data={"title": "To Delete"},
            )
            if r10_up.status_code == 201:
                del_id = r10_up.json()["id"]
                r10_del = await client.delete(f"/api/videos/{del_id}")
                report("DELETE /api/videos/{id} → 204", r10_del.status_code == 204)

                # Verify not in default list
                r10_list = await client.get("/api/videos")
                ids = [v["id"] for v in r10_list.json()]
                report("Deleted video not in default list", del_id not in ids)
            else:
                report("Throwaway upload for delete test", False, r10_up.text)

    # =================================================================
    # SUMMARY
    # =================================================================
    print("\n" + "=" * 60)
    passed = sum(1 for _, p, _ in results if p)
    failed = sum(1 for _, p, _ in results if not p)
    total = len(results)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print("\nFailed tests:")
        for name, p, detail in results:
            if not p:
                print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
