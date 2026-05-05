import asyncio
import json
import sqlalchemy
from sqlmodel import Session, SQLModel, create_engine, select
from unittest.mock import AsyncMock, Mock

from app import database
from app.routers.videos import sync_metrics
from app.models import (
    Device,
    DeviceAccount,
    DeviceStatus,
    MetricsStatus,
    Task,
    TaskStatus,
    PushStatus,
    Video,
    UploadStatus,
    VideoAssignment,
    VideoAssignmentMetricSnapshot,
)
from app.services.script_runner import ScriptRunner
from app.services.task_engine import TaskResult
from app.services.task_queue import TaskQueue
from app.services.tiktok_controller import TikTokController
from app.services.video_service import _assignment_to_dict, video_service


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _make_engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path}/legacy_videos.db", echo=False)


def _create_legacy_video_tables(engine):
    with engine.connect() as conn:
        conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE video (
                    id INTEGER PRIMARY KEY,
                    filename VARCHAR NOT NULL,
                    filepath VARCHAR NOT NULL,
                    file_hash VARCHAR NOT NULL,
                    file_size INTEGER NOT NULL,
                    duration FLOAT,
                    title VARCHAR,
                    tags VARCHAR,
                    status VARCHAR,
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE videoassignment (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL,
                    device_id INTEGER NOT NULL,
                    platform VARCHAR NOT NULL,
                    push_status VARCHAR DEFAULT 'pending',
                    device_path TEXT,
                    pushed_at DATETIME,
                    uploaded_at DATETIME,
                    task_id INTEGER,
                    error TEXT,
                    created_at DATETIME,
                    UNIQUE(video_id, platform)
                )
                """
            )
        )
        conn.commit()


def _seed_legacy_video_rows(engine):
    with engine.connect() as conn:
        conn.execute(
            sqlalchemy.text(
                """
                INSERT INTO video (
                    id, filename, filepath, file_hash, file_size, duration,
                    title, tags, status, created_at
                )
                VALUES (
                    1, 'legacy.mp4', '/srv/videos/legacy.mp4', 'hash-legacy', 2048, 12.5,
                    'Legacy title', 'legacy,seed', 'available', '2026-03-30 10:00:00'
                )
                """
            )
        )
        conn.execute(
            sqlalchemy.text(
                """
                INSERT INTO videoassignment (
                    id, video_id, device_id, platform, push_status, device_path, created_at
                )
                VALUES (
                    1, 1, 1, 'tiktok', 'pushed', '/sdcard/DCIM/AndroidControl/legacy.mp4',
                    '2026-03-30 10:05:00'
                )
                """
            )
        )
        conn.commit()


def _seed_devices_and_accounts(engine):
    with Session(engine) as session:
        session.add(
            Device(
                id=1,
                name="Device A",
                ip_address="192.168.1.10",
                adb_port=5555,
                status=DeviceStatus.ONLINE,
            )
        )
        session.add(
            Device(
                id=2,
                name="Device B",
                ip_address="192.168.1.11",
                adb_port=5555,
                status=DeviceStatus.ONLINE,
            )
        )
        session.add(
            DeviceAccount(
                device_id=1,
                platform="tiktok",
                account_name="@legacy_a",
                notes="seed",
            )
        )
        session.add(
            DeviceAccount(
                device_id=2,
                platform="tiktok",
                account_name="@legacy_b",
                notes="seed",
            )
        )
        session.commit()


def _unique_index_columns(engine, table):
    with engine.connect() as conn:
        indexes = []
        for row in conn.execute(sqlalchemy.text(f"PRAGMA index_list('{table}')")):
            if not bool(row[2]):
                continue
            cols = tuple(
                col_row[2]
                for col_row in conn.execute(
                    sqlalchemy.text(f"PRAGMA index_info('{row[1]}')")
                )
            )
            indexes.append((row[1], cols))
        return indexes


def test_migrate_db_restores_legacy_video_listing(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    _create_legacy_video_tables(engine)
    database.create_db_and_tables()
    _seed_legacy_video_rows(engine)
    _seed_devices_and_accounts(engine)

    database.migrate_db()

    with Session(engine) as session:
        videos = video_service.get_videos(session)

    assert len(videos) == 1
    video = videos[0]
    assert video["id"] == 1
    assert video["title"] == "Legacy title"
    assert video["description"] is None
    assert video["thumbnail"] is None
    assert _enum_value(video["status"]) == "available"

    assert len(video["assignments"]) == 1
    assignment = video["assignments"][0]
    assert assignment["device_id"] == 1
    assert assignment["device_name"] == "Device A"
    assert assignment["account_name"] == "@legacy_a"
    assert _enum_value(assignment["push_status"]) == "pushed"
    assert _enum_value(assignment["upload_status"]) == "pending"

    tiktok_summary = video["platform_summary"]["tiktok"]
    assert tiktok_summary["eligible_targets"] == 2
    assert tiktok_summary["assigned_targets"] == 1
    assert tiktok_summary["missing_targets"] == 1


def test_migrate_db_rebuilds_legacy_videoassignment_uniqueness(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    _create_legacy_video_tables(engine)
    database.create_db_and_tables()
    _seed_legacy_video_rows(engine)
    _seed_devices_and_accounts(engine)

    database.migrate_db()

    unique_indexes = _unique_index_columns(engine, "videoassignment")
    unique_signatures = {cols for _, cols in unique_indexes}
    assert ("video_id", "platform") not in unique_signatures
    assert ("video_id", "device_id", "platform") in unique_signatures

    with engine.connect() as conn:
        backup = conn.execute(
            sqlalchemy.text(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'videoassignment__backup_pre_rebuild'
                """
            )
        ).first()
    assert backup is not None

    with Session(engine) as session:
        created, error = video_service.assign_video(session, 1, 2, "tiktok")
        assert error is None
        assert created is not None
        assert created["device_id"] == 2

        assignments = session.exec(
            select(VideoAssignment).where(VideoAssignment.video_id == 1)
        ).all()

    assert len(assignments) == 2
    assert sorted(item.device_id for item in assignments) == [1, 2]


