import sqlite3
import os
import csv
import glob
import sys
from datetime import datetime, date

import requests

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH   = os.path.join("data", "leaderboard.db")

# Google Sheets — SUB-8 leaderboard tab (gid=1452671563)
SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1zgmOYJBULyHLqs9lGB6-cO4QhRoJdgOpd9WpUWpILYo"
    "/export?format=csv&gid=1452671563"
)


def get_csv_path() -> str:
    """Return the path of the most recent RSG-*.csv in data/."""
    matches = sorted(glob.glob(os.path.join("data", "RSG-*.csv")))
    if not matches:
        raise FileNotFoundError(
            "No RSG-*.csv found in data/. Run with --download first."
        )
    return matches[-1]


def download_sheet(url: str) -> str:
    """Download the sheet, delete any old RSG-*.csv, save as RSG-YYYY-MM-DD.csv.
    Returns the path of the newly saved file.
    """
    today     = date.today().isoformat()          # e.g. 2026-03-12
    dest      = os.path.join("data", f"RSG-{today}.csv")

    print(f"Downloading sheet from Google Sheets...")
    response  = requests.get(url, timeout=30)
    response.raise_for_status()

    content = response.text
    if content.strip().startswith("<!DOCTYPE") or content.strip().startswith("<html"):
        raise ValueError("Got HTML instead of CSV — sheet may not be public.")

    # Delete any previously downloaded RSG-*.csv files
    for old in glob.glob(os.path.join("data", "RSG-*.csv")):
        if old != dest:
            os.remove(old)
            print(f"  Deleted old file: {old}")

    os.makedirs("data", exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  Saved {content.count(chr(10)):,} lines to {dest}")
    return dest

# ── Column index map (0-based) ─────────────────────────────────────────────────
# The spreadsheet has 3 header rows; data starts at row index 3.
#
# Runner name/flag SHIFT RULE:
#   A runner's FIRST (fastest) appearance:   col[3]=flag, col[4]=runner, col[5]=blank
#   All SUBSEQUENT (slower) appearances:     col[3]=blank, col[4]=flag,  col[5]=runner
#
# We detect and normalise this in parse_runner_cols() before reading anything else.
# All other columns are fixed regardless of the shift.

COL = {
    # cols 3/4/5 handled by parse_runner_cols()
    "is_wr":                     6,
    "is_pb":                     7,
    "in_game_time":              8,
    "re_timed_time":             9,
    "date":                     10,
    "speedrun_com_status":      11,
    "seed":                     12,
    "instances":                13,
    "used_calculator":          14,
    "link":                     15,
    # ── Split data (only ~first 28 runs) ──────────────────────────────────────
    "overworld_type":           17,
    "used_tnt":                 18,
    "portal_type":              19,
    "nether_enter":             20,
    "ne_to_s1":                 21,
    "s1_enter":                 22,
    "s1_type":                  23,
    "s1_exit":                  25,
    "s1_to_s2":                 26,
    "s2_enter":                 27,
    "s2_type":                  28,
    "s2_exit":                  30,
    "rods_dropped":             32,
    "blazes_killed":            33,
    "s2_to_e1":                 35,
    "all_rods_before_e1":       36,
    "num_nether_exits":         37,
    "nether_exit_1":            38,
    "exit_1_type":              39,
    "triangulation_split":      40,
    "eyes_thrown":              41,
    "eyes_broken":              42,
    "eyes_left":                43,
    "reenter":                  45,
    "reenter_to_e2":            46,
    "stronghold_distance":      47,
    "nether_exit_2":            48,
    "theoretical_blind":        49,
    "nether_split":             50,
    "total_nether":             51,
    "total_ow2":                52,
    "post_blind":               53,
    "s2_exit_to_stronghold":    55,
    "stronghold_enter":         56,
    "nav_strat":                57,
    "portal_frames_filled":     59,
    "end_enter":                60,
    "end_strat":                61,
    "explosives_used":          62,
    "zero_explosives_used":     63,
    "perch_explosives_used":    64,
    "end_platform":             65,
    "dragon_node":              66,
    "tower_height":             67,
    "tower_name":               68,
    "standing_height":          69,
    "credits":                  71,
    "bastion_type":             72,
    "bastion_route":            73,
    "chests_checked":           74,
    "bastion_generation_info":  75,
    "loot_obsidian":            76,
    "loot_string":              77,
    "loot_glowstone":           78,
    "loot_arrows":              79,
    "loot_pearls":              80,
    "loot_crying_obsidian":     81,
    "timeloss":                 82,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_get(row: list, index: int) -> str:
    try:
        return row[index]
    except IndexError:
        return ""


def fix_encoding(value: str) -> str:
    """Fix double-encoded UTF-8 emoji/text (e.g. flag emoji mangled on CSV export).
    Google Sheets sometimes exports UTF-8 bytes interpreted as latin-1, resulting
    in strings like 'ð\x9f\x87¨' instead of '🇨'. Reversing the mis-encode fixes it.
    Falls back to the original string if decoding fails.
    """
    if not value:
        return value
    try:
        return value.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def parse_runner_cols(row: list) -> tuple[str | None, str | None]:
    """
    Resolve the runner name and flag regardless of column shift.

    First appearance (fastest run):  col[3]=flag, col[4]=runner, col[5]=blank
    Later appearances (slower runs): col[3]=blank, col[4]=flag,  col[5]=runner

    Returns: (runner_name, flag)
    """
    col3 = safe_get(row, 3).strip()
    col4 = safe_get(row, 4).strip()
    col5 = safe_get(row, 5).strip()

    if col5:
        # Shifted layout: col4=flag, col5=runner
        return col5 or None, fix_encoding(col4) or None
    else:
        # Normal layout: col3=flag, col4=runner
        return col4 or None, fix_encoding(col3) or None


def parse_time_to_ms(value: str) -> int | None:
    """Convert 'M:SS.mmm' or 'H:MM:SS.mmm' to total milliseconds."""
    if not value or value.strip() in ("", "--", "#VALUE!"):
        return None
    value = value.strip()
    try:
        parts = value.split(":")
        if len(parts) == 2:
            return round((int(parts[0]) * 60 + float(parts[1])) * 1000)
        elif len(parts) == 3:
            return round((int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])) * 1000)
    except (ValueError, IndexError):
        return None
    return None


