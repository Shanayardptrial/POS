import os
import re
import html
import json
import uuid
import zipfile
import shutil
import logging
import csv
import secrets
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps
from io import StringIO
from flask import Flask, render_template, request, jsonify, send_file, Response, session, redirect, url_for

# Canonical config — single source of truth (config.py)
from config import BASE_DIR, DATA_DIR, BACKUPS_DIR, LOG_DIR, DATABASE_URL, HOST as CFG_HOST, PORT as CFG_PORT, DEBUG as CFG_DEBUG

from database import (
    db, init_db, migrate_json_data,
    User, Category, MenuItem, Order, OrderItem,
    Table as POSModelTable, PendingOrder, PendingOrderItem,
    Expense, Staff, SalaryPayment, AdminCred, Settings,
    InventoryItem, KOT, KOTItem,
    verify_admin_password, get_admin_role, logger,
    _safe_json_list,
)

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
def _get_secret_key():
    """Return persistent secret key: env var overrides, else data/admin/secret.key (hex 32 bytes)."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_path = Path(__file__).resolve().parent / "data" / "admin" / "secret.key"
    try:
        if key_path.exists():
            key = key_path.read_text(encoding="utf-8").strip()
            if key:
                return key
        key_path.parent.mkdir(parents=True, exist_ok=True)
        new_key = secrets.token_hex(32)
        key_path.write_text(new_key, encoding="utf-8")
        try:
            os.chmod(key_path, 0o600)
        except Exception:
            pass
        return new_key
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to load/generate secret.key: %s", exc)
        return secrets.token_hex(32)

app = Flask(__name__)
app.secret_key = _get_secret_key()
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Session / cookie hardening
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
app.config["SESSION_COOKIE_NAME"] = "pos_session"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
# Limit request payload / uploads (16 MB general, tighter for backup restore)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

init_db(app)
migrate_json_data(app)

# ---------------------------------------------------------------------------
# Security headers & request limits
# ---------------------------------------------------------------------------
@app.after_request
def _set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Basic CSP - allow self, inline styles/scripts needed for admin UI; adjust as needed
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.before_request
def _enforce_content_length():
    # Flask already enforces MAX_CONTENT_LENGTH; return 413 is automatic.
    pass

def get_current_user_id():
    """Return current logged in user ID from session or None."""
    return session.get("user_id")

def seed_default_data_for_user(user_id):
    """Seed initial tables and starter menu items for a new registered user."""
    try:
        default_tables = [
            ("T1", "Table 1", "indoor", 4), ("T2", "Table 2", "indoor", 4),
            ("T3", "Table 3", "indoor", 4), ("T4", "Table 4", "indoor", 4),
            ("T5", "Table 5", "indoor", 4), ("T6", "Table 6", "indoor", 4),
            ("T7", "Table 7", "indoor", 4), ("T8", "Table 8", "indoor", 6),
            ("T9", "Table 9", "indoor", 6), ("T10", "Table 10", "indoor", 8),
            ("P1", "Patio 1", "outdoor", 4), ("P2", "Patio 2", "outdoor", 4),
            ("P3", "Patio 3", "outdoor", 6)
        ]
        for tid, tname, tzone, tcap in default_tables:
            tb = POSModelTable(table_id=f"{tid}_u{user_id}", user_id=user_id, name=tname, zone=tzone, capacity=tcap, status="available")
            db.session.add(tb)

        cats = [
            ("biryani", "Biryani & Rice", "🍲"),
            ("starter", "Starters & Tandoori", "🍗"),
            ("curry", "Main Course Curries", "🥘"),
            ("bread", "Roti & Naan", "🫓"),
            ("beverage", "Drinks & Lassi", "🥤"),
            ("dessert", "Desserts & Sweets", "🍨")
        ]
        for cid, cname, cicon in cats:
            if not db.session.execute(db.select(Category).where(Category.id == cid)).scalar_one_or_none():
                db.session.add(Category(id=cid, name=cname, icon=cicon))

        items = [
            ("chicken_biryani", "Chicken Dum Biryani", 280.0, "biryani", "🍲"),
            ("mutton_biryani", "Hyderabadi Mutton Biryani", 350.0, "biryani", "🍲"),
            ("paneer_tikka", "Paneer Tikka", 220.0, "starter", "🧀"),
            ("chicken_tikka", "Chicken Tikka (6 pcs)", 260.0, "starter", "🍗"),
            ("butter_chicken", "Butter Chicken", 310.0, "curry", "🥘"),
            ("dal_makhani", "Dal Makhani", 210.0, "curry", "🫕"),
            ("butter_naan", "Butter Naan", 45.0, "bread", "🫓"),
            ("mango_lassi", "Mango Lassi", 90.0, "beverage", "🥤"),
            ("gulab_jamun", "Gulab Jamun (2 pcs)", 80.0, "dessert", "🍨")
        ]
        for item_id, item_name, price, cat_id, icon in items:
            mi = MenuItem(id=f"{item_id}_u{user_id}", user_id=user_id, name=item_name, price=price, category_id=cat_id, icon=icon, available=True)
            db.session.add(mi)

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning("Error seeding default data for user %s: %s", user_id, exc)

# ---------------------------------------------------------------------------
# Auth Routes & Endpoints
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login_route():
    if request.method == "GET":
        if "user_id" in session:
            return redirect("/")
        return render_template("login.html")
    
    data = request.get_json(silent=True) or request.form
    username_or_email = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username_or_email or not password:
        return jsonify({"success": False, "message": "Username/email and password required"}), 400

    user = db.session.execute(
        db.select(User).where(
            (User.username == username_or_email) | (User.email == username_or_email.lower())
        )
    ).scalar_one_or_none()

    if not user or not user.check_password(password):
        return jsonify({"success": False, "message": "Invalid username or password"}), 401

    session["user_id"] = user.id
    session["username"] = user.username
    session["restaurant_name"] = user.restaurant_name
    session["admin_token"] = secrets.token_hex(16)
    session["admin_role"] = "admin"
    session.permanent = True

    return jsonify({"success": True, "message": "Login successful", "user": user.to_dict()})


@app.route("/register", methods=["GET", "POST"])
def register_route():
    if request.method == "GET":
        if "user_id" in session:
            return redirect("/")
        return render_template("login.html")

    data = request.get_json(silent=True) or request.form
    restaurant_name = (data.get("restaurant_name") or "My Restaurant").strip()
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not email or not password:
        return jsonify({"success": False, "message": "All fields are required"}), 400

    existing_user = db.session.execute(
        db.select(User).where((User.username == username) | (User.email == email))
    ).scalar_one_or_none()

    if existing_user:
        return jsonify({"success": False, "message": "Username or Email already registered"}), 400

    new_user = User(username=username, email=email, restaurant_name=restaurant_name)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    # Seed initial user tables and menu
    seed_default_data_for_user(new_user.id)

    session["user_id"] = new_user.id
    session["username"] = new_user.username
    session["restaurant_name"] = new_user.restaurant_name
    session["admin_token"] = secrets.token_hex(16)
    session["admin_role"] = "admin"
    session.permanent = True

    return jsonify({"success": True, "message": "Registration successful", "user": new_user.to_dict()})


@app.route("/logout")
def logout_route():
    session.clear()
    return redirect("/login")


@app.route("/api/me")
def api_me():
    if "user_id" not in session:
        return jsonify({"authenticated": False}), 401
    user = db.session.execute(db.select(User).where(User.id == session["user_id"])).scalar_one_or_none()
    if not user:
        session.clear()
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": user.to_dict()})

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

GST_RATE_KEY = "gst_rate"

def _get_gst_rate():
    s = db.session.execute(db.select(Settings).where(Settings.key == GST_RATE_KEY)).scalar_one_or_none()
    try:
        return float(s.value) if s else 5.0
    except (ValueError, TypeError):
        return 5.0


def _err(message, code="GENERAL_ERROR", status=400):
    """Return a consistent error response."""
    return jsonify({"error": message, "code": code}), status


def _total_paid_for_staff_month(staff_id, month):
    """Compute total amount already paid for a staff+month via SalaryPayment records (equal split)."""
    try:
        payments = db.session.execute(
            db.select(SalaryPayment).where(SalaryPayment.month == month)
        ).scalars().all()
        total = 0.0
        for p in payments:
            ids = _safe_json_list(p.staff_ids, [])
            if staff_id in ids and ids:
                # equal split across staff in that payment
                try:
                    total += float(p.amount or 0) / len(ids)
                except Exception:
                    total += float(p.amount or 0)
        return round(total, 2)
    except Exception:
        return 0.0


def _staff_pending_for_month(staff_obj, month):
    paid = _total_paid_for_staff_month(staff_obj.id, month)
    try:
        sal = float(staff_obj.salary or 0)
    except Exception:
        sal = 0.0
    pending = round(max(0.0, sal - paid), 2)
    return paid, pending


# ---------------------------------------------------------------------------
# Input sanitization helpers
# ---------------------------------------------------------------------------
_TABLE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
_CUSTOMER_MAX = 100
_NAME_MAX = 200
_CATEGORY_MAX = 50

def _sanitize_str(raw, max_len=200):
    if not isinstance(raw, str):
        return ""
    return html.escape(raw.strip()[:max_len])

def _validate_table_id(tid):
    if not isinstance(tid, str):
        raise ValueError("Invalid table ID")
    tid = tid.strip()
    if not tid or len(tid) > 20 or not _TABLE_RE.match(tid):
        raise ValueError("Invalid table ID format (alphanumeric, _- , max 20 chars)")
    return tid

def _sanitize_customer(name):
    if not isinstance(name, str):
        return ""
    return html.escape(name.strip()[:_CUSTOMER_MAX])

def _sanitize_discount(subtotal, discount_value, discount_type):
    """Clamp discount: percent 0-100, fixed 0-subtotal, prevent negative totals / XSS."""
    try:
        discount_value = float(discount_value)
    except (ValueError, TypeError):
        discount_value = 0.0
    # Guard against NaN / inf
    if not isinstance(discount_value, (int, float)) or discount_value != discount_value or discount_value in (float("inf"), float("-inf")):
        discount_value = 0.0
    if discount_type == "percent":
        discount_value = max(0.0, min(100.0, discount_value))
    else:
        discount_type = "fixed" if discount_type == "fixed" else "percent" if discount_type == "percent" else "fixed"
        # clamp fixed to [0, subtotal]
        try:
            subtotal_f = float(subtotal)
        except Exception:
            subtotal_f = 0.0
        discount_value = max(0.0, min(subtotal_f, discount_value))
    return discount_value, discount_type

def _sanitize_item_name(name):
    return _sanitize_str(name, _NAME_MAX)

# ---------------------------------------------------------------------------
# Rate limiting (in-memory) for admin login
# ---------------------------------------------------------------------------
_login_attempts: dict = {}  # ip -> {"count": int, "blocked_until": datetime|None, "first": datetime}
_RATE_LIMIT_MAX_FAILS = 5
_RATE_LIMIT_WINDOW = timedelta(minutes=5)

def _is_rate_limited(ip):
    rec = _login_attempts.get(ip)
    if not rec:
        return False, 0
    blocked_until = rec.get("blocked_until")
    if blocked_until and datetime.utcnow() < blocked_until:
        remaining = int((blocked_until - datetime.utcnow()).total_seconds())
        return True, remaining
    # window expired -> reset
    if blocked_until and datetime.utcnow() >= blocked_until:
        _login_attempts.pop(ip, None)
        return False, 0
    # if first failure older than window, reset
    first = rec.get("first")
    if first and datetime.utcnow() - first > _RATE_LIMIT_WINDOW and rec.get("count", 0) < _RATE_LIMIT_MAX_FAILS:
        _login_attempts.pop(ip, None)
        return False, 0
    return False, 0

def _record_failed_login(ip):
    now = datetime.utcnow()
    rec = _login_attempts.get(ip)
    if not rec:
        _login_attempts[ip] = {"count": 1, "first": now, "blocked_until": None}
    else:
        # if blocked period expired, reset
        if rec.get("blocked_until") and now >= rec["blocked_until"]:
            _login_attempts[ip] = {"count": 1, "first": now, "blocked_until": None}
            return
        rec["count"] = rec.get("count", 0) + 1
        if rec["count"] >= _RATE_LIMIT_MAX_FAILS:
            rec["blocked_until"] = now + _RATE_LIMIT_WINDOW

def _clear_login_attempts(ip):
    _login_attempts.pop(ip, None)

# ---------------------------------------------------------------------------
# Auth decorators (fixed)
# ---------------------------------------------------------------------------

def _extract_token():
    token = (
        request.headers.get("Authorization", "")
        or request.headers.get("X-Admin-Token", "")
        or request.cookies.get("admin_token")
        or ""
    )
    if token.startswith("Bearer "):
        token = token[7:]
    return token.strip()


def _require_admin(f):
    """Decorator: require valid admin token matching session['admin_token']."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_token()
        if not token:
            return _err("Authentication required", "UNAUTHORIZED", 401)
        session_token = session.get("admin_token")
        if not session_token or token != session_token:
            return _err("Invalid or expired token", "UNAUTHORIZED", 401)
        return f(*args, **kwargs)
    return decorated


