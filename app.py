"""
Free Online Shopping — Flask + SQLite (JSON-blob CMS) + Jinja2
* Public content editable from /admin CMS, saved to `site_data` table (JSON blob per key).
* Protected keys: admin_users, users, admin_account — never overwritten by plain re-import.
* Seed file site_data.json populates DB only on first boot; afterwards site.db is source of truth.
* Render persistent disk: set DATA_DIR=/opt/render/project/src/data
"""
import os, json, sqlite3, secrets, re, html
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
import urllib.request
import urllib.parse
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, g, abort, send_from_directory, jsonify)
from jinja2 import pass_context

# ---------- Config ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
APP_DOC_DIR = os.path.join(DATA_DIR, "app_docs")
os.makedirs(APP_DOC_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "site.db")
SEED_PATH = os.path.join(BASE_DIR, "site_data.json")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-free-online-shopping-change-me")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB uploads
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR

ALLOWED_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
MAGIC = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],  # + WEBP at bytes 8..12 (checked separately)
}
PROTECTED_KEYS = {"admin_users", "users", "admin_account"}

# scrypt unavailable on some system Pythons (Xcode build) — pin to pbkdf2
def hash_pw(pw: str) -> str:
    try:
        return generate_password_hash(pw, method="scrypt")
    except Exception:
        return generate_password_hash(pw, method="pbkdf2:sha256:600000")

