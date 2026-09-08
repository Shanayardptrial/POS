import os
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime
from functools import lru_cache

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Text, func, DateTime, String, Float, Boolean, Integer, ForeignKey, inspect, text
from sqlalchemy.orm import DeclarativeBase, relationship
import bcrypt

# Canonical paths — single source of truth lives in config.py
from config import (
    BASE_DIR,
    DATA_DIR,
    LOG_DIR,
    LOGS_DIR,
    LOGS,
    BACKUPS_DIR,
    BACKUPS,
    DATABASE_URL,
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "pos.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Re-export for backwards-compat: `from database import BACKUPS_DIR, DATA_DIR` etc.
__all__ = [
    "BASE_DIR",
    "DATA_DIR",
    "LOG_DIR",
    "LOGS_DIR",
    "LOGS",
    "BACKUPS_DIR",
    "BACKUPS",
    "DATABASE_URL",
]

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Category(Base):
    __tablename__ = "categories"

    id = db.Column(String(50), primary_key=True)
    name = db.Column(String(100), nullable=False)
    icon = db.Column(String(20), default="")

    items = relationship("MenuItem", back_populates="category", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "icon": self.icon or ""}


# Helper: safe JSON list loader
def _safe_json_list(value, default=None):
    """Safely parse JSON list from string; return default on failure."""
    if default is None:
        default = []
    if value is None:
        return default
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s or s == "":
            return default
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, list) else default
        except Exception:
            return default
    return default


def _parse_date_flexible(date_str):
    """Try multiple date formats, fallback to utcnow. Handles iso and legacy formats."""
    if not date_str or not isinstance(date_str, str):
        return datetime.utcnow()
    s = date_str.strip()
    if not s:
        return datetime.utcnow()
    formats = ("%d-%m-%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M:%S")
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Try isoformat as last resort
    try:
        # fromisoformat handles 2026-01-04T12:00:00 etc.
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        pass
    logger.warning("Unparseable date '%s', using utcnow()", s)
    return datetime.utcnow()


