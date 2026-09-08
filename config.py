"""
Canonical configuration for Restaurant POS.

This module is the single source of truth for filesystem paths,
environment defaults, and app settings. Both `database.py` and
`pos_app.py` should import path constants from here to avoid
duplication and drift.

Backwards-compat: legacy names (MENU_FILE, ORDERS_DIR, etc.) are
kept so any existing import `from config import X` keeps working.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Core paths — canonical definitions
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

LOGS_DIR: Path = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
# Alias kept for backwards-compat (database.py historically used LOG_DIR)
LOG_DIR: Path = LOGS_DIR
LOGS: Path = LOGS_DIR  # requested name

BACKUPS_DIR: Path = DATA_DIR / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)
BACKUPS: Path = BACKUPS_DIR  # requested alias

# ---------------------------------------------------------------------------
# Legacy / feature sub-paths
# ---------------------------------------------------------------------------
MENU_FILE: Path = DATA_DIR / "menu.json"

ORDERS_DIR: Path = DATA_DIR / "orders"
ORDERS_DIR.mkdir(exist_ok=True)

PENDING_DIR: Path = DATA_DIR / "pending"
PENDING_DIR.mkdir(exist_ok=True)

ADMIN_DIR: Path = DATA_DIR / "admin"
ADMIN_DIR.mkdir(exist_ok=True)

ADMIN_CREDENTIALS: Path = ADMIN_DIR / "credentials.json"
EXPENSES_FILE: Path = ADMIN_DIR / "expenses.json"
STAFF_FILE: Path = ADMIN_DIR / "staff.json"
SALARY_PAYMENTS_FILE: Path = ADMIN_DIR / "salary_payments.json"

DB_FILE: Path = DATA_DIR / "pos.db"
DATABASE_URL: str = f"sqlite:///{DB_FILE.resolve()}"

# ---------------------------------------------------------------------------
# Environment-driven settings (with sane defaults)
# ---------------------------------------------------------------------------
# Prefer python-dotenv if installed; silently ignore if not.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

SECRET_KEY: str = os.environ.get("SECRET_KEY", "")
HOST: str = os.environ.get("HOST", "127.0.0.1")
PORT: int = int(os.environ.get("PORT", "5500"))
try:
    GST_RATE: float = float(os.environ.get("GST_RATE", "5.0"))
except ValueError:
    GST_RATE = 5.0

DEBUG: bool = os.environ.get("FLASK_DEBUG", os.environ.get("DEBUG", "0")).lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Flask env helper — when FLASK_ENV=production force debug off
if os.environ.get("FLASK_ENV", "").lower() == "production":
    DEBUG = False
