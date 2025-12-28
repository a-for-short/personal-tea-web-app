from flask import Flask, render_template, request, redirect, url_for
from flask_wtf.csrf import CSRFProtect
import sqlite3
from markupsafe import Markup
import os
import logging
from logging.handlers import RotatingFileHandler
import time

# ==================== CONFIGURATION ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())
csrf = CSRFProtect(app)
DB_PATH = "/app/data/tea.db"

# ==================== LOGGING SETUP ====================
# Simple logging setup at the top of app.py, after imports:
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== VALIDATION ====================
def validate_float(value, default=0.0, min_val=None, max_val=None):
    """Validate and convert to float with bounds checking"""
    try:
        if value is None or value == '':
            return default
        val = float(value)
        if min_val is not None and val < min_val:
            return min_val
        if max_val is not None and val > max_val:
            return max_val
        return val
    except (ValueError, TypeError):
        return default

def validate_text(value, max_length=None):
    """Validate text input"""
    if value is None:
        return ""
    text = str(value).strip()
    if max_length and len(text) > max_length:
        return text[:max_length]
    return text

def validate_tea_name(name):
    """Validate tea name - cannot be empty"""
    name = validate_text(name, max_length=100)
    if not name or len(name.strip()) == 0:
        raise ValueError("Tea name cannot be empty")
    return name

def validate_location_name(name):
    """Validate location name"""
    name = validate_text(name, max_length=50)
    if not name or len(name.strip()) == 0:
        raise ValueError("Location name cannot be empty")
    return name

# ==================== DATABASE ====================
class DatabaseConnection:
    """Context manager for safe database operations"""
    
    def __init__(self):
        self.conn = None
    
    def __enter__(self):
        """Establish database connection with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.conn = sqlite3.connect(DB_PATH, timeout=30)
                self.conn.row_factory = sqlite3.Row
                self.conn.execute("PRAGMA foreign_keys = ON")
                self.conn.execute("PRAGMA journal_mode = WAL")
                self.conn.execute("PRAGMA synchronous = NORMAL")
                self.conn.execute("PRAGMA busy_timeout = 5000")
                return self.conn
            except sqlite3.Error as e:
                logger.error(f"DB connection attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))
        raise sqlite3.Error("Failed to connect to database")
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up database connection"""
        if self.conn:
            if exc_type is not None:
                self.conn.rollback()
                logger.error(f"Database error in context: {exc_val}")
            else:
                self.conn.commit()
            self.conn.close()
        return False

