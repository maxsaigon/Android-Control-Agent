import sqlalchemy
from sqlmodel import create_engine

from app import database
from app.services.device_identity import cloud_display_name


def test_cloud_display_name_is_idempotent():
    assert cloud_display_name("Pixel", 7) == "Pixel #7"
    assert cloud_display_name("Pixel #7", 7) == "Pixel #7"


def test_migrate_db_adds_stable_device_identity(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/legacy_devices.db")
    monkeypatch.setattr(database, "engine", engine)

    with engine.connect() as conn:
        conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE device (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    ip_address VARCHAR NOT NULL,
                    adb_port INTEGER NOT NULL
                )
                """
            )
        )
        conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE devicelinkrequest (
                    id INTEGER PRIMARY KEY,
                    request_id VARCHAR NOT NULL
                )
                """
            )
        )
        conn.commit()

    database.migrate_db()

    with engine.connect() as conn:
        device_columns = {
            row[1]
            for row in conn.execute(sqlalchemy.text("PRAGMA table_info('device')"))
        }
        request_columns = {
            row[1]
            for row in conn.execute(
                sqlalchemy.text("PRAGMA table_info('devicelinkrequest')")
            )
        }
        unique_indexes = [
            row[1]
            for row in conn.execute(sqlalchemy.text("PRAGMA index_list('device')"))
            if bool(row[2])
        ]

    assert "installation_id" in device_columns
    assert "installation_id" in request_columns
    assert "ix_device_installation_id" in unique_indexes
