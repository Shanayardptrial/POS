# Restaurant POS - Bug Fix Report & Status

![Fixed](https://img.shields.io/badge/bugs-fixed-success?style=for-the-badge)
![Port](https://img.shields.io/badge/port-5500-orange?style=flat-square)
![Security](https://img.shields.io/badge/security-hardened-blue?style=flat-square)

> **Port consistency:** All docs, code, and launchers now use **`5500`** via `config.py` + `.env` `PORT` (no hard-coded drift).

## Fixed Bugs ✅

### 1. Missing `loadCharts()` Function
**Issue:** Charts tab button called `loadCharts()` but function didn't exist
**Fix:** Added complete `loadCharts()` function with all 4 charts (Daily, Categories, Top Items, Income/Expense)
**Location:** `templates/admin.html` line ~587

### 2. Duplicate ID Conflict
**Issue:** `staff-salary` used for both stat card and input field
**Fix:** Changed stat card ID to `stat-total-salary`
**Location:** `templates/admin.html` line 371, 598

### 3. Missing menu.json File
**Issue:** Menu was hardcoded but no JSON file existed
**Fix:** Created `data/menu.json` with all 16 menu items
**Location:** `data/menu.json`

### 4. Config Duplication & Drift (NEW)
**Issue:** `config.py` was legacy/unused; `database.py` and `pos_app.py` both defined `BASE_DIR`/`DATA_DIR`/`BACKUPS_DIR` independently → risk of path drift
**Fix:** Made `config.py` canonical: now defines `BASE_DIR`, `DATA_DIR`, `LOGS`/`LOG_DIR`/`LOGS_DIR`, `BACKUPS`/`BACKUPS_DIR`, `DATABASE_URL`, env defaults (`HOST`, `PORT`, `SECRET_KEY`, `GST_RATE`, `DEBUG`). Both `database.py` and `pos_app.py` import from `config.py`; `database.py` re-exports for backwards-compat
**Location:** `config.py:1`, `database.py:14`, `pos_app.py:15`

### 5. Missing Production Deps (NEW)
**Issue:** `requirements.txt` only had 3 deps, missing `waitress`/`gunicorn`, `python-dotenv`, `Flask-Cors`, and pins
**Fix:** Pinned all deps (`Flask 3.1`, `SQLAlchemy 2.0.36`, etc.), added `waitress`, `gunicorn`, `python-dotenv`, `Flask-Cors`, `Werkzeug/Jinja2/itsdangerous`
**Location:** `requirements.txt`

### 6. Fragile Launchers (NEW)
**Issue:** `start.bat` / `run_server.bat` didn't handle `.conda` env, missing error handling, no auto-open browser, no logs display
**Fix:** Both BATs now: detect `.conda` → `.conda\Scripts\activate` → `venv` → fallback; load `.env` `PORT`/`HOST`; auto-open browser after 2-3s; check `flask` import & `pip install`; ensure `data/`/`logs/` exist; show `logs/pos.log` tail on crash
**Location:** `start.bat`, `run_server.bat`

### 7. Missing `.env.example` (NEW)
**Issue:** No env template for `SECRET_KEY`/`PORT`/`HOST`/`GST_RATE`
**Fix:** Created `.env.example` with defaults, comments, and `USE_WAITRESS` toggle
**Location:** `.env.example`

### 8. Weak Restore Endpoint (NEW)
**Issue:** `POST /api/admin/restore` did no ZIP validation, no safety backup, vulnerable to ZipSlip
**Fix:** Hardened restore: validates ZIP header & `is_zipfile`, size limit, `testzip()`, rejects absolute/`..` paths, allows only `data/` prefixes, requires `pos.db`, creates `pre_restore_backup_*.zip` before overwrite, closes DB engine, handles both `pos.db` and `data/pos.db` layouts, safe extraction, temp file cleanup
**Location:** `pos_app.py:1768`

### 9. Hard-coded Host/Port/Debug (NEW)
**Issue:** `pos_app.py:__main__` hard-coded `host="127.0.0.1" port=5500 debug=False`, no env override, no `0.0.0.0` LAN support
**Fix:** `__main__` now reads `HOST`/`PORT`/`DEBUG` from `config.py`/env, allows `0.0.0.0` vs `127.0.0.1`, validates host, respects `FLASK_ENV`, auto-migrates, optionally serves via `waitress` when `USE_WAITRESS=1`
**Location:** `pos_app.py:1805`

### 10. `.gitignore` Gaps (NEW)
**Issue:** `data/*.db` pattern missing, `logs` not fully ignored, `.conda` not ignored, `.gitkeep` edge cases
**Fix:** Added `data/*.db`, `data/*.sqlite*`, `.conda/`, `!logs/.gitkeep`, `!data/.gitkeep` etc., `!.env.example`, removed bat ignores, ensured `data/admin/secret.key` ignored
**Location:** `.gitignore`

### 11. API Docs Drift (NEW)
**Issue:** `README.md` / `BUGFIX_REPORT.md` API tables could drift from code; port inconsistency risk
**Fix:** Verified all 52 routes via `Select-String @app.route` and synced `README.md` + `API_REFERENCE.md` tables, added `Auth` column, consistent `5500` references, added badges & GIF placeholder, added Security Notes
**Location:** `README.md:108`, `API_REFERENCE.md:1`

---

## Current System Status ✅

| Component | Status | Details |
|-----------|--------|---------|
| **Menu API** | ✅ Working | 16 items, 6 categories |
| **Orders** | ✅ Working | 10 orders stored |
| **Pending Orders** | ✅ Working | 2 tables pending |
| **Admin Login** | ✅ Working | admin/admin123 (bcrypt) |
| **Staff Management** | ✅ Working | 3 staff members |
| **Salary Payments** | ✅ Working | 3 payment records |
| **Charts** | ✅ Working | 4 chart types |
| **CSV Export** | ✅ Working | Orders, Expenses, Staff, Inventory |
| **Discount System** | ✅ Working | % or fixed amount |
| **Backup** | ✅ Working | ZIP with DB + menu.json |
| **Restore** | ✅ Hardened | Validates ZIP, safety backup, ZipSlip-safe |
| **Config** | ✅ Canonical | `config.py` single source |
| **Launchers** | ✅ Robust | `.conda` + venv + fallback |
| **Port** | ✅ Consistent | `5500` everywhere, env-overridable |

---

## URLs (port 5500 consistent)

- **POS Interface:** http://127.0.0.1:5500
- **Admin Dashboard:** http://127.0.0.1:5500/admin
- **Login:** admin / admin123
- **Health:** `GET http://127.0.0.1:5500/api/menu` → 200

---

## Security Notes

- Change default `admin/admin123` on first login; set strong `SECRET_KEY` in `.env` (auto-generated to `data/admin/secret.key` chmod 600 if missing)
- `SESSION_COOKIE_SECURE=true` when serving over HTTPS; `HOST=0.0.0.0` exposes to LAN — firewall accordingly
- `POST /api/admin/restore` now validates ZIPs and creates `pre_restore_backup_*.zip` automatically
- All responses include hardened headers: `X-Content-Type-Options`, `X-Frame-Options`, `CSP`, `Referrer-Policy`
- Logs at `logs/pos.log` (ignored by git, kept via `logs/.gitkeep`)

---

## Quick-Start GIF Placeholder

![Quick Start Demo](docs/demo.gif)
*Replace `docs/demo.gif` with a 10-15s recording: double-click `start.bat` → browser opens → place order → pay → admin charts.*

---

## Features Working
1. ✅ Menu display with category tabs
2. ✅ Cart system with item selection
3. ✅ Table/Pending order management
4. ✅ Bill calculation with GST
5. ✅ Discount system (% or ₹)
6. ✅ Print bill (new window)
7. ✅ Payment mode selection (Cash/UPI/Card)
8. ✅ Order history search
9. ✅ Admin dashboard with login
10. ✅ Sales charts (4 types)
11. ✅ Expense tracking
12. ✅ Staff management
13. ✅ Salary payment tracking
14. ✅ CSV export for all data
15. ✅ Keyboard shortcuts (1-6, Enter, Esc)
16. ✅ Backup & Restore (hardened)
17. ✅ Inventory auto-deduction + low-stock alerts
18. ✅ KOT generation & completion
19. ✅ Bill splitting (equal/fixed)
