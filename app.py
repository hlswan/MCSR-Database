import sqlite3
import os
from flask import Flask, render_template, g, request

app = Flask(__name__)

DB_PATH = os.path.join("data", "leaderboard.db")
COURIWAY_DB_PATH = os.path.join("data", "couriway_runs.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
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
    view = request.args.get("view", "leaderboard")

    if view == "all":
        runs = db.execute("""
            SELECT position, flag, runner, in_game_time_raw, re_timed_time_raw,
                   date, speedrun_com_status, link
            FROM all_runs_ranked
            ORDER BY position ASC
        """).fetchall()
    else:
        view = "leaderboard"
        runs = db.execute("""
            SELECT lb_position AS position, flag, runner, in_game_time_raw, re_timed_time_raw,
                   date, speedrun_com_status, link
            FROM leaderboard
            ORDER BY lb_position ASC
        """).fetchall()

    return render_template("leaderboard.html", runs=runs, view=view)


@app.route("/stats")
def stats():
    return render_template("stats.html")


@app.route("/stats/player")
def stats_player():
    db = get_db()
    runner_name = request.args.get("runner", "").strip()

    # All runner names for search suggestions
    all_runners = db.execute("""
        SELECT name FROM runners ORDER BY name ASC
    """).fetchall()
    all_runner_names = [r["name"] for r in all_runners]

    # World record progression — all runs marked is_wr, ordered by date
    wr_runs = db.execute("""
        SELECT rn.name AS runner, r.re_timed_time_ms, r.date
        FROM runs r
        JOIN runners rn ON rn.id = r.runner_id
        WHERE r.is_wr = 1
          AND r.re_timed_time_ms IS NOT NULL
          AND r.date IS NOT NULL
        ORDER BY r.date ASC
    """).fetchall()

    selected_runner = None
    runner_stats    = None
    runner_runs     = None
    pb_progression  = None

    if runner_name:
        # Check runner exists
        row = db.execute(
            "SELECT id, name, flag FROM runners WHERE name = ?", (runner_name,)
        ).fetchone()

        if row:
            selected_runner = dict(row)
            runner_id = row["id"]

            # All runs for this runner ordered by date
            runner_runs = db.execute("""
                SELECT r.re_timed_time_ms, r.re_timed_time_raw,
                       r.in_game_time_raw, r.date, r.speedrun_com_status,
                       r.link, r.is_wr, r.is_pb
                FROM runs r
                WHERE r.runner_id = ?
                  AND r.re_timed_time_ms IS NOT NULL
                ORDER BY r.date ASC, r.re_timed_time_ms ASC
            """, (runner_id,)).fetchall()

            # Leaderboard position and PB
            lb_row = db.execute("""
                SELECT lb_position, re_timed_time_raw, re_timed_time_ms
                FROM leaderboard
                WHERE runner = ?
            """, (runner_name,)).fetchone()

            # Sub counts
            sub_counts = db.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN re_timed_time_ms < 600000  THEN 1 ELSE 0 END) AS sub10,
                    SUM(CASE WHEN re_timed_time_ms < 540000  THEN 1 ELSE 0 END) AS sub9,
                    SUM(CASE WHEN re_timed_time_ms < 480000  THEN 1 ELSE 0 END) AS sub8,
                    SUM(CASE WHEN re_timed_time_ms < 420000  THEN 1 ELSE 0 END) AS sub7
                FROM runs
                WHERE runner_id = ?
                  AND re_timed_time_ms IS NOT NULL
            """, (runner_id,)).fetchone()

            # PB progression — each time a new PB was set, ordered by date
            pb_progression_rows = db.execute("""
                SELECT re_timed_time_ms, date
                FROM runs
                WHERE runner_id = ?
                  AND is_pb = 1
                  AND re_timed_time_ms IS NOT NULL
                  AND date IS NOT NULL
                ORDER BY date ASC
            """, (runner_id,)).fetchall()

            runner_stats = {
                "lb_position":   lb_row["lb_position"] if lb_row else None,
                "pb":            lb_row["re_timed_time_raw"] if lb_row else None,
                "pb_ms":         lb_row["re_timed_time_ms"] if lb_row else None,
                "total":         sub_counts["total"],
                "sub10":         sub_counts["sub10"] or 0,
                "sub9":          sub_counts["sub9"]  or 0,
                "sub8":          sub_counts["sub8"]  or 0,
                "sub7":          sub_counts["sub7"]  or 0,
            }

            pb_progression = [dict(r) for r in pb_progression_rows]

    return render_template(
        "player_stats.html",
        all_runner_names=all_runner_names,
        selected_runner=selected_runner,
        runner_stats=runner_stats,
        runner_runs=runner_runs,
        pb_progression=pb_progression,
        wr_runs=[dict(r) for r in wr_runs],
        runner_name=runner_name,
    )


@app.route("/stats/runs")
def stats_runs():
    return render_template("run_stats.html")



if __name__ == "__main__":
    app.run(debug=True)