def parse_date(value: str) -> str | None:
    """Parse '11 Jun 2025' (with possible non-breaking spaces) to ISO format.
    Returns None if the value is empty or unparseable."""
    if not value or not value.strip():
        return None
    # Strip both plain non-breaking space (\xa0) and the Â\xa0 mojibake
    # that appears when a non-breaking space is double-encoded on export.
    cleaned = value.replace("Â\xa0", " ").replace("\xa0", " ").strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None  # unparseable — caller can check original raw value for warning


def parse_bool(value: str) -> bool | None:
    if not value or not value.strip():
        return None

    raw = value
    value = fix_encoding(value)
    v = value.strip().lower()
    v = v.strip()

    if v in ("✔", "yes", "true", "1"):
        return True
    if v in ("x", "✗", "no", "false", "0"):
        return False

    print(f"[WARN] Unknown boolean value: '{raw}' → '{v}'")
    return None


def parse_status(value: str) -> str | None:
    """Convert SRC status shorthand to full display name."""
    mapping = {
        "(V)": "Verified",
        "(Q)": "In Queue",
        "(U)": "Unsubmitted",
        "(X)": "Rejected",
        "(B)": "Banned",
    }
    return mapping.get(value.strip()) if value and value.strip() else None


def parse_float(value: str) -> float | None:
    if not value or value.strip() in ("", "--", "#VALUE!"):
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def parse_int(value: str) -> int | None:
    if not value or value.strip() in ("", "--"):
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


# ── Row parser ────────────────────────────────────────────────────────────────

