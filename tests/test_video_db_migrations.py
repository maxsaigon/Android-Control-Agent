import sqlalchemy
from sqlmodel import Session, SQLModel, create_engine, select

from app import database
from app.models import Device, DeviceAccount, DeviceStatus, VideoAssignment
from app.services.video_service import video_service


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