# ---------- DB helpers ----------
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    first_boot = not os.path.exists(DB_PATH)
    con = db()
    con.execute("CREATE TABLE IF NOT EXISTS site_data (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS contact_messages
                   (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT,
                    subject TEXT, message TEXT, created TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS orders
                   (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT, email TEXT,
                    phone TEXT, address TEXT, city TEXT, notes TEXT,
                    items_json TEXT, total REAL, status TEXT DEFAULT 'pending', created TEXT)""")
    # payment columns migration (idempotent)
    _cols = [r["name"] for r in con.execute("PRAGMA table_info(orders)").fetchall()]
    for _col, _def in [
        ("payment_method", "TEXT"),
        ("payment_status", "TEXT DEFAULT 'pending'"),
        ("payment_reference", "TEXT"),
        ("receipt_path", "TEXT"),
        ("paid_at", "TEXT"),
    ]:
        if _col not in _cols:
            con.execute(f"ALTER TABLE orders ADD COLUMN {_col} {_def}")
    con.execute("""CREATE TABLE IF NOT EXISTS admin_payments (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   type TEXT DEFAULT 'ad_fee',
                   user_id TEXT,
                   product_id INTEGER,
                   amount REAL,
                   currency TEXT DEFAULT 'SSP',
                   method TEXT,
                   status TEXT DEFAULT 'pending',
                   reference TEXT,
                   receipt_path TEXT,
                   created TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS applications
                   (id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, name TEXT, email TEXT,
                    phone TEXT, message TEXT, doc TEXT, status TEXT DEFAULT 'new', created TEXT)""")
    con.commit()
    # seed on first boot only
    row = con.execute("SELECT COUNT(*) AS n FROM site_data").fetchone()
    if row["n"] == 0 and os.path.exists(SEED_PATH):
        with open(SEED_PATH, "r", encoding="utf-8") as f:
            seed = json.load(f)
        for k, v in seed.items():
            con.execute("INSERT OR IGNORE INTO site_data(key,value) VALUES(?,?)",
                        (k, json.dumps(v) if not isinstance(v, str) else v if k.startswith("_") else json.dumps(v)))
        # ensure default admin exists
        ensure_default_admin(con)
        con.commit()
    else:
        ensure_default_admin(con)
        con.commit()
    con.close()

def ensure_default_admin(con=None):
    close = False
    if con is None:
        con = db(); close = True
    row = con.execute("SELECT value FROM site_data WHERE key='admin_users'").fetchone()
    admins = json.loads(row["value"]) if row else []
    if not admins:
        default_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
        admins = [{"username": os.environ.get("ADMIN_USERNAME", "admin"),
                   "pw_hash": hash_pw(default_pw),
                   "created": datetime.utcnow().isoformat()}]
        con.execute("INSERT OR REPLACE INTO site_data(key,value) VALUES('admin_users',?)",
                    (json.dumps(admins),))
        if close: con.commit()
    if close: con.close()

def get_blob(key, default=None):
    con = db()
    r = con.execute("SELECT value FROM site_data WHERE key=?", (key,)).fetchone()
    con.close()
    if not r: return default
    try: return json.loads(r["value"])
    except Exception: return r["value"]

def set_blob(key, value):
    con = db()
    con.execute("INSERT OR REPLACE INTO site_data(key,value) VALUES(?,?)", (key, json.dumps(value)))
    con.commit(); con.close()

def get_all_content():
    con = db()
    rows = con.execute("SELECT key,value FROM site_data").fetchall()
    con.close()
    out = {}
    for r in rows:
        try: out[r["key"]] = json.loads(r["value"])
        except Exception: out[r["key"]] = r["value"]
    return out

def safe_import_content(new_data: dict):
    """Merge imported JSON but NEVER overwrite protected keys."""
    con = db()
    count = 0
    for k, v in new_data.items():
        if k in PROTECTED_KEYS:
            continue
        con.execute("INSERT OR REPLACE INTO site_data(key,value) VALUES(?,?)", (k, json.dumps(v)))
        count += 1
    con.commit(); con.close()
    return count

# ---------- Auth / CSRF ----------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]

def valid_csrf(tok):
    return tok and session.get("_csrf") and secrets.compare_digest(str(tok), str(session.get("_csrf")))

def current_user():
    return session.get("user")

def is_admin():
    u = current_user()
    return bool(u and u.get("is_admin"))

def visible_products():
    """Public catalog: admin products + approved marketplace posts."""
    now = datetime.utcnow()
    out = []
    for p in get_blob("products", []):
        if p.get("post_type") == "user" and p.get("status") != "approved":
            continue
        if p.get("post_type") == "user":
            exp = p.get("expires_at")
            if exp:
                try:
                    if datetime.fromisoformat(exp) < now:
                        continue
                except ValueError:
                    pass
        out.append(p)
    return out

def is_expired(p):
    """Whether a marketplace post has expired."""
    exp = (p or {}).get("expires_at")
    if not exp:
        return False
    try:
        return datetime.fromisoformat(exp) < datetime.utcnow()
    except ValueError:
        return False

def expiry_label(p):
    """Human-readable expiry status for a post."""
    exp = (p or {}).get("expires_at")
    if not exp:
        return "no expiry"
    try:
        dt = datetime.fromisoformat(exp)
        if dt < datetime.utcnow():
            return "expired"
        delta = (dt - datetime.utcnow()).days
        if delta <= 7:
            return f"expires in {delta}d"
        return f"expires {dt.date().isoformat()}"
    except ValueError:
        return "no expiry"

def ad_fee():
    return int(get_blob("fees", {}).get("per_post", 5000))


def payment_enabled():
    """Whether the customer-facing payment system is switched on."""
    return bool(get_blob("site", {}).get("payment_enabled", True))

def user_record(username):
    for u in get_blob("users", []):
        if u.get("username") == username:
            return u
    return None

# ---------- Access rights ----------
# Every customer account carries a status plus a set of permission flags.
# Admins are never restricted.
ACCESS_STATUSES = ("active", "suspended", "blocked")
ACCESS_PERMS = {
    "shop": "Browse the shop and place orders",
    "sell": "Post products in the marketplace",
    "payment": "Manage payment methods and pay for orders",
    "apply": "Submit job applications",
    "contact": "Send messages through the contact form",
    "advertise": "Pay for advertising your own products",
}
DEFAULT_PERMS = {k: True for k in ACCESS_PERMS}

def user_status(rec):
    """Effective account status; missing/legacy accounts are active."""
    if not rec:
        return "active"
    st = rec.get("status", "active")
    return st if st in ACCESS_STATUSES else "active"

def user_perms(rec):
    """Effective permission map; unknown/absent flags default to allowed."""
    saved = (rec or {}).get("perms") or {}
    out = {}
    for k in ACCESS_PERMS:
        out[k] = bool(saved.get(k, True))
    return out

def has_perm(perm):
    """Whether the current user may perform a restricted action."""
    u = current_user()
    if not u:
        return False
    if u.get("is_admin"):
        return True
    rec = user_record(u.get("username", ""))
    if not rec:
        return False
    if user_status(rec) != "active":
        return False
    return user_perms(rec).get(perm, True)

def can_sell():
    """Seller right: always for admins, for shoppers only when granted by admin."""
    u = current_user()
    if not u:
        return False
    if u.get("is_admin"):
        return True
    rec = user_record(u.get("username", ""))
    return bool(rec and rec.get("can_sell") and has_perm("sell"))

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not current_user():
            flash("Please log in first.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_admin():
            flash("Admin login required.", "danger")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w

def perm_required(perm, guest_ok=True):
    """Gate a route on a customer permission flag (admins always pass).

    With guest_ok=True a not-yet-logged-in visitor is allowed through, so the
    check only bites for accounts an admin has actually restricted.
    """
    def deco(f):
        @wraps(f)
        def w(*a, **kw):
            u = current_user()
            if not u:
                if guest_ok:
                    return f(*a, **kw)
                flash("Please log in first.", "warning")
                return redirect(url_for("login", next=request.path))
            if not has_perm(perm):
                flash(f"Your account does not have the “{perm}” permission right now.", "danger")
                return redirect(url_for("index"))
            return f(*a, **kw)
        return w
    return deco

def find_user(username):
    users = get_blob("users", [])
    for u in users:
        if u.get("username","").lower() == username.lower():
            return u, False
    admins = get_blob("admin_users", [])
    for a in admins:
        if a.get("username","").lower() == username.lower():
            return a, True
    return None, False

def find_user_by_login(identifier):
    """Login accepts a username OR an email address (form says "Username or email").
    Matches the username first, then falls back to the email field."""
    ident = (identifier or "").strip().lower()
    if not ident:
        return None, False
    u, admin_flag = find_user(ident)
    if u:
        return u, admin_flag
    # email fallback — customer accounts first, then admin accounts
    for u in get_blob("users", []):
        if (u.get("email") or "").strip().lower() == ident:
            return u, False
    for a in get_blob("admin_users", []):
        if (a.get("email") or "").strip().lower() == ident:
            return a, True
    return None, False

# ---------- Uploads ----------
def allowed_ext(fname):
    return "." in fname and fname.rsplit(".",1)[1].lower() in ALLOWED_EXTS

def valid_magic(head: bytes, ext: str):
    ext = ext.lower()
    if ext == "webp":
        return head[:4] == b"RIFF" and len(head) >= 12 and head[8:12] == b"WEBP"
    for sig in MAGIC.get(ext, []):
        if head.startswith(sig):
            return True
    return False

def save_upload(file_storage):
    fname = secure_filename(file_storage.filename or "")
    if not fname or not allowed_ext(fname):
        return None, "File type not allowed (png/jpg/jpeg/webp/gif only)."
    ext = fname.rsplit(".",1)[1].lower()
    head = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if not valid_magic(head, ext):
        return None, "File content does not match its extension."
    unique = secrets.token_hex(8) + "_" + fname
    dest = os.path.join(UPLOAD_DIR, unique)
    file_storage.save(dest)
    return unique, None

DOC_EXTS = {"pdf", "doc", "docx", "txt", "rtf", "png", "jpg", "jpeg", "webp", "gif"}
DOC_MAGIC = {
    "pdf": [b"%PDF"],
    "doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    "docx": [b"PK\x03\x04"],
    "rtf": [b"{\\rtf"],
}

def save_doc_upload(file_storage):
    """Store applicant documents privately in APP_DOC_DIR (never under public /uploads)."""
    fname = secure_filename(file_storage.filename or "")
    ext = fname.rsplit(".", 1)[1].lower() if "." in fname else ""
    if not fname or ext not in DOC_EXTS:
        return None, "Document type not allowed (pdf/doc/docx/txt/rtf or image)."
    head = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if ext in DOC_MAGIC:
        if not any(head.startswith(sig) for sig in DOC_MAGIC[ext]):
            return None, "File content does not match its extension."
    elif ext in {"png", "jpg", "jpeg", "webp", "gif"}:
        if not valid_magic(head, ext):
            return None, "File content does not match its extension."
    else:  # txt — reject binary junk
        sample = file_storage.stream.read(512)
        file_storage.stream.seek(0)
        if b"\x00" in sample:
            return None, "Text file looks like binary data."
    unique = secrets.token_hex(8) + "_" + fname
    dest = os.path.join(APP_DOC_DIR, unique)
    file_storage.save(dest)
    return unique, None

# ---------- Email via HTTPS API (SMTP often blocked) ----------
def send_email_https(to_email, subject, body):
    """Try Resend HTTPS API if RESEND_API_KEY set; else log & store as flash. Returns (ok,msg)."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")
    if not api_key:
        app.logger.info(f"[email-mock] to={to_email} subject={subject} body={body[:200]}")
        return True, "logged (no RESEND_API_KEY set)"
    try:
        data = json.dumps({"from": from_email, "to": [to_email],
                           "subject": subject, "text": body}).encode()
        req = urllib.request.Request("https://api.resend.com/emails",
            data=data, headers={"Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return True, f"sent ({r.status})"
    except Exception as e:
        app.logger.warning(f"email failed: {e}")
        return False, str(e)

# ---------- Cart ----------
def get_cart():
    return session.get("cart", {})

def cart_detailed():
    products = {str(p.get("id")): p for p in get_blob("products", [])}
    cart = get_cart()
    items, total, count = [], 0.0, 0
    for pid, qty in cart.items():
        p = products.get(str(pid))
        if not p: continue
        qty = max(1, min(99, int(qty)))
        line = float(p.get("price", 0)) * qty
        total += line; count += qty
        items.append({"product": p, "qty": qty, "line": line})
    return items, total, count

# ---------- Language (multi-language support) ----------
DEFAULT_LANGUAGE = "en"
LANGUAGES_DIR = os.path.join(BASE_DIR, "static", "lang")


def load_languages():
    """Load all language JSON files from static/lang/."""
    langs = {}
    try:
        for fname in os.listdir(LANGUAGES_DIR):
            if fname.endswith(".json"):
                path = os.path.join(LANGUAGES_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                langs[data.get("code", fname[:-5])] = data
    except FileNotFoundError:
        pass
    if DEFAULT_LANGUAGE not in langs:
        langs[DEFAULT_LANGUAGE] = {
            "code": DEFAULT_LANGUAGE,
            "name": "English",
            "dir": "ltr",
            "strings": {},
        }
    return langs


LANGUAGES = load_languages()


@app.template_filter("t")
@pass_context
def translate(ctx, key, **kwargs):
    """Translate a key using the current language; fall back to English, then the key itself.

    Declared with ``pass_context`` on purpose: Jinja's optimizer constant-folds
    filters whose arguments are all literals (e.g. ``{{ 'nav.cart'|t }}``), which
    would bake the language of the *first* request into the compiled template
    and serve that language to every later request. Passing the context marks
    the filter as context-dependent, so it is evaluated per request.
    """
    lang_code = request.cookies.get("language") or DEFAULT_LANGUAGE
    lang = LANGUAGES.get(lang_code) or LANGUAGES.get(DEFAULT_LANGUAGE)
    strings = lang.get("strings", {}) if lang else {}
    text = strings.get(key)
    if text is None:
        en = LANGUAGES.get(DEFAULT_LANGUAGE, {})
        text = en.get("strings", {}).get(key)
    if text is None:
        text = key
    try:
        return text.format(**kwargs)
    except (KeyError, ValueError):
        return text


@app.context_processor
def inject_globals():
    content = get_all_content()
    site = content.get("site", {})
    _, _, cart_count = cart_detailed()
    try:
        c = db()
        n_apps = c.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        c.close()
    except Exception:
        n_apps = 0
    n_pend = sum(1 for x in get_blob("products", [])
                 if x.get("post_type") == "user"
                 and x.get("status") in ("pending", "reviewing"))
    n_sellreq = sum(1 for x in get_blob("users", [])
                    if x.get("sell_request") == "pending" and not x.get("can_sell"))
    currencies = site.get("currencies") or DEFAULT_CURRENCIES
    currency = request.cookies.get("currency") or site.get("currency", "SSP")
    if currency not in [c.get("code") for c in currencies]:
        currency = site.get("currency", "SSP")
    language = request.cookies.get("language") or DEFAULT_LANGUAGE
    if language not in LANGUAGES:
        language = DEFAULT_LANGUAGE
    lang_dir = LANGUAGES[language].get("dir", "ltr") if language in LANGUAGES else "ltr"
    currency_symbol = next((c.get("symbol") for c in currencies if c.get("code") == currency), site.get("currency", "SSP"))
    return dict(site=site, content=content, cart_count=cart_count,
                csrf=csrf_token(), json=json,
                n_apps=n_apps, n_pend=n_pend, n_sellreq=n_sellreq,
                currency=currency, currencies=currencies, currency_symbol=currency_symbol,
                language=language, languages=LANGUAGES, lang_dir=lang_dir,
                user=current_user(), is_admin=is_admin(), payment_enabled=payment_enabled)

# ---------- Currency (multi-currency support) ----------
DEFAULT_CURRENCIES = [
    {"code": "SSP", "name": "South Sudanese Pound", "symbol": "SSP", "rate": 1.0, "decimals": 0},
    {"code": "USD", "name": "US Dollar", "symbol": "US$", "rate": 0.000741, "decimals": 2},
    {"code": "EGP", "name": "Egyptian Pound", "symbol": "\u00a3", "rate": 0.0303, "decimals": 2},
    {"code": "KES", "name": "Kenyan Shilling", "symbol": "KSh", "rate": 0.0909, "decimals": 2},
    {"code": "XOF", "name": "West African CFA Franc", "symbol": "CFA", "rate": 0.444, "decimals": 0},
    {"code": "UGX", "name": "Ugandan Shilling", "symbol": "USh", "rate": 2.74, "decimals": 0},
    {"code": "ETB", "name": "Ethiopian Birr", "symbol": "Br", "rate": 0.10, "decimals": 2},
    {"code": "SDG", "name": "Sudanese Pound", "symbol": "SDG", "rate": 0.444, "decimals": 2},
    {"code": "TZS", "name": "Tanzanian Shilling", "symbol": "TSh", "rate": 1.85, "decimals": 0},
    {"code": "RWF", "name": "Rwandan Franc", "symbol": "RF", "rate": 0.963, "decimals": 0},
    {"code": "BIF", "name": "Burundian Franc", "symbol": "FBu", "rate": 2.19, "decimals": 0},
    {"code": "NGN", "name": "Nigerian Naira", "symbol": "₦", "rate": 1.11, "decimals": 2},
    {"code": "GBP", "name": "British Pound", "symbol": "£", "rate": 0.000585, "decimals": 2},
    {"code": "EUR", "name": "Euro", "symbol": "€", "rate": 0.000681, "decimals": 2},
    {"code": "AED", "name": "UAE Dirham", "symbol": "AED", "rate": 0.00272, "decimals": 2},
    {"code": "CNY", "name": "Chinese Yuan", "symbol": "¥", "rate": 0.00537, "decimals": 2},
]


@app.before_request
def persist_currency():
    """Persist the chosen currency in a cookie and redirect to a clean URL."""
    code = request.args.get("currency", "").strip().upper()
    if not code:
        return
    qs = request.full_path.split("?", 1)[1] if "?" in request.full_path else ""
    parts = [p for p in qs.split("&") if p.split("=", 1)[0] != "currency"]
    new_qs = "&".join(parts)
    target = request.path + ("?" + new_qs if new_qs else "")
    resp = redirect(target)
    resp.set_cookie("currency", code, max_age=60 * 60 * 24 * 30, path="/")
    return resp


@app.before_request
def persist_language():
    """Persist the chosen language in a cookie and redirect to a clean URL."""
    code = request.args.get("language", "").strip().lower()
    if not code:
        return
    if code not in LANGUAGES:
        return
    qs = request.full_path.split("?", 1)[1] if "?" in request.full_path else ""
    parts = [p for p in qs.split("&") if p.split("=", 1)[0] != "language"]
    new_qs = "&".join(parts)
    target = request.path + ("?" + new_qs if new_qs else "")
    resp = redirect(target)
    resp.set_cookie("language", code, max_age=60 * 60 * 24 * 30, path="/")
    return resp


@app.template_filter("curfmt")
def format_currency(value, code=None):
    """Render a base-currency price in the requested currency code."""
    site = get_all_content().get("site", {}) or {}
    currencies = site.get("currencies") or DEFAULT_CURRENCIES
    code = (code or site.get("currency") or "SSP").upper()
    cur = None
    for c in currencies:
        if c.get("code") == code:
            cur = c
            break
    if cur is None and currencies:
        cur = currencies[0]
    if cur is None:
        cur = DEFAULT_CURRENCIES[0]
    try:
        ssp = float(value)
    except (TypeError, ValueError):
        return ""
    val = ssp * float(cur.get("rate", 1.0))
    decimals = int(cur.get("decimals", 2))
    sym = str(cur.get("symbol", ""))
    if decimals > 0:
        return "{:.{}f}".format(val, decimals)
    return "{:,.0f}".format(val)



@app.before_request
def csrf_guard():
    if request.method == "POST":
        tok = request.form.get("csrf_token", "")
        if not valid_csrf(tok):
            flash("Security token expired. Please try again.", "danger")
            return redirect(request.path or url_for("index"))

@app.before_request
def enforce_account_status():
    """Log out blocked accounts, and keep suspended ones browse-only."""
    u = current_user()
    if not u:
        return
    if u.get("is_admin"):
        return
    rec = user_record(u.get("username", ""))
    if rec is None:
        # Account was removed by an admin while this session was open.
        session.pop("user", None)
        flash("Your account is no longer available.", "danger")
        return redirect(url_for("index"))
    if user_status(rec) == "blocked":
        session.pop("user", None)
        flash("Your account has been blocked. Please contact support.", "danger")
        return redirect(url_for("index"))

# ============================================================
# PUBLIC ROUTES
# ============================================================
@app.route("/")
def index():
    products = visible_products()
    cats = get_blob("categories", [])
    featured = products[:8]
    return render_template("index.html", featured=featured, categories=cats,
                           testimonials=get_blob("testimonials", []),
                           partners=get_blob("partners", []))

@app.route("/shop")
def shop():
    products = visible_products()
    cats = get_blob("categories", [])
    q = request.args.get("q", "").strip().lower()
    cat = request.args.get("cat", "").strip()
    sort = request.args.get("sort", "")
    min_price = request.args.get("min_price", "").strip()
    max_price = request.args.get("max_price", "").strip()
    if q:
        products = [p for p in products if q in p.get("name","").lower() or q in p.get("desc","").lower()]
    if cat:
        products = [p for p in products if p.get("category") == cat]
    if min_price:
        try:
            m = float(min_price)
            products = [p for p in products if p.get("price", 0) >= m]
        except ValueError:
            pass
    if max_price:
        try:
            m = float(max_price)
            products = [p for p in products if p.get("price", 0) <= m]
        except ValueError:
            pass
    if sort == "low": products = sorted(products, key=lambda p: p.get("price",0))
    elif sort == "high": products = sorted(products, key=lambda p: p.get("price",0), reverse=True)
    elif sort == "name": products = sorted(products, key=lambda p: p.get("name",""))
    return render_template("shop.html", products=products, categories=cats, q=q, cat=cat, sort=sort, min_price=min_price, max_price=max_price)

@app.route("/product/<int:pid>")
def product_detail(pid):
    for p in visible_products():
        if p.get("id") == pid:
            related = [x for x in visible_products() if x.get("category")==p.get("category") and x.get("id")!=pid][:4]
            return render_template("product.html", p=p, related=related)
    abort(404)

@app.route("/cart")
def cart():
    items, total, count = cart_detailed()
    return render_template("cart.html", items=items, total=total, count=count)

@app.route("/cart/add/<int:pid>", methods=["POST"])
@perm_required("shop")
def cart_add(pid):
    if not any(p.get("id") == pid for p in visible_products()):
        flash("That item is not available.", "danger")
        return redirect(url_for("shop"))
    try:
        qty = max(1, min(99, int(request.form.get("qty", 1))))
    except (TypeError, ValueError):
        qty = 1
    cart = get_cart()
    cart[str(pid)] = min(99, cart.get(str(pid), 0) + qty)
    session["cart"] = cart
    flash("Added to cart 🛒", "success")
    return redirect(request.form.get("next", url_for("cart")))

@app.route("/cart/update", methods=["POST"])
@perm_required("shop")
def cart_update():
    cart = get_cart()
    for k in list(cart.keys()):
        f = f"qty_{k}"
        if f in request.form:
            try:
                q = int(request.form[f])
            except ValueError:
                q = 1
            if q <= 0: cart.pop(k, None)
            else: cart[k] = min(99, q)
    if request.form.get("remove"):
        cart.pop(str(request.form["remove"]), None)
    session["cart"] = cart
    return redirect(url_for("cart"))

@app.route("/cart/clear", methods=["POST"])
@perm_required("shop")
def cart_clear():
    session.pop("cart", None)
    flash("Cart cleared.", "info")
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["GET", "POST"])
@perm_required("shop")
def checkout():
    items, total, count = cart_detailed()
    if not items:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("shop"))
    pay_enabled = payment_enabled()
    # user's saved payment methods
    pms = []
    u = current_user()
    if u:
        users = get_blob("users", [])
        rec = next((x for x in users if x.get("username") == u.get("username")), None)
        if rec:
            pms = rec.get("payment_methods", [])
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip()
        phone = request.form.get("phone","").strip()
        address = request.form.get("address","").strip()
        # store chosen payment method (may be a saved pm id or a new method name)
        pay = request.form.get("payment","Cash on Delivery")
        chosen = request.form.get("chosen_payment", pay).strip()
        city = request.form.get("city","Juba").strip()
        notes = request.form.get("notes","").strip()
        if not name or not phone or not address:
            flash("Name, phone and address are required.", "danger")
            return render_template("checkout.html", items=items, total=total, pms=pms, pay_enabled=pay_enabled)
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Invalid email address.", "danger")
            return render_template("checkout.html", items=items, total=total, pms=pms, pay_enabled=pay_enabled)

        if not pay_enabled and chosen.lower() != "cod":
            flash("The payment system is currently disabled. Only Cash on Delivery is available.", "danger")
            return render_template("checkout.html", items=items, total=total, pms=pms, pay_enabled=pay_enabled)
        con = db()
        cur = con.execute("""INSERT INTO orders(customer_name,email,phone,address,city,notes,items_json,total,status,created,payment_method,payment_status)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (html.escape(name), html.escape(email), html.escape(phone),
                     html.escape(address), html.escape(city), html.escape(notes),
                     json.dumps(items, default=str), total, f"pending — {pay}",
                     datetime.utcnow().isoformat(), chosen,
                     "pending" if chosen.lower() == "cod" else "pending"))
        # decrement stock
        products = get_blob("products", [])
        cmap = {str(k): v for k, v in get_cart().items()}
        for p in products:
            if str(p.get("id")) in cmap:
                p["stock"] = max(0, int(p.get("stock",0)) - int(cmap[str(p["id"])]))
        con.execute("INSERT OR REPLACE INTO site_data(key,value) VALUES('products',?)", (json.dumps(products),))
        con.commit()
        order_id = cur.lastrowid
        con.close()
        session.pop("cart", None)
        is_cod = chosen.lower() == "cod"
        site = get_blob("site", {})
        if email:
            send_email_https(email, f"Order received — {site.get('name','Free Online Shopping')}",
                f"Hi {name},\n\nThanks for your order (#{order_id}). Total: {total:,.0f} {site.get('currency','SSP')}.\nPayment: {pay}\nWe will call you on {phone} for delivery.\n\n— {site.get('name')}")
        if is_cod:
            return redirect(url_for("order_success", oid=order_id))
        return redirect(url_for("order_pay", oid=order_id))
    return render_template("checkout.html", items=items, total=total, pms=pms, pay_enabled=pay_enabled)

@app.route("/order/<int:oid>")
def order_success(oid):
    con = db()
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    con.close()
    if not o: abort(404)
    return render_template("order_success.html", o=o, items=json.loads(o["items_json"]))

# PAYMENT_ROUTES_MARKER
PAYMENT_TYPES = [
    ("visa", "Visa Card"),
    ("mtn_momo", "MTN Mobile Money"),
    ("airtel_money", "Airtel Money"),
    ("bank_transfer", "Bank Transfer"),
    ("cod", "Pay on Delivery"),
]


def _pm_id():
    return "pm_" + secrets.token_hex(6)


@app.route("/user/payment", methods=["GET", "POST"])
@login_required
@perm_required("payment")
def user_payment():
    if not payment_enabled():
        flash("The payment system is currently disabled.", "warning")
        return redirect(url_for("account"))
    me = current_user().get("username", "")
    users = get_blob("users", [])
    u = next((x for x in users if x.get("username") == me), None)
    if not u:
        abort(404)
    pms = u.get("payment_methods", [])
    if request.method == "POST":
        act = request.form.get("action", "add")
        if act == "add":
            ptype = request.form.get("ptype", "").strip()
            label = request.form.get("label", "").strip() or dict(PAYMENT_TYPES).get(ptype, ptype)
            if ptype not in dict(PAYMENT_TYPES):
                flash("Invalid payment method.", "danger")
                return redirect(url_for("user_payment"))
            pm = {"id": _pm_id(), "type": ptype, "label": label, "is_default": False}
            if ptype == "visa":
                pm["card_last4"] = request.form.get("card_last4", "").strip()[-4:]
                pm["card_name"] = html.escape(request.form.get("card_name", "").strip())
            elif ptype in ("mtn_momo", "airtel_money"):
                pm["phone"] = html.escape(request.form.get("phone", "").strip())
                pm["provider"] = "mtn" if ptype == "mtn_momo" else "airtel"
            elif ptype == "bank_transfer":
                pm["bank_name"] = html.escape(request.form.get("bank_name", "").strip())
                pm["account_name"] = html.escape(request.form.get("account_name", "").strip())
                pm["account_last4"] = request.form.get("account_last4", "").strip()[-4:]
            if not any(x.get("is_default") for x in pms):
                pm["is_default"] = True
            pms.append(pm)
            u["payment_methods"] = pms
            set_blob("users", users)
            flash("Payment method added.", "success")
            return redirect(url_for("user_payment"))
        elif act == "delete":
            pid = request.form.get("pmid", "").strip()
            u["payment_methods"] = [x for x in pms if x.get("id") != pid]
            set_blob("users", users)
            flash("Payment method removed.", "info")
            return redirect(url_for("user_payment"))
        elif act == "default":
            pid = request.form.get("pmid", "").strip()
            for x in pms:
                x["is_default"] = (x.get("id") == pid)
            u["payment_methods"] = pms
            set_blob("users", users)
            flash("Default payment method updated.", "success")
            return redirect(url_for("user_payment"))
    return render_template("user_payment.html", pms=pms, types=PAYMENT_TYPES, pay_enabled=payment_enabled())


@app.route("/order/pay/<int:oid>", methods=["GET", "POST"])
@login_required
@perm_required("payment")
def order_pay(oid):
    con = db()
    if not payment_enabled():
        flash("The payment system is currently disabled.", "warning")
        return redirect(url_for("account"))
    o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    con.close()
    if not o:
        abort(404)
    items = json.loads(o["items_json"] or "[]")
    if request.method == "POST":
        act = request.form.get("action", "pay")
        if act == "pay":
            pmethod = ",".join(request.form.getlist("payment_method"))
            pref = request.form.get("payment_reference", "").strip()
            receipt = request.files.get("receipt")
            rpath = None
            if receipt and receipt.filename:
                rpath, err = save_upload(receipt)
                if err:
                    flash(err, "danger")
                    return render_template("order_pay.html", o=o, items=items, types=PAYMENT_TYPES, pay_enabled=payment_enabled())
            con = db()
            con.execute(
                "UPDATE orders SET payment_method=?, payment_reference=?, receipt_path=?, payment_status=? WHERE id=?",
                (pmethod, pref or None, rpath, "pending", oid),
            )
            con.commit()
            con.close()
            flash("Payment details submitted. Awaiting admin verification.", "info")
            return redirect(url_for("account"))
        elif act == "cancel":
            con = db()
            con.execute("UPDATE orders SET payment_status=? WHERE id=?", ("cancelled", oid))
            con.commit()
            con.close()
            flash("Payment cancelled.", "info")
            return redirect(url_for("account"))
    return render_template("order_pay.html", o=o, items=items, types=PAYMENT_TYPES, pay_enabled=payment_enabled())


@app.route("/contact", methods=["GET", "POST"])
@perm_required("contact")
def contact():
    if request.method == "POST":
        name = request.form.get("name","").strip()[:100]
        email = request.form.get("email","").strip()[:150]
        subject = request.form.get("subject","").strip()[:150]
        message = request.form.get("message","").strip()[:5000]
        if not name or not message or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""):
            flash("Please fill name, valid email and message.", "danger")
        else:
            con = db()
            con.execute("INSERT INTO contact_messages(name,email,subject,message,created) VALUES(?,?,?,?,?)",
                        (html.escape(name), html.escape(email), html.escape(subject), html.escape(message),
                         datetime.utcnow().isoformat()))
            con.commit(); con.close()
            flash("Message sent! We will reply soon. ✉️", "success")
            return redirect(url_for("contact"))
    return render_template("contact.html", prefill=request.args.get("subject", "")[:150])

@app.route("/admin/payments", methods=["GET", "POST"])
@admin_required
def admin_payments():
    con = db()
    if request.method == "POST":
        if not payment_enabled():
            flash("The payment system is currently disabled.", "warning")
            con.close()
            return redirect(url_for("admin_payments"))
        pid = request.form.get("pid")
        action = request.form.get("action")
        if action in ("verify", "reject") and pid:
            new_st = "paid" if action == "verify" else "rejected"
            con.execute("UPDATE admin_payments SET status=? WHERE id=?", (new_st, pid))
            con.commit()
            flash("Payment " + action + "d.", "success")
        elif action == "record":
            uid = request.form.get("user_id", "").strip()
            amt = float(request.form.get("amount", 0) or 0)
            meth = request.form.get("method", "cod")
            ref = request.form.get("reference", "").strip()
            receipt = request.files.get("receipt")
            rpath = None
            if receipt and receipt.filename:
                rpath, err = save_upload(receipt)
                if err:
                    flash(err, "danger")
                    con.close()
                    return redirect(url_for("admin_payments"))
            con.execute(
                "INSERT INTO admin_payments(type,user_id,amount,method,status,reference,receipt_path,created) VALUES(?,?,?,?,?,?,?,?)",
                ("ad_fee", uid, amt, meth, "pending", ref or None, rpath, datetime.utcnow().isoformat()),
            )
            con.commit()
            flash("Ad-fee payment recorded (pending verification).", "info")
        con.close()
        return redirect(url_for("admin_payments"))
    rows = con.execute(
        "SELECT * FROM admin_payments ORDER BY id DESC"
    ).fetchall()
    con.close()
    users = get_blob("users", [])
    return render_template("admin_payments.html", rows=rows, users=users)

@app.route("/admin/settings/payments", methods=["GET", "POST"])
@admin_required
def admin_payment_toggle():
    site = get_blob("site", {})
    if request.method == "POST":
        site["payment_enabled"] = request.form.get("enabled") == "on"
        set_blob("site", site)
        flash(f"Payment system {'enabled' if site['payment_enabled'] else 'disabled'}.", "success")
        return redirect(url_for("admin_payment_toggle"))
    return render_template("admin_payment_toggle.html", enabled=site.get("payment_enabled", True))

@app.route("/apply/<int:pid>", methods=["GET", "POST"])
@perm_required("apply")
def apply(pid):
    job = None
    for p in get_blob("products", []):
        if p.get("id") == pid and p.get("category") == "jobs":
            job = p
            break
    if not job:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        email = request.form.get("email", "").strip()[:150]
        phone = request.form.get("phone", "").strip()[:40]
        message = request.form.get("message", "").strip()[:5000]
        if not name or not message or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""):
            flash("Please fill your name, a valid email and the message.", "danger")
        else:
            doc = None
            if "doc" in request.files and request.files["doc"].filename:
                doc, err = save_doc_upload(request.files["doc"])
                if err:
                    flash(err, "danger")
                    return redirect(url_for("apply", pid=pid))
            con = db()
            con.execute("INSERT INTO applications(job,name,email,phone,message,doc,created) VALUES(?,?,?,?,?,?,?)",
                        (html.escape(job["name"]), html.escape(name), html.escape(email),
                         html.escape(phone), html.escape(message), doc, datetime.utcnow().isoformat()))
            con.commit()
            con.close()
            flash("Application submitted! We will review it and get back to you. 📄", "success")
            return redirect(url_for("apply", pid=pid))
    return render_template("apply.html", p=job)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        # Sign-up lives on the combined login page now
        return redirect(url_for("login", tab="signup"))
    if request.method == "POST":
        username = request.form.get("username","").strip()[:50]
        email = request.form.get("email","").strip()[:150]
        pw = request.form.get("password","")
        if len(username) < 3 or len(pw) < 4:
            flash("Username (3+) and password (4+) required.", "danger")
            return render_template("login.html", next=url_for("index"), tab="signup")
        elif find_user(username)[0]:
            flash("Username already taken.", "danger")
            return render_template("login.html", next=url_for("index"), tab="signup")
        else:
            users = get_blob("users", [])
            users.append({"username": username, "email": html.escape(email),
                          "pw_hash": hash_pw(pw),
                          "created": datetime.utcnow().isoformat(),
                          "status": "active",
                          "perms": dict(DEFAULT_PERMS)})
            set_blob("users", users)
            session["user"] = {"username": username, "is_admin": False}
            flash(f"Welcome, {html.escape(username)}! 🎉", "success")
            return redirect(url_for("index"))

@app.route("/login", methods=["GET", "POST"])
def login():
    nxt = request.args.get("next") or request.form.get("next") or url_for("index")
    if request.method == "POST":
        username = request.form.get("username","").strip()
        pw = request.form.get("password","")
        u, admin_flag = find_user_by_login(username)
        if u and check_password_hash(u.get("pw_hash",""), pw):
            if not admin_flag:
                st = user_status(u)
                if st == "blocked":
                    flash("Your account has been blocked. Please contact support.", "danger")
                    return render_template("login.html", next=nxt, tab=request.args.get("tab",""))
            session["user"] = {"username": u["username"], "is_admin": bool(admin_flag)}
            flash(f"Welcome back, {html.escape(u['username'])}!", "success")
            return redirect(nxt if nxt.startswith("/") else url_for("index"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html", next=nxt, tab=request.args.get("tab", ""))

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out.", "info")
    return redirect(url_for("index"))

@app.route("/account")
@login_required
def account():
    con = db()
    email_like = (current_user() or {}).get("username","")
    me = (current_user() or {}).get("username","")
    orders = con.execute("SELECT * FROM orders WHERE customer_name=? ORDER BY id DESC LIMIT 50", (me,)).fetchall()
    con.close()
    rec = user_record(me) or {}
    return render_template("account.html", orders=orders,
                           my_status=user_status(rec),
                           my_perms=user_perms(rec),
                           perm_labels=ACCESS_PERMS)

@app.route("/myproducts", methods=["GET", "POST"])
@login_required
def myproducts():
    if not payment_enabled():
        flash("The payment system is currently disabled.", "warning")
        return redirect(url_for("account"))
    me = current_user().get("username", "")
    fee = ad_fee()
    cat_ids = {c.get("id") for c in get_blob("categories", [])}
    if request.method == "POST":
        act = request.form.get("action", "add")
        if act == "request_access":
            if not has_perm("sell"):
                flash("Seller access is not available on your account right now.", "danger")
                return redirect(url_for("myproducts"))
            users = get_blob("users", [])
            for u in users:
                if u.get("username") == me:
                    u["sell_request"] = "pending"
            set_blob("users", users)
            flash("Seller access requested! The admin will review it — you can post once granted. ✋", "success")
            return redirect(url_for("myproducts"))
        if act == "pay_ad":
            if not has_perm("advertise"):
                flash("You are not allowed to pay for advertising right now. Contact the admin.", "danger")
                return redirect(url_for("myproducts"))
            if not payment_enabled():
                flash("The payment system is currently disabled.", "warning")
                return redirect(url_for("myproducts"))
            pid = int(request.form.get("pid", 0))
            duration = request.form.get("duration", "monthly")
            if duration not in ("monthly", "annual", "permanent"):
                duration = "monthly"
            products = get_blob("products", [])
            for p in products:
                if p.get("id") == pid and p.get("seller") == me and p.get("status") == "approved" and p.get("fee_status") != "paid":
                    p["fee_status"] = "paid"
                    p["paid_at"] = datetime.utcnow().isoformat()
                    p["paid_by"] = me
                    p["post_duration"] = duration
                    if duration == "monthly":
                        p["expires_at"] = (datetime.utcnow() + timedelta(days=30)).isoformat()
                    elif duration == "annual":
                        p["expires_at"] = (datetime.utcnow() + timedelta(days=365)).isoformat()
                    else:
                        p["expires_at"] = None  # permanent
                    set_blob("products", products)
                    flash(f"Advertisement fee paid for “{p['name']}”! 🎉", "success")
                    return redirect(url_for("myproducts"))
            flash("Nothing to pay for.", "info")
            return redirect(url_for("myproducts"))
        if act in ("add", "edit", "delete") and not can_sell():
            flash("You need seller access to manage posts. Request it below.", "danger")
            return redirect(url_for("myproducts"))
        products = get_blob("products", [])
        if act == "add":
            name = request.form.get("name", "").strip()[:120]
            cat = request.form.get("category", "")[:50]
            desc = request.form.get("desc", "").strip()[:2000]
            if not name or not desc:
                flash("Please fill in the product name and description.", "danger")
            elif cat not in cat_ids:
                flash("Please choose a valid category from the list.", "danger")
            else:
                imgs = collect_images()
                nid = max([p.get("id", 0) for p in products] + [0]) + 1
                products.append({"id": nid, "name": name, "category": cat,
                    "price": float(request.form.get("price", 0) or 0),
                    "old_price": 0.0, "stock": int(request.form.get("stock", 1) or 1),
                    "badge": "", "image": imgs[0] if imgs else "", "images": imgs, "desc": desc,
                    "post_type": "user", "seller": me, "status": "pending",
                    "fee_status": "unpaid", "fee_amount": fee,
                    "created": datetime.utcnow().isoformat()})
                set_blob("products", products)
                flash("Product submitted! Pay the advertisement fee after review — your post goes live once it is approved and the fee is settled.", "success")
                return redirect(url_for("myproducts"))
        elif act == "edit":
            pid = int(request.form.get("pid", 0))
            name = request.form.get("name", "").strip()[:120]
            cat = request.form.get("category", "")[:50]
            for p in products:
                if p.get("id") == pid and p.get("seller") == me and p.get("status") != "approved":
                    if name:
                        p["name"] = name
                    if cat in cat_ids:
                        p["category"] = cat
                    p["price"] = float(request.form.get("price", 0) or 0)
                    p["stock"] = int(request.form.get("stock", 0) or 0)
                    p["desc"] = request.form.get("desc", "").strip()[:2000]
                    imgs = collect_images()
                    if imgs:
                        p["images"] = imgs
                        p["image"] = imgs[0]
                    p["status"] = "pending"
                    flash("Post updated — waiting for review again.", "success")
                    break
            set_blob("products", products)
        elif act == "delete":
            pid = int(request.form.get("pid", 0))
            removed, kept = [], []
            for p in products:
                if p.get("id") == pid and p.get("seller") == me:
                    imgs = p.get("images") or ([p.get("image", "")] if p.get("image") else [])
                    removed = [s for s in imgs if s.startswith("/uploads/")]
                else:
                    kept.append(p)
            products = kept
            set_blob("products", products)
            rest = json.dumps(products)
            for u in removed:
                fn = u.split("/uploads/", 1)[-1]
                if fn and fn not in rest:
                    try:
                        os.remove(os.path.join(UPLOAD_DIR, fn))
                    except OSError:
                        pass
            flash("Post deleted.", "info")
        return redirect(url_for("myproducts"))
    mine = [p for p in get_blob("products", []) if p.get("seller") == me]
    rec = user_record(me) or {}
    return render_template("myproducts.html", mine=mine, fee=fee,
                           categories=get_blob("categories", []),
                           seller=can_sell(), request_status=rec.get("sell_request", ""),
                           my_perms=user_perms(rec), my_status=user_status(rec),
                           advertise_perm=has_perm("advertise"), pay_enabled=payment_enabled())

@app.route("/uploads/<path:fname>")
def uploads(fname):
    return send_from_directory(UPLOAD_DIR, fname)

@app.route("/healthz")
def healthz():
    return jsonify(ok=True, time=datetime.utcnow().isoformat())

# ============================================================
# ADMIN CMS
# ============================================================
@app.route("/admin")
@admin_required
def admin_dash():
    con = db()
    n_orders = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    n_msg = con.execute("SELECT COUNT(*) FROM contact_messages").fetchone()[0]
    n_apps = con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    pending = con.execute("SELECT COUNT(*) FROM orders WHERE status LIKE 'pending%'").fetchone()[0]
    rev = con.execute("SELECT COALESCE(SUM(total),0) FROM orders").fetchone()[0]
    recent = con.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 5").fetchall()
    con.close()
    return render_template("admin_dash.html", n_orders=n_orders, n_msg=n_msg, n_apps=n_apps,
                           pending=pending, rev=rev, recent=recent)

@app.route("/admin/content", methods=["GET", "POST"])
@admin_required
def admin_content():
    if request.method == "POST":
        site = get_blob("site", {})
        for f in ["name","tagline","hero_title","hero_subtitle","hero_cta","hero_image","currency","announcement","about","mission","contact_email","contact_phone","address","footer_text"]:
            if f in request.form:
                site[f] = request.form[f].strip()[:2000]
    if "currencies" in request.form:
        try:
            site["currencies"] = json.loads(request.form["currencies"] or "[]")
        except ValueError:
            flash("Currency list is invalid JSON — not saved.", "danger")
        set_blob("site", site)
        flash("Site content saved.", "success")
        return redirect(url_for("admin_content"))
    return render_template("admin_content.html", site=get_blob("site", {}))

def collect_images(maxn=8):
    """Merged product photo list: kept photos from the hidden field + newly uploaded ones."""
    imgs = []
    try:
        for s in json.loads(request.form.get("existing_images", "[]") or "[]"):
            if isinstance(s, str) and s.startswith("/uploads/"):
                imgs.append(s)
    except Exception:
        pass
    for f in request.files.getlist("images"):
        if f and f.filename:
            fname, err = save_upload(f)
            if err:
                flash(err, "danger")
                continue
            imgs.append("/uploads/" + fname)
    seen = set()
    out = []
    for u in imgs:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:maxn]

@app.route("/admin/products", methods=["GET", "POST"])
@admin_required
def admin_products():
    products = get_blob("products", [])
    cats = get_blob("categories", [])
    if request.method == "POST":
        act = request.form.get("action", "")
        if act == "add":
            imgs = collect_images()
            nid = max([p.get("id",0) for p in products] + [0]) + 1
            products.append({"id": nid, "name": request.form.get("name","")[:120],
                "category": request.form.get("category",""), "price": float(request.form.get("price",0) or 0),
                "old_price": float(request.form.get("old_price",0) or 0), "stock": int(request.form.get("stock",0) or 0),
                "badge": request.form.get("badge","")[:30], "image": imgs[0] if imgs else "",
                "images": imgs, "desc": request.form.get("desc","")[:2000]})
            set_blob("products", products); flash("Product added.", "success")
        elif act == "delete":
            pid = int(request.form.get("pid",0))
            removed = []
            for p in products:
                if p.get("id") == pid:
                    imgs = p.get("images") or ([p.get("image","")] if p.get("image") else [])
                    removed = [s for s in imgs if s.startswith("/uploads/")]
            products = [p for p in products if p.get("id") != pid]
            set_blob("products", products)
            rest = json.dumps(products)
            for u in removed:
                fn = u.split("/uploads/", 1)[-1]
                if fn and fn not in rest:
                    try:
                        os.remove(os.path.join(UPLOAD_DIR, fn))
                    except OSError:
                        pass
            flash("Product deleted.", "info")
        elif act == "edit":
            pid = int(request.form.get("pid",0))
            for p in products:
                if p.get("id") == pid:
                    p["name"] = request.form.get("name","")[:120]
                    p["category"] = request.form.get("category","")[:50]
                    p["price"] = float(request.form.get("price",0) or 0)
                    p["old_price"] = float(request.form.get("old_price",0) or 0)
                    p["stock"] = int(request.form.get("stock",0) or 0)
                    p["badge"] = request.form.get("badge","")[:30]
                    p["desc"] = request.form.get("desc","")[:2000]
                    p["images"] = collect_images()
                    p["image"] = p["images"][0] if p["images"] else ""
                    break
            set_blob("products", products); flash("Product updated.", "success")
        elif act == "img_primary":
            pid = int(request.form.get("pid",0)); u = request.form.get("img_url","")[:300]
            for p in products:
                if p.get("id") == pid:
                    imgs = p.get("images") or ([p.get("image","")] if p.get("image") else [])
                    if u in imgs:
                        imgs = [u] + [s for s in imgs if s != u]
                        p["images"] = imgs
                        p["image"] = u
            set_blob("products", products); flash("Primary photo updated.", "success")
        elif act == "img_delete":
            pid = int(request.form.get("pid",0)); u = request.form.get("img_url","")[:300]
            for p in products:
                if p.get("id") == pid:
                    imgs = p.get("images") or ([p.get("image","")] if p.get("image") else [])
                    imgs = [s for s in imgs if s != u]
                    if p.get("image") == u:
                        p["image"] = imgs[0] if imgs else ""
                    p["images"] = imgs
            set_blob("products", products)
            fn = u.split("/uploads/", 1)[-1]
            if fn and not any(fn in json.dumps(x) for x in products):
                try:
                    os.remove(os.path.join(UPLOAD_DIR, fn))
                except OSError:
                    pass
            flash("Photo removed.", "info")
        elif act == "stock":
            pid = int(request.form.get("pid",0)); st = int(request.form.get("stock",0))
            for p in products:
                if p.get("id")==pid: p["stock"]=st
            set_blob("products", products); flash("Stock updated.", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin_products.html", products=products, categories=cats)

@app.route("/admin/listings", methods=["GET", "POST"])
@admin_required
def admin_listings():
    products = get_blob("products", [])
    if request.method == "POST":
        if not payment_enabled():
            flash("The payment system is currently disabled.", "warning")
            return redirect(url_for("admin_payments"))
        act = request.form.get("action", "")
        pid = int(request.form.get("pid", 0))
        if act == "fee_set":
            try:
                v = max(0, int(request.form.get("fee", 5000) or 0))
            except ValueError:
                v = 5000
            set_blob("fees", {"per_post": v})
            flash(f"Advertisement fee set to {v} per post.", "success")
        else:
            for p in products:
                if p.get("id") == pid and p.get("post_type") == "user":
                    if act == "approve":
                        p["status"] = "approved"
                        flash(f"“{p['name']}” is now live in the shop. 🎉", "success")
                    elif act == "reject":
                        p["status"] = "rejected"
                        flash("Post rejected — seller can edit and resubmit.", "info")
                    elif act == "fee_paid":
                        p["fee_status"] = "paid"
                        flash("Advertisement fee marked as paid. 💰", "success")
                    elif act == "fee_unpaid":
                        p["fee_status"] = "unpaid"
                        flash("Fee reset to unpaid.", "info")
                    elif act == "delete":
                        imgs = p.get("images") or ([p.get("image", "")] if p.get("image") else [])
                        removed = [s for s in imgs if s.startswith("/uploads/")]
                        products = [x for x in products
                                    if not (x.get("id") == pid and x.get("post_type") == "user")]
                        set_blob("products", products)
                        rest = json.dumps(products)
                        for u in removed:
                            fn = u.split("/uploads/", 1)[-1]
                            if fn and fn not in rest:
                                try:
                                    os.remove(os.path.join(UPLOAD_DIR, fn))
                                except OSError:
                                    pass
                        flash("Post deleted.", "info")
                        return redirect(url_for("admin_listings"))
                    break
            set_blob("products", products)
        return redirect(url_for("admin_listings"))
    listings = [p for p in products if p.get("post_type") == "user"]
    return render_template("admin_listings.html", listings=listings, fee=ad_fee(),
                           users=get_blob("users", []), now_iso=datetime.utcnow().isoformat())

@app.route("/admin/listings/review/<int:pid>", methods=["GET", "POST"])
@admin_required
def admin_review(pid):
    products = get_blob("products", [])
    p = next((x for x in products
              if x.get("id") == pid and x.get("post_type") == "user"), None)
    if not p:
        flash("Marketplace post not found.", "danger")
        return redirect(url_for("admin_listings"))
    if request.method == "POST":
        act = request.form.get("action", "notes")
        notes = request.form.get("notes", "").strip()[:2000]
        if act == "notes":
            p["review_notes"] = notes
            p["reviewed_at"] = datetime.utcnow().isoformat()
            if p.get("status") == "pending":
                p["status"] = "reviewing"
            flash("Review notes saved — visible to the seller. 📝", "success")
        elif act == "approve":
            if notes:
                p["review_notes"] = notes
            p["status"] = "approved"
            p["approved_at"] = datetime.utcnow().isoformat()
            flash(f"“{p['name']}” approved and live in the shop. 🎉", "success")
        elif act == "reject":
            if notes:
                p["review_notes"] = notes
            p["status"] = "rejected"
            p["reviewed_at"] = datetime.utcnow().isoformat()
            flash("Post rejected — feedback sent to the seller.", "info")
        elif act == "fee_paid":
            p["fee_status"] = "paid"
            flash("Advertisement fee marked as paid. 💰", "success")
        elif act == "fee_unpaid":
            p["fee_status"] = "unpaid"
            flash("Fee reset to unpaid.", "info")
        set_blob("products", products)
        return redirect(url_for("admin_review", pid=pid))
    seller = user_record(p.get("seller", "")) or {}
    return render_template("admin_review.html", p=p, seller=seller, fee=ad_fee())

@app.route("/admin/orders", methods=["GET", "POST"])
@admin_required
def admin_orders():
    con = db()
    if request.method == "POST":
        oid = request.form.get("oid")
        if request.form.get("action") == "verify_payment" and oid:
            con.execute("UPDATE orders SET payment_status='paid', paid_at=? WHERE id=?", (datetime.utcnow().isoformat(), oid))
            flash("Order payment marked as paid.", "success")
        elif request.form.get("action") == "reject_payment" and oid:
            con.execute("UPDATE orders SET payment_status='rejected' WHERE id=?", (oid,))
            flash("Order payment rejected.", "info")
        else:
            con.execute("UPDATE orders SET status=? WHERE id=?", (request.form.get("status","pending")[:100], oid))
            flash("Order updated.", "success")
        con.commit()
        con.close(); return redirect(url_for("admin_orders"))
    orders = con.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    con.close()
    return render_template("admin_orders.html", orders=orders)

@app.route("/admin/messages", methods=["GET", "POST"])
@admin_required
def admin_messages():
    con = db()
    if request.method == "POST" and request.form.get("mid"):
        con.execute("DELETE FROM contact_messages WHERE id=?", (request.form["mid"],))
        con.commit(); flash("Message deleted.", "info")
        con.close(); return redirect(url_for("admin_messages"))
    msgs = con.execute("SELECT * FROM contact_messages ORDER BY id DESC").fetchall()
    con.close()
    return render_template("admin_messages.html", msgs=msgs)

@app.route("/admin/applications", methods=["GET", "POST"])
@admin_required
def admin_applications():
    con = db()
    if request.method == "POST":
        if request.form.get("did"):
            row = con.execute("SELECT doc FROM applications WHERE id=?", (request.form["did"],)).fetchone()
            con.execute("DELETE FROM applications WHERE id=?", (request.form["did"],))
            con.commit()
            if row and row["doc"]:
                try:
                    os.remove(os.path.join(APP_DOC_DIR, row["doc"]))
                except OSError:
                    pass
            flash("Application deleted.", "info")
        elif request.form.get("aid"):
            allowed = {"new", "reviewing", "shortlisted", "hired", "rejected"}
            st = request.form.get("status", "new")
            con.execute("UPDATE applications SET status=? WHERE id=?",
                        (st if st in allowed else "new", request.form["aid"]))
            con.commit()
            flash("Application status updated.", "success")
        con.close()
        return redirect(url_for("admin_applications"))
    apps = con.execute("SELECT * FROM applications ORDER BY id DESC").fetchall()
    con.close()
    return render_template("admin_applications.html", apps=apps)

@app.route("/admin/applications/<int:aid>/doc")
@admin_required
def application_doc(aid):
    con = db()
    row = con.execute("SELECT doc FROM applications WHERE id=?", (aid,)).fetchone()
    con.close()
    if not row or not row["doc"]:
        abort(404)
    original = row["doc"].split("_", 1)[1] if "_" in row["doc"] else row["doc"]
    inline = original.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt"))
    return send_from_directory(APP_DOC_DIR, row["doc"], download_name=original,
                               as_attachment=not inline)

@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    if request.method == "POST":
        users = get_blob("users", [])
        act = request.form.get("action")
        if act == "delete":
            users = [u for u in users if u.get("username")!=request.form.get("username")]
            set_blob("users", users); flash("User removed.", "info")
        elif act in ("grant", "revoke"):
            for u in users:
                if u.get("username") == request.form.get("username"):
                    u["can_sell"] = (act == "grant")
                    u.pop("sell_request", None)
                    if act == "grant":
                        u["can_sell_granted"] = datetime.utcnow().isoformat()
            set_blob("users", users)
            flash(f"Seller access {'granted 🎉' if act == 'grant' else 'revoked.'}", "success")
        elif act == "status":
            st = request.form.get("status", "active")
            if st not in ACCESS_STATUSES:
                st = "active"
            for u in users:
                if u.get("username") == request.form.get("username"):
                    u["status"] = st
                    u["status_changed"] = datetime.utcnow().isoformat()
            set_blob("users", users)
            flash(f"Account status set to {st}.", "success")
        elif act == "perms":
            target = request.form.get("username")
            for u in users:
                if u.get("username") == target:
                    cur = user_perms(u)
                    for k in ACCESS_PERMS:
                        # checkboxes only submit when ticked
                        cur[k] = (k in request.form)
                    u["perms"] = cur
                    u["perms_changed"] = datetime.utcnow().isoformat()
            set_blob("users", users)
            flash("Access rights updated.", "success")
        elif act == "reset_perms":
            for u in users:
                if u.get("username") == request.form.get("username"):
                    u["perms"] = dict(DEFAULT_PERMS)
            set_blob("users", users)
            flash("Access rights reset to default (all allowed).", "info")
        return redirect(url_for("admin_users"))
    return render_template("admin_users.html", users=get_blob("users", []),
                           statuses=ACCESS_STATUSES, perm_labels=ACCESS_PERMS)

@app.route("/admin/account", methods=["GET", "POST"])
@admin_required
def admin_account():
    admins = get_blob("admin_users", [])
    if request.method == "POST":
        act = request.form.get("action","")
        if act=="add":
            u = request.form.get("username","").strip()
            pw = request.form.get("password","")
            em = request.form.get("email","").strip()[:150]
            if u and len(pw)>=4 and not any(a["username"].lower()==u.lower() for a in admins):
                admins.append({"username":u,"email":html.escape(em),"pw_hash":hash_pw(pw),"created":datetime.utcnow().isoformat()})
                set_blob("admin_users", admins); flash("Admin added.","success")
            else: flash("Invalid or duplicate admin.","danger")
        elif act=="password":
            me = current_user()["username"]
            for a in admins:
                if a["username"]==me: a["pw_hash"]=hash_pw(request.form.get("password",""))
            set_blob("admin_users", admins); flash("Password changed.","success")
        elif act=="email":
            me = current_user()["username"]
            em = request.form.get("email","").strip()[:150]
            for a in admins:
                if a["username"]==me: a["email"]=html.escape(em)
            set_blob("admin_users", admins); flash("Email updated.","success")
        elif act=="delete":
            if len(admins)>1:
                admins=[a for a in admins if a["username"]!=request.form.get("username")]
                set_blob("admin_users", admins); flash("Admin removed.","info")
            else: flash("Cannot delete last admin.","danger")
        return redirect(url_for("admin_account"))
    me_rec = next((a for a in admins if a.get("username") == (current_user() or {}).get("username")), {})
    return render_template("admin_account.html", admins=admins, me=me_rec)

@app.route("/admin/export")
@admin_required
def admin_export():
    return jsonify(get_all_content())

@app.route("/admin/import", methods=["GET", "POST"])
@admin_required
def admin_import():
    if request.method == "POST":
        try:
            data = json.loads(request.form.get("json_data","{}"))
            n = safe_import_content(data)
            flash(f"Imported {n} keys (protected keys untouched).", "success")
        except Exception as e:
            flash(f"Import failed: {e}", "danger")
        return redirect(url_for("admin_import"))
    return render_template("admin_import.html")

if __name__ == "__main__":
    init_db()
    # macOS AirPlay Receiver owns port 5000, so default to 8080 locally.
    # Render/production always provides PORT (and runs via gunicorn, not this block).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