def clean_row(row: list) -> dict | None:
    """
    Convert a raw CSV row into a cleaned dictionary.
    Returns None if the row has no in_game_time (i.e. not a real run).
    """
    igt_raw = safe_get(row, COL["in_game_time"]).strip()
    if not igt_raw:
        return None

    runner_name, flag = parse_runner_cols(row)

    return {
        # ── Core run info ─────────────────────────────────────────────────────
        "runner":                   runner_name,
        "flag":                     flag,
        "is_wr":                    parse_bool(safe_get(row, COL["is_wr"])),
        "is_pb":                    parse_bool(safe_get(row, COL["is_pb"])),
        "in_game_time_ms":          parse_time_to_ms(igt_raw),
        "in_game_time_raw":         igt_raw,
        "re_timed_time_ms":         parse_time_to_ms(safe_get(row, COL["re_timed_time"])),
        "re_timed_time_raw":        safe_get(row, COL["re_timed_time"]).strip() or None,
        "date":                     parse_date(safe_get(row, COL["date"])),
        "date_raw":                 safe_get(row, COL["date"]).replace("\xa0", " ").strip() or None,
        "speedrun_com_status":      parse_status(safe_get(row, COL["speedrun_com_status"])),
        "seed":                     safe_get(row, COL["seed"]).strip() or None,
        "instances":                safe_get(row, COL["instances"]).strip() or None,
        "used_calculator":          safe_get(row, COL["used_calculator"]).strip() or None,
        "link":                     safe_get(row, COL["link"]).strip() or None,
        # ── Split data (NULL if not recorded) ─────────────────────────────────
        "overworld_type":               safe_get(row, COL["overworld_type"]).strip() or None,
        "used_tnt":                     parse_bool(safe_get(row, COL["used_tnt"])),
        "portal_type":                  safe_get(row, COL["portal_type"]).strip() or None,
        "nether_enter_ms":              parse_time_to_ms(safe_get(row, COL["nether_enter"])),
        "ne_to_s1_ms":                  parse_time_to_ms(safe_get(row, COL["ne_to_s1"])),
        "s1_enter_ms":                  parse_time_to_ms(safe_get(row, COL["s1_enter"])),
        "s1_type":                      safe_get(row, COL["s1_type"]).strip() or None,
        "s1_exit_ms":                   parse_time_to_ms(safe_get(row, COL["s1_exit"])),
        "s1_to_s2_ms":                  parse_time_to_ms(safe_get(row, COL["s1_to_s2"])),
        "s2_enter_ms":                  parse_time_to_ms(safe_get(row, COL["s2_enter"])),
        "s2_type":                      safe_get(row, COL["s2_type"]).strip() or None,
        "s2_exit_ms":                   parse_time_to_ms(safe_get(row, COL["s2_exit"])),
        "rods_dropped":                 parse_int(safe_get(row, COL["rods_dropped"])),
        "blazes_killed":                parse_int(safe_get(row, COL["blazes_killed"])),
        "s2_to_e1_ms":                  parse_time_to_ms(safe_get(row, COL["s2_to_e1"])),
        "all_rods_before_e1":           safe_get(row, COL["all_rods_before_e1"]).strip() or None,
        "num_nether_exits":             parse_int(safe_get(row, COL["num_nether_exits"])),
        "nether_exit_1_ms":             parse_time_to_ms(safe_get(row, COL["nether_exit_1"])),
        "exit_1_type":                  safe_get(row, COL["exit_1_type"]).strip() or None,
        "triangulation_split_ms":       parse_time_to_ms(safe_get(row, COL["triangulation_split"])),
        "eyes_thrown":                  parse_int(safe_get(row, COL["eyes_thrown"])),
        "eyes_broken":                  parse_int(safe_get(row, COL["eyes_broken"])),
        "eyes_left":                    parse_int(safe_get(row, COL["eyes_left"])),
        "reenter_ms":                   parse_time_to_ms(safe_get(row, COL["reenter"])),
        "reenter_to_e2_ms":             parse_time_to_ms(safe_get(row, COL["reenter_to_e2"])),
        "stronghold_distance":          parse_int(safe_get(row, COL["stronghold_distance"])),
        "nether_exit_2_ms":             parse_time_to_ms(safe_get(row, COL["nether_exit_2"])),
        "theoretical_blind_ms":         parse_time_to_ms(safe_get(row, COL["theoretical_blind"])),
        "nether_split_ms":              parse_time_to_ms(safe_get(row, COL["nether_split"])),
        "total_nether_ms":              parse_time_to_ms(safe_get(row, COL["total_nether"])),
        "total_ow2_ms":                 parse_time_to_ms(safe_get(row, COL["total_ow2"])),
        "post_blind_ms":                parse_time_to_ms(safe_get(row, COL["post_blind"])),
        "s2_exit_to_stronghold_ms":     parse_time_to_ms(safe_get(row, COL["s2_exit_to_stronghold"])),
        "stronghold_enter_ms":          parse_time_to_ms(safe_get(row, COL["stronghold_enter"])),
        "nav_strat":                    safe_get(row, COL["nav_strat"]).strip() or None,
        "portal_frames_filled":         parse_int(safe_get(row, COL["portal_frames_filled"])),
        "end_enter_ms":                 parse_time_to_ms(safe_get(row, COL["end_enter"])),
        "end_strat":                    safe_get(row, COL["end_strat"]).strip() or None,
        "explosives_used":              parse_int(safe_get(row, COL["explosives_used"])),
        "zero_explosives_used":         parse_int(safe_get(row, COL["zero_explosives_used"])),
        "perch_explosives_used":        parse_int(safe_get(row, COL["perch_explosives_used"])),
        "end_platform":                 safe_get(row, COL["end_platform"]).strip() or None,
        "dragon_node":                  safe_get(row, COL["dragon_node"]).strip() or None,
        "tower_height":                 safe_get(row, COL["tower_height"]).strip() or None,
        "tower_name":                   safe_get(row, COL["tower_name"]).strip() or None,
        "standing_height":              safe_get(row, COL["standing_height"]).strip() or None,
        "credits_ms":                   parse_time_to_ms(safe_get(row, COL["credits"])),
        "bastion_type":                 safe_get(row, COL["bastion_type"]).strip() or None,
        "bastion_route":                safe_get(row, COL["bastion_route"]).strip() or None,
        "chests_checked":               safe_get(row, COL["chests_checked"]).strip() or None,
        "bastion_generation_info":      safe_get(row, COL["bastion_generation_info"]).strip() or None,
        "loot_obsidian":                parse_int(safe_get(row, COL["loot_obsidian"])),
        "loot_string":                  parse_int(safe_get(row, COL["loot_string"])),
        "loot_glowstone":               parse_int(safe_get(row, COL["loot_glowstone"])),
        "loot_arrows":                  parse_int(safe_get(row, COL["loot_arrows"])),
        "loot_pearls":                  parse_int(safe_get(row, COL["loot_pearls"])),
        "loot_crying_obsidian":         parse_int(safe_get(row, COL["loot_crying_obsidian"])),
        "timeloss":                     safe_get(row, COL["timeloss"]).strip() or None,
    }


