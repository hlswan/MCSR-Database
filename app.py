import sqlite3
import os
from flask import Flask, render_template, g, request

app = Flask(__name__)

DB_PATH = os.path.join("data", "leaderboard.db")
COURIWAY_DB_PATH = os.path.join("data", "couriway_runs.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row  # lets us access columns by name
    return g.db


@app.template_filter("format_ms")
def format_ms(ms):
    """Convert milliseconds to M:SS.mmm display string."""
    if ms is None:
        return "—"
    total_s = ms / 1000
    m = int(total_s // 60)
    s = total_s % 60
    return f"{m}:{s:06.3f}"


@app.template_filter("format_int")
def format_int(n):
    """Format integer with comma thousands separator."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.route("/")
def leaderboard():
    db   = get_db()
    view = request.args.get("view", "leaderboard")  # "leaderboard" or "all"

    if view == "all":
        runs = db.execute("""
            SELECT position, flag, runner, in_game_time_raw, re_timed_time_raw,
                   date, speedrun_com_status, link
            FROM all_runs_ranked
            ORDER BY position ASC
        """).fetchall()
    else:
        view = "leaderboard"  # sanitise unexpected values
        runs = db.execute("""
            SELECT lb_position AS position, flag, runner, in_game_time_raw, re_timed_time_raw,
                   date, speedrun_com_status, link
            FROM leaderboard
            ORDER BY lb_position ASC
        """).fetchall()

    return render_template("leaderboard.html", runs=runs, view=view)


@app.route("/stats")
def stats():
    db = get_db()
    runs = db.execute("""
        SELECT runner, re_timed_time_ms, date, speedrun_com_status, is_pb, is_wr
        FROM all_runs_ranked
        WHERE speedrun_com_status != 'Banned'
          AND re_timed_time_ms IS NOT NULL
          AND date IS NOT NULL
        ORDER BY date ASC
    """).fetchall()
    return render_template("stats.html", runs=runs)


@app.route("/couriway")
def couriway():
    view = request.args.get("view", "recent")

    conn = sqlite3.connect(COURIWAY_DB_PATH)
    conn.row_factory = sqlite3.Row

    # ── Filtered run list ──────────────────────────────────────────────────
    if view == "all":
        runs = conn.execute("""
            SELECT * FROM runs ORDER BY run_id DESC
        """).fetchall()
    elif view == "best":
        runs = conn.execute("""
            SELECT * FROM runs
            WHERE igt_ms IS NOT NULL
            ORDER BY igt_ms ASC
            LIMIT 100
        """).fetchall()
    elif view == "sub20":
        runs = conn.execute("""
            SELECT * FROM runs
            WHERE igt_ms IS NOT NULL AND igt_ms < 1200000
            ORDER BY igt_ms ASC
        """).fetchall()
    else:  # recent (default)
        runs = conn.execute("""
            SELECT * FROM runs ORDER BY run_id DESC LIMIT 100
        """).fetchall()

    # ── Summary stats ──────────────────────────────────────────────────────
    row = conn.execute("""
        SELECT
            COUNT(*)                              AS total,
            MIN(igt_ms)                           AS best_igt_ms,
            AVG(igt_ms)                           AS avg_igt_ms,
            SUM(CASE WHEN igt_ms < 1200000 THEN 1 ELSE 0 END) AS sub_20
        FROM runs
        WHERE igt_ms IS NOT NULL
    """).fetchone()

    avg_last_25 = conn.execute("""
        SELECT AVG(igt_ms) FROM (
            SELECT igt_ms FROM runs
            WHERE igt_ms IS NOT NULL
            ORDER BY run_id DESC LIMIT 25
        )
    """).fetchone()[0]

    avg_last_100 = conn.execute("""
        SELECT AVG(igt_ms) FROM (
            SELECT igt_ms FROM runs
            WHERE igt_ms IS NOT NULL
            ORDER BY run_id DESC LIMIT 100
        )
    """).fetchone()[0]

    total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    conn.close()

    def ms_to_display(ms):
        if ms is None:
            return "—"
        total_s = ms / 1000
        m = int(total_s // 60)
        s = total_s % 60
        return f"{m}:{s:06.3f}"

    stats = {
        "best_igt": ms_to_display(row["best_igt_ms"]),
        "avg_igt": ms_to_display(int(row["avg_igt_ms"])) if row["avg_igt_ms"] else "—",
        "sub_20_count": row["sub_20"] or 0,
        "avg_last_25": ms_to_display(int(avg_last_25)) if avg_last_25 else "—",
        "avg_last_100": ms_to_display(int(avg_last_100)) if avg_last_100 else "—",
    }

    return render_template(
        "couriway.html",
        runs=runs,
        stats=stats,
        view=view,
        total_runs=total_runs,
    )


if __name__ == "__main__":
    app.run(debug=True)