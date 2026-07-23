"""Small SQLite repository with no ORM-wide coupling."""

import hashlib
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from .models import DeviceCreate, DeviceStatus, DeviceView, TransportKind, utc_now


class Repository:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    address TEXT NOT NULL DEFAULT '',
                    token_hash TEXT UNIQUE,
                    status TEXT NOT NULL DEFAULT 'offline',
                    battery_level INTEGER,
                    last_seen TEXT,
                    helper_json TEXT NOT NULL DEFAULT '{}',
                    legacy_id INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admins (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    device_id INTEGER NOT NULL REFERENCES devices(id),
                    workflow TEXT NOT NULL,
                    status TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS media (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(devices)").fetchall()
            }
            if "legacy_id" not in columns:
                db.execute("ALTER TABLE devices ADD COLUMN legacy_id INTEGER")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_devices_legacy_id "
                "ON devices(legacy_id) WHERE legacy_id IS NOT NULL"
            )

    def ensure_admin(self, username: str, password_hash: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO admins (username, password_hash, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO NOTHING
                """,
                (username, password_hash, utc_now()),
            )

    def get_admin_password_hash(self, username: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT password_hash FROM admins WHERE username = ?", (username,)
            ).fetchone()
        return row["password_hash"] if row else None

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_device(self, data: DeviceCreate) -> tuple[DeviceView, str | None]:
        token = secrets.token_urlsafe(32) if data.transport == TransportKind.CLOUD else None
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO devices
                    (name, transport, address, token_hash, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data.name,
                    data.transport.value,
                    data.address,
                    self.hash_token(token) if token else None,
                    DeviceStatus.OFFLINE.value,
                    utc_now(),
                ),
            )
            device_id = int(cursor.lastrowid)
        return self.get_device(device_id), token

    def list_devices(self) -> list[DeviceView]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM devices ORDER BY name, id").fetchall()
        return [self._device(row) for row in rows]

    def get_device(self, device_id: int) -> DeviceView:
        with self.connect() as db:
            row = db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if row is None:
            raise KeyError(device_id)
        return self._device(row)

    def find_device_by_token(self, token: str) -> DeviceView | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM devices WHERE token_hash = ?",
                (self.hash_token(token),),
            ).fetchone()
        return self._device(row) if row else None

    def update_device_presence(
        self,
        device_id: int,
        *,
        status: DeviceStatus,
        battery_level: int | None = None,
        helper: dict[str, Any] | None = None,
    ) -> None:
        current = self.get_device(device_id)
        with self.connect() as db:
            db.execute(
                """
                UPDATE devices
                SET status = ?, battery_level = ?, last_seen = ?, helper_json = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    battery_level if battery_level is not None else current.battery_level,
                    utc_now(),
                    json.dumps(helper if helper is not None else current.helper),
                    device_id,
                ),
            )

    def set_status(self, device_id: int, status: DeviceStatus) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE devices SET status = ?, last_seen = ? WHERE id = ?",
                (status.value, utc_now(), device_id),
            )

    def insert_run(self, run: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO runs
                    (id, device_id, workflow, status, params_json, steps_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["id"],
                    run["device_id"],
                    run["workflow"],
                    run["status"],
                    json.dumps(run["params"]),
                    "[]",
                    run["created_at"],
                ),
            )

    def update_run(self, run: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE runs SET status = ?, steps_json = ?, started_at = ?,
                    finished_at = ?, error = ? WHERE id = ?
                """,
                (
                    run["status"],
                    json.dumps(run["steps"]),
                    run.get("started_at"),
                    run.get("finished_at"),
                    run.get("error"),
                    run["id"],
                ),
            )

    def list_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._run(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._run(row)

    def add_media(self, item: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO media
                    (id, filename, storage_path, size_bytes, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["filename"],
                    item["storage_path"],
                    item["size_bytes"],
                    item["sha256"],
                    item["created_at"],
                ),
            )

    def list_media(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM media ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def get_media(self, media_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        if row is None:
            raise KeyError(media_id)
        return dict(row)

    @staticmethod
    def _device(row: sqlite3.Row) -> DeviceView:
        return DeviceView(
            id=row["id"],
            name=row["name"],
            transport=row["transport"],
            address=row["address"],
            status=row["status"],
            battery_level=row["battery_level"],
            last_seen=row["last_seen"],
            helper=json.loads(row["helper_json"] or "{}"),
        )

    @staticmethod
    def _run(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "device_id": row["device_id"],
            "workflow": row["workflow"],
            "status": row["status"],
            "params": json.loads(row["params_json"]),
            "steps": json.loads(row["steps_json"]),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "error": row["error"],
        }
