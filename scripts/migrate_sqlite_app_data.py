#!/usr/bin/env python3
"""One-time NyankoFace application-data migration from SQLite to PostgreSQL."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import psycopg


METRICS_TABLES = ("agents", "repo_views", "browser_views", "repo_likes")


def rows(source: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    columns = [item[1] for item in source.execute(f'PRAGMA table_info("{table}")')]
    return columns, source.execute(f'SELECT * FROM "{table}"').fetchall()


def copy_table(source: sqlite3.Connection, target: psycopg.Connection, table: str) -> int:
    columns, values = rows(source, table)
    if not values:
        return 0
    names = ", ".join(f'"{name}"' for name in columns)
    placeholders = ", ".join("%s" for _ in columns)
    updates = ", ".join(
        f'"{name}" = EXCLUDED."{name}"' for name in columns if name not in {"id", "delivery_id"}
    )
    conflict = '"delivery_id"' if "delivery_id" in columns else '"id"' if "id" in columns else None
    if table == "repo_likes":
        conflict = '"agent_id", "owner", "repo"'
    query = f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})'
    if conflict:
        query += f" ON CONFLICT ({conflict}) DO UPDATE SET {updates}" if updates else f" ON CONFLICT ({conflict}) DO NOTHING"
    target.cursor().executemany(query, values)
    return len(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("metrics", "maintenance"), required=True)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--postgres", required=True)
    args = parser.parse_args()
    if not args.sqlite.is_file():
        raise SystemExit(f"SQLite source does not exist: {args.sqlite}")

    source = sqlite3.connect(f"file:{args.sqlite.as_posix()}?mode=ro&immutable=1", uri=True)
    target = psycopg.connect(args.postgres)
    try:
        tables = METRICS_TABLES if args.kind == "metrics" else ("jobs",)
        with target:
            for table in tables:
                count = copy_table(source, target, table)
                print(f"{table}: {count} rows")
            if args.kind == "metrics":
                for table in ("agents", "repo_views", "browser_views"):
                    target.execute(
                        "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM " + table + "), 1), true)",
                        (table,),
                    )
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    main()