# ── Warnings ─────────────────────────────────────────────────────────────────

def warn(row_num: int, runner: str, message: str):
    print(f"  [WARN] Row {row_num} ({runner}): {message}")


def validate_run(run: dict, row_num: int) -> set[str]:
    """Check a cleaned run dict for data quality issues and print warnings.
    Returns a set of issue category strings that were triggered."""
    runner = run.get("runner") or "Unknown runner"
    issues = set()

    # Unparseable time — raw value exists but ms is None
    if run.get("in_game_time_raw") and run.get("in_game_time_ms") is None:
        warn(row_num, runner, f"unparseable IGT: '{run['in_game_time_raw']}'")
        issues.add("time")
    if run.get("re_timed_time_raw") and run.get("re_timed_time_ms") is None:
        warn(row_num, runner, f"unparseable RTT: '{run['re_timed_time_raw']}'")
        issues.add("time")

    # Missing core fields
    if not run.get("runner"):
        warn(row_num, runner, "missing runner name")
        issues.add("runner")
    if not run.get("link"):
        warn(row_num, runner, "missing link")
        issues.add("link")

    # Date validation
    date_raw = run.get("date_raw")
    date     = run.get("date")
    if date_raw and not date:
        warn(row_num, runner, f"unparseable date: '{date_raw}'")
        issues.add("date")
    elif not date_raw:
        warn(row_num, runner, "missing date")
        issues.add("date")
    else:
        run_date = datetime.strptime(date, "%Y-%m-%d").date()
        today    = datetime.now().date()
        earliest = datetime(2019, 1, 1).date()
        if run_date > today:
            warn(row_num, runner, f"date is in the future: '{date}'")
            issues.add("date")
        elif run_date < earliest:
            warn(row_num, runner, f"date is before 2019-01-01: '{date}'")
            issues.add("date")

    # Negative retime
    igt = run.get("in_game_time_ms")
    rtt = run.get("re_timed_time_ms")
    if igt is not None and rtt is not None and rtt < igt:
        diff  = igt - rtt
        level = "ERROR" if diff > 30000 else "WARN"
        print(f"  [{level}] Row {row_num} ({runner}): negative retime of {diff}ms ({diff/1000:.3f}s): IGT {run['in_game_time_raw']} → RTT {run['re_timed_time_raw']}")
        issues.add("retime")

    # Any cell containing "todo" (case-insensitive)
    for key, value in run.items():
        if isinstance(value, str) and "todo" in value.lower():
            warn(row_num, runner, f"'todo' found in field '{key}': '{value}'")
            issues.add("todo")

    return issues


