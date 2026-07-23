import sqlite3

from android_control.import_legacy import import_devices


def test_import_is_dry_run_by_default_and_idempotent(tmp_path):
    source = tmp_path / "legacy.db"
    target = tmp_path / "target.db"
    with sqlite3.connect(source) as database:
        database.execute(
            "CREATE TABLE device "
            "(id INTEGER, name TEXT, ip_address TEXT, adb_port INTEGER, status TEXT)"
        )
        database.execute(
            "INSERT INTO device VALUES (7, 'Pixel Lab', '192.168.1.8', 5555, 'online')"
        )

    dry_run = import_devices(source, target)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["would_create"][0]["address"] == "192.168.1.8:5555"

    applied = import_devices(source, target, apply=True)
    repeated = import_devices(source, target, apply=True)
    assert len(applied["created"]) == 1
    assert repeated["created"] == []
    assert repeated["skipped_existing"][0]["legacy_id"] == 7

    with sqlite3.connect(target) as database:
        row = database.execute(
            "SELECT legacy_id, status, token_hash FROM devices"
        ).fetchone()
    assert row == (7, "offline", None)
