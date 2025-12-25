from flask import Flask, render_template, request, redirect, url_for, Response
import sqlite3
from markupsafe import Markup
import os
from functools import wraps

app = Flask(__name__)
DB_PATH = "tea.db"

# ----------------- БАЗОВАЯ АУТЕНТИФИКАЦИЯ -----------------
def check_auth(username, password):
    return (username == os.environ.get('ADMIN_USERNAME', 'admin') and 
            password == os.environ.get('ADMIN_PASSWORD', 'changeme123'))

def authenticate():
    return Response(
        'Please login',
        401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# ----------------- ФИЛЬТР ШАБЛОНОВ -----------------
@app.template_filter('nl2br')
def nl2br_filter(s):
    if s:
        return Markup(s.replace("\n", "<br>"))
    return ""

# ----------------- РАБОТА С БАЗОЙ ДАННЫХ -----------------
def get_db_connection():
    """Создает и возвращает соединение с БД с таймаутом"""
    conn = sqlite3.connect(DB_PATH, timeout=30)  # Увеличенный таймаут
    conn.row_factory = sqlite3.Row
    # Включаем поддержку внешних ключей
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Инициализация базы данных"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Таблица локаций
        cur.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT ''
        )
        """)
        
        # Таблица чая
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tea (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT DEFAULT '',
            default_dose REAL DEFAULT 4.0,
            notes TEXT DEFAULT '',
            seller TEXT DEFAULT '',
            price_per_gram REAL DEFAULT 0,
            grams_bought REAL NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Таблица количества чая по локациям
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tea_location (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tea_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            amount REAL DEFAULT 0,
            FOREIGN KEY(tea_id) REFERENCES tea(id) ON DELETE CASCADE,
            FOREIGN KEY(location_id) REFERENCES locations(id) ON DELETE CASCADE,
            UNIQUE(tea_id, location_id)
        )
        """)
        
        # Добавляем стандартные локации, если их нет
        default_locations = [
            ('home', '🏠 Дом'),
            ('work', '💼 Работа'),
        ]
        
        for loc_name, loc_desc in default_locations:
            cur.execute("INSERT OR IGNORE INTO locations (name, description) VALUES (?, ?)", 
                       (loc_name, loc_desc))
        
        conn.commit()
    finally:
        conn.close()

# Инициализируем БД при запуске
init_db()

# ----------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ -----------------
def get_all_locations():
    """Получить все локации"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, description FROM locations ORDER BY name")
        return cur.fetchall()
    finally:
        conn.close()

def get_tea_with_locations():
    """Получить все чаи с информацией о локациях"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Получаем все чаи
        cur.execute("SELECT * FROM tea ORDER BY id DESC")
        teas = cur.fetchall()
        
        # Получаем все локации
        cur.execute("SELECT id FROM locations")
        location_ids = [row['id'] for row in cur.fetchall()]
        
        # Для каждого чая получаем количество в каждой локации
        result = []
        for tea in teas:
            tea_dict = dict(tea)
            tea_dict['locations'] = {}
            
            for loc_id in location_ids:
                cur.execute("""
                    SELECT amount FROM tea_location 
                    WHERE tea_id = ? AND location_id = ?
                """, (tea['id'], loc_id))
                row = cur.fetchone()
                tea_dict['locations'][loc_id] = row['amount'] if row else 0
            
            result.append(tea_dict)
        
        return result
    finally:
        conn.close()

