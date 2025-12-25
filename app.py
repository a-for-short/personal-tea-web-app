from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from markupsafe import Markup

app = Flask(__name__)
DB_PATH = "tea.db"

# ----------------- Filter -----------------
@app.template_filter('nl2br')
def nl2br_filter(s):
    if s:
        return Markup(s.replace("\n", "<br>"))
    return ""

# ----------------- DB -----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Create table if it doesn't exist
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tea (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT DEFAULT '',
        default_dose REAL DEFAULT 4,
        notes TEXT DEFAULT '',
        seller TEXT DEFAULT '',
        price_per_gram REAL DEFAULT 0,
        grams_bought REAL NOT NULL
    )
    """)

    # Ensure columns exist for old DBs
    for col, dtype, default in [
        ("type", "TEXT", "''"),
        ("default_dose", "REAL", "4"),
        ("notes", "TEXT", "''"),
        ("seller", "TEXT", "''"),
        ("price_per_gram", "REAL", "0")
    ]:
        try:
            cur.execute(f"ALTER TABLE tea ADD COLUMN {col} {dtype} DEFAULT {default}")
        except sqlite3.OperationalError:
            # Column already exists
            pass

    # Tea location table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tea_location (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tea_id INTEGER,
        location TEXT,
        amount REAL,
        FOREIGN KEY(tea_id) REFERENCES tea(id)
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ----------------- ADMIN / DEBUG -----------------
@app.route("/", methods=["GET", "POST"])
def index():
    conn = get_db()
    cur = conn.cursor()

    # ----------------- Remove tea -----------------
    if request.method == "POST" and "remove_tea" in request.form:
        tea_id = request.form.get("remove_tea")
        if tea_id:
            cur.execute("DELETE FROM tea WHERE id=?", (tea_id,))
            cur.execute("DELETE FROM tea_location WHERE tea_id=?", (tea_id,))
            conn.commit()

    # ----------------- Add new tea -----------------
    if request.method == "POST" and "add_tea" in request.form:
        name = request.form["name"].strip()
        if name:  # only add if name is provided
            tea_type = request.form.get("type", "")
            dose = float(request.form.get("dose") or 4)
            notes = request.form.get("notes", "")
            seller = request.form.get("seller", "")
            price = float(request.form.get("price") or 0)
            grams_bought = float(request.form.get("grams_bought") or 0)

            cur.execute("""
            INSERT INTO tea (name, type, default_dose, notes, seller, price_per_gram, grams_bought)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, tea_type, dose, notes, seller, price, grams_bought))
            tea_id = cur.lastrowid

            # Initialize home/work amounts
            for loc in ("home", "work"):
                cur.execute("""
                INSERT INTO tea_location (tea_id, location, amount)
                VALUES (?, ?, ?)
                """, (tea_id, loc, 0))
            conn.commit()

    # ----------------- Update teas -----------------
    if request.method == "POST" and "update_tea" in request.form:
        cur.execute("SELECT id FROM tea")
        tea_ids = [row[0] for row in cur.fetchall()]
        for tea_id in tea_ids:
            name = request.form.get(f"name_{tea_id}", "").strip()
            tea_type = request.form.get(f"type_{tea_id}", "")
            default_dose = float(request.form.get(f"dose_{tea_id}") or 4)
            notes = request.form.get(f"notes_{tea_id}", "")
            seller = request.form.get(f"seller_{tea_id}", "")
            price = float(request.form.get(f"price_{tea_id}") or 0)
            grams_bought = float(request.form.get(f"grams_bought_{tea_id}") or 0)

            cur.execute("""
            UPDATE tea
            SET name=?, type=?, default_dose=?, notes=?, seller=?, price_per_gram=?, grams_bought=?
            WHERE id=?
            """, (name, tea_type, default_dose, notes, seller, price, grams_bought, tea_id))

            # Update home/work amounts
            home_val = float(request.form.get(f"home_{tea_id}", 0))
            work_val = float(request.form.get(f"work_{tea_id}", 0))
            cur.execute("UPDATE tea_location SET amount=? WHERE tea_id=? AND location='home'", (home_val, tea_id))
            cur.execute("UPDATE tea_location SET amount=? WHERE tea_id=? AND location='work'", (work_val, tea_id))

        conn.commit()

    # ----------------- Fetch teas -----------------
    cur.execute("""
    SELECT
        tea.id,
        tea.name,
        tea.type,
        tea.default_dose,
        tea.notes,
        tea.seller,
        tea.price_per_gram,
        tea.grams_bought,
        SUM(CASE WHEN location = 'home' THEN amount END) AS home_amount,
        SUM(CASE WHEN location = 'work' THEN amount END) AS work_amount
    FROM tea
    JOIN tea_location ON tea.id = tea_location.tea_id
    GROUP BY tea.id
    ORDER BY tea.id DESC
    """)
    teas = cur.fetchall()
    conn.close()

    return render_template("index.html", teas=teas)

# ----------------- BREW INTERFACE -----------------
@app.route("/brew", methods=["GET", "POST"])
def brew():
    if request.method == "POST":
        return redirect(url_for("select_location"))
    return render_template("brew.html")

@app.route("/select_location", methods=["GET", "POST"])
def select_location():
    if request.method == "POST":
        location = request.form["location"]
        return redirect(url_for("brew_result", location=location))
    return render_template("select_location.html")

@app.route("/brew_result/<location>", methods=["GET", "POST"])
def brew_result(location):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    SELECT tea.id, tea.name, tea.type, tea.default_dose, tea.notes, tea_location.amount
    FROM tea
    JOIN tea_location ON tea.id = tea_location.tea_id
    WHERE tea_location.location=? AND tea_location.amount>0
    ORDER BY tea.id ASC
    LIMIT 1
    """, (location,))
    tea = cur.fetchone()

    if tea is None:
        conn.close()
        return render_template("brew_result.html", location=location, tea=None)

    if request.method == "POST":
        new_amount = max(tea["amount"] - (tea["default_dose"] or 4), 0)
        review = request.form.get("review", "").strip()
        cur.execute("UPDATE tea_location SET amount=? WHERE tea_id=? AND location=?", (new_amount, tea["id"], location))
        if review:
            updated_notes = (tea["notes"] or "") + "\n" + review
            cur.execute("UPDATE tea SET notes=? WHERE id=?", (updated_notes, tea["id"]))
        conn.commit()
        conn.close()
        return redirect(url_for("brew_result", location=location))

    conn.close()
    return render_template("brew_result.html", location=location, tea=tea)

if __name__ == "__main__":
    app.run(debug=True)