# ── Load CSV ──────────────────────────────────────────────────────────────────

def load_csv(path: str) -> list[dict]:
    """Read the CSV, skip the 6 header/blank rows, return list of cleaned run dicts."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    # New CSV format: 3 header rows each followed by a blank row (6 rows total),
    # then data rows also separated by blank rows. We skip the first 6 rows and
    # filter out any subsequent blank rows before parsing.
    data_rows = [r for r in rows[6:] if any(c.strip() for c in r)]

    runs = []
    all_issues: set[str] = set()
    for i, raw_row in enumerate(data_rows, start=7):
        cleaned = clean_row(raw_row)
        if cleaned:
            issues = validate_run(cleaned, i)
            all_issues |= issues
            runs.append(cleaned)

    if "date" not in all_issues:
        print("  [INFO] All dates are valid.")
    if "time" not in all_issues:
        print("  [INFO] All times are parseable.")
    if "runner" not in all_issues:
        print("  [INFO] All runs have a runner name.")
    if "link" not in all_issues:
        print("  [INFO] All runs have a link.")
    if "retime" not in all_issues:
        print("  [INFO] No negative retimes.")
    if "todo" not in all_issues:
        print("  [INFO] No 'todo' values found.")

    return runs


# ── Database ──────────────────────────────────────────────────────────────────

CREATE_RUNNERS_SQL = """
CREATE TABLE IF NOT EXISTS runners (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE,
    flag    TEXT            -- country flag emoji, nullable
);
"""

CREATE_RUNS_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    runner_id                   INTEGER NOT NULL REFERENCES runners(id),

    -- Core run info
    is_wr                       INTEGER,    -- 0/1 boolean
    is_pb                       INTEGER,    -- 0/1 boolean
    in_game_time_ms             INTEGER,    -- milliseconds
    in_game_time_raw            TEXT,       -- original string e.g. "6:48.508"
    re_timed_time_ms            INTEGER,    -- milliseconds
    re_timed_time_raw           TEXT,
    date                        TEXT,       -- ISO date YYYY-MM-DD
    speedrun_com_status         TEXT,       -- "(V)" verified, "(Q)" queue, etc.
    seed                        TEXT,
    instances                   TEXT,
    used_calculator             TEXT,
    link                        TEXT,

    -- Split data (NULL if not recorded for this run)
    overworld_type              TEXT,
    used_tnt                    INTEGER,    -- 0/1 boolean
    portal_type                 TEXT,
    nether_enter_ms             INTEGER,
    ne_to_s1_ms                 INTEGER,
    s1_enter_ms                 INTEGER,
    s1_type                     TEXT,
    s1_exit_ms                  INTEGER,
    s1_to_s2_ms                 INTEGER,
    s2_enter_ms                 INTEGER,
    s2_type                     TEXT,
    s2_exit_ms                  INTEGER,
    rods_dropped                INTEGER,
    blazes_killed               INTEGER,
    s2_to_e1_ms                 INTEGER,
    all_rods_before_e1          TEXT,
    num_nether_exits            INTEGER,
    nether_exit_1_ms            INTEGER,
    exit_1_type                 TEXT,
    triangulation_split_ms      INTEGER,
    eyes_thrown                 INTEGER,
    eyes_broken                 INTEGER,
    eyes_left                   INTEGER,
    reenter_ms                  INTEGER,
    reenter_to_e2_ms            INTEGER,
    stronghold_distance         INTEGER,
    nether_exit_2_ms            INTEGER,
    theoretical_blind_ms        INTEGER,
    nether_split_ms             INTEGER,
    total_nether_ms             INTEGER,
    total_ow2_ms                INTEGER,
    post_blind_ms               INTEGER,
    s2_exit_to_stronghold_ms    INTEGER,
    stronghold_enter_ms         INTEGER,
    nav_strat                   TEXT,
    portal_frames_filled        INTEGER,
    end_enter_ms                INTEGER,
    end_strat                   TEXT,
    explosives_used             INTEGER,
    zero_explosives_used        INTEGER,
    perch_explosives_used       INTEGER,
    end_platform                TEXT,
    dragon_node                 TEXT,
    tower_height                TEXT,
    tower_name                  TEXT,
    standing_height             TEXT,
    credits_ms                  INTEGER,
    bastion_type                TEXT,
    bastion_route               TEXT,
    chests_checked              TEXT,
    bastion_generation_info     TEXT,
    loot_obsidian               INTEGER,
    loot_string                 INTEGER,
    loot_glowstone              INTEGER,
    loot_arrows                 INTEGER,
    loot_pearls                 INTEGER,
    loot_crying_obsidian        INTEGER,
    timeloss                    TEXT
);
"""