def init_db():
    """Initialize database schema"""
    try:
        with DatabaseConnection() as conn:
            cur = conn.cursor()
            
            # Create locations table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT DEFAULT ''
                )
            """)
            
            # Create tea table
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
            
            # Create tea_location junction table
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
            
            # Add default locations
            default_locations = [
                ('home', 'Home'),
                ('work', 'Work'),
                ('parents', 'Parents'),
            ]
            
            for loc_name, loc_desc in default_locations:
                cur.execute(
                    "INSERT OR IGNORE INTO locations (name, description) VALUES (?, ?)",
                    (loc_name, loc_desc)
                )
            
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")
        raise

# Initialize database on startup
init_db()

# ==================== TEMPLATE FILTERS ====================
@app.template_filter('nl2br')
def nl2br_filter(s):
    """Convert newlines to <br> tags for display"""
    if s:
        return Markup(s.replace("\n", "<br>"))
    return ""

# ==================== ROUTES ====================
@app.route("/", methods=["GET", "POST"])
def index():
    """Main admin page for managing teas and locations"""
    try:
        with DatabaseConnection() as conn:
            cur = conn.cursor()
            
            # Get all locations
            cur.execute("SELECT id, name, description FROM locations ORDER BY name")
            locations = cur.fetchall()
            
            # Handle POST requests
            if request.method == "POST":
                # Remove tea
                if "remove_tea" in request.form:
                    tea_id = request.form.get("remove_tea")
                    if tea_id and tea_id.isdigit():
                        try:
                            cur.execute("DELETE FROM tea WHERE id = ?", (tea_id,))
                            logger.info(f"Deleted tea ID {tea_id}")
                        except sqlite3.Error as e:
                            logger.error(f"Failed to delete tea {tea_id}: {e}")
                
                # Add new location
                elif "add_location" in request.form:
                    try:
                        loc_name = validate_location_name(request.form.get("location_name", ""))
                        loc_desc = validate_text(request.form.get("location_desc", ""), max_length=100) or loc_name
                        
                        cur.execute("""
                            INSERT OR IGNORE INTO locations (name, description) VALUES (?, ?)
                        """, (loc_name, loc_desc))
                        
                        new_loc_id = cur.lastrowid
                        if new_loc_id:
                            # Add entries for existing teas
                            cur.execute("SELECT id FROM tea")
                            tea_ids = [row['id'] for row in cur.fetchall()]
                            for tea_id in tea_ids:
                                cur.execute("""
                                    INSERT OR IGNORE INTO tea_location (tea_id, location_id, amount)
                                    VALUES (?, ?, 0)
                                """, (tea_id, new_loc_id))
                            logger.info(f"Added location: {loc_name}")
                    
                    except ValueError as e:
                        logger.warning(f"Invalid location data: {e}")
                    except sqlite3.Error as e:
                        logger.error(f"Failed to add location: {e}")
                
                # Add new tea
                elif "add_tea" in request.form:
                    try:
                        name = validate_tea_name(request.form.get("name", ""))
                        tea_type = validate_text(request.form.get("type", ""), max_length=50)
                        dose = validate_float(request.form.get("dose", 4.0), min_val=0.1, max_val=100.0)
                        notes = validate_text(request.form.get("notes", ""), max_length=1000)
                        seller = validate_text(request.form.get("seller", ""), max_length=100)
                        price = validate_float(request.form.get("price", 0), min_val=0.0, max_val=10000.0)
                        grams_bought = validate_float(request.form.get("grams_bought", 0), min_val=0.0, max_val=100000.0)
                        
                        cur.execute("""
                            INSERT INTO tea (name, type, default_dose, notes, seller, price_per_gram, grams_bought)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (name, tea_type, dose, notes, seller, price, grams_bought))
                        
                        tea_id = cur.lastrowid
                        # Create entries for all locations
                        for location in locations:
                            cur.execute("""
                                INSERT INTO tea_location (tea_id, location_id, amount)
                                VALUES (?, ?, 0)
                            """, (tea_id, location['id']))
                        
                        logger.info(f"Added tea: {name}")
                    
                    except ValueError as e:
                        logger.warning(f"Invalid tea data: {e}")
                    except sqlite3.Error as e:
                        logger.error(f"Failed to add tea: {e}")
                
                # Update all teas
                elif "update_tea" in request.form:
                    try:
                        cur.execute("BEGIN TRANSACTION")
                        cur.execute("SELECT id FROM tea ORDER BY id")
                        tea_ids = [row['id'] for row in cur.fetchall()]
                        
                        for tea_id in tea_ids:
                            try:
                                # Update tea info
                                name = validate_tea_name(request.form.get(f"name_{tea_id}", ""))
                                tea_type = validate_text(request.form.get(f"type_{tea_id}", ""), max_length=50)
                                default_dose = validate_float(request.form.get(f"dose_{tea_id}", "4.0"), min_val=0.1, max_val=100.0)
                                notes = validate_text(request.form.get(f"notes_{tea_id}", ""), max_length=1000)
                                seller = validate_text(request.form.get(f"seller_{tea_id}", ""), max_length=100)
                                price = validate_float(request.form.get(f"price_{tea_id}", "0"), min_val=0.0, max_val=10000.0)
                                grams_bought = validate_float(request.form.get(f"grams_bought_{tea_id}", "0"), min_val=0.0, max_val=100000.0)
                                
                                cur.execute("""
                                    UPDATE tea SET
                                    name=?, type=?, default_dose=?, notes=?, seller=?,
                                    price_per_gram=?, grams_bought=? WHERE id=?
                                """, (name, tea_type, default_dose, notes, seller, price, grams_bought, tea_id))
                                
                                # Update location amounts
                                for location in locations:
                                    amount_key = f"location_{location['id']}_{tea_id}"
                                    amount = validate_float(request.form.get(amount_key, "0"), min_val=0.0, max_val=100000.0)
                                    cur.execute("""
                                        INSERT OR REPLACE INTO tea_location (tea_id, location_id, amount)
                                        VALUES (?, ?, ?)
                                    """, (tea_id, location['id'], amount))
                            
                            except ValueError as e:
                                logger.warning(f"Validation error for tea {tea_id}: {e}")
                                continue
                        
                        conn.commit()
                        logger.info(f"Updated {len(tea_ids)} teas")
                    
                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Failed to update teas: {e}")
            
            # Get all teas with their location amounts
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
    
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        return render_template("error.html", 
                             error_message="An error occurred while loading the page. Please try again."), 500