def verify_password(plain_password, hashed):
    """Verify plain password against bcrypt hash, handling corrupted hashes gracefully."""
    try:
        if not plain_password or not hashed:
            return False
        if isinstance(hashed, str):
            hashed_bytes = hashed.encode("utf-8")
        else:
            hashed_bytes = hashed
        if isinstance(plain_password, str):
            plain_bytes = plain_password.encode("utf-8")
        else:
            plain_bytes = plain_password
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception as exc:
        logger.warning("Corrupted password hash encountered: %s", exc)
        return False


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        db.Index("idx_menu_items_category", "category_id"),
        db.Index("idx_menu_items_available", "available"),
    )

    id = db.Column(String(50), primary_key=True)
    name = db.Column(String(200), nullable=False)
    price = db.Column(Float, nullable=False)
    category_id = db.Column(String(50), ForeignKey("categories.id"), nullable=False)
    available = db.Column(Boolean, default=True)
    icon = db.Column(String(20), default="")

    category = relationship("Category", back_populates="items")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "price": self.price,
            "category": self.category_id,
            "available": self.available if self.available is not None else True,
            "icon": self.icon or "",
        }


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        db.Index("idx_orders_table", "table"),
        db.Index("idx_orders_date", "date"),
        db.Index("idx_orders_customer", "customer"),
    )

    bill_id = db.Column(String(20), primary_key=True)
    date = db.Column(DateTime, nullable=False)
    table = db.Column(String(20), default="")
    customer = db.Column(String(100), default="")
    payment_mode = db.Column(String(20), default="cash")
    subtotal = db.Column(Float, default=0.0)
    discount = db.Column(Float, default=0.0)
    gst = db.Column(Float, default=0.0)
    total = db.Column(Float, default=0.0)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "bill_id": self.bill_id,
            "date": self.date.strftime("%d-%m-%Y %H:%M") if self.date else "",
            "table": self.table,
            "customer": self.customer,
            "paymentMode": self.payment_mode,
            "items": [item.to_dict() for item in self.items],
            "subtotal": round(self.subtotal, 2),
            "discount": round(self.discount, 2),
            "gst": round(self.gst, 2),
            "total": round(self.total, 2),
        }


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        db.Index("idx_order_items_bill", "order_bill_id"),
        db.Index("idx_order_items_item", "item_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_bill_id = db.Column(String(20), ForeignKey("orders.bill_id"), nullable=False)
    item_id = db.Column(String(50), nullable=False)
    name = db.Column(String(200), nullable=False)
    price = db.Column(Float, nullable=False)
    qty = db.Column(Integer, nullable=False)
    item_total = db.Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")

    def to_dict(self):
        return {
            "id": self.item_id,
            "name": self.name,
            "price": self.price,
            "qty": self.qty,
            "item_total": round(self.item_total, 2),
        }


class Table(Base):
    __tablename__ = "tables"
    __table_args__ = (
        db.Index("idx_tables_status", "status"),
    )

    table_id = db.Column(String(20), primary_key=True)
    name = db.Column(String(100), default="")
    status = db.Column(String(20), default="available")
    capacity = db.Column(Integer, default=4)
    zone = db.Column(String(50), default="indoor")
    updated_at = db.Column(DateTime)

    def to_dict(self):
        return {
            "table_id": self.table_id,
            "name": self.name or self.table_id,
            "status": self.status,
            "capacity": self.capacity if self.capacity is not None else 4,
            "zone": self.zone or "indoor",
            "updated_at": self.updated_at.strftime("%d-%m-%Y %H:%M") if self.updated_at else "",
        }


class PendingOrder(Base):
    __tablename__ = "pending_orders"
    __table_args__ = (
        db.Index("idx_pending_orders_updated", "updated_at"),
    )

    table_id = db.Column(String(20), primary_key=True)
    customer = db.Column(String(100), default="")
    subtotal = db.Column(Float, default=0.0)
    gst = db.Column(Float, default=0.0)
    total = db.Column(Float, default=0.0)
    updated_at = db.Column(DateTime)

    items = relationship("PendingOrderItem", back_populates="pending", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "table": self.table_id,
            "customer": self.customer,
            "items": [item.to_dict() for item in self.items],
            "subtotal": round(self.subtotal, 2),
            "gst": round(self.gst, 2),
            "total": round(self.total, 2),
            "updated_at": self.updated_at.strftime("%d-%m-%Y %H:%M") if self.updated_at else "",
        }


class PendingOrderItem(Base):
    __tablename__ = "pending_order_items"
    __table_args__ = (
        db.Index("idx_pending_items_table", "pending_table_id"),
        db.Index("idx_pending_items_item", "item_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    pending_table_id = db.Column(String(20), ForeignKey("pending_orders.table_id"), nullable=False)
    item_id = db.Column(String(50), nullable=False)
    name = db.Column(String(200), nullable=False)
    price = db.Column(Float, nullable=False)
    qty = db.Column(Integer, nullable=False)
    item_total = db.Column(Float, nullable=False)

    pending = relationship("PendingOrder", back_populates="items")

    def to_dict(self):
        return {
            "id": self.item_id,
            "name": self.name,
            "price": self.price,
            "qty": self.qty,
            "item_total": round(self.item_total, 2),
        }


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        db.Index("idx_expenses_date", "date"),
        db.Index("idx_expenses_category", "category"),
    )

    id = db.Column(String(20), primary_key=True)
    date = db.Column(DateTime, nullable=False)
    category = db.Column(String(100), default="")
    description = db.Column(String(500), default="")
    amount = db.Column(Float, nullable=False)
    paid_by = db.Column(String(50), default="admin")

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.strftime("%d-%m-%Y %H:%M") if self.date else "",
            "category": self.category,
            "description": self.description,
            "amount": round(self.amount, 2),
            "paid_by": self.paid_by,
        }


class Staff(Base):
    __tablename__ = "staff"
    __table_args__ = (
        db.Index("idx_staff_role", "role"),
    )

    id = db.Column(String(20), primary_key=True)
    name = db.Column(String(100), nullable=False)
    role = db.Column(String(50), default="staff")
    salary = db.Column(Float, nullable=False)
    join_date = db.Column(String(20), default="")
    paid_months = db.Column(Text, default="[]")

    def to_dict(self):
        pm = _safe_json_list(self.paid_months, [])
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "salary": round(self.salary, 2),
            "join_date": self.join_date,
            "paid_months": pm,
        }


class SalaryPayment(Base):
    __tablename__ = "salary_payments"
    __table_args__ = (
        db.Index("idx_salary_month", "month"),
        db.Index("idx_salary_date", "date"),
    )

    id = db.Column(String(20), primary_key=True)
    date = db.Column(DateTime, nullable=False)
    month = db.Column(String(7), nullable=False)
    staff_ids = db.Column(Text, default="[]")
    amount = db.Column(Float, nullable=False)
    paid_by = db.Column(String(50), default="admin")
    payment_type = db.Column(String(20), default="full")
    notes = db.Column(Text, default="")
    status = db.Column(String(20), default="completed")

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.strftime("%d-%m-%Y %H:%M") if self.date else "",
            "month": self.month,
            "staff_ids": _safe_json_list(self.staff_ids, []),
            "amount": round(self.amount, 2),
            "paid_by": self.paid_by,
            "payment_type": (self.payment_type or "full"),
            "notes": self.notes or "",
            "status": (self.status or "completed"),
        }


class AdminCred(Base):
    __tablename__ = "admin_creds"
    __table_args__ = (
        db.Index("idx_admin_username", "username"),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(String(50), unique=True, nullable=False, default="admin")
    password_hash = db.Column(String(255), nullable=False)
    role = db.Column(String(50), default="admin")
    created_at = db.Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"username": self.username, "role": self.role, "created_at": self.created_at.strftime("%d-%m-%Y %H:%M")}