def test_update_assignment_moves_target_and_resets_runtime(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    _create_legacy_video_tables(engine)
    database.create_db_and_tables()
    _seed_legacy_video_rows(engine)
    _seed_devices_and_accounts(engine)

    database.migrate_db()

    with Session(engine) as session:
        updated, error = video_service.update_assignment(
            session,
            1,
            device_id=2,
            platform="tiktok",
        )
        assert error is None
        assert updated is not None
        assert updated["device_id"] == 2
        assert _enum_value(updated["push_status"]) == "pending"
        assert _enum_value(updated["upload_status"]) == "pending"

        assignment = session.get(VideoAssignment, 1)
        assert assignment is not None
        assert assignment.device_id == 2
        assert assignment.platform == "tiktok"
        assert assignment.device_path is None
        assert assignment.task_id is None
        assert assignment.push_status == PushStatus.PENDING
        assert assignment.upload_status == UploadStatus.PENDING


def test_delete_assignment_removes_row(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    _create_legacy_video_tables(engine)
    database.create_db_and_tables()
    _seed_legacy_video_rows(engine)
    _seed_devices_and_accounts(engine)

    database.migrate_db()

    with Session(engine) as session:
        error = video_service.delete_assignment(session, 1)
        assert error is None
        assert session.get(VideoAssignment, 1) is None


def test_migrate_db_repairs_stale_runtime_storage_paths(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    _create_legacy_video_tables(engine)
    database.create_db_and_tables()
    _seed_legacy_video_rows(engine)
    _seed_devices_and_accounts(engine)
    database.migrate_db()

    runtime_video_dir = tmp_path / "runtime-data" / "videos"
    runtime_thumb_dir = runtime_video_dir / "thumbnails"
    runtime_thumb_dir.mkdir(parents=True, exist_ok=True)
    video_file = runtime_video_dir / "legacy.mp4"
    thumb_file = runtime_thumb_dir / "1.jpg"
    video_file.write_bytes(b"video")
    thumb_file.write_bytes(b"thumb")

    with engine.connect() as conn:
        conn.execute(
            sqlalchemy.text(
                """
                UPDATE video
                SET filepath = :filepath,
                    thumbnail = :thumbnail
                WHERE id = 1
                """
            ),
            {
                "filepath": "/tmp/android-control/data/videos/legacy.mp4",
                "thumbnail": "/tmp/android-control/data/videos/thumbnails/1.jpg",
            },
        )
        conn.commit()

    monkeypatch.setattr(database.settings, "video_storage_dir", str(runtime_video_dir))
    database.migrate_db()

    with Session(engine) as session:
        video = session.get(Video, 1)

    assert video is not None
    assert video.filepath == str(video_file)
    assert video.thumbnail == str(thumb_file)


def test_migrate_db_preserves_metrics_columns_after_legacy_rebuild(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    _create_legacy_video_tables(engine)
    database.create_db_and_tables()
    _seed_legacy_video_rows(engine)
    _seed_devices_and_accounts(engine)

    database.migrate_db()

    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(
                sqlalchemy.text("PRAGMA table_info('videoassignment')")
            )
        }

    assert "metrics_status" in columns
    assert "metrics_last_synced_at" in columns
    assert "latest_views" in columns
    assert "metrics_task_id" in columns

    with Session(engine) as session:
        assignment = session.get(VideoAssignment, 1)

    assert assignment is not None
    assert assignment.metrics_status == MetricsStatus.PENDING


def test_save_manual_metrics_requires_payload_and_persists_full_snapshot(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        assignment = VideoAssignment(
            video_id=1,
            device_id=1,
            platform="tiktok",
            upload_status=UploadStatus.UPLOADED,
            latest_likes=10,
            latest_comments=4,
            latest_shares=2,
        )
        session.add(assignment)
        session.commit()
        session.refresh(assignment)

        result, error = video_service.save_manual_metrics(session, assignment.id)
        assert result is None
        assert error is not None

        result, error = video_service.save_manual_metrics(
            session,
            assignment.id,
            views=123,
        )
        assert error is None
        assert result is not None

        session.refresh(assignment)
        snapshots = session.exec(select(VideoAssignmentMetricSnapshot)).all()

    assert assignment.metrics_status == MetricsStatus.SYNCED
    assert assignment.latest_views == 123
    assert assignment.latest_likes == 10
    assert len(snapshots) == 1
    assert snapshots[0].views == 123
    assert snapshots[0].likes == 10
    assert snapshots[0].comments == 4
    assert snapshots[0].shares == 2


def test_assignment_to_dict_counts_comments_or_shares_as_metrics():
    assignment = VideoAssignment(
        video_id=1,
        device_id=1,
        platform="tiktok",
        upload_status=UploadStatus.UPLOADED,
        latest_comments=7,
        latest_shares=3,
    )

    payload = _assignment_to_dict(assignment)

    assert payload["has_metrics"] is True


def test_sync_metrics_creates_task_without_upload_assignment_link(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            Device(
                id=1,
                name="Device A",
                ip_address="192.168.1.10",
                adb_port=5555,
                status=DeviceStatus.ONLINE,
            )
        )
        assignment = VideoAssignment(
            video_id=1,
            device_id=1,
            platform="tiktok",
            upload_status=UploadStatus.UPLOADED,
        )
        session.add(assignment)
        session.commit()
        session.refresh(assignment)

        submitted: list[int] = []

        async def _fake_submit(task_id: int):
            submitted.append(task_id)

        monkeypatch.setattr("app.routers.videos.task_queue.submit", _fake_submit)

        result = asyncio.run(sync_metrics(assignment.id, session=session))
        session.refresh(assignment)
        task = session.get(Task, assignment.metrics_task_id)

    assert result["success"] is True
    assert submitted == [task.id]
    assert assignment.metrics_status == MetricsStatus.SYNCING
    assert task is not None
    assert task.assignment_id is None
    assert task.template == "tiktok_metrics_sync"
    assert task.template_vars["assignment_id"] == assignment.id


def test_save_automated_metrics_marks_review_and_keeps_snapshot(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        assignment = VideoAssignment(
            video_id=1,
            device_id=1,
            platform="tiktok",
            upload_status=UploadStatus.UPLOADED,
            latest_views=111,
            latest_likes=22,
        )
        session.add(assignment)
        session.commit()
        session.refresh(assignment)

        result, error = video_service.save_automated_metrics(
            session,
            assignment.id,
            views=150,
            error="Could not return to profile after reading post detail",
            artifact_dir="/tmp/artifacts",
            raw_payload='{"partial":true}',
        )
        session.refresh(assignment)
        snapshot = session.exec(select(VideoAssignmentMetricSnapshot)).first()

    assert error is None
    assert result is not None
    assert assignment.metrics_status == MetricsStatus.NEEDS_REVIEW
    assert assignment.metrics_error == "Could not return to profile after reading post detail"
    assert assignment.latest_views == 150
    assert assignment.latest_likes == 22
    assert snapshot is not None
    assert snapshot.views == 150
    assert snapshot.likes == 22
    assert snapshot.error == "Could not return to profile after reading post detail"


def test_metrics_task_failure_does_not_corrupt_upload_status(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr("app.services.task_queue.engine", engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        device = Device(
            id=1,
            name="Device A",
            ip_address="192.168.1.10",
            adb_port=5555,
            status=DeviceStatus.ONLINE,
        )
        assignment = VideoAssignment(
            video_id=1,
            device_id=1,
            platform="tiktok",
            upload_status=UploadStatus.UPLOADED,
            metrics_status=MetricsStatus.SYNCING,
        )
        task = Task(
            device_id=1,
            command="Sync TikTok metrics",
            template="tiktok_metrics_sync",
            execution_mode="script",
            max_steps=30,
            max_retries=0,
        )
        task.template_vars = {"assignment_id": 1}
        session.add(device)
        session.add(assignment)
        session.commit()
        task.template_vars = {"assignment_id": assignment.id}
        session.add(task)
        session.commit()
        session.refresh(task)
        assignment_id = assignment.id
        task_id = task.id

    async def _fake_execute(**_kwargs):
        return TaskResult(
            success=False,
            reason="Could not navigate to profile",
            steps=2,
            error="Could not navigate to profile",
        )

    monkeypatch.setattr("app.services.task_queue.task_engine.execute", _fake_execute)

    queue = TaskQueue(max_concurrent=1)
    asyncio.run(queue._execute(task_id))

    with Session(engine) as session:
        refreshed_assignment = session.get(VideoAssignment, assignment_id)
        refreshed_task = session.get(Task, task_id)

    assert refreshed_assignment is not None
    assert refreshed_task is not None
    assert refreshed_assignment.upload_status == UploadStatus.UPLOADED
    assert refreshed_assignment.metrics_status == MetricsStatus.NEEDS_REVIEW
    assert refreshed_assignment.metrics_error == "Could not navigate to profile"
    assert refreshed_task.status == TaskStatus.FAILED


def test_metrics_runner_saves_review_state_on_early_navigation_failure(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        assignment = VideoAssignment(
            video_id=1,
            device_id=1,
            platform="tiktok",
            upload_status=UploadStatus.UPLOADED,
            metrics_status=MetricsStatus.SYNCING,
        )
        session.add(
            Device(
                id=1,
                name="Device A",
                ip_address="192.168.1.10",
                adb_port=5555,
                status=DeviceStatus.ONLINE,
            )
        )
        session.add(assignment)
        session.commit()
        session.refresh(assignment)

    runner = ScriptRunner()
    runner._device = "cloud:1"
    runner._step_num = 0
    runner._step_log = []
    runner._open_app = AsyncMock()
    runner._wait = AsyncMock()
    runner._step = AsyncMock()

    fake_tiktok = Mock()
    fake_tiktok.ensure_on_feed = AsyncMock(return_value=False)
    fake_tiktok.ensure_on_profile = AsyncMock(return_value=True)
    fake_tiktok.navigate_to_videos_tab = AsyncMock(return_value=True)
    fake_tiktok.read_profile_grid_metrics = AsyncMock(return_value=[])
    fake_tiktok.open_profile_video_at_position = AsyncMock(return_value=False)
    fake_tiktok.read_post_detail_metrics = AsyncMock(return_value={})
    fake_tiktok.navigate_back_from_post_detail = AsyncMock(return_value=True)
    fake_tiktok.capture_debug_snapshot = AsyncMock()
    runner._get_tiktok_controller = Mock(return_value=fake_tiktok)

    result = asyncio.run(runner._tiktok_metrics_sync(assignment_id=assignment.id))

    with Session(engine) as session:
        refreshed_assignment = session.get(VideoAssignment, assignment.id)
        snapshot = session.exec(select(VideoAssignmentMetricSnapshot)).first()

    assert result.success is False
    assert "Could not get to TikTok feed" in result.reason
    assert refreshed_assignment is not None
    assert refreshed_assignment.metrics_status == MetricsStatus.NEEDS_REVIEW
    assert refreshed_assignment.metrics_error == "Could not get to TikTok feed"
    assert snapshot is not None
    assert snapshot.error == "Could not get to TikTok feed"


def test_build_metrics_candidate_positions_prioritizes_hint_neighbors():
    runner = ScriptRunner()

    candidates = runner._build_metrics_candidate_positions(
        {"grid_position_hint": 2},
        [
            {"position": 0},
            {"position": 1},
            {"position": 2},
            {"position": 3},
        ],
        max_candidates=6,
    )

    assert candidates[:4] == [2, 3, 1, 4]
    assert 0 in candidates


def test_metrics_runner_matches_locator_across_candidate_positions(monkeypatch, tmp_path):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)
    SQLModel.metadata.create_all(engine)

    locator_builder = TikTokController(adb_agent=Mock())
    locator = locator_builder.build_post_locator(
        caption_text="Mix đồ đi biển cực cháy #VungTau #Outfit",
        account_name="@demo",
        grid_position_hint=0,
        upload_timestamp="2026-04-06T10:00:00+00:00",
    )

    with Session(engine) as session:
        assignment = VideoAssignment(
            video_id=1,
            device_id=1,
            platform="tiktok",
            upload_status=UploadStatus.UPLOADED,
            metrics_status=MetricsStatus.SYNCING,
            post_locator=json.dumps(locator),
        )
        session.add(
            Device(
                id=1,
                name="Device A",
                ip_address="192.168.1.10",
                adb_port=5555,
                status=DeviceStatus.ONLINE,
            )
        )
        session.add(assignment)
        session.commit()
        session.refresh(assignment)
        assignment_id = assignment.id

    runner = ScriptRunner()
    runner._device = "cloud:1"
    runner._step_num = 0
    runner._step_log = []
    runner._open_app = AsyncMock()
    runner._wait = AsyncMock()
    runner._step = AsyncMock()

    fake_tiktok = TikTokController(adb_agent=Mock())
    fake_tiktok.ensure_on_feed = AsyncMock(return_value=True)
    fake_tiktok.ensure_on_profile = AsyncMock(return_value=True)
    fake_tiktok.navigate_to_videos_tab = AsyncMock(return_value=True)
    fake_tiktok.read_profile_grid_metrics = AsyncMock(
        return_value=[
            {"position": 0, "views_text": "100", "views_int": 100, "bounds": (0, 720, 360, 1080)},
            {"position": 1, "views_text": "200", "views_int": 200, "bounds": (360, 720, 720, 1080)},
        ]
    )
    opened_positions: list[int] = []

    async def _open_candidate(_device: str, position: int = 0):
        opened_positions.append(position)
        return True

    fake_tiktok.open_profile_video_at_position = AsyncMock(side_effect=_open_candidate)
    fake_tiktok.read_post_detail_locator_signals = AsyncMock(
        side_effect=[
            {
                "author": "demo",
                "description": "cach nau pho bo tai nha #amthuc",
                "signature_texts": ["cach nau pho bo tai nha", "#amthuc"],
                "caption_preview": "cach nau pho bo tai nha #amthuc",
                "caption_tokens": ["cach", "nau", "pho", "#amthuc"],
                "caption_fingerprint": locator_builder.build_post_locator(
                    caption_text="cach nau pho bo tai nha #amthuc",
                    account_name="@demo",
                )["caption_fingerprint"],
            },
            {
                "author": "demo",
                "description": "mix do di bien cuc chay #vungtau #outfit",
                "signature_texts": ["mix do di bien cuc chay", "#vungtau #outfit"],
                "caption_preview": "mix do di bien cuc chay #vungtau #outfit",
                "caption_tokens": ["mix", "bien", "chay", "#vungtau", "#outfit"],
                "caption_fingerprint": locator["caption_fingerprint"],
            },
        ]
    )
    fake_tiktok.read_post_detail_metrics = AsyncMock(
        return_value={"views": 222, "likes": 33, "comments": 4, "shares": 5, "raw": {}}
    )
    fake_tiktok.navigate_back_from_post_detail = AsyncMock(return_value=True)
    fake_tiktok.capture_debug_snapshot = AsyncMock()
    runner._get_tiktok_controller = Mock(return_value=fake_tiktok)

    result = asyncio.run(runner._tiktok_metrics_sync(assignment_id=assignment_id))

    with Session(engine) as session:
        refreshed_assignment = session.get(VideoAssignment, assignment_id)
        snapshot = session.exec(select(VideoAssignmentMetricSnapshot)).first()

    assert result.success is True
    assert opened_positions == [0, 1]
    assert fake_tiktok.navigate_back_from_post_detail.await_count == 2
    assert refreshed_assignment is not None
    assert refreshed_assignment.metrics_status == MetricsStatus.SYNCED
    assert refreshed_assignment.latest_views == 222
    assert refreshed_assignment.latest_likes == 33
    assert snapshot is not None
    assert snapshot.views == 222
    assert json.loads(refreshed_assignment.post_locator)["grid_position_hint"] == 1