CREATE_CALCULATIONS_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS runs_with_calculations AS
SELECT
    *,
    -- Calculated splits (NULL if either component is missing)
    CASE WHEN s1_exit_ms IS NOT NULL AND s1_enter_ms IS NOT NULL
         THEN s1_exit_ms - s1_enter_ms END AS s1_split_ms,
    CASE WHEN s2_exit_ms IS NOT NULL AND s2_enter_ms IS NOT NULL
         THEN s2_exit_ms - s2_enter_ms END AS s2_split_ms,
    CASE WHEN end_enter_ms IS NOT NULL AND stronghold_enter_ms IS NOT NULL
         THEN end_enter_ms - stronghold_enter_ms END AS sh_split_ms,
    CASE WHEN credits_ms IS NOT NULL AND end_enter_ms IS NOT NULL
         THEN credits_ms - end_enter_ms END AS end_split_ms,
    -- Retime: how much time was added from IGT to RTT
    CASE WHEN re_timed_time_ms IS NOT NULL AND in_game_time_ms IS NOT NULL
         THEN re_timed_time_ms - in_game_time_ms END AS retime_ms,
    -- Blaze rates as "dropped/killed" string
    CASE WHEN rods_dropped IS NOT NULL AND blazes_killed IS NOT NULL
         THEN CAST(rods_dropped AS TEXT) || '/' || CAST(blazes_killed AS TEXT) END AS blaze_rates,
    -- Total eye loss: broken + left
    CASE WHEN eyes_broken IS NOT NULL AND eyes_left IS NOT NULL
         THEN eyes_broken + eyes_left END AS total_eye_loss,
    -- S2 to finish: credits - s2_enter
    CASE WHEN credits_ms IS NOT NULL AND s2_enter_ms IS NOT NULL
         THEN credits_ms - s2_enter_ms END AS s2_to_finish_ms
FROM runs;
"""


CREATE_ALL_RUNS_RANKED_SQL = """
CREATE VIEW IF NOT EXISTS all_runs_ranked AS
SELECT
    RANK() OVER (ORDER BY r.re_timed_time_ms ASC) AS position,
    rn.name AS runner,
    rn.flag,
    r.in_game_time_ms,
    r.in_game_time_raw,
    r.re_timed_time_ms,
    r.re_timed_time_raw,
    r.date,
    r.speedrun_com_status,
    r.seed,
    r.link,
    r.is_wr,
    r.is_pb
FROM runs r
JOIN runners rn ON rn.id = r.runner_id
WHERE r.re_timed_time_ms IS NOT NULL;
"""

CREATE_LEADERBOARD_SQL = """
CREATE VIEW IF NOT EXISTS leaderboard AS
WITH best_runs AS (
    SELECT
        r.*,
        rn.name AS runner,
        rn.flag,
        ROW_NUMBER() OVER (
            PARTITION BY r.runner_id
            ORDER BY r.re_timed_time_ms ASC
        ) AS rn_rank
    FROM runs r
    JOIN runners rn ON rn.id = r.runner_id
    WHERE r.re_timed_time_ms IS NOT NULL
)
SELECT
    RANK() OVER (ORDER BY re_timed_time_ms ASC) AS lb_position,
    runner,
    flag,
    in_game_time_ms,
    in_game_time_raw,
    re_timed_time_ms,
    re_timed_time_raw,
    date,
    speedrun_com_status,
    seed,
    link,
    is_wr
