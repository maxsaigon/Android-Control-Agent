"""Database engine and session management."""

import logging
from pathlib import Path

import sqlalchemy
from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

logger = logging.getLogger(__name__)

# Create engine
engine = create_engine(settings.database_url, echo=False)


def _table_exists(conn: sqlalchemy.engine.Connection, table: str) -> bool:
    row = conn.execute(
        sqlalchemy.text(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table"
        ),
        {"table": table},
    ).first()
    return row is not None


def _table_columns(
    conn: sqlalchemy.engine.Connection,
    table: str,
) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {
        row[1]  # index 1 = column name in PRAGMA table_info
        for row in conn.execute(sqlalchemy.text(f"PRAGMA table_info('{table}')"))
    }


def _add_column_if_missing(
    conn: sqlalchemy.engine.Connection,
    table: str,
    column: str,
    column_def: str,
) -> None:
    existing_cols = _table_columns(conn, table)
    if column in existing_cols:
        return
    try:
        conn.execute(
            sqlalchemy.text(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
        )
        conn.commit()
        logger.info("migrate_db: added column %s.%s", table, column)
    except Exception as exc:  # pragma: no cover
        logger.warning("migrate_db: could not add %s.%s: %s", table, column, exc)


def _normalize_enum_column(
    conn: sqlalchemy.engine.Connection,
    table: str,
    column: str,
    mapping: dict[str, str],
) -> None:
    if column not in _table_columns(conn, table):
        return
    for old_value, new_value in mapping.items():
        try:
            conn.execute(
                sqlalchemy.text(
                    f"UPDATE {table} SET {column} = :new_value "
                    f"WHERE {column} = :old_value"
                ),
                {"new_value": new_value, "old_value": old_value},
            )
            conn.commit()
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "migrate_db: could not normalize %s.%s (%s -> %s): %s",
                table,
                column,
                old_value,
                new_value,
                exc,
            )


def _backfill_nulls(
    conn: sqlalchemy.engine.Connection,
    table: str,
    column: str,
    sql_value: str,
) -> None:
    if column not in _table_columns(conn, table):
        return
    try:
        conn.execute(
            sqlalchemy.text(
                f"UPDATE {table} SET {column} = {sql_value} WHERE {column} IS NULL"
            )
        )
        conn.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "migrate_db: could not backfill %s.%s with %s: %s",
            table,
            column,
            sql_value,
            exc,
        )


def _index_definitions(
    conn: sqlalchemy.engine.Connection,
    table: str,
) -> list[tuple[str, bool, tuple[str, ...]]]:
    if not _table_exists(conn, table):
        return []
    result: list[tuple[str, bool, tuple[str, ...]]] = []
    for row in conn.execute(sqlalchemy.text(f"PRAGMA index_list('{table}')")):
        idx_name = row[1]
        is_unique = bool(row[2])
        idx_cols = tuple(
            col_row[2]
            for col_row in conn.execute(
                sqlalchemy.text(f"PRAGMA index_info('{idx_name}')")
            )
        )
        result.append((idx_name, is_unique, idx_cols))
    return result


def _column_copy_expr(
    existing_columns: set[str],
    column: str,
    *,
    default_sql: str = "NULL",
) -> str:
    if column in existing_columns:
        return f"COALESCE({column}, {default_sql}) AS {column}"
    return f"{default_sql} AS {column}"


def _legacy_videoassignment_indexes(
    conn: sqlalchemy.engine.Connection,
) -> list[tuple[str, tuple[str, ...]]]:
    legacy_signatures = {
        ("device_id", "platform"),
        ("video_id", "platform"),
    }
    return [
        (name, cols)
        for name, is_unique, cols in _index_definitions(conn, "videoassignment")
        if is_unique and cols in legacy_signatures
    ]


