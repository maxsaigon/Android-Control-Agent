"""Database engine and session management."""

import logging

import sqlalchemy
from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

logger = logging.getLogger(__name__)

# Create engine
engine = create_engine(settings.database_url, echo=False)


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
        ("videoassignment", "upload_status", "VARCHAR DEFAULT 'pending'"),
        ("videoassignment", "last_error", "TEXT"),
        ("videoassignment", "last_run_at", "DATETIME"),
        ("videoassignment", "push_status", "VARCHAR DEFAULT 'pending'"),
    ]

    with engine.connect() as conn:
        for table, col, col_def in _migrations:
            existing_cols = {
                row[1]  # index 1 = column name in PRAGMA table_info
                for row in conn.execute(
                    sqlalchemy.text(f"PRAGMA table_info('{table}')")
                )
            }
            if col not in existing_cols:
                try:
                    conn.execute(
                        sqlalchemy.text(
                            f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"
                        )
                    )
                    conn.commit()
                    logger.info("migrate_db: added column %s.%s", table, col)
                except Exception as exc:  # pragma: no cover
                    logger.warning(
                        "migrate_db: could not add %s.%s: %s", table, col, exc
                    )

        # Normalize legacy enum values written as lowercase strings.
        # SQLAlchemy Enum stores member names (e.g., PENDING), while some old rows
        # may contain member values (e.g., pending), causing lookup errors.
        enum_normalizers = [
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

        # Cleanup accidental unique index on (device_id, platform) for VideoAssignment.
        # This index incorrectly limits each device+platform to a single assignment.
        try:
            for row in conn.execute(sqlalchemy.text("PRAGMA index_list('videoassignment')")):
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
                if idx_cols != ("device_id", "platform"):
                    continue
                if idx_name.startswith("sqlite_autoindex"):
                    logger.warning(
                        "migrate_db: detected auto unique index %s on videoassignment(device_id, platform). "
                        "SQLite cannot drop auto indexes directly; table rebuild is required.",
                        idx_name,
                    )
                    continue
                conn.execute(sqlalchemy.text(f"DROP INDEX IF EXISTS {idx_name}"))
                conn.commit()
                logger.info("migrate_db: dropped incorrect unique index %s", idx_name)
        except Exception as exc:  # pragma: no cover
            logger.warning("migrate_db: index cleanup warning: %s", exc)

        # Replace legacy uniqueness on (video_id, platform) with (video_id, device_id, platform).
        try:
            for row in conn.execute(sqlalchemy.text("PRAGMA index_list('videoassignment')")):
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
                if idx_cols != ("video_id", "platform"):
                    continue
                if idx_name.startswith("sqlite_autoindex"):
                    logger.warning(
                        "migrate_db: detected auto unique index %s on videoassignment(video_id, platform). "
                        "SQLite cannot drop auto indexes directly; table rebuild would be required if this env still uses the old table definition.",
                        idx_name,
                    )
                    continue
                conn.execute(sqlalchemy.text(f"DROP INDEX IF EXISTS {idx_name}"))
                conn.commit()
                logger.info("migrate_db: dropped legacy unique index %s", idx_name)
        except Exception as exc:  # pragma: no cover
            logger.warning("migrate_db: legacy video/platform index cleanup warning: %s", exc)


def get_session():
    """Dependency: yields a database session."""
    with Session(engine) as session:
        yield session
