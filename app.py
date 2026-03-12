import sqlite3
import os
from flask import Flask, render_template, g, request

app = Flask(__name__)

DB_PATH = os.path.join("data", "leaderboard.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row  # lets us access columns by name
    return g.db


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


if __name__ == "__main__":
    app.run(debug=True)