def _require_role(min_role):
    """Decorator: require admin token AND role at least min_role.
    Role hierarchy: admin > manager > waiter > cashier
    Default role is lowest permission (cashier) to avoid privilege escalation.
    """
    _ROLE_LEVEL = {"admin": 4, "manager": 3, "waiter": 2, "cashier": 1}
    min_level = _ROLE_LEVEL.get(min_role, 1)

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = _extract_token()
            if not token:
                return _err("Authentication required", "UNAUTHORIZED", 401)
            session_token = session.get("admin_token")
            if not session_token or token != session_token:
                return _err("Invalid or expired token", "UNAUTHORIZED", 401)
            # Default to lowest privilege, not admin
            current_role = session.get("admin_role", "cashier")
            current_level = _ROLE_LEVEL.get(current_role, 1)
            if current_level < min_level:
                return _err("Insufficient permissions. Required: " + min_role.upper(), "FORBIDDEN", 403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def _deduct_stock_from_order(items):
    """Auto-deduct inventory stock for each menu item in an order.
    Maps menu item ID → inventory item ID (same ID scheme).
    """
    deductions = []
    for entry in items:
        item_id = entry.get("id")
        qty = entry.get("qty", 1)
        if not item_id or not isinstance(qty, int) or qty < 1:
            continue
        success, error = InventoryItem.deduct_stock(item_id, qty)
        if not success:
            logger.warning("Stock deduction skipped for %s: %s", item_id, error)
        else:
            deductions.append({"item_id": item_id, "qty": qty, "success": success})
    return deductions


def _build_order_items(items, menu_items):
    """Validate and enrich cart items with price/name from menu DB."""
    price_map = {m.id: m.price for m in menu_items}
    name_map = {m.id: m.name for m in menu_items}

    if not items or not isinstance(items, list) or len(items) == 0:
        raise ValueError("No items in order")

    order_items = []
    subtotal = 0.0

    for entry in items:
        item_id = entry.get("id")
        qty = entry.get("qty", 1)

        if not item_id or not isinstance(qty, int) or qty < 1:
            raise ValueError(f"Invalid item data: id={item_id}, qty={qty}")

        if item_id not in price_map:
            raise ValueError(f"Invalid item id: {item_id} not found in menu")

        price = price_map[item_id]
        item_total = round(price * qty, 2)
        subtotal = round(subtotal + item_total, 2)

        order_items.append({
            "id": item_id,
            "name": name_map.get(item_id, item_id),
            "price": price,
            "qty": qty,
            "item_total": item_total,
        })

    if not order_items:
        raise ValueError("No valid items in order")

    return order_items, subtotal


def _apply_discount(subtotal, discount_value, discount_type):
    """Return (discount_amount, after_discount, gst, final_total)."""
    import math
    # sanitize subtotal
    try:
        subtotal = float(subtotal)
    except (ValueError, TypeError):
        subtotal = 0.0
    if math.isnan(subtotal) or math.isinf(subtotal) or subtotal < 0:
        subtotal = 0.0
    # sanitize discount_value: handle NaN/negative/inf/None
    try:
        discount_value = float(discount_value)
    except (ValueError, TypeError):
        discount_value = 0.0
    if math.isnan(discount_value) or math.isinf(discount_value) or discount_value < 0:
        discount_value = 0.0

    if discount_type == "percent":
        # cap percent at 0-100
        discount_value = max(0.0, min(100.0, discount_value))
        discount_amount = round(subtotal * (discount_value / 100), 2)
    else:
        # cap fixed discount at subtotal
        discount_value = max(0.0, min(float(subtotal), discount_value))
        discount_amount = round(float(discount_value), 2)

    # ensure discount never exceeds subtotal
    discount_amount = min(discount_amount, subtotal)
    after_discount = round(max(0.0, subtotal - discount_amount), 2)
    gst_rate = _get_gst_rate()
    gst = round(after_discount * (gst_rate / 100), 2)
    final_total = round(after_discount + gst, 2)
    # final safety clamp
    if final_total < 0:
        final_total = 0.0
    if after_discount < 0:
        after_discount = 0.0

    return discount_amount, after_discount, gst, final_total


def _create_final_order(table, customer, payment_mode, items, discount_value, discount_type):
    """Create and persist a finalised order record. Atomic: single commit.
    Sanitizes table/customer/discount to prevent XSS and invalid totals."""
    if not items or not isinstance(items, list) or len(items) == 0:
        raise ValueError("No items in order")
    # Sanitize table/customer/payment_mode
    if table:
        try:
            table = _validate_table_id(str(table))
        except ValueError:
            # sanitize but allow walk-in style: escape and truncate
            table = _sanitize_str(str(table), 20)
    else:
        table = ""
    customer = _sanitize_customer(str(customer) if customer else "")
    valid_modes = {"cash", "card", "upi", "wallet", "online"}
    if payment_mode not in valid_modes:
        payment_mode = "cash"
    discount_type = discount_type if discount_type in ("percent", "fixed") else "percent"
    menu_items = db.session.execute(db.select(MenuItem)).scalars().all()
    order_items_data, subtotal = _build_order_items(items, menu_items)

    if not order_items_data:
        raise ValueError("No valid items in order")

    discount_amount, after_discount, gst, final_total = _apply_discount(
        subtotal, discount_value, discount_type
    )

    bill_id = str(uuid.uuid4())[:8].upper()
    now = datetime.utcnow()
    order = Order(
        bill_id=bill_id,
        date=now,
        table=table,
        customer=customer,
        payment_mode=payment_mode,
        subtotal=subtotal,
        discount=discount_amount,
        gst=gst,
        total=final_total,
    )
    db.session.add(order)
    for oidata in order_items_data:
        oi = OrderItem(
            order_bill_id=bill_id,
            item_id=oidata["id"],
            name=oidata["name"],
            price=oidata["price"],
            qty=oidata["qty"],
            item_total=oidata["item_total"],
        )
        db.session.add(oi)
    # Flush to get order persisted before stock deduction but keep in same transaction
    db.session.flush()

    # Auto-deduct stock without intermediate commit (atomic)
    deductions = []
    for entry in order_items_data:
        item_id = entry.get("id")
        qty = entry.get("qty", 1)
        # Deduct stock inline without committing per item — defer commit
        inv_item = db.session.execute(
            db.select(InventoryItem).where(InventoryItem.id == item_id)
        ).scalar_one_or_none()
        if inv_item:
            if inv_item.quantity >= qty:
                inv_item.quantity -= qty
                deductions.append({"item_id": item_id, "qty": qty, "success": True})
            else:
                logger.warning("Stock deduction skipped for %s: insufficient stock", item_id)
        else:
            logger.warning("Stock deduction skipped for %s: inventory item not found", item_id)

    # Single atomic commit for order + stock
    db.session.commit()
    logger.info("Order created %s | table=%s | total=₹%s | stock_deducted=%d items",
                bill_id, table or "walk-in", final_total, len([d for d in deductions if d.get("success")]))
    return order.to_dict()


# ---------------------------------------------------------------------------
# POS Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("pos_index.html")


@app.route("/api/menu")
def get_menu():
    menu_items = db.session.execute(db.select(MenuItem)).scalars().all()
    categories = db.session.execute(db.select(Category)).scalars().all()
    return jsonify({
        "categories": [c.to_dict() for c in categories],
        "items": [m.to_dict() for m in menu_items],
    })


@app.route("/api/inventory/low-stock")
def api_low_stock():
    items = InventoryItem.low_stock_items()
    return jsonify([i.to_dict() for i in items])


@app.route("/api/order", methods=["POST"])
def create_order():
    try:
        data = request.get_json(silent=True) or {}
        items = data.get("items", [])
        if not items or not isinstance(items, list) or len(items) == 0:
            return _err("No items in order", "INVALID_ORDER")
        # robust discount parsing
        try:
            discount_value = float(data.get("discount", 0))
        except (ValueError, TypeError):
            discount_value = 0.0
        import math as _math
        if _math.isnan(discount_value) or _math.isinf(discount_value):
            discount_value = 0.0
        order = _create_final_order(
            table=data.get("table", ""),
            customer=data.get("customer", ""),
            payment_mode=data.get("paymentMode", "cash"),
            items=items,
            discount_value=discount_value,
            discount_type=data.get("discountType", "percent"),
        )
        return jsonify(order)
    except ValueError as exc:
        logger.warning("Order creation failed: %s", exc)
        return _err(str(exc), "INVALID_ORDER")
    except Exception as exc:
        logger.error("Unexpected error in create_order: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/orders")
def get_orders():
    # pagination via query params: limit and offset/page
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        limit = 50
    limit = max(1, min(limit, 100))  # clamp 1-100

    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)

    # support page param as alternative to offset
    page_param = request.args.get("page")
    if page_param is not None:
        try:
            page = int(page_param)
            if page >= 1:
                offset = (page - 1) * limit
        except (ValueError, TypeError):
            pass

    orders = db.session.execute(
        db.select(Order).order_by(Order.date.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return jsonify([o.to_dict() for o in orders])


@app.route("/api/pending-list")
def list_pending():
    pending = db.session.execute(
        db.select(PendingOrder).order_by(PendingOrder.updated_at.desc())
    ).scalars().all()
    return jsonify({p.table_id: p.to_dict() for p in pending})


@app.route("/api/order/<bill_id>")
def get_order(bill_id):
    order = db.session.execute(
        db.select(Order).where(Order.bill_id == bill_id)
    ).scalar_one_or_none()
    if order:
        return jsonify(order.to_dict())
    return _err("Bill not found", "NOT_FOUND", 404)


@app.route("/api/pending/<table>", methods=["GET"])
def get_pending_order(table):
    try:
        table = _validate_table_id(table)
    except ValueError:
        return _err("Invalid table ID", "INVALID_REQUEST")
    po = db.session.execute(
        db.select(PendingOrder).where(PendingOrder.table_id == table)
    ).scalar_one_or_none()
    if po:
        return jsonify(po.to_dict())
    return jsonify(None)


@app.route("/api/pending", methods=["POST"])
def save_pending_order():
    try:
        data = request.get_json(silent=True) or {}
        table = data.get("table", "")
        if not table:
            return _err("Table is required", "INVALID_REQUEST")
        try:
            table = _validate_table_id(str(table))
        except ValueError as ve:
            return _err(str(ve), "INVALID_REQUEST")
        customer = _sanitize_customer(str(data.get("customer", "")) if data.get("customer") else "")

        menu_items = db.session.execute(db.select(MenuItem)).scalars().all()
        items = data.get("items", [])
        order_items_data, subtotal = _build_order_items(items, menu_items)

        gst_rate = _get_gst_rate()
        gst = round(subtotal * (gst_rate / 100), 2)
        total = round(subtotal + gst, 2)

        po = db.session.execute(
            db.select(PendingOrder).where(PendingOrder.table_id == table)
        ).scalar_one_or_none()

        if po:
            po.customer = customer
            po.subtotal = subtotal
            po.gst = gst
            po.total = total
            po.updated_at = datetime.utcnow()
            # Fix: delete ALL existing PendingOrderItems, handle empty safely
            for old in list(po.items):
                db.session.delete(old)
            db.session.flush()
            for oidata in order_items_data:
                poi = PendingOrderItem(
                    pending_table_id=table,
                    item_id=oidata["id"],
                    name=oidata["name"],
                    price=oidata["price"],
                    qty=oidata["qty"],
                    item_total=oidata["item_total"],
                )
                db.session.add(poi)
        else:
            po = PendingOrder(
                table_id=table,
                customer=customer,
                subtotal=subtotal,
                gst=gst,
                total=total,
                updated_at=datetime.utcnow(),
            )
            db.session.add(po)
            for oidata in order_items_data:
                poi = PendingOrderItem(
                    pending_table_id=table,
                    item_id=oidata["id"],
                    name=oidata["name"],
                    price=oidata["price"],
                    qty=oidata["qty"],
                    item_total=oidata["item_total"],
                )
                db.session.add(poi)

        db.session.commit()
        logger.info("Pending order saved for table %s", table)
        return jsonify(po.to_dict())

    except Exception as exc:
        logger.error("Error saving pending order: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/pending/<table>", methods=["DELETE"])
def clear_pending_order(table):
    try:
        table = _validate_table_id(table)
    except ValueError:
        return _err("Invalid table ID", "INVALID_REQUEST")
    po = db.session.execute(
        db.select(PendingOrder).where(PendingOrder.table_id == table)
    ).scalar_one_or_none()
    if po:
        db.session.delete(po)
        db.session.commit()
        logger.info("Pending order cleared for table %s", table)
    return jsonify({"success": True})


@app.route("/api/pay", methods=["POST"])
def pay_order():
    try:
        data = request.get_json(silent=True) or {}
        table = data.get("table", "")
        customer = data.get("customer", "")
        payment_mode = data.get("paymentMode", "cash")
        items = data.get("items", [])

        if not items or not isinstance(items, list) or len(items) == 0:
            return _err("No items in order", "INVALID_ORDER")

        try:
            discount_value = float(data.get("discount", 0))
        except (ValueError, TypeError):
            discount_value = 0.0
        import math as _math2
        if _math2.isnan(discount_value) or _math2.isinf(discount_value):
            discount_value = 0.0

        order = _create_final_order(
            table=table,
            customer=customer,
            payment_mode=payment_mode,
            items=items,
            discount_value=discount_value,
            discount_type=data.get("discountType", "percent"),
        )

        if table:
            po = db.session.execute(
                db.select(PendingOrder).where(PendingOrder.table_id == table)
            ).scalar_one_or_none()
            if po:
                db.session.delete(po)
                db.session.commit()
            logger.info("Pending order cleared for table %s after payment", table)

        return jsonify(order)

    except ValueError as exc:
        logger.warning("Payment failed: %s", exc)
        return _err(str(exc), "INVALID_ORDER")
    except Exception as exc:
        logger.error("Unexpected error in pay_order: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------------------------------------------------------------------------
# Table Management
# ---------------------------------------------------------------------------

@app.route("/api/table/<table_id>/status", methods=["POST"])
def set_table_status(table_id):
    try:
        try:
            table_id = _validate_table_id(table_id)
        except ValueError as ve:
            return _err(str(ve), "INVALID_REQUEST")
        data = request.get_json(silent=True) or {}
        status = data.get("status", "")
        if status not in ("available", "busy", "reserved"):
            return _err("Invalid status", "INVALID_REQUEST")

        table = db.session.execute(
            db.select(POSModelTable).where(POSModelTable.table_id == table_id)
        ).scalar_one_or_none()
        if not table:
            table = POSModelTable(table_id=table_id, status=status)
            db.session.add(table)
        else:
            table.status = status
            table.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info("Table %s status set to %s", table_id, status)
        return jsonify(table.to_dict())
    except Exception as exc:
        logger.error("Error setting table status: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/tables", methods=["GET"])
def list_tables():
    tables = db.session.execute(db.select(POSModelTable)).scalars().all()
    # numeric sort: T1, T2, ... T10 (lexical would put T10 after T1)
    def _sort_key(t):
        import re as _re
        m = _re.search(r'(\d+)$', t.table_id or '')
        return (int(m.group(1)) if m else 9999, t.table_id or '')
    tables.sort(key=_sort_key)
    return jsonify([t.to_dict() for t in tables])


@app.route("/api/tables", methods=["POST"])
@_require_admin
def create_table():
    try:
        data = request.get_json(silent=True) or {}
        tid = (data.get("table_id") or data.get("id") or "").strip()
        name = _sanitize_str(data.get("name", tid), 100).strip() or tid
        zone = _sanitize_str(data.get("zone", "indoor"), 50).strip().lower() or "indoor"
        if zone not in ("indoor", "outdoor", "patio", "vip", "balcony"):
            zone = "indoor"
            # allow any custom but sanitized; map patio/outdoor
        try:
            tid = _validate_table_id(str(tid))
        except ValueError as ve:
            return _err(str(ve), "INVALID_REQUEST")
        existing = db.session.execute(db.select(POSModelTable).where(POSModelTable.table_id == tid)).scalar_one_or_none()
        if existing:
            return _err("Table ID already exists", "DUPLICATE", 409)
        try:
            capacity = int(data.get("capacity", 4))
        except (ValueError, TypeError):
            capacity = 4
        capacity = max(1, min(capacity, 50))
        status = (data.get("status") or "available").strip().lower()
        if status not in ("available", "busy", "reserved", "clean"):
            status = "available"
        if not name:
            name = tid
        table = POSModelTable(table_id=tid, name=name, status=status, capacity=capacity, zone=zone, updated_at=datetime.utcnow())
        db.session.add(table)
        db.session.commit()
        logger.info("Table created %s (%s)", tid, name)
        return jsonify(table.to_dict())
    except Exception as exc:
        logger.error("Error creating table: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/tables/<table_id>", methods=["PUT"])
@_require_admin
def update_table(table_id):
    try:
        try:
            table_id = _validate_table_id(table_id)
        except ValueError as ve:
            return _err(str(ve), "INVALID_REQUEST")
        table = db.session.execute(db.select(POSModelTable).where(POSModelTable.table_id == table_id)).scalar_one_or_none()
        if not table:
            return _err("Table not found", "NOT_FOUND", 404)
        data = request.get_json(silent=True) or {}
        # rename id? allow new_id
        new_id = data.get("new_id") or data.get("new_table_id")
        if new_id and str(new_id).strip() != table_id:
            try:
                new_id = _validate_table_id(str(new_id).strip())
            except ValueError as ve:
                return _err(str(ve), "INVALID_REQUEST")
            exists = db.session.execute(db.select(POSModelTable).where(POSModelTable.table_id == new_id)).scalar_one_or_none()
            if exists:
                return _err("New Table ID already exists", "DUPLICATE", 409)
            # Prevent rename if pending order exists for old id
            pending = db.session.execute(db.select(PendingOrder).where(PendingOrder.table_id == table_id)).scalar_one_or_none()
            if pending:
                return _err("Cannot rename table with pending order. Clear pending first.", "CONFLICT", 409)
            # Create new row and delete old (PK change)
            new_table = POSModelTable(table_id=new_id, name=table.name, status=table.status, capacity=table.capacity, zone=table.zone, updated_at=datetime.utcnow())
            # copy over mutable fields from request if provided
            if "name" in data:
                n = _sanitize_str(data.get("name",""), 100).strip()
                if n: new_table.name = n
            if "zone" in data:
                z = _sanitize_str(data.get("zone",""), 50).strip().lower()
                if z: new_table.zone = z
            if "capacity" in data:
                try:
                    c = int(data.get("capacity"))
                    new_table.capacity = max(1, min(c, 50))
                except: pass
            if "status" in data:
                s = str(data.get("status")).strip().lower()
                if s in ("available","busy","reserved","clean"):
                    new_table.status = s
            db.session.add(new_table)
            db.session.delete(table)
            db.session.flush()
            db.session.commit()
            logger.info("Table renamed %s -> %s", table_id, new_id)
            return jsonify(new_table.to_dict())
        if "name" in data:
            n = _sanitize_str(data.get("name",""), 100).strip()
            if not n:
                return _err("Name cannot be empty", "INVALID_REQUEST")
            table.name = n
        if "zone" in data:
            z = _sanitize_str(data.get("zone",""), 50).strip().lower()
            if z:
                # normalize
                if z not in ("indoor","outdoor","patio","vip","balcony"):
                    # keep sanitized but allow
                    pass
                table.zone = z
        if "capacity" in data:
            try:
                c = int(data.get("capacity"))
                if c < 1 or c > 50:
                    return _err("Capacity must be 1-50", "INVALID_REQUEST")
                table.capacity = c
            except (ValueError, TypeError):
                return _err("Invalid capacity", "INVALID_REQUEST")
        if "status" in data:
            s = str(data.get("status")).strip().lower()
            if s not in ("available","busy","reserved","clean"):
                return _err("Invalid status", "INVALID_REQUEST")
            table.status = s
        table.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info("Table updated %s", table_id)
        return jsonify(table.to_dict())
    except Exception as exc:
        logger.error("Error updating table: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/tables/<table_id>", methods=["DELETE"])
@_require_admin
def delete_table(table_id):
    try:
        try:
            table_id = _validate_table_id(table_id)
        except ValueError as ve:
            return _err(str(ve), "INVALID_REQUEST")
        table = db.session.execute(db.select(POSModelTable).where(POSModelTable.table_id == table_id)).scalar_one_or_none()
        if not table:
            return _err("Table not found", "NOT_FOUND", 404)
        # check pending order
        pending = db.session.execute(db.select(PendingOrder).where(PendingOrder.table_id == table_id)).scalar_one_or_none()
        if pending:
            # option: force delete with query param? default block
            force = request.args.get("force", "").lower() in ("1","true","yes")
            if not force:
                return _err("Table has pending order. Clear pending or use force delete.", "CONFLICT", 409)
            db.session.delete(pending)
        db.session.delete(table)
        db.session.commit()
        logger.info("Table deleted %s", table_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("Error deleting table: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------------------------------------------------------------------------
# Split Bill
# ---------------------------------------------------------------------------

@app.route("/api/order/split", methods=["POST"])
def split_bill():
    try:
        data = request.get_json(silent=True) or {}
        bill_id = data.get("bill_id", "")
        split_type = data.get("split_type", "equal")
        try:
            portions = int(data.get("portions", 2))
        except (ValueError, TypeError):
            return _err("Invalid portions value", "INVALID_REQUEST")
        custom_amounts = data.get("custom_amounts", [])

        if portions < 2:
            return _err("Portions must be >= 2", "INVALID_REQUEST")

        order = db.session.execute(
            db.select(Order).where(Order.bill_id == bill_id)
        ).scalar_one_or_none()
        if not order:
            return _err("Order not found", "NOT_FOUND", 404)

        if split_type == "equal":
            # Equal split: total/portions for each portion with correct subtotal/gst distribution
            # Use proportional distribution to ensure sum equals order totals (handle rounding)
            split_items = []
            # Calculate per-portion amounts rounded, last portion absorbs rounding residue
            base_total = round(order.total / portions, 2)
            base_subtotal = round(order.subtotal / portions, 2)
            base_gst = round(order.gst / portions, 2)
            base_discount = round(order.discount / portions, 2)

            # Pre-calc sums for n-1 portions, last gets remainder
            for i in range(portions):
                if i < portions - 1:
                    p_total = base_total
                    p_subtotal = base_subtotal
                    p_gst = base_gst
                    p_discount = base_discount
                else:
                    # last portion gets remainder to ensure sum matches order
                    p_total = round(order.total - base_total * (portions - 1), 2)
                    p_subtotal = round(order.subtotal - base_subtotal * (portions - 1), 2)
                    p_gst = round(order.gst - base_gst * (portions - 1), 2)
                    p_discount = round(order.discount - base_discount * (portions - 1), 2)
                    # clamp negatives due to rounding
                    p_total = max(0.0, p_total)
                    p_subtotal = max(0.0, p_subtotal)
                    p_gst = max(0.0, p_gst)
                    p_discount = max(0.0, p_discount)
                split_items.append({
                    "portion": i + 1,
                    "items": [],  # equal split is monetary, not item slicing
                    "subtotal": round(p_subtotal, 2),
                    "discount": round(p_discount, 2),
                    "gst": round(p_gst, 2),
                    "total": round(p_total, 2),
                })

        elif split_type == "fixed":
            if not custom_amounts or not isinstance(custom_amounts, list) or len(custom_amounts) < 2:
                return _err("custom_amounts required for fixed split", "INVALID_REQUEST")
            if len(custom_amounts) != portions:
                return _err("custom_amounts length must match portions", "INVALID_REQUEST")
            # validate custom_amounts are numbers and sum approx equals order.total
            try:
                custom_floats = [round(float(a), 2) for a in custom_amounts]
            except (ValueError, TypeError):
                return _err("Invalid custom_amounts values", "INVALID_REQUEST")
            if any(a < 0 for a in custom_floats):
                return _err("custom_amounts cannot be negative", "INVALID_REQUEST")
            total_assigned = round(sum(custom_floats), 2)
            # allow rounding tolerance: max 1.0 or portions*0.02
            tolerance = max(1.0, portions * 0.02)
            # tighter check: also allow 0.05 per portion
            if abs(total_assigned - round(order.total, 2)) > tolerance:
                return _err(f"custom_amounts sum ({total_assigned}) must approx equal order total ({round(order.total,2)}) within ±{tolerance}", "INVALID_REQUEST")
            split_items = []
            for i in range(portions):
                amt = custom_floats[i]
                # proportional subtotal/gst/discount based on ratio to total
                ratio = (amt / order.total) if order.total else 0
                p_subtotal = round(order.subtotal * ratio, 2)
                p_gst = round(order.gst * ratio, 2)
                p_discount = round(order.discount * ratio, 2)
                # For last portion, adjust to ensure sums match due to rounding
                if i == portions - 1:
                    prev_sub = sum(round(order.subtotal * (custom_floats[j]/order.total),2) for j in range(portions-1)) if order.total else 0
                    prev_gst = sum(round(order.gst * (custom_floats[j]/order.total),2) for j in range(portions-1)) if order.total else 0
                    prev_disc = sum(round(order.discount * (custom_floats[j]/order.total),2) for j in range(portions-1)) if order.total else 0
                    p_subtotal = round(order.subtotal - prev_sub, 2)
                    p_gst = round(order.gst - prev_gst, 2)
                    p_discount = round(order.discount - prev_disc, 2)
                    p_subtotal = max(0.0, p_subtotal)
                    p_gst = max(0.0, p_gst)
                    p_discount = max(0.0, p_discount)
                split_items.append({
                    "portion": i + 1,
                    "custom_amount": round(amt, 2),
                    "items": [],
                    "subtotal": round(p_subtotal, 2),
                    "discount": round(p_discount, 2),
                    "gst": round(p_gst, 2),
                    "total": round(amt, 2),
                })
        else:
            return _err("Invalid split_type. Use 'equal' or 'fixed'", "INVALID_REQUEST")

        return jsonify({
            "bill_id": bill_id,
            "split_type": split_type,
            "portions": portions,
            "split_items": split_items,
        })
    except Exception as exc:
        logger.error("Error splitting bill: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------------------------------------------------------------------------
# KOT (Kitchen Order Ticket)
# ---------------------------------------------------------------------------

@app.route("/api/kot", methods=["POST"])
def generate_kot():
    try:
        data = request.get_json(silent=True) or {}
        order_id = data.get("order_id", "")
        table = data.get("table", "")
        customer = data.get("customer", "")
        items = data.get("items", [])

        if not items or not isinstance(items, list) or len(items) == 0:
            return _err("items are required", "INVALID_REQUEST")

        # validate order_id exists or allow walk-in
        # allow walk-in: order_id empty, "walk-in", "walkin", "WALK-IN" etc, or table-based kot without order
        is_walkin = False
        if not order_id or str(order_id).strip().lower() in ("walk-in", "walkin", "walk_in", ""):
            is_walkin = True
            if not order_id:
                order_id = "WALK-IN"
            # walk-in requires either table or customer or items
            if not table and not customer:
                # still allow but log
                pass
        else:
            # verify order exists
            existing_order = db.session.execute(
                db.select(Order).where(Order.bill_id == str(order_id))
            ).scalar_one_or_none()
            if not existing_order:
                return _err(f"Order {order_id} not found (or use walk-in)", "NOT_FOUND", 404)

        # dedup kot_id collision: loop until unique
        kot_id = str(uuid.uuid4())[:8].upper()
        for _ in range(5):
            exists = db.session.execute(db.select(KOT).where(KOT.id == kot_id)).scalar_one_or_none()
            if not exists:
                break
            kot_id = str(uuid.uuid4())[:8].upper()

        # sanitize table/customer for XSS
        table_s = _sanitize_str(str(table), 20) if table else ""
        if table_s:
            try:
                _validate_table_id(table_s)
            except ValueError:
                table_s = _sanitize_str(table_s, 20)
        customer_s = _sanitize_customer(str(customer) if customer else "")
        kot = KOT(
            id=kot_id,
            order_id=html.escape(str(order_id)[:20]),
            table=table_s,
            customer=customer_s,
            status="pending",
            created_at=datetime.utcnow(),
        )
        db.session.add(kot)
        for item in items:
            item_id = _sanitize_str(str(item.get("id", "")).strip(), 50)
            name = _sanitize_str(str(item.get("name", item_id)).strip(), 200)
            try:
                qty = int(item.get("qty", 1))
            except (ValueError, TypeError):
                qty = 1
            qty = max(1, min(qty, 100))  # clamp qty
            category = _sanitize_str(str(item.get("category", "")).strip(), 50)
            notes = _sanitize_str(str(item.get("special_notes", "")), 500)
            if item_id:
                ki = KOTItem(kot_id=kot_id, item_id=item_id, name=name, qty=qty,
                             category=category, special_notes=notes)
                db.session.add(ki)
        db.session.commit()
        logger.info("KOT generated %s for order %s table=%s", kot_id, order_id, table)
        return jsonify(kot.to_dict())
    except Exception as exc:
        logger.error("Error generating KOT: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/kot/list")
def list_kots():
    kots = db.session.execute(
        db.select(KOT).order_by(KOT.created_at.desc())
    ).scalars().all()
    return jsonify([k.to_dict() for k in kots])


@app.route("/api/kot/<kot_id>", methods=["GET"])
def get_kot(kot_id):
    kot = db.session.execute(
        db.select(KOT).where(KOT.id == kot_id)
    ).scalar_one_or_none()
    if kot:
        return jsonify(kot.to_dict())
    return _err("KOT not found", "NOT_FOUND", 404)


@app.route("/api/kot/<kot_id>/complete", methods=["PUT"])
def complete_kot(kot_id):
    kot = db.session.execute(
        db.select(KOT).where(KOT.id == kot_id)
    ).scalar_one_or_none()
    if not kot:
        return _err("KOT not found", "NOT_FOUND", 404)
    if kot.status == "completed":
        return _err("KOT already completed", "ALREADY_COMPLETED")
    kot.status = "completed"
    kot.completed_at = datetime.utcnow()
    db.session.commit()
    logger.info("KOT %s marked as completed", kot_id)
    return jsonify(kot.to_dict())


# ---------------------------------------------------------------------------
# Inventory Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/admin/inventory", methods=["GET"])
@_require_admin
def get_inventory():
    items = db.session.execute(
        db.select(InventoryItem).order_by(InventoryItem.category, InventoryItem.name)
    ).scalars().all()
    return jsonify([i.to_dict() for i in items])


@app.route("/api/admin/inventory/low-stock", methods=["GET"])
@_require_admin
def get_low_stock():
    items = InventoryItem.low_stock_items()
    return jsonify([i.to_dict() for i in items])


@app.route("/api/admin/inventory", methods=["POST"])
@_require_admin
def add_inventory_item():
    try:
        data = request.get_json(silent=True) or {}
        item_id = _sanitize_str(data.get("id", ""), 50).strip()
        name = _sanitize_str(data.get("name", ""), 200)
        category = _sanitize_str(data.get("category", ""), 100)
        quantity = int(data.get("quantity", 0))
        unit = _sanitize_str(data.get("unit", "pcs"), 20).strip() or "pcs"
        reorder_level = int(data.get("reorder_level", 10))
        cost_per_unit = float(data.get("cost_per_unit", 0))
        # clamp numeric ranges
        quantity = max(0, min(quantity, 1000000))
        reorder_level = max(0, min(reorder_level, 1000000))
        cost_per_unit = max(0.0, min(cost_per_unit, 1e9))

        if not item_id or not name:
            return _err("id and name are required", "INVALID_REQUEST")
        if len(item_id) > 50 or len(name) > 200:
            return _err("id/name too long", "INVALID_REQUEST")

        existing = db.session.execute(
            db.select(InventoryItem).where(InventoryItem.id == item_id)
        ).scalar_one_or_none()
        if existing:
            return _err("Inventory item with this id already exists", "DUPLICATE", 409)

        item = InventoryItem(
            id=item_id,
            name=name,
            category=category,
            quantity=quantity,
            unit=unit,
            reorder_level=reorder_level,
            cost_per_unit=cost_per_unit,
        )
        db.session.add(item)
        db.session.commit()
        logger.info("Inventory item added: %s (%s)", name, item_id)
        return jsonify(item.to_dict())
    except Exception as exc:
        logger.error("Error adding inventory item: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/admin/inventory/<item_id>", methods=["PUT"])
@_require_admin
def update_inventory_item(item_id):
    try:
        data = request.get_json(silent=True) or {}
        item = db.session.execute(
            db.select(InventoryItem).where(InventoryItem.id == item_id)
        ).scalar_one_or_none()
        if not item:
            return _err("Inventory item not found", "NOT_FOUND", 404)

        if "name" in data:
            item.name = _sanitize_str(data["name"], 200)
            if not item.name:
                return _err("Invalid name", "INVALID_REQUEST")
        if "category" in data:
            item.category = _sanitize_str(data["category"], 100)
        if "quantity" in data:
            try:
                qty = int(data["quantity"])
                if qty < 0 or qty > 1000000:
                    return _err("Quantity out of range", "INVALID_REQUEST")
                item.quantity = qty
            except (ValueError, TypeError):
                return _err("Invalid quantity", "INVALID_REQUEST")
        if "unit" in data:
            item.unit = _sanitize_str(data["unit"], 20) or "pcs"
        if "reorder_level" in data:
            try:
                rl = int(data["reorder_level"])
                if rl < 0 or rl > 1000000:
                    return _err("reorder_level out of range", "INVALID_REQUEST")
                item.reorder_level = rl
            except (ValueError, TypeError):
                return _err("Invalid reorder_level", "INVALID_REQUEST")
        if "cost_per_unit" in data:
            try:
                cpu = float(data["cost_per_unit"])
                if cpu < 0 or cpu > 1e9 or cpu != cpu or cpu in (float("inf"), float("-inf")):
                    return _err("Invalid cost_per_unit", "INVALID_REQUEST")
                item.cost_per_unit = cpu
            except (ValueError, TypeError):
                return _err("Invalid cost_per_unit", "INVALID_REQUEST")

        db.session.commit()
        logger.info("Inventory item updated: %s", item_id)
        return jsonify(item.to_dict())
    except Exception as exc:
        logger.error("Error updating inventory item: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/admin/inventory/<item_id>", methods=["DELETE"])
@_require_admin
def delete_inventory_item(item_id):
    try:
        item = db.session.execute(
            db.select(InventoryItem).where(InventoryItem.id == item_id)
        ).scalar_one_or_none()
        if not item:
            return _err("Inventory item not found", "NOT_FOUND", 404)
        db.session.delete(item)
        db.session.commit()
        logger.info("Inventory item deleted: %s", item_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("Error deleting inventory item: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------------

@app.route("/admin")
def admin_page():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("admin.html")


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    ip = request.remote_addr or "unknown"
    limited, remaining = _is_rate_limited(ip)
    if limited:
        logger.warning("Rate limited login attempt from IP %s", ip)
        return _err(f"Too many failed attempts. Try again in {remaining}s", "RATE_LIMITED", 429)
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()[:50]
    password = data.get("password", "")
    if not username or not password:
        return _err("Username and password are required", "INVALID_REQUEST")
    if len(password) > 128:
        return _err("Password too long", "INVALID_REQUEST")
    logged_username, role = verify_admin_password(username, password)
    if logged_username:
        _clear_login_attempts(ip)
        token = secrets.token_hex(16)
        session.clear()
        session["admin_user"] = logged_username
        session["admin_role"] = role or "admin"
        session["admin_token"] = token
        session.permanent = True
        logger.info("Admin login successful: %s (role=%s) token=%s…", logged_username, role or "admin", token[:4])
        resp = jsonify({
            "success": True,
            "token": token,
            "username": logged_username,
            "role": role or "admin",
        })
        # Also set admin_token cookie (HttpOnly) for decorator compatibility
        resp.set_cookie("admin_token", token, httponly=True, samesite="Lax",
                        secure=app.config["SESSION_COOKIE_SECURE"], max_age=12*3600)
        return resp
    _record_failed_login(ip)
    logger.warning("Failed login attempt for '%s' from IP %s", username, ip)
    return _err("Invalid credentials", "INVALID_CREDENTIALS", 401)


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    resp = jsonify({"success": True})
    resp.delete_cookie("admin_token")
    return resp


@app.route("/api/admin/sales")
@_require_admin
def admin_sales():
    orders = db.session.execute(
        db.select(Order).order_by(Order.date.desc())
    ).scalars().all()
    return jsonify([o.to_dict() for o in orders])


@app.route("/api/admin/sales-summary")
@_require_admin
def admin_sales_summary():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    query = db.select(Order)
    if start:
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            query = query.where(Order.date >= start_dt)
        except ValueError:
            pass
    if end:
        try:
            end_dt = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.where(Order.date <= end_dt)
        except ValueError:
            pass
    orders = db.session.execute(query.order_by(Order.date.desc())).scalars().all()
    total_sales = sum(o.total for o in orders)
    total_orders = len(orders)
    return jsonify({
        "start": start,
        "end": end,
        "total_orders": total_orders,
        "total_sales": round(total_sales, 2),
        "orders": [o.to_dict() for o in orders],
    })


# ---------- Expenses ----------

@app.route("/api/admin/expenses", methods=["GET"])
@_require_admin
def get_expenses():
    expenses = db.session.execute(
        db.select(Expense).order_by(Expense.date.desc())
    ).scalars().all()
    return jsonify([e.to_dict() for e in expenses])


@app.route("/api/admin/expenses", methods=["POST"])
@_require_admin
def add_expense():
    try:
        data = request.get_json(silent=True) or {}
        expense = Expense(
            id=str(uuid.uuid4())[:6].upper(),
            date=datetime.utcnow(),
            category=data.get("category", ""),
            description=data.get("description", ""),
            amount=float(data.get("amount", 0)),
            paid_by=data.get("paid_by", "admin"),
        )
        db.session.add(expense)
        db.session.commit()
        logger.info("Expense added: ₹%s (%s)", expense.amount, expense.category)
        return jsonify(expense.to_dict())
    except Exception as exc:
        logger.error("Error adding expense: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/admin/expenses/<expense_id>", methods=["DELETE"])
@_require_admin
def delete_expense(expense_id):
    try:
        expense = db.session.execute(
            db.select(Expense).where(Expense.id == expense_id)
        ).scalar_one_or_none()
        if not expense:
            return _err("Expense not found", "NOT_FOUND", 404)
        db.session.delete(expense)
        db.session.commit()
        logger.info("Expense deleted: %s", expense_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("Error deleting expense: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------- Staff ----------

@app.route("/api/admin/staff", methods=["GET"])
@_require_admin
def get_staff():
    staff = db.session.execute(db.select(Staff).order_by(Staff.name)).scalars().all()
    return jsonify([s.to_dict() for s in staff])


@app.route("/api/admin/staff", methods=["POST"])
@_require_admin
def add_staff():
    try:
        data = request.get_json(silent=True) or {}
        member = Staff(
            id=str(uuid.uuid4())[:6].upper(),
            name=data.get("name", ""),
            role=data.get("role", "staff"),
            salary=float(data.get("salary", 0)),
            join_date=data.get("join_date", datetime.utcnow().strftime("%d-%m-%Y")),
        )
        db.session.add(member)
        db.session.commit()
        logger.info("Staff added: %s (%s)", member.name, member.role)
        return jsonify(member.to_dict())
    except Exception as exc:
        logger.error("Error adding staff: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/admin/staff/<staff_id>", methods=["DELETE"])
@_require_admin
def delete_staff(staff_id):
    try:
        staff = db.session.execute(db.select(Staff).where(Staff.id == staff_id)).scalar_one_or_none()
        if not staff:
            return _err("Staff not found", "NOT_FOUND", 404)
        db.session.delete(staff)
        db.session.commit()
        logger.info("Staff deleted: %s", staff_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("Error deleting staff: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------- Stats ----------

@app.route("/api/admin/stats")
@_require_admin
def admin_stats():
    orders = db.session.execute(db.select(Order)).scalars().all()
    expenses = db.session.execute(db.select(Expense)).scalars().all()
    staff = db.session.execute(db.select(Staff)).scalars().all()
    salary_payments = db.session.execute(
        db.select(SalaryPayment).order_by(SalaryPayment.date.desc())
    ).scalars().all()

    today = datetime.utcnow().strftime("%d-%m-%Y")
    today_orders = [o for o in orders if o.date.strftime("%d-%m-%Y") == today]
    today_sales = sum(o.total for o in today_orders)
    all_sales = sum(o.total for o in orders)
    total_orders = len(orders)

    today_expenses = sum(e.amount for e in expenses if e.date.strftime("%d-%m-%Y") == today)
    total_expenses = sum(e.amount for e in expenses)

    total_salary = sum(s.salary for s in staff)

    current_month = datetime.utcnow().strftime("%Y-%m")
    current_month_paid = sum(p.amount for p in salary_payments if p.month == current_month)
    total_salary_paid = sum(p.amount for p in salary_payments)

    pending_tables = db.session.execute(
        db.select(POSModelTable).where(POSModelTable.status == "busy")
    ).scalars().all()

    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%d-%m-%Y")
    yesterday_orders = [o for o in orders if o.date.strftime("%d-%m-%Y") == yesterday]
    yesterday_sales = sum(o.total for o in yesterday_orders)

    now = datetime.utcnow()
    this_month_orders = [o for o in orders if o.date.month == now.month and o.date.year == now.year]
    this_month_sales = sum(o.total for o in this_month_orders)

    # clamp pending to >=0 (staff may have joined mid-month)
    current_month_pending = max(0.0, total_salary - current_month_paid)
    # net_profit should use actually paid salary, not total obligation
    net_profit = all_sales - total_expenses - total_salary_paid

    # per-staff pending breakdown for accurate UI (advance-aware)
    salary_pending_details = []
    for s in staff:
        paid, pending = _staff_pending_for_month(s, current_month)
        pm = _safe_json_list(s.paid_months, [])
        is_fully_paid = current_month in pm or pending == 0 and paid > 0
        if paid == 0:
            status = "not_paid"
        elif is_fully_paid or pending == 0:
            status = "full"
        else:
            status = "advance"
        salary_pending_details.append({
            "staff_id": s.id,
            "name": s.name,
            "salary": round(float(s.salary or 0), 2),
            "paid": round(paid, 2),
            "pending": round(pending, 2),
            "status": status,
        })

    return jsonify({
        "today_sales": round(today_sales, 2),
        "yesterday_sales": round(yesterday_sales, 2),
        "today_orders": len(today_orders),
        "all_time_sales": round(all_sales, 2),
        "total_orders": total_orders,
        "today_expenses": round(today_expenses, 2),
        "total_expenses": round(total_expenses, 2),
        "total_salary": round(total_salary, 2),
        "this_month_sales": round(this_month_sales, 2),
        "this_month_orders": len(this_month_orders),
        "current_month_salary": round(total_salary, 2),
        "current_month_paid": round(current_month_paid, 2),
        "current_month_pending": round(current_month_pending, 2),
        "total_salary_paid": round(total_salary_paid, 2),
        "net_profit": round(net_profit, 2),
        "pending_tables": len(pending_tables),
        "salary_pending_details": salary_pending_details,
    })


# ---------- Search ----------

@app.route("/api/admin/search", methods=["GET"])
@_require_admin
def search_orders():
    q = request.args.get("q", "").lower()
    orders = db.session.execute(db.select(Order).order_by(Order.date.desc())).scalars().all()

    if q:
        orders = [
            o for o in orders
            if q in o.bill_id.lower()
            or q in o.customer.lower()
            or q in o.table.lower()
        ]

    return jsonify([o.to_dict() for o in orders])


# ---------- Salary Payments ----------

@app.route("/api/admin/salary-payments", methods=["GET"])
@_require_admin
def get_salary_payments():
    payments = db.session.execute(
        db.select(SalaryPayment).order_by(SalaryPayment.date.desc())
    ).scalars().all()
    return jsonify([p.to_dict() for p in payments])


@app.route("/api/admin/salary-pay", methods=["POST"])
@_require_admin
def pay_salary():
    try:
        data = request.get_json(silent=True) or {}
        staff_ids = data.get("staff_ids", [])
        month = (data.get("month") or datetime.utcnow().strftime("%Y-%m")).strip()
        payment_type = (data.get("payment_type") or data.get("type") or "full").strip().lower()
        if payment_type not in ("full", "advance", "partial", "pending"):
            payment_type = "full"
        notes = _sanitize_str(data.get("notes", ""), 500)
        # paid_by from session if available
        paid_by = _sanitize_str(data.get("paid_by") or session.get("admin_user") or "admin", 50)

        if not isinstance(staff_ids, list) or not staff_ids:
            return _err("staff_ids is required", "INVALID_REQUEST")
        # normalize ids
        staff_ids = [str(x).strip() for x in staff_ids if str(x).strip()]
        if not staff_ids:
            return _err("staff_ids is required", "INVALID_REQUEST")
        if not re.match(r"^\d{4}-\d{2}$", month):
            return _err("Invalid month format, expected YYYY-MM", "INVALID_REQUEST")
        try:
            amount = float(data.get("amount", 0))
        except (ValueError, TypeError):
            return _err("Invalid amount", "INVALID_REQUEST")
        if amount <= 0 or amount != amount or amount in (float("inf"), float("-inf")):
            return _err("Amount must be positive", "INVALID_REQUEST")
        if amount > 1e9:
            return _err("Amount too large", "INVALID_REQUEST")

        # fetch staff objs
        staff_objs = db.session.execute(db.select(Staff).where(Staff.id.in_(staff_ids))).scalars().all()
        if len(staff_objs) != len(staff_ids):
            return _err("One or more staff not found", "NOT_FOUND", 404)
        total_salary = sum(float(s.salary or 0) for s in staff_objs)

        # validate amount vs salary based on type
        if payment_type in ("advance", "partial"):
            # advance/partial must be less than total salary (allow equal with warning but not exceed pending)
            # compute total pending for selected staff
            total_pending = 0.0
            for s in staff_objs:
                _, pending = _staff_pending_for_month(s, month)
                total_pending += pending
            # pending already excludes paid amounts from prior payments
            if total_pending == 0:
                return _err("Staff already fully paid for " + month, "ALREADY_PAID")
            if amount > total_pending + 0.01:
                return _err(f"Advance/Partial amount ₹{amount} exceeds pending ₹{round(total_pending,2)} for {month}", "INVALID_REQUEST")
        elif payment_type == "pending":
            total_pending = 0.0
            for s in staff_objs:
                _, pending = _staff_pending_for_month(s, month)
                total_pending += pending
            if total_pending <= 0:
                return _err("No pending amount for " + month, "ALREADY_PAID")
            # allow slight tolerance but amount should approx equal pending
            if abs(amount - total_pending) > max(1.0, total_pending * 0.02):
                # not strict error - just info; allow but clamp
                pass
        elif payment_type == "full":
            # if any staff already marked fully paid for month, reject
            for s in staff_objs:
                pm = _safe_json_list(s.paid_months, [])
                if month in pm:
                    return _err(f"Staff {s.name} already fully paid for {month}", "ALREADY_PAID")
                # also if already partially paid, full would exceed? We'll allow full to pay pending remainder
                # but disallow if amount != total_salary? allow editable, so not strict
                pass

        # status logic
        if payment_type in ("full", "pending"):
            status_val = "completed"
        else:
            status_val = "advance" if payment_type == "advance" else "partial"

        payment_record = SalaryPayment(
            id=str(uuid.uuid4())[:8].upper(),
            date=datetime.utcnow(),
            month=month,
            staff_ids=json.dumps(staff_ids),
            amount=round(amount, 2),
            paid_by=paid_by,
            payment_type=payment_type,
            notes=notes,
            status=status_val,
        )
        db.session.add(payment_record)
        db.session.flush()

        # update paid_months only when fully settled
        for s in staff_objs:
            pm = _safe_json_list(s.paid_months, [])
            if payment_type == "full":
                if month not in pm:
                    pm.append(month)
                    s.paid_months = json.dumps(pm)
            elif payment_type == "pending":
                # after this pending payment, check if fully paid
                paid_after = _total_paid_for_staff_month(s.id, month)
                # _total includes the just-flushed payment (divide equally)
                # compute expected salary
                try:
                    sal = float(s.salary or 0)
                except Exception:
                    sal = 0
                if paid_after >= sal - 0.01:  # tolerance
                    if month not in pm:
                        pm.append(month)
                        s.paid_months = json.dumps(pm)
            else:  # advance / partial: do NOT mark as fully paid
                # ensure not marked as paid; if pending reaches salary via advances, auto-mark
                paid_after = _total_paid_for_staff_month(s.id, month)
                try:
                    sal = float(s.salary or 0)
                except Exception:
                    sal = 0
                if paid_after >= sal - 0.01:
                    if month not in pm:
                        pm.append(month)
                        s.paid_months = json.dumps(pm)

        db.session.commit()
        logger.info("Salary paid: ₹%s for %d staff (month %s) type=%s by %s", amount, len(staff_ids), month, payment_type, paid_by)
        return jsonify(payment_record.to_dict())
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("Error paying salary: %s", exc)
        return _err("Server error: " + str(exc), "SERVER_ERROR", 500)


@app.route("/api/admin/salary-history", methods=["GET"])
@_require_admin
def get_salary_history():
    return get_salary_payments()


# ---------- Charts ----------

@app.route("/api/admin/charts/daily")
@_require_admin
def chart_daily():
    orders = db.session.execute(db.select(Order)).scalars().all()
    try:
        days = int(request.args.get("days", 30))
    except (ValueError, TypeError):
        days = 30
    days = max(1, min(days, 365))
    labels, data_list = [], []

    for i in range(days):
        d = datetime.utcnow() - timedelta(days=i)
        # use full date key with year to avoid cross-year collision, label stays %d-%m
        date_key = d.strftime("%Y-%m-%d")
        label = d.strftime("%d-%m")
        day_sales = sum(o.total for o in orders if o.date.strftime("%Y-%m-%d") == date_key)
        labels.append(label)
        data_list.append(round(day_sales, 2))

    return jsonify({"labels": labels[::-1], "data": data_list[::-1]})


@app.route("/api/admin/charts/categories")
@_require_admin
def chart_categories():
    orders = db.session.execute(db.select(Order)).scalars().all()
    menu_items = db.session.execute(db.select(MenuItem)).scalars().all()
    item_cat_map = {m.id: m.category_id for m in menu_items}
    categories = db.session.execute(db.select(Category)).scalars().all()
    cat_names = {c.id: c.name for c in categories}

    category_sales = {}
    for order in orders:
        for item in order.items:
            cat_id = item_cat_map.get(item.item_id)
            cat_name = cat_names.get(cat_id, "Other")
            category_sales[cat_name] = category_sales.get(cat_name, 0) + item.item_total

    return jsonify({
        "labels": list(category_sales.keys()),
        "data": [round(v, 2) for v in category_sales.values()],
    })


@app.route("/api/admin/charts/top-items")
@_require_admin
def chart_top_items():
    orders = db.session.execute(db.select(Order)).scalars().all()
    item_sales = {}
    for order in orders:
        for item in order.items:
            name = item.name or item.item_id
            item_sales[name] = item_sales.get(name, 0) + item.item_total

    sorted_items = sorted(item_sales.items(), key=lambda x: x[1], reverse=True)[:10]
    return jsonify({
        "labels": [x[0] for x in sorted_items],
        "data": [round(x[1], 2) for x in sorted_items],
    })


@app.route("/api/admin/charts/expenses-income")
@_require_admin
def chart_expenses_income():
    orders = db.session.execute(db.select(Order)).scalars().all()
    expenses = db.session.execute(db.select(Expense)).scalars().all()
    months = 6
    labels, income, expense_data = [], [], []

    for i in range(months):
        d = datetime.utcnow() - timedelta(days=30 * i)
        month_str = d.strftime("%b %Y")
        labels.append(month_str)

        month_start = d.replace(day=1, hour=0, minute=0, second=0)
        month_income = sum(
            o.total for o in orders
            if o.date >= month_start and o.date.month == d.month and o.date.year == d.year
        )
        month_expense = sum(
            e.amount for e in expenses
            if e.date >= month_start and e.date.month == d.month and e.date.year == d.year
        )
        income.append(month_income)
        expense_data.append(month_expense)

    return jsonify({
        "labels": labels[::-1],
        "income": income[::-1],
        "expenses": expense_data[::-1],
    })


# ---------- Export ----------

@app.route("/api/admin/export/orders")
@_require_admin
def export_orders():
    fmt = request.args.get("format", "csv")
    orders = db.session.execute(db.select(Order).order_by(Order.date.desc())).scalars().all()

    if fmt == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Bill ID", "Date", "Table", "Customer", "Items", "Subtotal", "GST", "Total", "Payment Mode"])
        for o in orders:
            items_str = ", ".join([f"{i.name}x{i.qty}" for i in o.items])
            writer.writerow([
                o.bill_id, o.date.strftime("%d-%m-%Y %H:%M"), o.table, o.customer,
                items_str, round(o.subtotal, 2), round(o.gst, 2), round(o.total, 2),
                o.payment_mode,
            ])
        output.seek(0)
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment;filename=orders.csv"})
    return jsonify([o.to_dict() for o in orders])


@app.route("/api/admin/export/expenses")
@_require_admin
def export_expenses():
    fmt = request.args.get("format", "csv")
    expenses = db.session.execute(db.select(Expense).order_by(Expense.date.desc())).scalars().all()

    if fmt == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Category", "Description", "Amount", "Paid By"])
        for e in expenses:
            writer.writerow([
                e.date.strftime("%d-%m-%Y %H:%M") if e.date else "",
                e.category, e.description, round(e.amount, 2), e.paid_by,
            ])
        output.seek(0)
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment;filename=expenses.csv"})
    return jsonify([e.to_dict() for e in expenses])


@app.route("/api/admin/export/staff")
@_require_admin
def export_staff():
    fmt = request.args.get("format", "csv")
    staff = db.session.execute(db.select(Staff).order_by(Staff.name)).scalars().all()

    if fmt == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "Role", "Join Date", "Monthly Salary"])
        for s in staff:
            writer.writerow([s.name, s.role, s.join_date, round(s.salary, 2)])
        output.seek(0)
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment;filename=staff.csv"})
    return jsonify([s.to_dict() for s in staff])


@app.route("/api/admin/export/inventory")
@_require_admin
def export_inventory():
    fmt = request.args.get("format", "csv")
    items = db.session.execute(
        db.select(InventoryItem).order_by(InventoryItem.category, InventoryItem.name)
    ).scalars().all()

    if fmt == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Name", "Category", "Quantity", "Unit", "Reorder Level", "Cost/Unit", "Low Stock"])
        for item in items:
            writer.writerow([
                item.id, item.name, item.category, item.quantity, item.unit,
                item.reorder_level, round(item.cost_per_unit, 2),
                "Yes" if item.quantity <= item.reorder_level else "No",
            ])
        output.seek(0)
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment;filename=inventory.csv"})
    return jsonify([i.to_dict() for i in items])


# ---------------------------------------------------------------------------
# Daily Report
# ---------------------------------------------------------------------------

@app.route("/api/admin/report/daily")
@_require_admin
def daily_report():
    date = request.args.get("date", datetime.utcnow().strftime("%d-%m-%Y"))
    orders = db.session.execute(db.select(Order)).scalars().all()
    day_orders = [o for o in orders if o.date.strftime("%d-%m-%Y") == date]
    total_sales = sum(o.total for o in day_orders)

    hour_counts = {}
    for o in day_orders:
        hour = o.date.strftime("%H")
        hour_counts[hour] = hour_counts.get(hour, 0) + 1

    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else "-"

    item_counts = {}
    for o in day_orders:
        for item in o.items:
            item_counts[item.name] = item_counts.get(item.name, 0) + item.qty
    top_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # payment mode breakdown
    payment_breakdown = {}
    payment_totals = {}
    for o in day_orders:
        mode = (o.payment_mode or "cash").lower()
        payment_breakdown[mode] = payment_breakdown.get(mode, 0) + 1
        payment_totals[mode] = round(payment_totals.get(mode, 0) + o.total, 2)

    return jsonify({
        "date": date,
        "total_orders": len(day_orders),
        "total_sales": round(total_sales, 2),
        "avg_order": round(total_sales / len(day_orders), 2) if day_orders else 0,
        "peak_hour": f"{peak_hour}:00" if peak_hour != "-" else "-",
        "top_items": [{"name": i[0], "qty": i[1]} for i in top_items],
        "payment_breakdown": payment_breakdown,
        "payment_totals": payment_totals,
        "payment_modes": {k: {"count": payment_breakdown[k], "total": payment_totals[k]} for k in payment_breakdown},
    })


# ---------------------------------------------------------------------------
# Menu Editor
# ---------------------------------------------------------------------------

@app.route("/api/admin/menu/items", methods=["GET"])
@_require_admin
def get_menu_items():
    items = db.session.execute(db.select(MenuItem)).scalars().all()
    return jsonify([m.to_dict() for m in items])


@app.route("/api/admin/menu/items", methods=["POST"])
@_require_admin
def add_menu_item():
    try:
        data = request.get_json(silent=True) or {}
        name = data.get("name", "").strip()
        price = data.get("price", 0)
        category = data.get("category", "starter")

        if not name or not price:
            return _err("Name and price are required", "INVALID_REQUEST")

        item = MenuItem(
            id=str(uuid.uuid4())[:8].lower(),
            name=name,
            price=float(price),
            category_id=category,
            available=data.get("available", True),
            icon=(data.get("icon") or data.get("emoji") or "").strip()[:20],
        )
        db.session.add(item)
        db.session.commit()
        logger.info("Menu item added: %s (₹%s)", name, item.price)
        return jsonify(item.to_dict())
    except Exception as exc:
        logger.error("Error adding menu item: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/admin/menu/items/<item_id>", methods=["PUT"])
@_require_admin
def update_menu_item(item_id):
    try:
        data = request.get_json(silent=True) or {}
        item = db.session.execute(
            db.select(MenuItem).where(MenuItem.id == item_id)
        ).scalar_one_or_none()
        if not item:
            return _err("Item not found", "NOT_FOUND", 404)

        item.name = data.get("name", item.name).strip()
        item.price = float(data.get("price", item.price))
        item.category_id = data.get("category", item.category_id)
        item.available = data.get("available", item.available)
        if "icon" in data or "emoji" in data:
            item.icon = (data.get("icon") or data.get("emoji") or "").strip()[:20]
        db.session.commit()
        logger.info("Menu item updated: %s", item_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("Error updating menu item: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/admin/menu/items/<item_id>", methods=["DELETE"])
@_require_admin
def delete_menu_item(item_id):
    try:
        item = db.session.execute(
            db.select(MenuItem).where(MenuItem.id == item_id)
        ).scalar_one_or_none()
        if not item:
            return _err("Item not found", "NOT_FOUND", 404)
        db.session.delete(item)
        db.session.commit()
        logger.info("Menu item deleted: %s", item_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("Error deleting menu item: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------------------------------------------------------------------------
# Menu Categories
# ---------------------------------------------------------------------------

@app.route("/api/admin/menu/categories", methods=["GET"])
@_require_admin
def get_menu_categories():
    categories = db.session.execute(db.select(Category).order_by(Category.id)).scalars().all()
    return jsonify([c.to_dict() for c in categories])


@app.route("/api/admin/menu/categories", methods=["POST"])
@_require_admin
def add_menu_category():
    try:
        data = request.get_json(silent=True) or {}
        cat_id = data.get("id", "").strip()
        name = data.get("name", "").strip()
        icon = data.get("icon", "")

        if not cat_id or not name:
            return _err("id and name are required", "INVALID_REQUEST")

        existing = db.session.execute(
            db.select(Category).where(Category.id == cat_id)
        ).scalar_one_or_none()
        if existing:
            return _err("Category already exists", "DUPLICATE", 409)

        category = Category(id=cat_id, name=name, icon=icon)
        db.session.add(category)
        db.session.commit()
        logger.info("Category added: %s", name)
        return jsonify(category.to_dict())
    except Exception as exc:
        logger.error("Error adding category: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/admin/menu/categories/<cat_id>", methods=["PUT"])
@_require_admin
def update_menu_category(cat_id):
    try:
        data = request.get_json(silent=True) or {}
        category = db.session.execute(
            db.select(Category).where(Category.id == cat_id)
        ).scalar_one_or_none()
        if not category:
            return _err("Category not found", "NOT_FOUND", 404)
        if "name" in data:
            name = _sanitize_str(data.get("name", ""), 100).strip()
            if not name:
                return _err("Invalid name", "INVALID_REQUEST")
            category.name = name
        if "icon" in data:
            icon = _sanitize_str(data.get("icon", ""), 20).strip()
            category.icon = icon
        db.session.commit()
        logger.info("Category updated: %s -> name=%s icon=%s", cat_id, category.name, category.icon)
        return jsonify(category.to_dict())
    except Exception as exc:
        logger.error("Error updating category: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


@app.route("/api/admin/menu/categories/<cat_id>", methods=["DELETE"])
@_require_admin
def delete_menu_category(cat_id):
    try:
        category = db.session.execute(
            db.select(Category).where(Category.id == cat_id)
        ).scalar_one_or_none()
        if not category:
            return _err("Category not found", "NOT_FOUND", 404)
        db.session.delete(category)
        db.session.commit()
        logger.info("Category deleted: %s", cat_id)
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("Error deleting category: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
def get_public_settings():
    # public — for POS header & print (no auth)
    s = _load_settings()
    # expose only safe fields + logo b64
    return jsonify({
        "restaurant_name": s.get("restaurant_name", "Restaurant POS"),
        "restaurant_address": s.get("restaurant_address", ""),
        "restaurant_phone": s.get("restaurant_phone", ""),
        "restaurant_email": s.get("restaurant_email", ""),
        "gst_number": s.get("gst_number", ""),
        "gst_rate": s.get("gst_rate", "5"),
        "footer_text": s.get("footer_text", ""),
        "restaurant_logo_b64": s.get("restaurant_logo_b64", ""),
    })


@app.route("/api/admin/settings", methods=["GET"])
@_require_admin
def get_settings():
    settings = _load_settings()
    return jsonify(settings)


def _load_settings():
    """Load all settings into a dict."""
    rows = db.session.execute(db.select(Settings)).scalars().all()
    return {r.key: r.value for r in rows}


@app.route("/api/admin/settings", methods=["PUT"])
@_require_admin
def update_settings():
    try:
        data = request.get_json(silent=True) or {}
        for key in ("restaurant_name", "restaurant_address", "restaurant_phone", "restaurant_email", "gst_number", "gst_rate", "footer_text"):
            if key in data:
                s = db.session.execute(
                    db.select(Settings).where(Settings.key == key)
                ).scalar_one_or_none()
                if s:
                    s.value = str(data[key])
                else:
                    db.session.add(Settings(key=key, value=str(data[key])))
                # also sync logo_data if present as base64
                if key == "restaurant_logo" and data.get("restaurant_logo"):
                    # store separately handled by upload endpoint, but allow base64 fallback
                    pass
        # handle logo base64 if sent as restaurant_logo_b64
        if "restaurant_logo_b64" in data:
            s = db.session.execute(db.select(Settings).where(Settings.key == "restaurant_logo_b64")).scalar_one_or_none()
            v = str(data["restaurant_logo_b64"])[:800000]  # cap 800k
            if s:
                s.value = v
            else:
                db.session.add(Settings(key="restaurant_logo_b64", value=v))
        db.session.commit()
        logger.info("Settings updated")
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("Error updating settings: %s", exc)
        return _err("Server error", "SERVER_ERROR", 500)


# ---------------------------------------------------------------------------
# Firm Logo — upload & serve (dot-matrix bill header)
# ---------------------------------------------------------------------------

@app.route("/api/firm/logo", methods=["GET"])
def get_firm_logo():
    # serve firm logo — b64 from Settings or file
    b64_row = db.session.execute(db.select(Settings).where(Settings.key == "restaurant_logo_b64")).scalar_one_or_none()
    if b64_row and b64_row.value and b64_row.value.startswith("data:"):
        # redirect to data url not needed — return 404, frontend will use Settings directly
        return _err("Use settings b64", "NOT_FILE", 404)
    logo_path = DATA_DIR / "firm_logo.png"
    if logo_path.exists():
        return send_file(str(logo_path), mimetype="image/png")
    # fallback — check Settings file path
    row = db.session.execute(db.select(Settings).where(Settings.key == "restaurant_logo")).scalar_one_or_none()
    if row and row.value and Path(row.value).exists():
        return send_file(row.value, mimetype="image/png")
    return _err("No logo", "NOT_FOUND", 404)


@app.route("/api/admin/firm/logo", methods=["POST"])
@_require_admin
def upload_firm_logo():
    try:
        # accept multipart file OR json b64
        if request.files.get("logo"):
            f = request.files["logo"]
            if f.content_length and f.content_length > 2 * 1024 * 1024:
                return _err("Logo too large (max 2MB)", "TOO_LARGE")
            data = f.read()
            if len(data) > 2 * 1024 * 1024:
                return _err("Logo too large (max 2MB)", "TOO_LARGE")
            # validate png/jpg
            import base64
            b64 = base64.b64encode(data).decode("ascii")
            mime = f.mimetype or "image/png"
            if "jpeg" in mime or "jpg" in mime:
                mime = "image/jpeg"
            else:
                mime = "image/png"
            data_url = f"data:{mime};base64,{b64}"
            s = db.session.execute(db.select(Settings).where(Settings.key == "restaurant_logo_b64")).scalar_one_or_none()
            if s:
                s.value = data_url
            else:
                db.session.add(Settings(key="restaurant_logo_b64", value=data_url))
            # also save file for backup
            try:
                (DATA_DIR / "firm_logo.png").write_bytes(data)
            except Exception:
                pass
            db.session.commit()
            logger.info("Firm logo uploaded %s bytes", len(data))
            return jsonify({"success": True, "logo": data_url[:120]+"..."})

        data = request.get_json(silent=True) or {}
        b64 = data.get("logo_b64") or data.get("restaurant_logo_b64") or ""
        if b64 and b64.startswith("data:"):
            if len(b64) > 900000:
                return _err("Logo too large", "TOO_LARGE")
            s = db.session.execute(db.select(Settings).where(Settings.key == "restaurant_logo_b64")).scalar_one_or_none()
            if s:
                s.value = b64
            else:
                db.session.add(Settings(key="restaurant_logo_b64", value=b64))
            db.session.commit()
            return jsonify({"success": True})
        return _err("No logo provided", "INVALID_REQUEST")
    except Exception as exc:
        logger.error("Logo upload failed: %s", exc)
        return _err("Upload failed", "SERVER_ERROR", 500)


# ---------------------------------------------------------------------------
# Backup & Restore
# ---------------------------------------------------------------------------

@app.route("/api/admin/backup", methods=["POST"])
@_require_admin
def create_backup():
    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUPS_DIR / f"backup_{timestamp}.zip"

        with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Backup the SQLite database
            db_path = DATA_DIR / "pos.db"
            if db_path.exists():
                zipf.write(db_path, "data/pos.db")

            # Backup the menu JSON for compatibility
            menu_file = DATA_DIR / "menu.json"
            if menu_file.exists():
                zipf.write(menu_file, "data/menu.json")

        logger.info("Backup created: %s", backup_file.name)
        return jsonify({"success": True, "filename": backup_file.name})
    except Exception as exc:
        logger.error("Backup creation failed: %s", exc)
        return _err("Backup failed", "BACKUP_ERROR", 500)


@app.route("/api/admin/backups", methods=["GET"])
@_require_admin
def list_backups():
    if not BACKUPS_DIR.exists():
        return jsonify([])
    backups = []
    for f in sorted(BACKUPS_DIR.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        backups.append({
            "filename": f.name,
            "size": f.stat().st_size,
            "date": f.stat().st_mtime,
        })
    return jsonify(backups)


@app.route("/api/admin/download-backup/<filename>")
@_require_admin
def download_backup(filename):
    backup_file = BACKUPS_DIR / filename
    if not backup_file.exists():
        return _err("Backup not found", "NOT_FOUND", 404)
    return send_file(str(backup_file), as_attachment=True, download_name=filename)


@app.route("/api/admin/restore", methods=["POST"])
@_require_admin
def restore_backup():
    """POST /api/admin/restore — restore from backup.

    Accepts either:
      - multipart/form-data with field `file` (zip upload)
      - JSON body `{"filename": "backup_*.zip"}` (server-side file)

    Validates ZIP, backs up current DB, safely extracts, and cleans up.
    """
    def _safe_extract(zip_path: Path, extract_to: Path):
        """Validate and safely extract zip — prevents ZipSlip."""
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Validate zip integrity first
            bad = zf.testzip()
            if bad is not None:
                raise zipfile.BadZipFile(f"Corrupt entry: {bad}")
            members = zf.namelist()
            if not members:
                raise ValueError("Backup ZIP is empty")
            # Safety: reject absolute paths or path traversal
            for m in members:
                p = Path(m)
                if p.is_absolute() or ".." in p.parts:
                    raise ValueError(f"Unsafe path in ZIP: {m}")
                # Only allow expected prefixes
                if not (m.startswith("data/") or m.startswith("pos.db") or m.startswith("data\\")):
                    # Allow bare pos.db at root for older backups
                    if m not in ("pos.db", "menu.json") and not m.startswith("data/"):
                        logger.warning("Unexpected entry in backup: %s", m)
            # Ensure at least pos.db or data/pos.db present
            has_db = any(m.endswith("pos.db") for m in members)
            if not has_db:
                raise ValueError("Backup ZIP does not contain pos.db")
            zf.extractall(str(extract_to))

    def _backup_current_db():
        """Create a safety backup of current DB before overwriting."""
        db_file = DATA_DIR / "pos.db"
        if not db_file.exists():
            return None
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safety = BACKUPS_DIR / f"pre_restore_backup_{ts}.zip"
        try:
            with zipfile.ZipFile(safety, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(db_file, "data/pos.db")
                mf = DATA_DIR / "menu.json"
                if mf.exists():
                    zf.write(mf, "data/menu.json")
            logger.info("Safety backup created before restore: %s", safety.name)
            return safety
        except Exception as e:
            logger.warning("Failed to create safety backup: %s", e)
            return None

    temp_zip = None
    try:
        # --- Determine source ZIP ---
        if request.files.get("file"):
            uploaded = request.files["file"]
            if not uploaded.filename or not uploaded.filename.lower().endswith(".zip"):
                return _err("Only .zip files are accepted", "INVALID_REQUEST")
            # Enforce size limit already via MAX_CONTENT_LENGTH (16MB); extra check
            uploaded.seek(0, os.SEEK_END)
            size = uploaded.tell()
            uploaded.seek(0)
            if size > 50 * 1024 * 1024:
                return _err("Backup file too large (max 50MB)", "INVALID_REQUEST")
            # Validate zip header before saving
            header = uploaded.read(4)
            uploaded.seek(0)
            if header[:2] != b"PK":
                return _err("Invalid ZIP file", "INVALID_REQUEST")
            # Save to temp location for validation
            fd, temp_path = tempfile.mkstemp(suffix=".zip", dir=str(BACKUPS_DIR))
            os.close(fd)
            temp_zip = Path(temp_path)
            uploaded.save(str(temp_zip))
            # Validate is actually a zip
            if not zipfile.is_zipfile(temp_zip):
                temp_zip.unlink(missing_ok=True)
                return _err("Invalid ZIP file", "INVALID_REQUEST")
            source_zip = temp_zip
            is_upload = True
        else:
            data = request.get_json(silent=True) or {}
            backup_name = data.get("filename", "").strip()
            if not backup_name:
                return _err("Filename required (or upload file as 'file')", "INVALID_REQUEST")
            # Sanitize filename — no path separators
            if "/" in backup_name or "\\" in backup_name or ".." in backup_name:
                return _err("Invalid filename", "INVALID_REQUEST")
            if not backup_name.lower().endswith(".zip"):
                return _err("Only .zip backups can be restored", "INVALID_REQUEST")
            backup_file = BACKUPS_DIR / backup_name
            if not backup_file.exists():
                return _err("Backup not found", "NOT_FOUND", 404)
            if not zipfile.is_zipfile(backup_file):
                return _err("Backup file is not a valid ZIP", "RESTORE_ERROR", 500)
            source_zip = backup_file
            is_upload = False

        # --- Safety backup of current DB ---
        _backup_current_db()

        # --- Close DB connections before overwriting file ---
        try:
            db.session.close()
            db.engine.dispose()
        except Exception:
            pass

        # --- Safe extract ---
        _safe_extract(source_zip, DATA_DIR.parent if "data/pos.db" in zipfile.ZipFile(source_zip).namelist() else DATA_DIR)

        # Handle both zip layouts: some zips store data/pos.db, some store pos.db at root
        # If extracted to parent (contains data/pos.db), it's already correct
        # If extracted to DATA_DIR and created data/pos.db inside data/, move it
        nested = DATA_DIR / "data" / "pos.db"
        if nested.exists():
            # Zip contained data/pos.db but we extracted into DATA_DIR -> fix nesting
            shutil.move(str(nested), str(DATA_DIR / "pos.db"))
            # Clean empty nested dir
            try:
                (DATA_DIR / "data").rmdir()
            except Exception:
                pass

        # Cleanup temp file
        if is_upload and temp_zip and temp_zip.exists():
            temp_zip.unlink(missing_ok=True)

        logger.info("Data restored from %s (upload=%s)", source_zip.name, is_upload)
        return jsonify({"success": True, "restored_from": source_zip.name})
    except zipfile.BadZipFile as exc:
        logger.error("Restore failed — bad zip: %s", exc)
        if temp_zip and Path(temp_zip).exists():
            Path(temp_zip).unlink(missing_ok=True)
        return _err(f"Invalid backup ZIP: {exc}", "RESTORE_ERROR", 500)
    except ValueError as exc:
        logger.warning("Restore validation failed: %s", exc)
        if temp_zip and Path(temp_zip).exists():
            Path(temp_zip).unlink(missing_ok=True)
        return _err(str(exc), "INVALID_REQUEST")
    except Exception as exc:
        logger.error("Restore failed: %s", exc)
        if temp_zip and Path(temp_zip).exists():
            Path(temp_zip).unlink(missing_ok=True)
        return _err("Restore failed", "RESTORE_ERROR", 500)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Host/port/debug from env (via config) with fallbacks; auto-migrate already ran above.
    host = os.environ.get("HOST", CFG_HOST)
    # Support 0.0.0.0 for LAN exposure, 127.0.0.1 for local only
    if host not in ("127.0.0.1", "0.0.0.0", "localhost"):
        logger.warning("HOST=%s not in allowlist, defaulting to 127.0.0.1", host)
        host = "127.0.0.1"
    try:
        port = int(os.environ.get("PORT", str(CFG_PORT)))
    except ValueError:
        port = 5500
    debug = CFG_DEBUG
    # FLASK_DEBUG / DEBUG env already handled in config; allow --debug CLI override
    if os.environ.get("FLASK_ENV", "").lower() == "development":
        debug = True

    # Ensure DB migrated on startup (idempotent)
    try:
        with app.app_context():
            from database import db as _db
            _db.create_all()
    except Exception as exc:
        logger.warning("Auto-migrate check failed: %s", exc)

    logger.info("Restaurant POS Server starting on http://%s:%s (debug=%s)", host, port, debug)
    # Use waitress in production if available and not in debug
    use_waitress = os.environ.get("USE_WAITRESS", "0").lower() in ("1", "true", "yes") and not debug
    if use_waitress:
        try:
            from waitress import serve  # type: ignore
            logger.info("Serving with waitress (production)")
            serve(app, host=host, port=port)
        except ImportError:
            logger.warning("waitress not installed, falling back to Flask dev server")
            app.run(host=host, port=port, debug=debug)
    else:
        app.run(host=host, port=port, debug=debug)