# ----------------- МАРШРУТЫ -----------------
@app.route("/", methods=["GET", "POST"])
@requires_auth
def index():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Получаем все локации
        cur.execute("SELECT id, name, description FROM locations ORDER BY name")
        locations = cur.fetchall()
        
        # УДАЛЕНИЕ ЧАЯ
        if request.method == "POST" and "remove_tea" in request.form:
            tea_id = request.form.get("remove_tea")
            if tea_id:
                cur.execute("DELETE FROM tea WHERE id = ?", (tea_id,))
                conn.commit()
        
        # ДОБАВЛЕНИЕ НОВОЙ ЛОКАЦИИ
        elif request.method == "POST" and "add_location" in request.form:
            loc_name = request.form.get("location_name", "").strip()
            loc_desc = request.form.get("location_desc", "").strip()
            if loc_name:
                if not loc_desc:
                    loc_desc = loc_name
                
                cur.execute("INSERT INTO locations (name, description) VALUES (?, ?)", 
                           (loc_name, loc_desc))
                new_loc_id = cur.lastrowid
                
                # Для существующих чаев создаем записи в новой локации
                cur.execute("SELECT id FROM tea")
                tea_ids = [row['id'] for row in cur.fetchall()]
                for tea_id in tea_ids:
                    cur.execute("""
                        INSERT OR IGNORE INTO tea_location (tea_id, location_id, amount)
                        VALUES (?, ?, 0)
                    """, (tea_id, new_loc_id))
                
                conn.commit()
                # Обновляем список локаций
                cur.execute("SELECT id, name, description FROM locations ORDER BY name")
                locations = cur.fetchall()
        
        # ДОБАВЛЕНИЕ НОВОГО ЧАЯ
        elif request.method == "POST" and "add_tea" in request.form:
            name = request.form.get("name", "").strip()
            if name:
                tea_type = request.form.get("type", "").strip()
                dose = float(request.form.get("dose") or 4.0)
                notes = request.form.get("notes", "").strip()
                seller = request.form.get("seller", "").strip()
                price = float(request.form.get("price") or 0)
                grams_bought = float(request.form.get("grams_bought") or 0)
                
                cur.execute("""
                    INSERT INTO tea (name, type, default_dose, notes, seller, price_per_gram, grams_bought)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (name, tea_type, dose, notes, seller, price, grams_bought))
                
                tea_id = cur.lastrowid
                
                # Создаем записи для всех локаций
                for location in locations:
                    cur.execute("""
                        INSERT INTO tea_location (tea_id, location_id, amount)
                        VALUES (?, ?, 0)
                    """, (tea_id, location['id']))
                
                conn.commit()
        
        # ОБНОВЛЕНИЕ ВСЕХ ЧАЕВ
        elif request.method == "POST" and "update_tea" in request.form:
            try:
                # Начинаем транзакцию
                cur.execute("BEGIN TRANSACTION")
                
                # Получаем все ID чаев
                cur.execute("SELECT id FROM tea ORDER BY id")
                tea_ids = [row['id'] for row in cur.fetchall()]
                
                for tea_id in tea_ids:
                    # Обновляем основную информацию о чае
                    name = request.form.get(f"name_{tea_id}", "").strip()
                    if not name:  # Пропускаем если имя пустое
                        continue
                    
                    tea_type = request.form.get(f"type_{tea_id}", "").strip()
                    default_dose_str = request.form.get(f"dose_{tea_id}", "4.0")
                    default_dose = float(default_dose_str) if default_dose_str else 4.0
                    notes = request.form.get(f"notes_{tea_id}", "").strip()
                    seller = request.form.get(f"seller_{tea_id}", "").strip()
                    price_str = request.form.get(f"price_{tea_id}", "0")
                    price = float(price_str) if price_str else 0.0
                    grams_bought_str = request.form.get(f"grams_bought_{tea_id}", "0")
                    grams_bought = float(grams_bought_str) if grams_bought_str else 0.0
                    
                    cur.execute("""
                        UPDATE tea
                        SET name=?, type=?, default_dose=?, notes=?, seller=?, price_per_gram=?, grams_bought=?
                        WHERE id=?
                    """, (name, tea_type, default_dose, notes, seller, price, grams_bought, tea_id))
                    
                    # Обновляем количество в локациях
                    for location in locations:
                        amount_key = f"location_{location['id']}_{tea_id}"
                        amount_str = request.form.get(amount_key, "0")
                        try:
                            amount = float(amount_str) if amount_str else 0.0
                        except (ValueError, TypeError):
                            amount = 0.0
                        
                        cur.execute("""
                            INSERT OR REPLACE INTO tea_location (tea_id, location_id, amount)
                            VALUES (?, ?, ?)
                        """, (tea_id, location['id'], amount))
                
                # Фиксируем транзакцию
                conn.commit()
                
            except Exception as e:
                # Откатываем транзакцию в случае ошибки
                conn.rollback()
                print(f"Ошибка при обновлении чаев: {e}")
                # Здесь можно добавить логирование ошибки
                raise
        
        # Получаем все чаи с информацией о локациях
        teas = []
        cur.execute("SELECT * FROM tea ORDER BY id DESC")
        all_teas = cur.fetchall()
        
        for tea in all_teas:
            tea_dict = dict(tea)
            tea_dict['locations'] = {}
            
            for location in locations:
                cur.execute("""
                    SELECT amount FROM tea_location 
                    WHERE tea_id = ? AND location_id = ?
                """, (tea['id'], location['id']))
                row = cur.fetchone()
                tea_dict['locations'][location['id']] = row['amount'] if row else 0
            
            teas.append(tea_dict)
        
        return render_template("index.html", teas=teas, locations=locations)
    
    finally:
        if conn:
            conn.close()

@app.route("/brew", methods=["GET", "POST"])
def brew():
    """Главная страница заваривания чая"""
    if request.method == "POST":
        return redirect(url_for("select_location"))
    
    return render_template("brew.html")

@app.route("/select_location", methods=["GET", "POST"])
def select_location():
    """Выбор локации для заваривания"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Получаем все локации с количеством доступного чая
        cur.execute("""
            SELECT l.id, l.name, l.description,
                   COALESCE(SUM(tl.amount > 0), 0) as tea_count
            FROM locations l
            LEFT JOIN tea_location tl ON l.id = tl.location_id
            GROUP BY l.id
            ORDER BY l.name
        """)
        
        locations = []
        for row in cur.fetchall():
            loc = dict(row)
            locations.append(loc)
        
        if request.method == "POST":
            location_id = request.form.get("location")
            if location_id:
                return redirect(url_for("brew_result", location_id=location_id))
        
        return render_template("select_location.html", locations=locations)
    
    finally:
        conn.close()

@app.route("/brew_result/<int:location_id>", methods=["GET", "POST"])
def brew_result(location_id):
    """Страница с выбранным чаем для заваривания"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Получаем информацию о локации
        cur.execute("SELECT * FROM locations WHERE id = ?", (location_id,))
        location = cur.fetchone()
        
        if not location:
            return redirect(url_for("select_location"))
        
        # Находим чай с наибольшим количеством в этой локации
        cur.execute("""
            SELECT t.*, tl.amount
            FROM tea t
            JOIN tea_location tl ON t.id = tl.tea_id
            WHERE tl.location_id = ? AND tl.amount > 0
            ORDER BY tl.amount DESC, t.name ASC
            LIMIT 1
        """, (location_id,))
        
        tea = cur.fetchone()
        
        if request.method == "POST":
            if tea:
                # Обновляем количество чая
                review = request.form.get("review", "").strip()
                new_amount = max(tea['amount'] - (tea['default_dose'] or 4.0), 0)
                
                cur.execute("""
                    UPDATE tea_location 
                    SET amount = ? 
                    WHERE tea_id = ? AND location_id = ?
                """, (new_amount, tea['id'], location_id))
                
                # Добавляем отзыв, если есть
                if review:
                    # Получаем текущие заметки
                    cur.execute("SELECT notes FROM tea WHERE id = ?", (tea['id'],))
                    current_notes_row = cur.fetchone()
                    current_notes = current_notes_row['notes'] if current_notes_row and current_notes_row['notes'] else ""
                    
                    # Добавляем новую заметку
                    updated_notes = current_notes
                    if current_notes:
                        updated_notes += "\n"
                    updated_notes += f"[{location['description']}] {review}"
                    
                    cur.execute("UPDATE tea SET notes = ? WHERE id = ?", 
                               (updated_notes, tea['id']))
                
                conn.commit()
                # Перенаправляем снова на эту же страницу (будет выбран следующий чай)
                return redirect(url_for("brew_result", location_id=location_id))
        
        return render_template("brew_result.html", tea=tea, location=location)
    
    finally:
        conn.close()

@app.route("/health")
def health():
    """Проверка здоровья приложения"""
    return "OK"

# Глобальная обработка ошибок
@app.errorhandler(500)
def internal_error(error):
    return "Внутренняя ошибка сервера. Пожалуйста, попробуйте позже.", 500

@app.errorhandler(404)
def not_found(error):
    return "Страница не найдена.", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # В продакшене отключаем debug
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)