@app.route("/brew", methods=["GET", "POST"])
def brew():
    """Brew tea landing page"""
    if request.method == "POST":
        return redirect(url_for("select_location"))
    return render_template("brew.html")

@app.route("/select_location", methods=["GET", "POST"])
def select_location():
    """Choose location for brewing"""
    try:
        with DatabaseConnection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT l.id, l.name, l.description,
                       COALESCE(SUM(tl.amount > 0), 0) as tea_count
                FROM locations l
                LEFT JOIN tea_location tl ON l.id = tl.location_id
                GROUP BY l.id
                ORDER BY l.name
            """)
            
            locations = [dict(row) for row in cur.fetchall()]
            
            if request.method == "POST":
                location_id = request.form.get("location")
                if location_id and location_id.isdigit():
                    return redirect(url_for("brew_result", location_id=int(location_id)))
            
            return render_template("select_location.html", locations=locations)
    
    except Exception as e:
        logger.error(f"Error in select_location route: {e}")
        return render_template("error.html",
                             error_message="Unable to load locations. Please try again."), 500

@app.route("/brew_result/<int:location_id>", methods=["GET", "POST"])
def brew_result(location_id):
    """Brew tea at selected location"""
    try:
        with DatabaseConnection() as conn:
            cur = conn.cursor()
            
            # Get location info
            cur.execute("SELECT * FROM locations WHERE id = ?", (location_id,))
            location = cur.fetchone()
            if not location:
                logger.warning(f"Location {location_id} not found")
                return redirect(url_for("select_location"))
            
            # Find tea with most amount at this location
            cur.execute("""
                SELECT t.*, tl.amount
                FROM tea t
                JOIN tea_location tl ON t.id = tl.tea_id
                WHERE tl.location_id = ? AND tl.amount > 0
                ORDER BY tl.amount DESC, t.name ASC
                LIMIT 1
            """, (location_id,))
            
            tea = cur.fetchone()
            
            if request.method == "POST" and tea:
                try:
                    review = validate_text(request.form.get("review", ""), max_length=500)
                    new_amount = max(tea['amount'] - (tea['default_dose'] or 4.0), 0)
                    
                    cur.execute("""
                        UPDATE tea_location SET amount = ?
                        WHERE tea_id = ? AND location_id = ?
                    """, (new_amount, tea['id'], location_id))
                    
                    if review:
                        # Get current notes and append new review
                        cur.execute("SELECT notes FROM tea WHERE id = ?", (tea['id'],))
                        current_notes = cur.fetchone()['notes'] or ""
                        updated_notes = f"{current_notes}\n[{location['description']}] {review}".strip()
                        
                        cur.execute("UPDATE tea SET notes = ? WHERE id = ?",
                                   (updated_notes, tea['id']))
                    
                    logger.info(f"Brewed tea '{tea['name']}' at {location['description']}")
                
                except Exception as e:
                    logger.error(f"Error brewing tea: {e}")
                    # Continue to redirect anyway
                
                return redirect(url_for("brew_result", location_id=location_id))
            
            return render_template("brew_result.html", tea=tea, location=location)
    
    except Exception as e:
        logger.error(f"Error in brew_result route for location {location_id}: {e}")
        return render_template("error.html",
                             error_message="Unable to process brewing. Please try again."), 500

@app.route("/health")
def health():
    """Health check endpoint"""
    try:
        with DatabaseConnection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            if cur.fetchone()[0] == 1:
                return "OK", 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
    return "ERROR", 500

# ==================== ERROR HANDLERS ====================
@app.errorhandler(400)
def bad_request(error):
    logger.warning(f"Bad request: {error}")
    return render_template("error.html",
                         error_message="Bad request. Please check your input."), 400

@app.errorhandler(404)
def not_found(error):
    logger.info(f"Page not found: {request.path}")
    return render_template("error.html",
                         error_message="Page not found."), 404

@app.errorhandler(405)
def method_not_allowed(error):
    logger.warning(f"Method not allowed: {request.method} {request.path}")
    return render_template("error.html",
                         error_message="Method not allowed."), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return render_template("error.html",
                         error_message="Internal server error. Please try again later."), 500

@app.errorhandler(Exception)
def handle_unhandled_exception(error):
    logger.critical(f"Unhandled exception: {error}", exc_info=True)
    return render_template("error.html",
                         error_message="An unexpected error occurred. Please try again."), 500

# ==================== MAIN ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)