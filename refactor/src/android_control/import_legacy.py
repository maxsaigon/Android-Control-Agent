"""Selective, idempotent legacy device importer."""

import argparse
import json
import sqlite3
from pathlib import Path

from .config import Settings
from .database import Repository
from .models import utc_now


def import_devices(source: Path, target: Path, *, apply: bool = False) -> dict:
    repository = Repository(target)
    repository.initialize()
    source_db = sqlite3.connect(source)
    source_db.row_factory = sqlite3.Row
    rows = source_db.execute(
        "SELECT id, name, ip_address, adb_port, status FROM device ORDER BY id"
    ).fetchall()
    source_db.close()

    created = []
    updated = []
    skipped = []
    with repository.connect() as target_db:
        known = {
            row["legacy_id"]: row
            for row in target_db.execute(
                "SELECT legacy_id, name, transport, address "
                "FROM devices WHERE legacy_id IS NOT NULL"
            ).fetchall()
        }
        for row in rows:
            legacy_address = (row["ip_address"] or "").strip()
            cloud = legacy_address == "cloud" or legacy_address.startswith("cloud:")
            transport = "cloud" if cloud else "adb"
            address = "" if cloud else legacy_address
            if address and ":" not in address:
                address = f"{address}:{row['adb_port']}"
            item = {
                "legacy_id": row["id"],
                "name": row["name"],
                "transport": transport,
                "address": address or "",
                "source_status": row["status"],
            }
            if row["id"] in known:
                current = known[row["id"]]
                changed = any(
                    current[field] != item[field]
                    for field in ("name", "transport", "address")
                )
                (updated if changed else skipped).append(item)
                if apply and changed:
                    target_db.execute(
                        """
                        UPDATE devices SET name = ?, transport = ?, address = ?
                        WHERE legacy_id = ?
                        """,
                        (item["name"], item["transport"], item["address"], row["id"]),
                    )
                continue
            created.append(item)
            if apply:
                target_db.execute(
                    """
                    INSERT INTO devices
                        (name, transport, address, status, legacy_id, created_at)
                    VALUES (?, ?, ?, 'offline', ?, ?)
                    """,
                    (row["name"], transport, address or "", row["id"], utc_now()),
                )

    return {
        "mode": "apply" if apply else "dry-run",
        "source_count": len(rows),
        "would_create" if not apply else "created": created,
        "would_update" if not apply else "updated": updated,
        "skipped_existing": skipped,
        "tokens_imported": 0,
        "history_imported": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    report = import_devices(
        args.source,
        args.target or settings.database_path,
        apply=args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
