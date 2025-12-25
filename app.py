from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from pathlib import Path

app = Flask(__name__)
DB_PATH = Path("tea.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tea (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT,
        default_dose REAL,
        notes TEXT
    )
    """)

    conn.commit()
    conn.close()


@app.route("/", methods=["GET", "POST"])
def index():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        name = request.form["name"]
        tea_type = request.form["type"]
        dose = request.form["dose"]
        notes = request.form["notes"]

        cur.execute(
            "INSERT INTO tea (name, type, default_dose, notes) VALUES (?, ?, ?, ?)",
            (name, tea_type, dose, notes)
        )
        conn.commit()
        return redirect(url_for("index"))

    cur.execute("SELECT * FROM tea ORDER BY id DESC")
    teas = cur.fetchall()
    conn.close()

    return render_template("index.html", teas=teas)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