FROM best_runs
WHERE rn_rank = 1;
"""

CREATE_RUNNER_STATS_SQL = """
CREATE TABLE IF NOT EXISTS runner_stats (
    runner_id       INTEGER PRIMARY KEY REFERENCES runners(id),
    total_runs      INTEGER NOT NULL DEFAULT 0,
    sub_9           INTEGER NOT NULL DEFAULT 0,
    sub_8           INTEGER NOT NULL DEFAULT 0,
    sub_7           INTEGER NOT NULL DEFAULT 0,
    best_lb_pos     INTEGER           -- NULL if runner has no lb entry
);
"""

CREATE_OVERALL_STATS_SQL = """
CREATE TABLE IF NOT EXISTS overall_stats (
    id          INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    total_runs  INTEGER NOT NULL DEFAULT 0,
    sub_9       INTEGER NOT NULL DEFAULT 0,
    sub_8       INTEGER NOT NULL DEFAULT 0,
    sub_7       INTEGER NOT NULL DEFAULT 0
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(CREATE_RUNNERS_SQL)
    conn.execute(CREATE_RUNS_SQL)
    conn.execute(CREATE_CALCULATIONS_VIEW_SQL)
    conn.execute(CREATE_ALL_RUNS_RANKED_SQL)
    conn.execute(CREATE_LEADERBOARD_SQL)
    conn.execute(CREATE_RUNNER_STATS_SQL)
    conn.execute(CREATE_OVERALL_STATS_SQL)
    conn.commit()
    return conn


def get_or_create_runner(conn: sqlite3.Connection,
                          name: str,
                          flag: str | None) -> int:
    """
    Return the runner's id, inserting them if they don't exist yet.
    If the runner exists but has no flag yet, update it.
    """
    row = conn.execute("SELECT id, flag FROM runners WHERE name = ?", (name,)).fetchone()
    if row:
        runner_id, existing_flag = row
        if not existing_flag and flag:
            conn.execute("UPDATE runners SET flag = ? WHERE id = ?", (flag, runner_id))
        return runner_id
    cursor = conn.execute("INSERT INTO runners (name, flag) VALUES (?, ?)", (name, flag))
    return cursor.lastrowid


def insert_runs(conn: sqlite3.Connection, runs: list[dict]):
    EXCLUDE = {"runner", "flag", "date_raw"}
    run_fields   = [k for k in runs[0].keys() if k not in EXCLUDE]
    placeholders = ", ".join("?" for _ in run_fields)
    col_names    = ", ".join(run_fields)
    sql = f"INSERT INTO runs (runner_id, {col_names}) VALUES (?, {placeholders})"

    for run in runs:
        name      = run.get("runner") or "Unknown"
        flag      = run.get("flag")
        runner_id = get_or_create_runner(conn, name, flag)
        values    = [run[f] for f in run_fields]
        conn.execute(sql, [runner_id] + values)

    conn.commit()


# ── Preview ───────────────────────────────────────────────────────────────────

def ms_to_time(ms: int | None) -> str:
    if ms is None:
        return "N/A"
    total_seconds = ms / 1000
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:06.3f}"