class Settings(Base):
    __tablename__ = "settings"

    key = db.Column(String(50), primary_key=True)
    value = db.Column(Text, default="")


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        db.Index("idx_inventory_category", "category"),
        db.Index("idx_inventory_qty", "quantity"),
    )

    id = db.Column(String(50), primary_key=True)
    name = db.Column(String(200), nullable=False)
    category = db.Column(String(100), default="")
    quantity = db.Column(Integer, default=0)
    unit = db.Column(String(20), default="pcs")
    reorder_level = db.Column(Integer, default=10)
    cost_per_unit = db.Column(Float, default=0.0)
    created_at = db.Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "quantity": self.quantity,
            "unit": self.unit,
            "reorder_level": self.reorder_level,
            "cost_per_unit": round(self.cost_per_unit, 2),
            "created_at": self.created_at.strftime("%d-%m-%Y %H:%M") if self.created_at else "",
            "is_low_stock": self.quantity <= self.reorder_level,
        }

    @staticmethod
    def low_stock_items():
        return db.session.execute(
            db.select(InventoryItem).where(InventoryItem.quantity <= InventoryItem.reorder_level)
            .order_by(InventoryItem.quantity.asc())
        ).scalars().all()

    @staticmethod
    def deduct_stock(item_id, qty, commit=True):
        """Deduct stock; if commit=False use flush for batch/transactional caller. Quantity never negative."""
        try:
            qty = int(qty)
        except (ValueError, TypeError):
            return False, "Invalid quantity"
        if qty <= 0:
            return False, "Quantity must be positive"
        try:
            item = db.session.execute(
                db.select(InventoryItem).where(InventoryItem.id == item_id)
            ).scalar_one_or_none()
            if not item:
                return False, f"Inventory item '{item_id}' not found"
            # Ensure quantity is not None and race-safe check
            cur_qty = item.quantity if item.quantity is not None else 0
            if cur_qty < qty:
                return False, f"Insufficient stock for '{item.name}': available {cur_qty}, requested {qty}"
            # Double-check after potential concurrent modification via refresh
            # SQLite no FOR UPDATE, so we clamp and verify never negative
            new_qty = cur_qty - qty
            if new_qty < 0:
                return False, f"Insufficient stock for '{item.name}': available {cur_qty}, requested {qty}"
            item.quantity = new_qty
            if commit:
                db.session.commit()
            else:
                db.session.flush()
            logger.info("Deducted %d units from '%s' (item_id=%s). Remaining: %d", qty, item.name, item_id, item.quantity)
            return True, None
        except Exception as exc:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.error("deduct_stock failed for %s: %s", item_id, exc)
            return False, str(exc)

    @staticmethod
    def add_stock(item_id, qty, commit=True):
        try:
            qty = int(qty)
        except (ValueError, TypeError):
            return False, "Invalid quantity"
        if qty < 0:
            return False, "Quantity cannot be negative"
        if qty == 0:
            return True, None
        try:
            item = db.session.execute(
                db.select(InventoryItem).where(InventoryItem.id == item_id)
            ).scalar_one_or_none()
            if not item:
                return False, f"Inventory item '{item_id}' not found"
            cur_qty = item.quantity if item.quantity is not None else 0
            item.quantity = cur_qty + qty
            if commit:
                db.session.commit()
            else:
                db.session.flush()
            logger.info("Added %d units to '%s' (item_id=%s). New total: %d", qty, item.name, item_id, item.quantity)
            return True, None
        except Exception as exc:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.error("add_stock failed for %s: %s", item_id, exc)
            return False, str(exc)


class KOT(Base):
    __tablename__ = "kitchen_order_tickets"
    __table_args__ = (
        db.Index("idx_kot_order", "order_id"),
        db.Index("idx_kot_table", "table"),
        db.Index("idx_kot_status", "status"),
        db.Index("idx_kot_created", "created_at"),
    )

    id = db.Column(String(20), primary_key=True)
    order_id = db.Column(String(20), nullable=False)
    table = db.Column(String(20), nullable=False)
    customer = db.Column(String(100), default="")
    status = db.Column(String(20), default="pending")
    created_at = db.Column(DateTime, default=datetime.utcnow)
    completed_at = db.Column(DateTime)

    items = relationship("KOTItem", back_populates="kot", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "table": self.table,
            "customer": self.customer,
            "status": self.status,
            "created_at": self.created_at.strftime("%d-%m-%Y %H:%M") if self.created_at else "",
            "completed_at": self.completed_at.strftime("%d-%m-%Y %H:%M") if self.completed_at else "",
            "items": [{"id": i.item_id, "name": i.name, "qty": i.qty, "category": i.category, "special_notes": i.special_notes or ""} for i in self.items],
        }


