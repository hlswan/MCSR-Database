"""
couriway_main.py — Import Couriway 100K tracker CSV into couriway_runs.db

Usage:
  python couriway_main.py              # one-off import from local CSV
  python couriway_main.py --download   # download sheet then import
  python couriway_main.py --schedule   # download + import now, then repeat daily at midnight Pacific
"""

import csv
import io
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────

CSV_PATH  = os.path.join("data", "100KTracker8920.csv")
DB_PATH   = os.path.join("data", "couriway_runs.db")

# Google Sheets — raw data tab (gid=1760430564)
SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1Tyw9fwdZgsHJoHzlE-0LPSEDOduRkZwL2UUNA-_4Xo4"
    "/export?format=csv&gid=1760430564"
)

# Midnight Pacific = UTC-7 (PDT) or UTC-8 (PST)
# Fixed at UTC-7; close enough for a daily job.
PACIFIC = timezone(timedelta(hours=-7))


# ── Column indices ────────────────────────────────────────────────────────────

COL = {
    "date":                  0,
    "iron_source":           1,
    "enter_type":            2,
    "gold_source":           3,
    "spawn_biome":           4,
    "rta":                   5,
    "time_wood":             6,
    "time_iron_pick":        7,
    "time_nether":           8,
    "time_bastion":          9,
    "time_fortress":         10,
    "time_first_portal":     11,
    "time_second_portal":    12,
    "time_stronghold":       13,
    "time_end":              14,
    "igt":                   15,
    "gold_dropped":          16,
    "blaze_rods":            17,
    "blazes_killed":         18,
    "flint_picked_up":       19,
    "gravel_mined":          20,
    "deaths_total":          21,
    "jumps":                 22,
    "eyes_used":             23,
    "diamond_picks_crafted": 24,
    "ender_pearls_used":     25,
    "obsidian_placed":       26,
    "diamond_sword_crafted": 27,
    "stone_mined":           28,
    "netherrack_mined":      29,
    # 30–46: trade_* — excluded (broken data)
    "killed_blaze":          47,
    "killed_chicken":        48,
    "killed_cod":            49,
    "killed_cow":            50,
    "killed_creeper":        51,
    "killed_enderman":       52,
    "killed_endermite":      53,
    "killed_ghast":          54,
    "killed_hoglin":         55,
    "killed_iron_golem":     56,
    "killed_pig":            57,
    "killed_piglin":         58,
    "killed_salmon":         59,
    "killed_sheep":          60,
    "killed_skeleton":       61,
    "killed_spider":         62,
    "killed_witch":          63,
    "killed_wither_skeleton":64,
    "killed_zombie":         65,
    "eaten_bread":           66,
    "eaten_cooked_beef":     67,
    "eaten_cooked_chicken":  68,
    "eaten_cooked_cod":      69,
    "eaten_cooked_mutton":   70,
    "eaten_cooked_porkchop": 71,
    "eaten_cooked_salmon":   72,
    "eaten_ega":             73,
    "eaten_golden_apple":    74,
    "eaten_apple":           75,
    "eaten_rotten_flesh":    76,
    "eaten_golden_carrot":   77,
    "eaten_mushroom_stew":   78,
    "travel_walk_on_water":  79,
    "travel_walk":           80,
    "travel_walk_under_water":81,
    "travel_swim":           82,
    "travel_boat":           83,
    "travel_sprint":         84,
    "seed":                  85,
    # 86: igt_2 — duplicate
    # 87: date_played_est_2 — duplicate
    "bastion_type":          88,
    "end_fight_type":        89,
    "real_deaths":           90,
    "frame_eyes":            91,
    "run_id":                92,
    "recent_version":        93,
    "notes":                 102,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_get(row: list, idx: int) -> str:
    try:
        return row[idx]
    except IndexError:
        return ""


def parse_time_to_ms(value: str) -> int | None:
    """Parse H:MM:SS or M:SS to milliseconds. Returns None if blank/unparseable."""
    if not value or not value.strip():
        return None
    v = value.strip()
    try:
        parts = v.split(":")
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            return round((h * 3600 + m * 60 + s) * 1000)
        elif len(parts) == 2:
            m, s = int(parts[0]), float(parts[1])
            return round((m * 60 + s) * 1000)
    except (ValueError, IndexError):
        return None
    return None


def parse_int(value: str) -> int | None:
    if not value or not value.strip():
        return None
    try:
        return int(value.strip().replace(",", ""))
    except ValueError:
        return None


def parse_bool(value: str) -> int | None:
    """Return 1 for TRUE, 0 for FALSE, None if blank."""
    v = value.strip().upper()
    if v == "TRUE":
        return 1
    if v == "FALSE":
        return 0
    return None


def parse_date(value: str) -> str | None:
    """Parse M/D/YYYY H:MM:SS to ISO date string. Returns None if blank/unparseable."""
    if not value or not value.strip():
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ── Warnings ─────────────────────────────────────────────────────────────────

def warn(row_num: int, message: str):
    print(f"  [WARN] Row {row_num}: {message}")


def error(row_num: int, message: str):
    print(f"  [ERROR] Row {row_num}: {message}")


def validate_run(run: dict, row_num: int) -> set[str]:
    issues = set()
    run_id = run.get("run_id") or f"row {row_num}"

    if not run.get("date"):
        warn(row_num, f"run {run_id}: missing or unparseable date")
        issues.add("date")
    if run.get("igt_ms") is None:
        warn(row_num, f"run {run_id}: missing or unparseable IGT")
        issues.add("time")
    if run.get("rta_ms") is None:
        warn(row_num, f"run {run_id}: missing or unparseable RTA")
        issues.add("time")

    # Negative retime (rta < igt)
    igt = run.get("igt_ms")
    rta = run.get("rta_ms")
    if igt is not None and rta is not None and rta < igt:
        diff  = igt - rta
        level = "ERROR" if diff > 30000 else "WARN"
        print(f"  [{level}] Row {row_num} (run {run_id}): negative retime of {diff}ms ({diff/1000:.3f}s): IGT {run['igt_raw']} → RTA {run['rta_raw']}")
        issues.add("retime")

    for key, value in run.items():
        if isinstance(value, str) and "todo" in value.lower():
            warn(row_num, f"run {run_id}: 'todo' in field '{key}': '{value}'")
            issues.add("todo")

    return issues


# ── CSV parsing ───────────────────────────────────────────────────────────────

def clean_row(row: list) -> dict | None:
    """Parse a raw CSV row into a cleaned run dict. Returns None for blank rows."""
    run_id_raw = safe_get(row, COL["run_id"]).strip()
    if not run_id_raw:
        return None

    return {
        "run_id":                 parse_int(run_id_raw),
        "date":                   parse_date(safe_get(row, COL["date"])),
        "date_raw":               safe_get(row, COL["date"]).strip() or None,
        "iron_source":            safe_get(row, COL["iron_source"]).strip() or None,
        "enter_type":             safe_get(row, COL["enter_type"]).strip() or None,
        "gold_source":            safe_get(row, COL["gold_source"]).strip() or None,
        "spawn_biome":            safe_get(row, COL["spawn_biome"]).strip() or None,
        "rta_ms":                 parse_time_to_ms(safe_get(row, COL["rta"])),
        "rta_raw":                safe_get(row, COL["rta"]).strip() or None,
        "igt_ms":                 parse_time_to_ms(safe_get(row, COL["igt"])),
        "igt_raw":                safe_get(row, COL["igt"]).strip() or None,
        "time_wood_ms":           parse_time_to_ms(safe_get(row, COL["time_wood"])),
        "time_iron_pick_ms":      parse_time_to_ms(safe_get(row, COL["time_iron_pick"])),
        "time_nether_ms":         parse_time_to_ms(safe_get(row, COL["time_nether"])),
        "time_bastion_ms":        parse_time_to_ms(safe_get(row, COL["time_bastion"])),
        "time_fortress_ms":       parse_time_to_ms(safe_get(row, COL["time_fortress"])),
        "time_first_portal_ms":   parse_time_to_ms(safe_get(row, COL["time_first_portal"])),
        "time_second_portal_ms":  parse_time_to_ms(safe_get(row, COL["time_second_portal"])),
        "time_stronghold_ms":     parse_time_to_ms(safe_get(row, COL["time_stronghold"])),
        "time_end_ms":            parse_time_to_ms(safe_get(row, COL["time_end"])),
        "gold_dropped":           parse_int(safe_get(row, COL["gold_dropped"])),
        "blaze_rods":             parse_int(safe_get(row, COL["blaze_rods"])),
        "blazes_killed":          parse_int(safe_get(row, COL["blazes_killed"])),
        "flint_picked_up":        parse_int(safe_get(row, COL["flint_picked_up"])),
        "gravel_mined":           parse_int(safe_get(row, COL["gravel_mined"])),
        "deaths_total":           parse_int(safe_get(row, COL["deaths_total"])),
        "jumps":                  parse_int(safe_get(row, COL["jumps"])),
        "eyes_used":              parse_int(safe_get(row, COL["eyes_used"])),
        "diamond_picks_crafted":  parse_int(safe_get(row, COL["diamond_picks_crafted"])),
        "ender_pearls_used":      parse_int(safe_get(row, COL["ender_pearls_used"])),
        "obsidian_placed":        parse_int(safe_get(row, COL["obsidian_placed"])),
        "diamond_sword_crafted":  parse_int(safe_get(row, COL["diamond_sword_crafted"])),
        "stone_mined":            parse_int(safe_get(row, COL["stone_mined"])),
        "netherrack_mined":       parse_int(safe_get(row, COL["netherrack_mined"])),
        "killed_blaze":           parse_int(safe_get(row, COL["killed_blaze"])),
        "killed_chicken":         parse_int(safe_get(row, COL["killed_chicken"])),
        "killed_cod":             parse_int(safe_get(row, COL["killed_cod"])),
        "killed_cow":             parse_int(safe_get(row, COL["killed_cow"])),
        "killed_creeper":         parse_int(safe_get(row, COL["killed_creeper"])),
        "killed_enderman":        parse_int(safe_get(row, COL["killed_enderman"])),
        "killed_endermite":       parse_int(safe_get(row, COL["killed_endermite"])),
        "killed_ghast":           parse_int(safe_get(row, COL["killed_ghast"])),
        "killed_hoglin":          parse_int(safe_get(row, COL["killed_hoglin"])),
        "killed_iron_golem":      parse_int(safe_get(row, COL["killed_iron_golem"])),
        "killed_pig":             parse_int(safe_get(row, COL["killed_pig"])),
        "killed_piglin":          parse_int(safe_get(row, COL["killed_piglin"])),
        "killed_salmon":          parse_int(safe_get(row, COL["killed_salmon"])),
        "killed_sheep":           parse_int(safe_get(row, COL["killed_sheep"])),
        "killed_skeleton":        parse_int(safe_get(row, COL["killed_skeleton"])),
        "killed_spider":          parse_int(safe_get(row, COL["killed_spider"])),
        "killed_witch":           parse_int(safe_get(row, COL["killed_witch"])),
        "killed_wither_skeleton": parse_int(safe_get(row, COL["killed_wither_skeleton"])),
        "killed_zombie":          parse_int(safe_get(row, COL["killed_zombie"])),
        "eaten_bread":            parse_int(safe_get(row, COL["eaten_bread"])),
        "eaten_cooked_beef":      parse_int(safe_get(row, COL["eaten_cooked_beef"])),
        "eaten_cooked_chicken":   parse_int(safe_get(row, COL["eaten_cooked_chicken"])),
        "eaten_cooked_cod":       parse_int(safe_get(row, COL["eaten_cooked_cod"])),
        "eaten_cooked_mutton":    parse_int(safe_get(row, COL["eaten_cooked_mutton"])),
        "eaten_cooked_porkchop":  parse_int(safe_get(row, COL["eaten_cooked_porkchop"])),
        "eaten_cooked_salmon":    parse_int(safe_get(row, COL["eaten_cooked_salmon"])),
        "eaten_ega":              parse_int(safe_get(row, COL["eaten_ega"])),
        "eaten_golden_apple":     parse_int(safe_get(row, COL["eaten_golden_apple"])),
        "eaten_apple":            parse_int(safe_get(row, COL["eaten_apple"])),
        "eaten_rotten_flesh":     parse_int(safe_get(row, COL["eaten_rotten_flesh"])),
        "eaten_golden_carrot":    parse_int(safe_get(row, COL["eaten_golden_carrot"])),
        "eaten_mushroom_stew":    parse_int(safe_get(row, COL["eaten_mushroom_stew"])),
        "travel_walk_on_water":   parse_int(safe_get(row, COL["travel_walk_on_water"])),
        "travel_walk":            parse_int(safe_get(row, COL["travel_walk"])),
        "travel_walk_under_water":parse_int(safe_get(row, COL["travel_walk_under_water"])),
        "travel_swim":            parse_int(safe_get(row, COL["travel_swim"])),
        "travel_boat":            parse_int(safe_get(row, COL["travel_boat"])),
        "travel_sprint":          parse_int(safe_get(row, COL["travel_sprint"])),
        "seed":                   safe_get(row, COL["seed"]).strip() or None,
        "bastion_type":           safe_get(row, COL["bastion_type"]).strip() or None,
        "end_fight_type":         safe_get(row, COL["end_fight_type"]).strip() or None,
        "real_deaths":            parse_int(safe_get(row, COL["real_deaths"])),
        "frame_eyes":             parse_int(safe_get(row, COL["frame_eyes"])),
        "recent_version":         parse_bool(safe_get(row, COL["recent_version"])),
        "notes":                  safe_get(row, COL["notes"]).strip() or None,
    }


def load_csv(path: str) -> list[dict]:
    print(f"Loading CSV from: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    runs = []
    all_issues: set[str] = set()
    for i, raw_row in enumerate(rows[3:], start=4):
        cleaned = clean_row(raw_row)
        if cleaned:
            issues = validate_run(cleaned, i)
            all_issues |= issues
            runs.append(cleaned)

    if "date"   not in all_issues: print("  [INFO] All dates are valid.")
    if "time"   not in all_issues: print("  [INFO] All times are parseable.")
    if "retime" not in all_issues: print("  [INFO] No negative retimes.")
    if "todo"   not in all_issues: print("  [INFO] No 'todo' values found.")

    return runs


# ── Schema ────────────────────────────────────────────────────────────────────

CREATE_RUNS_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                   INTEGER UNIQUE,
    date                     TEXT,
    iron_source              TEXT,
    enter_type               TEXT,
    gold_source              TEXT,
    spawn_biome              TEXT,
    rta_ms                   INTEGER,
    rta_raw                  TEXT,
    igt_ms                   INTEGER,
    igt_raw                  TEXT,
    time_wood_ms             INTEGER,
    time_iron_pick_ms        INTEGER,
    time_nether_ms           INTEGER,
    time_bastion_ms          INTEGER,
    time_fortress_ms         INTEGER,
    time_first_portal_ms     INTEGER,
    time_second_portal_ms    INTEGER,
    time_stronghold_ms       INTEGER,
    time_end_ms              INTEGER,
    gold_dropped             INTEGER,
    blaze_rods               INTEGER,
    blazes_killed            INTEGER,
    flint_picked_up          INTEGER,
    gravel_mined             INTEGER,
    deaths_total             INTEGER,
    jumps                    INTEGER,
    eyes_used                INTEGER,
    diamond_picks_crafted    INTEGER,
    ender_pearls_used        INTEGER,
    obsidian_placed          INTEGER,
    diamond_sword_crafted    INTEGER,
    stone_mined              INTEGER,
    netherrack_mined         INTEGER,
    killed_blaze             INTEGER,
    killed_chicken           INTEGER,
    killed_cod               INTEGER,
    killed_cow               INTEGER,
    killed_creeper           INTEGER,
    killed_enderman          INTEGER,
    killed_endermite         INTEGER,
    killed_ghast             INTEGER,
    killed_hoglin            INTEGER,
    killed_iron_golem        INTEGER,
    killed_pig               INTEGER,
    killed_piglin            INTEGER,
    killed_salmon            INTEGER,
    killed_sheep             INTEGER,
    killed_skeleton          INTEGER,
    killed_spider            INTEGER,
    killed_witch             INTEGER,
    killed_wither_skeleton   INTEGER,
    killed_zombie            INTEGER,
    eaten_bread              INTEGER,
    eaten_cooked_beef        INTEGER,
    eaten_cooked_chicken     INTEGER,
    eaten_cooked_cod         INTEGER,
    eaten_cooked_mutton      INTEGER,
    eaten_cooked_porkchop    INTEGER,
    eaten_cooked_salmon      INTEGER,
    eaten_ega                INTEGER,
    eaten_golden_apple       INTEGER,
    eaten_apple              INTEGER,
    eaten_rotten_flesh       INTEGER,
    eaten_golden_carrot      INTEGER,
    eaten_mushroom_stew      INTEGER,
    travel_walk_on_water     INTEGER,
    travel_walk              INTEGER,
    travel_walk_under_water  INTEGER,
    travel_swim              INTEGER,
    travel_boat              INTEGER,
    travel_sprint            INTEGER,
    seed                     TEXT,
    bastion_type             TEXT,
    end_fight_type           TEXT,
    real_deaths              INTEGER,
    frame_eyes               INTEGER,
    recent_version           INTEGER,
    notes                    TEXT
);
"""


# ── Database ──────────────────────────────────────────────────────────────────

EXCLUDE = {"date_raw", "igt_raw", "rta_raw"}

def init_db(path: str, runs: list[dict]) -> None:
    print(f"Initialising database at: {path}")
    conn = sqlite3.connect(path)

    conn.execute("DELETE FROM runs") if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
    ).fetchone() else None
    conn.execute(CREATE_RUNS_SQL)

    run_fields   = [k for k in runs[0].keys() if k not in EXCLUDE]
    col_names    = ", ".join(run_fields)
    placeholders = ", ".join(["?"] * len(run_fields))
    sql          = f"INSERT OR REPLACE INTO runs ({col_names}) VALUES ({placeholders})"

    for run in runs:
        values = [run[f] for f in run_fields]
        conn.execute(sql, values)

    conn.commit()
    conn.close()


# ── Preview ───────────────────────────────────────────────────────────────────

def ms_to_time(ms: int | None) -> str:
    if ms is None:
        return "—"
    total_s = ms / 1000
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s % 60
    if h:
        return f"{h}:{m:02}:{s:06.3f}"
    return f"{m}:{s:06.3f}"


def preview(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT run_id, date, iron_source, bastion_type, igt_ms, rta_ms
        FROM runs
        ORDER BY run_id DESC
        LIMIT 10
    """).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.close()

    print()
    print("=" * 72)
    print("  COURIWAY RUNS PREVIEW — 10 most recent")
    print("=" * 72)
    print(f"  {'Run':<8} {'Date':<12} {'Iron Source':<28} {'Bastion':<20} {'IGT':<10} RTA")
    print(f"  {'-'*68}")
    for row in rows:
        igt = ms_to_time(row["igt_ms"]) if row["igt_ms"] else "—"
        rta = ms_to_time(row["rta_ms"]) if row["rta_ms"] else "—"
        print(f"  {row['run_id']:<8} {(row['date'] or '?'):<12} {(row['iron_source'] or '?'):<28} {(row['bastion_type'] or '?'):<20} {igt:<10} {rta}")
    print()
    print(f"  Total runs: {total:,}")
    print("=" * 72)


