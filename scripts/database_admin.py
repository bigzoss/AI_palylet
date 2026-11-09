"""Check, initialize, or migrate the project database without printing credentials."""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import settings
from backend.database import build_engine, public_database_info
from backend.db import Base, engine


def digest(rows):
    value = hashlib.sha256()
    for row in rows:
        value.update(
            json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        value.update(b"\n")
    return value.hexdigest()


def migrate_sqlite(source: Path, target, *, source_stopped=False):
    if not source_stopped:
        raise RuntimeError("Stop API and Worker first, then pass --source-stopped")
    if target.dialect.name != "mysql":
        raise RuntimeError("Migration target must be MySQL")
    source = source.resolve()
    if not source.is_file():
        raise RuntimeError("Source SQLite file does not exist")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as connection:
        active = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','cancel_requested')"
        ).fetchone()[0]
        if active:
            raise RuntimeError("Source contains active jobs; finish or cancel them before migrating")
        directory = settings.storage / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / (
            "studio_"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            + "_"
            + uuid4().hex[:6]
            + ".sqlite3"
        )
        with sqlite3.connect(backup) as snapshot:
            connection.backup(snapshot)
    source_engine = create_engine(URL.create("sqlite", database=str(backup)), hide_parameters=True)
    Base.metadata.create_all(target)
    report = {"source_backup": str(backup), "target": public_database_info(target), "tables": {}}
    try:
        with source_engine.connect() as read, target.begin() as write:
            if any(
                write.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables
            ):
                raise RuntimeError("Target tables must be empty; existing data will not be overwritten")
            for table in Base.metadata.sorted_tables:
                query = select(table).order_by(*table.primary_key.columns)
                rows = read.execute(query).mappings().all()
                for offset in range(0, len(rows), 100):
                    write.execute(table.insert(), [dict(row) for row in rows[offset : offset + 100]])
                copied = write.execute(query).mappings().all()
                src_digest, target_digest = digest(rows), digest(copied)
                if len(rows) != len(copied) or src_digest != target_digest:
                    raise RuntimeError("Migration verification failed; target transaction rolled back")
                report["tables"][table.name] = {"rows": len(rows), "sha256": target_digest, "verified": True}
    finally:
        source_engine.dispose()
    output = settings.storage / "backups" / "mysql_migration_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "init", "migrate"])
    parser.add_argument(
        "--local-mysql", action="store_true", help="Target the private local MySQL before activation"
    )
    parser.add_argument("--source", type=Path, default=settings.storage / "studio.db")
    parser.add_argument("--source-stopped", action="store_true")
    args = parser.parse_args()
    target = engine
    if args.local_mysql:
        from mysql_local import app_url

        target = build_engine(app_url())
    if args.action == "migrate":
        result = migrate_sqlite(args.source, target, source_stopped=args.source_stopped)
    else:
        if args.action == "init":
            Base.metadata.create_all(target)
        with target.connect() as connection:
            connection.execute(text("SELECT 1"))
            result = {"status": "ok", **public_database_info(target)}
            if target.dialect.name == "mysql":
                result["server_version"] = connection.scalar(text("SELECT VERSION()"))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            print(str(exc), file=sys.stderr)
        else:
            print(
                f"Database operation failed: {type(exc).__name__}; connection credentials omitted",
                file=sys.stderr,
            )
        raise SystemExit(1)
