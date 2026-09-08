# Restaurant POS System

![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python)
![Flask](https://img.shields.io/badge/Flask-3.1-black?style=for-the-badge&logo=flask)
![License](https://img.shields.io/badge/license-Private-red?style=for-the-badge)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=for-the-badge)
![Status](https://img.shields.io/badge/status-Stable-success?style=for-the-badge)
![Port](https://img.shields.io/badge/port-5500-orange?style=for-the-badge)

A professional Point of Sale (POS) system for restaurants, built with Flask. Designed for Indian restaurants with GST support, table management, kitchen order tickets, inventory tracking, expense management, staff payroll, and sales analytics.

> **Default port: `5500`** — all URLs below use `http://127.0.0.1:5500` consistently. Override via `PORT` env var or `.env` (see Configuration).

![Quick Start Demo](docs/demo.gif)
*Quick-start GIF placeholder — replace `docs/demo.gif` with a screen recording of: double-click `start.bat` → POS floor plan → place order → pay → admin dashboard.*

---

## ⚡ Quick Start

```bat
# Windows — double-click:
start.bat          # auto-detects .conda/venv, installs deps, opens http://127.0.0.1:5500

# Or manually:
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # optional — customize SECRET_KEY/PORT/HOST/GST_RATE
python pos_app.py        # → http://127.0.0.1:5500  (admin: admin/admin123)
```

```bash
# Linux / macOS
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python pos_app.py
# production: USE_WAITRESS=1 python pos_app.py  or  gunicorn -w 4 -b 0.0.0.0:5500 pos_app:app
```

---

## Features

### POS Interface
- **Floor Plan View** — Visual table grid with real-time status indicators (Available / Pending / Busy)
- **Menu Grid View** — Category-filtered item grid with search and keyboard shortcuts (1–9)
- **Cart System** — Add/remove items, quantity control, real-time price calculation
- **Table & Pending Orders** — Save orders to tables before payment; auto-restore on revisit
- **Bill Generation** — Automatic GST calculation (configurable rate), discount support (percentage or fixed amount)
- **Payment Modes** — Cash, UPI, Card
- **Bill Printing** — Print-ready thermal-receipt format with restaurant branding
- **Order History** — Search and reprint previous bills
- **KOT Generation** — Kitchen Order Ticket with special notes and category tracking
- **Bill Splitting** — Divide a bill equally or by fixed custom amounts among multiple people

### Admin Dashboard
- **Sales Analytics** — Dashboard with today's sales, yesterday comparison, monthly totals, all-time revenue, net profit, pending tables
- **Charts & Reports** — Daily sales trend (line), category breakdown (doughnut), top 10 items (bar), income vs expenses (grouped bar, last 6 months)
- **Daily Reports** — Peak hours, top-selling items, order statistics for any date, payment mode breakdown
- **Expense Tracking** — Categorize expenses, track spending history by category, monthly totals
- **Staff Management** — Add staff, assign roles (Waiter/Chef/Manager/Cashier/Cleaner/Host), track salaries, payment history
- **Inventory Management** — Track raw material stock, low-stock alerts, auto-deduct on order placement, restock capability
- **Menu Editor** — Add/edit/delete menu items, toggle availability, manage categories
- **Data Export** — Export orders, expenses, staff, and inventory data to CSV
- **Backup & Restore** — Create and restore complete data backups (ZIP) — restore validates ZIP, backs up current DB, and safely extracts
- **Settings** — Configure restaurant name, bill footer text, GST rate

### Security
- **Role-Based Access Control** — Admin, Manager, Waiter, Cashier roles with graded permissions
- **bcrypt Password Hashing** — All admin passwords stored as bcrypt hashes
- **Session Hardening** — `HttpOnly`, `SameSite=Lax`, optional `Secure` cookies, 12h session lifetime, server-side session validation
- **Security Headers** — `X-Content-Type-Options`, `X-Frame-Options`, `CSP`, `Referrer-Policy` on every response
- **Structured Logging** — All operations logged to `logs/pos.log` (also console)
- **Restore Validation** — ZIP validation, ZipSlip protection, pre-restore safety backup

---

## Screenshots

The application includes two main interfaces:

1. **POS Interface** (`http://127.0.0.1:5500`) — Dark-themed floor plan with color-coded table cards (green = available, orange = pending, red = busy), a slide-out order panel with cart, category tabs, KOT generation, split bill, and payment controls.

2. **Admin Dashboard** (`http://127.0.0.1:5500/admin`) — Animated login screen with floating particle effects, sidebar navigation with 10 sections, stat cards with gradient accents, interactive Chart.js visualizations, and full CRUD for menu/expenses/staff/inventory.

---

## Installation & Setup

### Prerequisites
- Python 3.10 or higher
- pip (Python package manager)

### Quick Install

```bash
# Navigate to the project directory
cd C:\Users\Admin\Desktop\POS

# Create a virtual environment (recommended)
python -m venv venv

# Activate the virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# (Optional) configure env
copy .env.example .env   # Windows
# cp .env.example .env   # Linux/macOS

# Run the application
python pos_app.py
```

The server starts at **http://127.0.0.1:5500** (configurable via `PORT`/`HOST` in `.env`).

Alternatively, double-click `start.bat` (Windows) — it auto-detects `.conda` or `venv`, installs deps, and opens the browser.

---

## Quick Start Guide

### First-Time Use
1. Open `http://127.0.0.1:5500` in your browser
2. Click a table card (e.g., "T1") to open the order panel
3. Select a category tab, click menu items to add them to the cart
4. Adjust quantities with +/− buttons
5. Set discount (percentage or fixed ₹ amount)
6. Choose payment mode (Cash / UPI / Card)
7. Click **Pay & Print** to finalize the bill and auto-deduct inventory

### Admin Panel
1. Click the **Admin** button in the top bar, or visit `http://127.0.0.1:5500/admin`
2. Login with default credentials:
   - **Username:** `admin`
   - **Password:** `admin123`
3. Navigate using the sidebar: Dashboard, Orders, Charts, Daily Report, Menu, Expenses, Staff, Tables, Inventory, Backup & Settings

> **Security note:** Change the default password immediately via Admin panel or `database.py` seed. Set a strong `SECRET_KEY` in `.env` — an ephemeral key is auto-generated if missing but sessions won't persist across restarts. Never commit `.env` or `data/admin/secret.key`.

### Inventory Auto-Deduction
When an order is placed, the system automatically deducts stock from corresponding inventory items (by matching item IDs). Low-stock items are flagged and visible in the Inventory section.

---

## API Endpoint Reference

All endpoints below are live — verified against `pos_app.py` routes. Port is consistently `5500` (override via `PORT` env).

### POS Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/` | — | POS interface page |
| `GET` | `/api/menu` | — | Get all menu items and categories |
| `GET` | `/api/inventory/low-stock` | — | Get low-stock inventory items |
| `POST` | `/api/order` | — | Create a walk-in order |
| `POST` | `/api/pay` | — | Pay and finalize a table order |
| `GET` | `/api/orders` | — | Get last 50 orders |
| `GET` | `/api/order/<bill_id>` | — | Get single order by bill ID |
| `POST` | `/api/pending` | — | Save/update a pending order for a table |
| `GET` | `/api/pending-list` | — | Get all pending orders |
| `GET` | `/api/pending/<table>` | — | Get pending order for a specific table |
| `DELETE` | `/api/pending/<table>` | — | Clear pending order for a table |
| `POST` | `/api/table/<table_id>/status` | — | Set table status (available/busy/reserved) |
| `GET` | `/api/tables` | — | Get all tables |
| `POST` | `/api/order/split` | — | Split a bill (equal or fixed amount) |
| `POST` | `/api/kot` | — | Generate a Kitchen Order Ticket |
| `GET` | `/api/kot/list` | — | List all KOTs |
| `GET` | `/api/kot/<kot_id>` | — | Get a single KOT |
| `PUT` | `/api/kot/<kot_id>/complete` | — | Mark a KOT as completed |

### Admin Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/admin` | — | Admin interface page |
| `POST` | `/api/admin/login` | — | Admin login (`{username, password}`) |
| `POST` | `/api/admin/logout` | ✅ | Admin logout |
| `GET` | `/api/admin/sales` | ✅ | Get all orders |
| `GET` | `/api/admin/sales-summary` | ✅ | Filtered sales summary (`start`, `end` dates) |
| `GET` | `/api/admin/stats` | ✅ | Dashboard statistics |
| `GET` | `/api/admin/search` | ✅ | Search orders (`q` param) |
| `GET` | `/api/admin/expenses` | ✅ | Get all expenses |
| `POST` | `/api/admin/expenses` | ✅ | Add expense |
| `DELETE` | `/api/admin/expenses/<id>` | ✅ | Delete an expense |
| `GET` | `/api/admin/staff` | ✅ | Get all staff |
| `POST` | `/api/admin/staff` | ✅ | Add staff member |
| `GET` | `/api/admin/salary-payments` | ✅ | Get salary payment history |
| `POST` | `/api/admin/salary-pay` | ✅ | Pay staff salaries |
| `GET` | `/api/admin/salary-history` | ✅ | Get salary history (alias) |
| `GET` | `/api/admin/charts/daily` | ✅* | Daily sales chart (`days` param) |
| `GET` | `/api/admin/charts/categories` | ✅* | Sales by category chart |
| `GET` | `/api/admin/charts/top-items` | ✅* | Top 10 items chart |
| `GET` | `/api/admin/charts/expenses-income` | ✅* | Income vs expenses chart |
| `GET` | `/api/admin/report/daily` | ✅ | Daily report (`date` param) |
| `GET` | `/api/admin/export/orders` | ✅ | Export orders (csv/json) |
| `GET` | `/api/admin/export/expenses` | ✅ | Export expenses (csv/json) |
| `GET` | `/api/admin/export/staff` | ✅ | Export staff (csv/json) |
| `GET` | `/api/admin/export/inventory` | ✅ | Export inventory (csv/json) |
| `GET` | `/api/admin/menu/items` | ✅ | Get all menu items |
| `POST` | `/api/admin/menu/items` | ✅ | Add menu item |
| `PUT` | `/api/admin/menu/items/<id>` | ✅ | Update menu item |
| `DELETE` | `/api/admin/menu/items/<id>` | ✅ | Delete menu item |
| `GET` | `/api/admin/menu/categories` | ✅ | Get all categories |
| `POST` | `/api/admin/menu/categories` | ✅ | Add category |
| `DELETE` | `/api/admin/menu/categories/<id>` | ✅ | Delete category |
| `GET` | `/api/admin/settings` | ✅ | Get settings |
| `PUT` | `/api/admin/settings` | ✅ | Update settings |
| `GET` | `/api/admin/inventory` | ✅ | Get all inventory items |
| `POST` | `/api/admin/inventory` | ✅ | Add inventory item |
| `PUT` | `/api/admin/inventory/<id>` | ✅ | Update inventory item |
| `DELETE` | `/api/admin/inventory/<id>` | ✅ | Delete inventory item |
| `GET` | `/api/admin/inventory/low-stock` | ✅ | Get low-stock items |
| `POST` | `/api/admin/backup` | ✅ | Create a backup ZIP |
| `GET` | `/api/admin/backups` | ✅ | List all backups |
| `GET` | `/api/admin/download-backup/<filename>` | ✅ | Download a backup ZIP |
| `POST` | `/api/admin/restore` | ✅ | Restore from backup (multipart `file` or JSON `{"filename":...}`) — validates ZIP, backs up current DB |

> `✅` = requires `Authorization: Bearer <token>` / `X-Admin-Token` / `admin_token` cookie. `✅*` = chart endpoints currently open but recommended to add `_require_admin` in production.

Full details with examples: see [`API_REFERENCE.md`](API_REFERENCE.md).

---

## Database Schema Overview

All data is stored in a single SQLite database: `data/pos.db`

### Tables

| Table | Primary Key | Key Columns |
|-------|-------------|-------------|
| `categories` | `id` (String) | `name`, `icon` |
| `menu_items` | `id` (String) | `name`, `price`, `category_id`, `available` |
| `orders` | `bill_id` (String) | `date`, `table`, `customer`, `payment_mode`, `subtotal`, `discount`, `gst`, `total` |
| `order_items` | `id` (Integer) | `order_bill_id`, `item_id`, `name`, `price`, `qty`, `item_total` |
| `tables` | `table_id` (String) | `status`, `updated_at` |
| `pending_orders` | `table_id` (String) | `customer`, `subtotal`, `gst`, `total`, `updated_at` |
| `pending_order_items` | `id` (Integer) | `pending_table_id`, `item_id`, `name`, `price`, `qty`, `item_total` |
| `expenses` | `id` (String) | `date`, `category`, `description`, `amount`, `paid_by` |
| `staff` | `id` (String) | `name`, `role`, `salary`, `join_date` |
| `salary_payments` | `id` (String) | `date`, `month`, `staff_ids`, `amount`, `paid_by` |
| `admin_creds` | `id` (Integer) | `username`, `password_hash`, `role`, `created_at` |
| `settings` | `key` (String) | `value` |
| `kitchen_order_tickets` | `id` (String) | `order_id`, `table`, `customer`, `status`, `created_at`, `completed_at` |
| `kot_items` | `id` (Integer) | `kot_id`, `item_id`, `name`, `qty`, `category`, `special_notes` |
| `inventory_items` | `id` (String) | `name`, `category`, `quantity`, `unit`, `reorder_level`, `cost_per_unit`, `created_at` |

---

## Configuration

Canonical config lives in `config.py` — `database.py` and `pos_app.py` both import from it (no duplication).

### Environment Variables (`.env` — see `.env.example`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | Auto-generated + persisted to `data/admin/secret.key` | Flask session secret — **set a strong value in production** |
| `HOST` | `127.0.0.1` | Bind host (`127.0.0.1` local only, `0.0.0.0` for LAN) |
| `PORT` | `5500` | Bind port — change here, not in code |
| `FLASK_DEBUG` / `DEBUG` | `0` | `1` enables debug/reload (never in production) |
| `FLASK_ENV` | `production` | `development` forces debug on |
| `GST_RATE` | `5.0` | Default GST%; also editable via Admin Settings API |
| `USE_WAITRESS` | `0` | `1` → serve with `waitress` (production) |
| `SESSION_COOKIE_SECURE` | `false` | `true` if serving over HTTPS |

### Settings (via Admin Panel or API)

| Setting Key | Default | Description |
|-------------|---------|-------------|
| `restaurant_name` | `My Restaurant` | Name displayed on receipts |
| `gst_rate` | `5` | GST percentage applied to bills |
| `footer_text` | *(empty)* | Custom footer text on receipts |

### Role Hierarchy

| Role | Level | Access |
|------|-------|--------|
| `admin` | 4 | Full access to all features |
| `manager` | 3 | Full access (can manage staff, expenses, inventory) |
| `waiter` | 2 | POS operations, view orders, create KOTs |
| `cashier` | 1 | Process payments, view orders |

### Data Directory

All data is stored under `data/`:

| Path | Contents |
|------|----------|
| `data/pos.db` | Main SQLite database |
| `data/menu.json` | Legacy menu file (auto-migrated) |
| `data/orders/*.json` | Legacy order files (auto-migrated) |
| `data/pending/*.json` | Legacy pending order files (auto-migrated) |
| `data/admin/credentials.json` | Legacy admin credentials (auto-migrated) |
| `data/admin/expenses.json` | Legacy expenses (auto-migrated) |
| `data/admin/staff.json` | Legacy staff data (auto-migrated) |
| `data/admin/salary_payments.json` | Legacy salary payments (auto-migrated) |
| `data/admin/secret.key` | Persisted SECRET_KEY (auto-generated, chmod 600) |
| `data/backups/*.zip` | Backup archives (pre-restore safety backups too) |
| `logs/pos.log` | Application log file |

---

## Security Notes

- **Change defaults:** `admin/admin123` is seed only — change on first login. Set `SECRET_KEY` to a long random string in `.env`.
- **Transport:** Use `SESSION_COOKIE_SECURE=true` + HTTPS in production; `HOST=0.0.0.0` exposes to LAN — firewall accordingly.
- **Backups:** Validate restores in staging first; each restore creates a `pre_restore_backup_*.zip` automatically.
- **Ports:** Default `5500` — ensure firewall allows it if exposing on LAN; override via `PORT` env, not by editing code.

---

## Troubleshooting

### Server won't start
- Ensure Python 3.10+ is installed: `python --version`
- Install dependencies: `pip install -r requirements.txt`
- Check that port 5500 is not in use: `netstat -ano | findstr :5500` → `PORT=5501 python pos_app.py` or set `PORT=5501` in `.env`

### Database errors on first run
- The application auto-creates the database and seeds default data on first launch
- If errors persist, delete `data/pos.db` and restart — it will be recreated

### Can't log into admin panel
- Default credentials: `admin` / `admin123`
- If credentials were changed and forgotten, delete the admin row via `sqlite3 data/pos.db "DELETE FROM admin_creds;"` and restart to re-seed

### Missing data after migration
- JSON data auto-migrates to SQLite on every startup
- If data appears missing, check `logs/pos.log` for migration warnings
- Old JSON files are preserved alongside the SQLite database

### Charts not displaying
- Requires internet connection to load Chart.js from CDN (`cdn.jsdelivr.net`)
- If offline, download `chart.umd.min.js` and reference it locally

### Port already in use
- Set `PORT=5501` in `.env` (recommended) or `set PORT=5501 && python pos_app.py`
- `start.bat` / `run_server.bat` automatically pick up `.env`

### Inventory deduction failing
- Inventory items must have IDs matching menu item IDs to auto-deduct
- Use the Inventory section in Admin to ensure IDs align

### Slow performance with many orders
- The `/api/orders` endpoint limits results to 50 newest orders by default
- Use the admin panel date filters for historical analysis

---

## License

Private use — Restaurant POS System
