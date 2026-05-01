"""
migrate_runners.py
──────────────────
Adds the new stat columns to the runners table in an existing leaderboard.db
and populates them without needing to re-import the full CSV.

Usage:
    python migrate_runners.py                  # uses data/leaderboard.db
    python migrate_runners.py path/to/file.db  # explicit path
"""

import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/leaderboard.db"

NEW_COLUMNS = [
    ("pb_ms",            "INTEGER"),
    ("pb_raw",           "TEXT"),
    ("lb_position",      "INTEGER"),
    ("best_lb_position", "INTEGER"),
    ("sub10",            "INTEGER NOT NULL DEFAULT 0"),
    ("sub9",             "INTEGER NOT NULL DEFAULT 0"),
    ("sub8",             "INTEGER NOT NULL DEFAULT 0"),
    ("sub7",             "INTEGER NOT NULL DEFAULT 0"),
    ("days_top10",       "INTEGER NOT NULL DEFAULT 0"),
]


def add_columns(conn: sqlite3.Connection) -> None:
    """Add any missing columns to runners; skip ones that already exist."""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(runners)").fetchall()
    }
    for col_name, col_def in NEW_COLUMNS:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE runners ADD COLUMN {col_name} {col_def}"
            )
            print(f"  Added column: runners.{col_name}")
        else:
            print(f"  Column already exists, skipping: runners.{col_name}")
    conn.commit()


def populate(conn: sqlite3.Connection) -> None:
    """Compute and write all stat columns."""

    # ── 1. Simple aggregates ──────────────────────────────────────────────────
    conn.execute("""
        UPDATE runners SET
            pb_ms = (
                SELECT MIN(re_timed_time_ms)
                FROM runs
                WHERE runner_id = runners.id
                  AND re_timed_time_ms IS NOT NULL
            ),
            pb_raw = (
                SELECT re_timed_time_raw
                FROM runs
                WHERE runner_id = runners.id
                  AND re_timed_time_ms IS NOT NULL
                ORDER BY re_timed_time_ms ASC
                LIMIT 1
            ),
            lb_position = (
                SELECT lb_position
                FROM leaderboard
                WHERE runner = runners.name
            ),
            sub10 = (
                SELECT COUNT(*)
                FROM runs
                WHERE runner_id = runners.id
                  AND re_timed_time_ms IS NOT NULL
                  AND re_timed_time_ms < 600000
            ),
            sub9 = (
                SELECT COUNT(*)
                FROM runs
                WHERE runner_id = runners.id
                  AND re_timed_time_ms IS NOT NULL
                  AND re_timed_time_ms < 540000
            ),
            sub8 = (
                SELECT COUNT(*)
                FROM runs
                WHERE runner_id = runners.id
                  AND re_timed_time_ms IS NOT NULL
                  AND re_timed_time_ms < 480000
            ),
            sub7 = (
                SELECT COUNT(*)
                FROM runs
                WHERE runner_id = runners.id
                  AND re_timed_time_ms IS NOT NULL
                  AND re_timed_time_ms < 420000
            )
    """)

    # ── 2. Historical replay ──────────────────────────────────────────────────
    pbs = conn.execute("""
        SELECT runner_id, re_timed_time_ms, date
        FROM runs
        WHERE is_pb = 1
          AND re_timed_time_ms IS NOT NULL
          AND date IS NOT NULL
        ORDER BY date ASC, re_timed_time_ms ASC
    """).fetchall()

    current_bests: dict[int, int] = {}
    best_ranks:    dict[int, int] = {}
    date_snapshots: dict[str, dict[int, int]] = {}

    for runner_id, ms, date in pbs:
        if runner_id not in current_bests or ms < current_bests[runner_id]:
            current_bests[runner_id] = ms

        date_snapshots[date] = dict(current_bests)

        sorted_runners = sorted(current_bests.items(), key=lambda x: x[1])
        for rank, (rid, _) in enumerate(sorted_runners, 1):
            if rid not in best_ranks or rank < best_ranks[rid]:
                best_ranks[rid] = rank

    # ── 3. days_top10 ────────────────────────────────────────────────────────
    days_top10: dict[int, int] = defaultdict(int)
    today = datetime.now().date()
    sorted_dates = sorted(date_snapshots.keys())

    for i, date in enumerate(sorted_dates):
        snapshot = date_snapshots[date]
        top10_ids = {rid for rid, _ in sorted(snapshot.items(), key=lambda x: x[1])[:10]}

        d1 = datetime.strptime(date, "%Y-%m-%d").date()
        d2 = (
            datetime.strptime(sorted_dates[i + 1], "%Y-%m-%d").date()
            if i + 1 < len(sorted_dates)
            else today
        )
        days = (d2 - d1).days
        for rid in top10_ids:
            days_top10[rid] += days

    # ── 4. Write back ─────────────────────────────────────────────────────────
    for (rid,) in conn.execute("SELECT id FROM runners").fetchall():
        conn.execute(
            "UPDATE runners SET best_lb_position = ?, days_top10 = ? WHERE id = ?",
            (best_ranks.get(rid), days_top10.get(rid, 0), rid),
        )

    conn.commit()


def preview(conn: sqlite3.Connection, n: int = 10) -> None:
    print(f"\n{'='*90}")
    print(f"  RUNNERS TABLE — top {n} by current leaderboard position")
    print(f"{'='*90}")
    header = f"  {'Name':<20} {'LB':>4} {'Best':>7} {'PB':<12} {'Sub10':>6} {'Sub9':>5} {'Sub8':>5} {'Sub7':>5} {'Days in top 10':>6}"
    print(header)
    print(f"  {'-'*86}")
    rows = conn.execute("""
        SELECT name, lb_position, best_lb_position, pb_raw,
               sub10, sub9, sub8, sub7, days_top10
        FROM runners
        WHERE lb_position IS NOT NULL
        ORDER BY lb_position ASC
        LIMIT ?
    """, (n,)).fetchall()
    for r in rows:
        name, lb, best_lb, pb_raw, s10, s9, s8, s7, days = r
        print(
            f"  {(name or ''):<20} {str(lb or ''):>4} {str(best_lb or ''):>7}"
            f" {(pb_raw or 'N/A'):<12} {s10:>6} {s9:>5} {s8:>5} {s7:>5} {days:>6}"
        )
    print(f"{'='*90}\n")


def main() -> None:
    print(f"Migrating: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    print("\n── Step 1: Add missing columns ──────────────────────────────────────")
    add_columns(conn)

    print("\n── Step 2: Populate stat columns ────────────────────────────────────")
    populate(conn)
    print("  Done.")

    print("\n── Step 3: Preview ──────────────────────────────────────────────────")
    preview(conn)

    conn.close()


if __name__ == "__main__":
    main()