class KOTItem(Base):
    __tablename__ = "kot_items"
    __table_args__ = (
        db.Index("idx_kot_items_kot", "kot_id"),
        db.Index("idx_kot_items_item", "item_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    kot_id = db.Column(String(20), ForeignKey("kitchen_order_tickets.id"), nullable=False)
    item_id = db.Column(String(50), nullable=False)
    name = db.Column(String(200), nullable=False)
    qty = db.Column(Integer, nullable=False)
    category = db.Column(String(50), default="")
    special_notes = db.Column(String(500), default="")

    kot = relationship("KOT", back_populates="items")

    def to_dict(self):
        return {"id": self.item_id, "name": self.name, "qty": self.qty, "category": self.category, "special_notes": self.special_notes}


# ---------------------------------------------------------------------------
# Migrations & Seed Data
# ---------------------------------------------------------------------------

def init_db(app):
    """Create all tables and run migrations."""
    DATA_DIR.mkdir(exist_ok=True)
    BACKUPS_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    db.init_app(app)
    with app.app_context():
        try:
            db.create_all()
            _migrate_schema_missing_columns()
            migrate_admin_credentials()
            seed_menu_if_empty()
            seed_tables_if_empty()
            seed_settings_if_empty()
            migrate_pending_orders()
            seed_inventory_if_empty()
        except Exception as exc:
            logger.error("Database initialization failed: %s", exc)
            raise


def _migrate_schema_missing_columns():
    """Add any missing columns to existing tables (SQLite ALTER TABLE). Idempotent & transaction-safe per table."""
    from sqlalchemy import text
    # table -> {column: sql_type_definition}
    table_column_defs = {
        "categories": {
            "icon": "VARCHAR(20) DEFAULT ''",
        },
        "menu_items": {
            "available": "BOOLEAN DEFAULT 1",
            "icon": "VARCHAR(20) DEFAULT ''",
        },
        "inventory_items": {
            "category": "VARCHAR(100) DEFAULT ''",
            "quantity": "INTEGER DEFAULT 0",
            "unit": "VARCHAR(20) DEFAULT 'pcs'",
            "reorder_level": "INTEGER DEFAULT 10",
            "cost_per_unit": "FLOAT DEFAULT 0.0",
            "created_at": "DATETIME",
        },
        "kitchen_order_tickets": {
            "order_id": "VARCHAR(20)",
            "table": "VARCHAR(20)",
            "customer": "VARCHAR(100) DEFAULT ''",
            "status": "VARCHAR(20) DEFAULT 'pending'",
            "created_at": "DATETIME",
            "completed_at": "DATETIME",
        },
        "kot_items": {
            "kot_id": "VARCHAR(20)",
            "item_id": "VARCHAR(50)",
            "name": "VARCHAR(200)",
            "qty": "INTEGER",
            "category": "VARCHAR(50) DEFAULT ''",
            "special_notes": "VARCHAR(500) DEFAULT ''",
        },
        "staff": {
            "paid_months": "TEXT DEFAULT '[]'",
        },
        "salary_payments": {
            "payment_type": "VARCHAR(20) DEFAULT 'full'",
            "notes": "TEXT DEFAULT ''",
            "status": "VARCHAR(20) DEFAULT 'completed'",
            "paid_by": "VARCHAR(50) DEFAULT 'admin'",
        },
        "admin_creds": {
            "role": "VARCHAR(50) DEFAULT 'admin'",
            "created_at": "DATETIME",
        },
        "orders": {
            "table": "VARCHAR(20) DEFAULT ''",
            "customer": "VARCHAR(100) DEFAULT ''",
            "payment_mode": "VARCHAR(20) DEFAULT 'cash'",
            "subtotal": "FLOAT DEFAULT 0.0",
            "discount": "FLOAT DEFAULT 0.0",
            "gst": "FLOAT DEFAULT 0.0",
            "total": "FLOAT DEFAULT 0.0",
        },
        "order_items": {
            "item_total": "FLOAT DEFAULT 0.0",
        },
        "tables": {
            "name": "VARCHAR(100) DEFAULT ''",
            "status": "VARCHAR(20) DEFAULT 'available'",
            "capacity": "INTEGER DEFAULT 4",
            "zone": "VARCHAR(50) DEFAULT 'indoor'",
            "updated_at": "DATETIME",
        },
        "pending_orders": {
            "customer": "VARCHAR(100) DEFAULT ''",
            "subtotal": "FLOAT DEFAULT 0.0",
            "gst": "FLOAT DEFAULT 0.0",
            "total": "FLOAT DEFAULT 0.0",
            "updated_at": "DATETIME",
        },
        "expenses": {
            "category": "VARCHAR(100) DEFAULT ''",
            "description": "VARCHAR(500) DEFAULT ''",
            "paid_by": "VARCHAR(50) DEFAULT 'admin'",
        },
    }
    try:
        inspector = inspect(db.engine)
        for table, col_defs in table_column_defs.items():
            try:
                if not inspector.has_table(table):
                    continue
                cols_exist = [c["name"] for c in inspector.get_columns(table)]
                for col, definition in col_defs.items():
                    if col not in cols_exist:
                        try:
                            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
                            db.session.commit()
                            logger.info("Added missing column '%s' to table '%s' (%s)", col, table, definition)
                        except Exception as col_exc:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                            if "duplicate" in str(col_exc).lower() or "already exists" in str(col_exc).lower():
                                logger.info("Column '%s' already exists in '%s' (race)", col, table)
                            else:
                                logger.warning("Failed to add column '%s' to '%s': %s", col, table, col_exc)
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Schema migration for %s skipped: %s", table, e)
    except Exception as exc:
        logger.warning("Database inspection skipped: %s", exc)

    # Fix legacy data: staff.paid_months empty string -> '[]'
    try:
        from sqlalchemy import text as _text
        # Update staff rows where paid_months is '' or NULL to '[]'
        db.session.execute(_text("UPDATE staff SET paid_months='[]' WHERE paid_months='' OR paid_months IS NULL"))
        db.session.commit()
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.warning("Fixing staff.paid_months defaults failed: %s", e)

    # Ensure indexes exist (idempotent)
    _ensure_indexes()


def _ensure_indexes():
    """Create indexes if missing for fast bill_id/table_id lookups. Idempotent & transaction-safe."""
    from sqlalchemy import text
    indexes = [
        ("idx_orders_table", "orders", "table"),
        ("idx_orders_date", "orders", "date"),
        ("idx_orders_customer", "orders", "customer"),
        ("idx_order_items_bill", "order_items", "order_bill_id"),
        ("idx_order_items_item", "order_items", "item_id"),
        ("idx_menu_items_category", "menu_items", "category_id"),
        ("idx_menu_items_available", "menu_items", "available"),
        ("idx_tables_status", "tables", "status"),
        ("idx_pending_items_table", "pending_order_items", "pending_table_id"),
        ("idx_pending_items_item", "pending_order_items", "item_id"),
        ("idx_kot_order", "kitchen_order_tickets", "order_id"),
        ("idx_kot_table", "kitchen_order_tickets", "table"),
        ("idx_kot_status", "kitchen_order_tickets", "status"),
        ("idx_kot_created", "kitchen_order_tickets", "created_at"),
        ("idx_kot_items_kot", "kot_items", "kot_id"),
        ("idx_kot_items_item", "kot_items", "item_id"),
        ("idx_inventory_category", "inventory_items", "category"),
        ("idx_inventory_qty", "inventory_items", "quantity"),
        ("idx_expenses_date", "expenses", "date"),
        ("idx_salary_month", "salary_payments", "month"),
        ("idx_salary_date", "salary_payments", "date"),
        ("idx_admin_username", "admin_creds", "username"),
        ("idx_staff_role", "staff", "role"),
    ]
    for idx_name, table, col in indexes:
        try:
            # CREATE INDEX IF NOT EXISTS is idempotent in SQLite
            # need to quote table/col that may be keyword like "table"
            col_escaped = f'"{col}"' if col in ("table", "key", "order") else col
            db.session.execute(text(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({col_escaped})'))
            db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("Index creation %s on %s(%s) failed: %s", idx_name, table, col, e)


def migrate_admin_credentials():
    """Hash plain-text password in admin_creds table. Idempotent & transaction-safe."""
    try:
        try:
            existing = db.session.execute(
                db.select(AdminCred).where(AdminCred.username == "admin")
            ).scalar_one_or_none()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            existing = None

        if not existing:
            creds_file = DATA_DIR / "admin" / "credentials.json"
            if creds_file.exists():
                try:
                    data = json.loads(creds_file.read_text(encoding="utf-8"))
                    password = data.get("pass", "admin123")
                    # also handle user vs username key
                    if not password and data.get("password"):
                        password = data.get("password")
                except Exception:
                    password = "admin123"
            else:
                password = "admin123"
            try:
                hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                admin = AdminCred(username="admin", password_hash=hashed, role="admin")
                db.session.add(admin)
                db.session.commit()
                logger.info("Admin credentials seeded for 'admin'")
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.error("Failed to seed admin credentials: %s", e)
        else:
            if not getattr(existing, "role", None):
                try:
                    existing.role = "admin"
                    db.session.commit()
                    logger.info("Patched admin role to 'admin'")
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    logger.warning("Failed to patch admin role: %s", e)
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("migrate_admin_credentials failed: %s", e)


def migrate_pending_orders():
    """Move pending JSON files into the pending_orders table. Idempotent & transaction-safe per file."""
    pending_dir = DATA_DIR / "pending"
    if not pending_dir.exists():
        return
    for f in pending_dir.glob("*.json"):
        table_id = f.stem
        try:
            existing = db.session.execute(
                db.select(PendingOrder).where(PendingOrder.table_id == table_id)
            ).scalar_one_or_none()
            if existing:
                continue
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("Pending check failed for %s: %s", table_id, e)
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # flexible date parsing
            updated = None
            if data.get("updated_at"):
                updated = _parse_date_flexible(str(data.get("updated_at")))
                # if original value is falsy, keep None
                if isinstance(data.get("updated_at"), str) and not data.get("updated_at").strip():
                    updated = None
            po = PendingOrder(
                table_id=table_id,
                customer=data.get("customer", ""),
                subtotal=float(data.get("subtotal", 0) or 0),
                gst=float(data.get("gst", 0) or 0),
                total=float(data.get("total", 0) or 0),
                updated_at=updated,
            )
            db.session.add(po)
            for item in data.get("items", []):
                try:
                    # handle naming mismatch item_total vs itemTotal vs total
                    _it = item.get("item_total", item.get("itemTotal", item.get("total", item.get("item_total", 0))))
                    poi = PendingOrderItem(
                        pending_table_id=table_id,
                        item_id=item["id"],
                        name=item["name"],
                        price=float(item.get("price", 0)),
                        qty=int(item.get("qty", 1)),
                        item_total=float(_it or 0),
                    )
                    db.session.add(poi)
                except Exception as ie:
                    logger.warning("Skipping corrupt pending item in %s: %s", f.name, ie)
                    continue
            db.session.commit()
            logger.info("Migrated pending order for table %s", table_id)
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("Skipping corrupt pending file %s: %s", f.name, e)


def seed_menu_if_empty():
    """Seed default menu if empty. Handles missing categories gracefully and avoids duplicates on partial data."""
    DEFAULT_CATEGORIES = [
        ("biryani", "Biryani", ""),
        ("curry", "Curry", ""),
        ("roti", "Roti", ""),
        ("drinks", "Drinks", ""),
        ("dessert", "Dessert", ""),
        ("starter", "Starter", ""),
    ]
    DEFAULT_ITEMS = [
        ("chicken_biryani", "Chicken Biryani", 180, "biryani"),
        ("mutton_biryani", "Mutton Biryani", 220, "biryani"),
        ("veg_biryani", "Veg Biryani", 120, "biryani"),
        ("butter_chicken", "Butter Chicken", 200, "curry"),
        ("paneer_curry", "Paneer Curry", 150, "curry"),
        ("dal_curry", "Dal Curry", 80, "curry"),
        ("tandoori_roti", "Tandoori Roti", 20, "roti"),
        ("butter_naan", "Butter Naan", 35, "roti"),
        ("garlic_naan", "Garlic Naan", 40, "roti"),
        ("lassi", "Sweet Lassi", 60, "drinks"),
        ("masala_chai", "Masala Chai", 30, "drinks"),
        ("cold_coffee", "Cold Coffee", 80, "drinks"),
        ("gulab_jamun", "Gulab Jamun", 50, "dessert"),
        ("ice_cream", "Ice Cream", 60, "dessert"),
        ("chicken_tikka", "Chicken Tikka", 160, "starter"),
        ("paneer_tikka", "Paneer Tikka", 140, "starter"),
    ]
    try:
        # Seed categories idempotently
        for cat_id, cat_name, icon in DEFAULT_CATEGORIES:
            try:
                exists = db.session.execute(db.select(Category).where(Category.id == cat_id)).scalar_one_or_none()
                if not exists:
                    db.session.add(Category(id=cat_id, name=cat_name, icon=icon))
                    logger.info("Seeded category %s", cat_id)
            except Exception as ce:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Category seed %s failed: %s", cat_id, ce)
                continue
        try:
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

        # Seed items idempotently, ensure category exists
        for item_id, name, price, cat_id in DEFAULT_ITEMS:
            try:
                exists = db.session.execute(db.select(MenuItem).where(MenuItem.id == item_id)).scalar_one_or_none()
                if exists:
                    continue
                # Ensure category exists; if missing, create stub gracefully
                cat_exists = db.session.execute(db.select(Category).where(Category.id == cat_id)).scalar_one_or_none()
                if not cat_exists:
                    try:
                        db.session.add(Category(id=cat_id, name=cat_id.capitalize(), icon=""))
                        db.session.flush()
                        logger.info("Auto-created missing category '%s' for item %s", cat_id, item_id)
                    except Exception as ce2:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        logger.warning("Failed to auto-create category %s: %s", cat_id, ce2)
                        continue
                db.session.add(MenuItem(id=item_id, name=name, price=float(price), category_id=cat_id, available=True))
            except Exception as ie:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Item seed %s failed: %s", item_id, ie)
                continue
        try:
            db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("Menu seed commit failed: %s", e)
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("seed_menu_if_empty failed: %s", e)


def seed_tables_if_empty():
    """Seed 10 tables T1-T10. Idempotent. Removes legacy extra tables to match required 10."""
    try:
        defaults = [("T1","Table 1","indoor",4),("T2","Table 2","indoor",4),("T3","Table 3","indoor",4),("T4","Table 4","indoor",4),("T5","Table 5","indoor",6),("T6","Table 6","indoor",6),("T7","Table 7","indoor",4),("T8","Table 8","indoor",4),("T9","Table 9","outdoor",6),("T10","Table 10","outdoor",8)]
        for tid, nm, zn, cap in defaults:
            try:
                exists = db.session.execute(db.select(Table).where(Table.table_id == tid)).scalar_one_or_none()
                if not exists:
                    db.session.add(Table(table_id=tid, name=nm, status="available", zone=zn, capacity=cap))
                else:
                    # backfill missing name/zone/capacity
                    changed=False
                    if not getattr(exists,"name",None): exists.name=nm; changed=True
                    if not getattr(exists,"zone",None): exists.zone=zn; changed=True
                    if not getattr(exists,"capacity",None): exists.capacity=cap; changed=True
                    if changed: db.session.flush()
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Seed table %s failed: %s", tid, e)
        # Normalize to exactly 10 tables: remove legacy P1-P3, T11-T20 if no pending order
        try:
            all_t = db.session.execute(db.select(Table)).scalars().all()
            keep = {d[0] for d in defaults}
            for t in all_t:
                if t.table_id not in keep:
                    # only delete if no pending order
                    has_pending = db.session.execute(db.select(PendingOrder).where(PendingOrder.table_id==t.table_id)).scalar_one_or_none()
                    if not has_pending:
                        db.session.delete(t)
                        logger.info("Pruned extra table %s to normalize to T1-T10", t.table_id)
                    else:
                        logger.warning("Keeping extra table %s - has pending order", t.table_id)
            db.session.flush()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("Prune extra tables failed: %s", e)
        try:
            db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("seed_tables commit failed: %s", e)
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("seed_tables_if_empty failed: %s", e)


def seed_settings_if_empty():
    """Seed default restaurant settings if empty. Idempotent per key."""
    defaults = {
        "restaurant_name": "My Restaurant",
        "gst_rate": "5",
        "footer_text": "",
    }
    try:
        for key, value in defaults.items():
            try:
                exists = db.session.execute(db.select(Settings).where(Settings.key == key)).scalar_one_or_none()
                if not exists:
                    db.session.add(Settings(key=key, value=value))
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Seed setting %s failed: %s", key, e)
        try:
            db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("seed_settings commit failed: %s", e)
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("seed_settings_if_empty failed: %s", e)


def seed_inventory_if_empty():
    """Seed default inventory items if empty. Idempotent per item."""
    DEFAULT_INVENTORY = [
        ("rice", "Rice", "groceries", 50, "kg", 20, 25.0),
        ("chicken", "Chicken", "groceries", 30, "kg", 10, 180.0),
        ("mutton", "Mutton", "groceries", 15, "kg", 5, 450.0),
        ("paneer", "Paneer", "groceries", 20, "kg", 5, 280.0),
        ("butter", "Butter", "groceries", 10, "kg", 3, 400.0),
        ("flour", "Atta/Flour", "groceries", 40, "kg", 15, 35.0),
        ("oil", "Cooking Oil", "groceries", 20, "litre", 5, 160.0),
        ("spices", "Spices Mix", "groceries", 15, "kg", 3, 200.0),
        ("yogurt", "Yogurt/Curd", "groceries", 12, "kg", 4, 80.0),
        ("milk", "Milk", "groceries", 25, "litre", 8, 60.0),
        ("chaipatti", "Tea Leaves", "groceries", 8, "kg", 2, 300.0),
        ("sugar", "Sugar", "groceries", 20, "kg", 5, 40.0),
        ("icecream_base", "Ice Cream Base", "dessert", 10, "litre", 3, 350.0),
        ("lemon", "Lemon", "groceries", 15, "pcs", 5, 20.0),
        ("gulab_jamun_mix", "Gulab Jamun Mix", "dessert", 12, "kg", 3, 180.0),
    ]
    try:
        for item_id, name, category, qty, unit, reorder, cost in DEFAULT_INVENTORY:
            try:
                exists = db.session.execute(db.select(InventoryItem).where(InventoryItem.id == item_id)).scalar_one_or_none()
                if not exists:
                    db.session.add(InventoryItem(
                        id=item_id,
                        name=name,
                        category=category,
                        quantity=qty,
                        unit=unit,
                        reorder_level=reorder,
                        cost_per_unit=cost,
                    ))
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Seed inventory %s failed: %s", item_id, e)
        try:
            db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning("seed_inventory commit failed: %s", e)
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error("seed_inventory_if_empty failed: %s", e)


# ---------------------------------------------------------------------------
# Admin auth helper
# ---------------------------------------------------------------------------

def verify_admin_password(username, password):
    """Verify a plain-text password against stored bcrypt hash. Returns (username, role) or (None, None). Handles corrupted hash."""
    try:
        admin = db.session.execute(
            db.select(AdminCred).where(AdminCred.username == username)
        ).scalar_one_or_none()
        if not admin:
            return None, None
        # Use robust helper that handles corrupted hash
        if not verify_password(password, admin.password_hash):
            return None, None
        return admin.username, admin.role
    except Exception as exc:
        logger.warning("verify_admin_password failed for '%s': %s", username, exc)
        return None, None


def get_admin_role(username):
    """Return the role for a given username. Robust to DB errors."""
    try:
        admin = db.session.execute(
            db.select(AdminCred).where(AdminCred.username == username)
        ).scalar_one_or_none()
        return admin.role if admin else None
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.warning("get_admin_role failed for '%s': %s", username, exc)
        return None


def migrate_json_data(app):
    """Migrate orders, expenses, staff from JSON to SQLite. Idempotent & transaction-safe per record."""
    import csv
    from io import StringIO
    with app.app_context():
        # Orders
        orders_dir = DATA_DIR / "orders"
        if orders_dir.exists():
            for f in orders_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    bill_id = data.get("bill_id")
                    if not bill_id:
                        continue
                    try:
                        existing = db.session.execute(
                            db.select(Order).where(Order.bill_id == bill_id)
                        ).scalar_one_or_none()
                        if existing:
                            continue
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        continue
                    # Flexible date parsing
                    date_val = _parse_date_flexible(str(data.get("date"))) if data.get("date") else datetime.utcnow()
                    try:
                        order = Order(
                            bill_id=bill_id,
                            date=date_val,
                            table=data.get("table", ""),
                            customer=data.get("customer", ""),
                            payment_mode=data.get("paymentMode", data.get("payment_mode", "cash")),
                            subtotal=float(data.get("subtotal", 0) or 0),
                            discount=float(data.get("discount", 0) or 0),
                            gst=float(data.get("gst", 0) or 0),
                            total=float(data.get("total", 0) or 0),
                        )
                        db.session.add(order)
                        db.session.flush()
                        for item in data.get("items", []):
                            try:
                                # handle item_total vs itemTotal vs total mismatch
                                _it = item.get("item_total", item.get("itemTotal", item.get("total", item.get("item_total", 0))))
                                # also handle qty as string
                                oi = OrderItem(
                                    order_bill_id=bill_id,
                                    item_id=item["id"],
                                    name=item.get("name", item["id"]),
                                    price=float(item.get("price", 0)),
                                    qty=int(item.get("qty", 1)),
                                    item_total=float(_it or 0),
                                )
                                db.session.add(oi)
                            except Exception as ie:
                                logger.warning("Skipping corrupt order item in %s: %s", f.name, ie)
                                continue
                        db.session.commit()
                        logger.info("Migrated order %s", bill_id)
                    except Exception as e:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        logger.warning("Skipping corrupt order file %s: %s", f.name, e)
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    logger.warning("Skipping corrupt order file %s: %s", f.name, e)

        # Expenses
        exp_file = DATA_DIR / "admin" / "expenses.json"
        if exp_file.exists():
            try:
                data = json.loads(exp_file.read_text(encoding="utf-8"))
                # handle if file contains dict or list
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    try:
                        eid = item.get("id")
                        if not eid:
                            continue
                        try:
                            existing = db.session.execute(
                                db.select(Expense).where(Expense.id == eid)
                            ).scalar_one_or_none()
                            if existing:
                                continue
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                            continue
                        date_val = _parse_date_flexible(str(item.get("date"))) if item.get("date") else datetime.utcnow()
                        expense = Expense(
                            id=eid,
                            date=date_val,
                            category=item.get("category", ""),
                            description=item.get("description", ""),
                            amount=float(item.get("amount", 0) or 0),
                            paid_by=item.get("paid_by", "admin"),
                        )
                        db.session.add(expense)
                        try:
                            db.session.commit()
                        except Exception as ce:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                            logger.warning("Expense %s commit failed: %s", eid, ce)
                    except Exception as ie:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        logger.warning("Skipping corrupt expense %s: %s", item, ie)
                logger.info("Migrated expenses")
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Skipping expenses migration: %s", e)

        # Staff
        staff_file = DATA_DIR / "admin" / "staff.json"
        if staff_file.exists():
            try:
                data = json.loads(staff_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    try:
                        sid = item.get("id")
                        if not sid:
                            continue
                        try:
                            existing = db.session.execute(
                                db.select(Staff).where(Staff.id == sid)
                            ).scalar_one_or_none()
                            if existing:
                                continue
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                            continue
                        # Handle paid_months if present in JSON
                        pm_val = item.get("paid_months", "[]")
                        if isinstance(pm_val, list):
                            pm_str = json.dumps(pm_val)
                        elif isinstance(pm_val, str):
                            # validate json
                            try:
                                json.loads(pm_val)
                                pm_str = pm_val
                            except Exception:
                                pm_str = "[]"
                        else:
                            pm_str = "[]"
                        staff = Staff(
                            id=sid,
                            name=item.get("name", "Unknown"),
                            role=item.get("role", "staff"),
                            salary=float(item.get("salary", 0) or 0),
                            join_date=item.get("join_date", ""),
                            paid_months=pm_str,
                        )
                        db.session.add(staff)
                        try:
                            db.session.commit()
                        except Exception as ce:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                            logger.warning("Staff %s commit failed: %s", sid, ce)
                    except Exception as ie:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        logger.warning("Skipping corrupt staff %s: %s", item, ie)
                logger.info("Migrated staff")
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Skipping staff migration: %s", e)

        # Salary payments
        salary_file = DATA_DIR / "admin" / "salary_payments.json"
        if salary_file.exists():
            try:
                data = json.loads(salary_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    try:
                        pid = item.get("id")
                        if not pid:
                            continue
                        try:
                            existing = db.session.execute(
                                db.select(SalaryPayment).where(SalaryPayment.id == pid)
                            ).scalar_one_or_none()
                            if existing:
                                continue
                        except Exception:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                            continue
                        date_val = _parse_date_flexible(str(item.get("date"))) if item.get("date") else datetime.utcnow()
                        sp = SalaryPayment(
                            id=pid,
                            date=date_val,
                            month=item.get("month", ""),
                            staff_ids=json.dumps(item.get("staff_ids", [])),
                            amount=float(item.get("amount", 0) or 0),
                            paid_by=item.get("paid_by", "admin"),
                        )
                        db.session.add(sp)
                        try:
                            db.session.commit()
                        except Exception as ce:
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                            logger.warning("SalaryPayment %s commit failed: %s", pid, ce)
                    except Exception as ie:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        logger.warning("Skipping corrupt salary payment %s: %s", item, ie)
                logger.info("Migrated salary payments")
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning("Skipping salary payments migration: %s", e)