def _rebuild_videoassignment_table(conn: sqlalchemy.engine.Connection) -> None:
    if not _table_exists(conn, "videoassignment"):
        return

    existing_columns = _table_columns(conn, "videoassignment")
    backup_table = "videoassignment__backup_pre_rebuild"

    logger.warning(
        "migrate_db: rebuilding legacy videoassignment table to preserve data "
        "and replace outdated unique constraints"
    )

    conn.execute(sqlalchemy.text(f"DROP TABLE IF EXISTS {backup_table}"))
    conn.execute(
        sqlalchemy.text(
            """
            CREATE TABLE videoassignment__new (
                id INTEGER PRIMARY KEY,
                video_id INTEGER NOT NULL,
                device_id INTEGER NOT NULL,
                platform VARCHAR NOT NULL,
                push_status VARCHAR DEFAULT 'PENDING',
                upload_status VARCHAR DEFAULT 'PENDING',
                device_path TEXT,
                pushed_at DATETIME,
                uploaded_at DATETIME,
                task_id INTEGER,
                error TEXT,
                last_error TEXT,
                last_run_at DATETIME,
                created_at DATETIME
            )
            """
        )
    )
    conn.execute(
        sqlalchemy.text(
            """
            INSERT OR IGNORE INTO videoassignment__new (
                id,
                video_id,
                device_id,
                platform,
                push_status,
                upload_status,
                device_path,
                pushed_at,
                uploaded_at,
                task_id,
                error,
                last_error,
                last_run_at,
                created_at
            )
            SELECT
                id,
                video_id,
                device_id,
                platform,
                """
            + _column_copy_expr(existing_columns, "push_status", default_sql="'PENDING'")
            + """,
                """
            + _column_copy_expr(existing_columns, "upload_status", default_sql="'PENDING'")
            + """,
                """
            + _column_copy_expr(existing_columns, "device_path")
            + """,
                """
            + _column_copy_expr(existing_columns, "pushed_at")
            + """,
                """
            + _column_copy_expr(existing_columns, "uploaded_at")
            + """,
                """
            + _column_copy_expr(existing_columns, "task_id")
            + """,
                """
            + _column_copy_expr(existing_columns, "error")
            + """,
                """
            + _column_copy_expr(existing_columns, "last_error")
            + """,
                """
            + _column_copy_expr(existing_columns, "last_run_at")
            + """,
                """
            + _column_copy_expr(existing_columns, "created_at", default_sql="CURRENT_TIMESTAMP")
            + """
            FROM videoassignment
            ORDER BY id DESC
            """
        )
    )
    conn.execute(sqlalchemy.text("ALTER TABLE videoassignment RENAME TO videoassignment__backup_pre_rebuild"))
    conn.execute(sqlalchemy.text("ALTER TABLE videoassignment__new RENAME TO videoassignment"))
    conn.execute(
        sqlalchemy.text("DROP INDEX IF EXISTS uq_videoassignment_video_device_platform")
    )
    conn.execute(
        sqlalchemy.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_videoassignment_video_device_platform
            ON videoassignment (video_id, device_id, platform)
            """
        )
    )
    conn.commit()
    logger.info(
        "migrate_db: rebuilt videoassignment table; legacy copy kept in %s",
        backup_table,
    )


def _repair_video_storage_paths(conn: sqlalchemy.engine.Connection) -> None:
    """Repair stale absolute video/thumbnail paths after runtime-dir changes.

    Older deploys stored absolute paths under `/tmp/android-control/...`. If the
    same file still exists in the current persistent storage, rewrite the DB row
    to the current path so thumbnails/videos survive future restarts.
    """
    if "video" not in {
        row[0]
        for row in conn.execute(
            sqlalchemy.text("SELECT name FROM sqlite_master WHERE type = 'table'")
        )
    }:
        return

    video_dir = Path(settings.video_storage_dir)
    thumb_dir = video_dir / "thumbnails"
    updated = 0

    rows = conn.execute(
        sqlalchemy.text("SELECT id, filepath, thumbnail FROM video")
    ).fetchall()
    for row in rows:
        video_id = row[0]
        filepath = row[1]
        thumbnail = row[2]
        values: dict[str, str] = {}

        if filepath:
            current = Path(filepath)
            candidate = video_dir / current.name
            if not current.exists() and candidate.exists():
                values["filepath"] = str(candidate)

        if thumbnail:
            current = Path(thumbnail)
            candidate = thumb_dir / current.name
            if not current.exists() and candidate.exists():
                values["thumbnail"] = str(candidate)

        if not values:
            continue

        set_clause = ", ".join(f"{col} = :{col}" for col in values)
        conn.execute(
            sqlalchemy.text(f"UPDATE video SET {set_clause} WHERE id = :video_id"),
            {**values, "video_id": video_id},
        )
        updated += 1

    if updated:
        conn.commit()
        logger.info("migrate_db: repaired storage paths for %s video row(s)", updated)


def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)


def migrate_db():
    """Apply additive schema migrations for columns added after initial deployment.

    SQLite does not support IF NOT EXISTS on ALTER TABLE ADD COLUMN.
    We inspect PRAGMA table_info() first and only add truly missing columns.

    This is intentionally limited to ADD COLUMN operations.
    Destructive changes (DROP / RENAME / type change) require manual handling.
    """
    _migrations = [
        # (table_name, column_name, sqlite_type_def)
        ("task", "template_vars_json", "TEXT"),
        ("task", "assignment_id", "INTEGER"),
        ("video", "description", "TEXT"),
        ("video", "file_cleaned_at", "DATETIME"),
        ("video", "ai_title", "TEXT"),
        ("video", "ai_tags", "TEXT"),
        ("video", "ai_description", "TEXT"),
        ("video", "ai_generated_at", "DATETIME"),
        ("video", "thumbnail", "TEXT"),
        ("video", "created_at", "DATETIME"),
        ("videoassignment", "device_path", "TEXT"),
        ("videoassignment", "pushed_at", "DATETIME"),
        ("videoassignment", "uploaded_at", "DATETIME"),
        ("videoassignment", "task_id", "INTEGER"),
        ("videoassignment", "error", "TEXT"),
        ("videoassignment", "upload_status", "VARCHAR DEFAULT 'pending'"),
        ("videoassignment", "last_error", "TEXT"),
        ("videoassignment", "last_run_at", "DATETIME"),
        ("videoassignment", "push_status", "VARCHAR DEFAULT 'pending'"),
        ("videoassignment", "created_at", "DATETIME"),
        ("deviceaccount", "account_name", "TEXT"),
        ("deviceaccount", "notes", "TEXT"),
        ("deviceaccount", "created_at", "DATETIME"),
    ]

    with engine.connect() as conn:
        for table, col, col_def in _migrations:
            _add_column_if_missing(conn, table, col, col_def)

        # Normalize legacy enum values written as lowercase strings.
        # SQLAlchemy Enum stores member names (e.g., PENDING), while some old rows
        # may contain member values (e.g., pending), causing lookup errors.
        enum_normalizers = [
            (
                "video",
                "status",
                {
                    "available": "AVAILABLE",
                    "archived": "ARCHIVED",
                },
            ),
            (
                "videoassignment",
                "upload_status",
                {
                    "pending": "PENDING",
                    "queued": "QUEUED",
                    "running": "RUNNING",
                    "uploaded": "UPLOADED",
                    "upload_failed": "UPLOAD_FAILED",
                    "verify_failed": "VERIFY_FAILED",
                },
            ),
            (
                "videoassignment",
                "push_status",
                {
                    "pending": "PENDING",
                    "pushed": "PUSHED",
                    "push_failed": "PUSH_FAILED",
                    "uploaded": "UPLOADED",
                    "failed": "FAILED",
                },
            ),
        ]
        for table, column, mapping in enum_normalizers:
            _normalize_enum_column(conn, table, column, mapping)

        # Backfill critical nulls so ORM reads do not fail on legacy rows.
        _backfill_nulls(conn, "video", "status", "'AVAILABLE'")
        _backfill_nulls(conn, "video", "created_at", "CURRENT_TIMESTAMP")
        _backfill_nulls(conn, "videoassignment", "push_status", "'PENDING'")
        _backfill_nulls(conn, "videoassignment", "upload_status", "'PENDING'")
        _backfill_nulls(conn, "videoassignment", "created_at", "CURRENT_TIMESTAMP")
        _backfill_nulls(conn, "deviceaccount", "created_at", "CURRENT_TIMESTAMP")

        # Recover stale assignment statuses left behind by restarted/failed workers.
        # Example: assignment upload_status still RUNNING while linked task is CANCELLED.
        try:
            conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE videoassignment
                    SET
                        upload_status = 'UPLOAD_FAILED',
                        last_error = COALESCE(
                            (SELECT t.error FROM task t WHERE t.id = videoassignment.task_id),
                            last_error,
                            'Recovered stale upload status'
                        )
                    WHERE
                        upload_status IN ('RUNNING', 'QUEUED')
                        AND task_id IS NOT NULL
                        AND EXISTS (
                            SELECT 1
                            FROM task t
                            WHERE t.id = videoassignment.task_id
                              AND t.status IN ('FAILED', 'CANCELLED')
                        )
                    """
                )
            )
            conn.commit()
        except Exception as exc:  # pragma: no cover
            logger.warning("migrate_db: stale-status recovery warning: %s", exc)

        # Ensure DB-level uniqueness for legacy databases created before constraints.
        required_unique_indexes = [
            (
                "videoassignment",
                "uq_videoassignment_video_device_platform",
                ("video_id", "device_id", "platform"),
            ),
            (
                "deviceaccount",
                "uq_deviceaccount_device_platform",
                ("device_id", "platform"),
            ),
        ]

        for table, index_name, columns in required_unique_indexes:
            index_rows = list(
                conn.execute(sqlalchemy.text(f"PRAGMA index_list('{table}')"))
            )
            existing_by_name = {row[1] for row in index_rows}
            has_equivalent_unique = False
            for row in index_rows:
                idx_name = row[1]
                is_unique = bool(row[2])
                if not is_unique:
                    continue
                idx_cols = tuple(
                    col_row[2]
                    for col_row in conn.execute(
                        sqlalchemy.text(f"PRAGMA index_info('{idx_name}')")
                    )
                )
                if idx_cols == columns:
                    has_equivalent_unique = True
                    break

            if index_name in existing_by_name or has_equivalent_unique:
                continue
            cols_sql = ", ".join(columns)
            try:
                conn.execute(
                    sqlalchemy.text(
                        f"CREATE UNIQUE INDEX {index_name} ON {table} ({cols_sql})"
                    )
                )
                conn.commit()
                logger.info("migrate_db: created unique index %s on %s", index_name, table)
            except Exception as exc:  # pragma: no cover
                    logger.warning(
                        "migrate_db: could not create unique index %s on %s: %s",
                        index_name,
                        table,
                        exc,
                    )

        # Replace legacy uniqueness on VideoAssignment via table rebuild so
        # old deploys keep their data while enabling per-device distribution.
        legacy_indexes = _legacy_videoassignment_indexes(conn)
        if legacy_indexes:
            try:
                _rebuild_videoassignment_table(conn)
            except Exception as exc:  # pragma: no cover
                logger.warning("migrate_db: videoassignment rebuild warning: %s", exc)

        try:
            _repair_video_storage_paths(conn)
        except Exception as exc:  # pragma: no cover
            logger.warning("migrate_db: video storage path repair warning: %s", exc)


def get_session():
    """Dependency: yields a database session."""
    with Session(engine) as session:
        yield session