def preview(conn: sqlite3.Connection, n: int = 10):
    print(f"\n{'='*72}")
    print(f"  LEADERBOARD PREVIEW — Top {n} runs by re-timed time")
    print(f"{'='*72}")
    print(f"  {'Pos':<5} {'LB':<6} {'Runner':<20} {'IGT':<12} {'RTT':<12} {'Date':<14} Status")
    print(f"  {'-'*68}")

    rows = conn.execute("""
        WITH all_runs_ranked AS (
            SELECT
                r.id,
                rn.name,
                r.in_game_time_ms,
                r.re_timed_time_ms,
                r.date,
                r.speedrun_com_status,
                RANK() OVER (ORDER BY r.re_timed_time_ms ASC) AS position
            FROM runs r
            JOIN runners rn ON rn.id = r.runner_id
            WHERE r.re_timed_time_ms IS NOT NULL
        ),
        best_per_runner AS (
            SELECT MIN(re_timed_time_ms) AS best_time, name
            FROM all_runs_ranked
            GROUP BY name
        ),
        lb_ranked AS (
            SELECT
                name,
                RANK() OVER (ORDER BY best_time ASC) AS lb_position
            FROM best_per_runner
        )
        SELECT
            a.position,
            l.lb_position,
            a.name,
            a.in_game_time_ms,
            a.re_timed_time_ms,
            a.date,
            a.speedrun_com_status
        FROM all_runs_ranked a
        LEFT JOIN lb_ranked l ON l.name = a.name AND a.re_timed_time_ms = (
            SELECT best_time FROM best_per_runner WHERE name = a.name
        )
        ORDER BY a.re_timed_time_ms ASC
        LIMIT ?
    """, (n,)).fetchall()

    for row in rows:
        pos, lb, name, igt_ms, rtt_ms, date, status = row
        print(
            f"  {str(pos or ''):<5} "
            f"{str(lb or ''):<6} "
            f"{(name or 'Unknown'):<20} "
            f"{ms_to_time(igt_ms):<12} "
            f"{ms_to_time(rtt_ms):<12} "
            f"{(date or 'N/A'):<14} "
            f"{status or ''}"
        )

    total_runs    = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    total_runners = conn.execute("SELECT COUNT(*) FROM runners").fetchone()[0]
    with_splits   = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE nether_enter_ms IS NOT NULL"
    ).fetchone()[0]

    print(f"\n  Total runs:           {total_runs}")
    print(f"  Unique runners:       {total_runners}")
    print(f"  Runs with splits:     {with_splits}")
    print(f"{'='*72}\n")


def compute_stats(conn: sqlite3.Connection) -> None:
    """Populate runner_stats and overall_stats from the runs table."""

    # ── Runner stats ─────────────────────────────────────────────────────────
    conn.execute("DELETE FROM runner_stats")
    conn.execute("""
        INSERT INTO runner_stats (runner_id, total_runs, sub_9, sub_8, sub_7, best_lb_pos)
        SELECT
            r.runner_id,
            COUNT(*)                                                        AS total_runs,
            SUM(CASE WHEN r.re_timed_time_ms <  9 * 60000 THEN 1 ELSE 0 END) AS sub_9,
            SUM(CASE WHEN r.re_timed_time_ms <  8 * 60000 THEN 1 ELSE 0 END) AS sub_8,
            SUM(CASE WHEN r.re_timed_time_ms <  7 * 60000 THEN 1 ELSE 0 END) AS sub_7,
            lb.lb_position
        FROM runs r
        LEFT JOIN leaderboard lb ON lb.runner = (
            SELECT name FROM runners WHERE id = r.runner_id
        )
        GROUP BY r.runner_id
    """)

    # ── Overall stats ─────────────────────────────────────────────────────────
    conn.execute("DELETE FROM overall_stats")
    conn.execute("""
        INSERT INTO overall_stats (id, total_runs, sub_9, sub_8, sub_7)
        SELECT
            1,
            COUNT(*),
            SUM(CASE WHEN re_timed_time_ms <  9 * 60000 THEN 1 ELSE 0 END),
            SUM(CASE WHEN re_timed_time_ms <  8 * 60000 THEN 1 ELSE 0 END),
            SUM(CASE WHEN re_timed_time_ms <  7 * 60000 THEN 1 ELSE 0 END)
        FROM runs
        WHERE re_timed_time_ms IS NOT NULL
          AND speedrun_com_status != 'Banned'
    """)

    conn.commit()
    print("Stats precomputed.")

# ── Main ──────────────────────────────────────────────────────────────────────

def run_pipeline(csv_path: str) -> None:
    info = "  [INFO] "
    print(f"{info}Loading CSV from: {csv_path}")
    runs = load_csv(csv_path)
    print(f"{info}Loaded {len(runs)} runs from CSV.")

    print(f"{info}Initialising database at: {DB_PATH}")
    conn = init_db(DB_PATH)

    # Clear existing data so re-runs don't duplicate
    conn.execute("DELETE FROM runs")
    conn.execute("DELETE FROM runners")
    conn.commit()

    insert_runs(conn, runs)
    print(f"{info}Insert complete.")

    compute_stats(conn)


    preview(conn)
    conn.close()
    print("Done.")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--download" in args:
        csv_path = download_sheet(SHEET_URL)
    else:
        csv_path = get_csv_path()

    run_pipeline(csv_path)