# ── Download ──────────────────────────────────────────────────────────────────

def download_sheet(url: str, dest: str) -> None:
    """Download the Google Sheet CSV and save it to dest."""
    print("Downloading sheet from Google Sheets...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    content = response.text
    if content.strip().startswith("<!DOCTYPE") or content.strip().startswith("<html"):
        raise ValueError("Got an HTML response instead of CSV — sheet may not be public.")

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)

    line_count = content.count("\n")
    print(f"  Saved {line_count:,} lines to {dest}")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def seconds_until_midnight_pacific() -> float:
    """Return seconds until the next midnight Pacific time."""
    now = datetime.now(PACIFIC)
    tomorrow_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (tomorrow_midnight - now).total_seconds()


def run_pipeline() -> None:
    """Download sheet, import to DB, print preview."""
    download_sheet(SHEET_URL, CSV_PATH)
    runs = load_csv(CSV_PATH)
    print(f"Loaded {len(runs):,} runs from CSV.")
    init_db(DB_PATH, runs)
    preview(DB_PATH)
    print("Done.")


def schedule_loop() -> None:
    """Run the pipeline now, then again every day at midnight Pacific."""
    while True:
        now_str = datetime.now(PACIFIC).strftime("%Y-%m-%d %H:%M:%S PT")
        print(f"\n[{now_str}] Running scheduled update...")
        try:
            run_pipeline()
        except Exception as e:
            print(f"  [ERROR] Pipeline failed: {e}")

        wait = seconds_until_midnight_pacific()
        next_run = datetime.now(PACIFIC) + timedelta(seconds=wait)
        print(f"  Next run at: {next_run.strftime('%Y-%m-%d %H:%M:%S PT')} ({wait/3600:.1f}h from now)")
        time.sleep(wait)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--schedule" in args:
        print("Starting scheduler — will update daily at midnight Pacific.")
        schedule_loop()
    elif "--download" in args:
        run_pipeline()
    else:
        # Local CSV import (original behaviour, no network needed)
        runs = load_csv(CSV_PATH)
        print(f"Loaded {len(runs):,} runs from CSV.")
        init_db(DB_PATH, runs)
        preview(DB_PATH)
        print("\nDone.")