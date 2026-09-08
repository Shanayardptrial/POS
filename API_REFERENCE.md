# API Reference — Restaurant POS System

Complete API documentation for the Restaurant POS System.

**Base URL:** `http://127.0.0.1:5500`

**Authentication:** Admin-protected endpoints require a valid session. Login via `POST /api/admin/login` with `{username, password}`. Protected endpoints check for `Authorization`, `X-Admin-Token`, or `admin_token` cookie headers. Role hierarchy: `admin` > `manager` > `waiter` > `cashier`.

---

## Error Response Format

All error responses follow this structure:

```json
{
  "error": "Human-readable message",
  "code": "ERROR_CODE"
}
```

## HTTP Status Codes

| Code | Meaning | Description |
|------|---------|-------------|
| `200` | OK | Request succeeded |
| `400` | Bad Request | Invalid input data (`INVALID_REQUEST`, `INVALID_ORDER`) |
| `401` | Unauthorized | Invalid or missing credentials (`UNAUTHORIZED`, `INVALID_CREDENTIALS`) |
| `403` | Forbidden | Insufficient permissions (`FORBIDDEN`) |
| `404` | Not Found | Resource does not exist (`NOT_FOUND`) |
| `409` | Conflict | Resource already exists (`DUPLICATE`) |
| `500` | Server Error | Unexpected server-side failure (`SERVER_ERROR`, `BACKUP_ERROR`, `RESTORE_ERROR`) |

---

## POS Endpoints

### Get Menu

```
GET /api/menu
```

Returns all menu categories and items. No authentication required.

**Response:**
```json
{
  "categories": [
    {"id": "biryani", "name": "Biryani", "icon": ""},
    {"id": "curry", "name": "Curry", "icon": ""}
  ],
  "items": [
    {
      "id": "chicken_biryani",
      "name": "Chicken Biryani",
      "price": 180.0,
      "category": "biryani",
      "available": true
    }
  ]
}
```

---

### Get Low-Stock Inventory

```
GET /api/inventory/low-stock
```

Returns inventory items where `quantity <= reorder_level`.

**Response:**
```json
[
  {"id": "rice", "name": "Rice", "category": "groceries", "quantity": 5, "unit": "kg", "reorder_level": 20, "cost_per_unit": 25.0, "is_low_stock": true}
]
```

---

### Create Walk-In Order

```
POST /api/order
Content-Type: application/json
```

Creates an order without a table assignment. Auto-deducts inventory stock.

**Request Body:**
```json
{
  "items": [
    {"id": "chicken_biryani", "qty": 2},
    {"id": "masala_chai", "qty": 2}
  ],
  "table": "",
  "customer": "",
  "paymentMode": "cash",
  "discount": 10,
  "discountType": "percent"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | array | yes | Array of `{id, qty}` objects |
| `table` | string | no | Table identifier (omit for walk-in) |
| `customer` | string | no | Customer name |
| `paymentMode` | string | no | `"cash"`, `"upi"`, or `"card"`. Default: `"cash"` |
| `discount` | number | no | Discount value. Default: 0 |
| `discountType` | string | no | `"percent"` or `"fixed"`. Default: `"percent"` |

**Response (200):**
```json
{
  "bill_id": "A1B2C3D4",
  "date": "07-09-2026 14:30",
  "table": "",
  "customer": "",
  "paymentMode": "cash",
  "items": [
    {"id": "chicken_biryani", "name": "Chicken Biryani", "price": 180, "qty": 2, "item_total": 360.0}
  ],
  "subtotal": 420.0,
  "discount": 42.0,
  "gst": 33.6,
  "total": 411.6
}
```

---

### Pay & Finalize Table Order

```
POST /api/pay
Content-Type: application/json
```

Same request body as `/api/order`, but clears any pending order for the table and auto-deducts inventory.

---

### Get Recent Orders

```
GET /api/orders
```

Returns the 50 most recent orders.

---

### Get Single Order

```
GET /api/order/<bill_id>
```

---

### Get All Pending Orders

```
GET /api/pending-list
```

**Response:**
```json
{
  "T1": {"table": "T1", "customer": "Rahul", "items": [...], "subtotal": 360.0, "gst": 18.0, "total": 378.0, "updated_at": "07-09-2026 14:00"},
  "T3": {...}
}
```

---

### Get Pending Order for Table

```
GET /api/pending/<table>
```

**Response (200):** Pending order object, or `null` if none exists.

---

### Save / Update Pending Order

```
POST /api/pending
Content-Type: application/json
```

**Request Body:**
```json
{
  "table": "T1",
  "customer": "Rahul Sharma",
  "items": [
    {"id": "chicken_biryani", "qty": 2},
    {"id": "butter_naan", "qty": 4}
  ]
}
```

---

### Clear Pending Order

```
DELETE /api/pending/<table>
```

**Response:** `{"success": true}`

---

### Set Table Status

```
POST /api/table/<table_id>/status
Content-Type: application/json
```

**Request Body:**
```json
{"status": "busy"}
```

Valid statuses: `"available"`, `"busy"`, `"reserved"`.

---

### Get All Tables

```
GET /api/tables
```

---

### Split Bill

```
POST /api/order/split
Content-Type: application/json
```

**Request Body (equal split):**
```json
{"bill_id": "A1B2C3D4", "split_type": "equal", "portions": 3}
```

**Request Body (fixed/custom split):**
```json
{
  "bill_id": "A1B2C3D4",
  "split_type": "fixed",
  "portions": 2,
  "custom_amounts": [150.0, 200.0]
}
```

---

### Generate Kitchen Order Ticket (KOT)

```
POST /api/kot
Content-Type: application/json
```

**Request Body:**
```json
{
  "order_id": "A1B2C3D4",
  "table": "T1",
  "customer": "Rahul",
  "items": [
    {"id": "chicken_biryani", "name": "Chicken Biryani", "qty": 2, "category": "biryani", "special_notes": "Extra spicy"},
    {"id": "butter_naan", "name": "Butter Naan", "qty": 4, "category": "roti", "special_notes": ""}
  ]
}
```

---

### List All KOTs

```
GET /api/kot/list
```

---

### Get Single KOT

```
GET /api/kot/<kot_id>
```

---

### Complete a KOT

```
PUT /api/kot/<kot_id>/complete
```

---

## Admin Endpoints

All admin endpoints (unless noted) require authentication via the `_require_admin` decorator. Send a valid token in the `Authorization: Bearer <token>` header, `X-Admin-Token` header, or `admin_token` cookie.

### Admin Login

```
POST /api/admin/login
Content-Type: application/json
```

**Request Body:**
```json
{"username": "admin", "password": "admin123"}
```

**Response (200):**
```json
{
  "success": true,
  "token": "a1b2c3d4e5f6g7h8",
  "username": "admin",
  "role": "admin"
}
```

**Response (401):**
```json
{"error": "Invalid credentials", "code": "INVALID_CREDENTIALS"}
```

---

### Admin Logout

```
POST /api/admin/logout
```

**Response:** `{"success": true}`

---

### Get All Sales

```
GET /api/admin/sales
```

Returns all orders ordered by date descending.

---

### Get Sales Summary (Date Filtered)

```
GET /api/admin/sales-summary?start=2026-09-01&end=2026-09-07
```

| Query Param | Description |
|-------------|-------------|
| `start` | Start date (YYYY-MM-DD). Optional. |
| `end` | End date (YYYY-MM-DD). Optional. |

**Response:**
```json
{
  "start": "2026-09-01",
  "end": "2026-09-07",
  "total_orders": 24,
  "total_sales": 4560.0,
  "orders": [...]
}
```

---

### Get Dashboard Stats

```
GET /api/admin/stats
```

**Response:**
```json
{
  "today_sales": 1250.0,
  "yesterday_sales": 980.0,
  "today_orders": 8,
  "all_time_sales": 45600.0,
  "total_orders": 312,
  "today_expenses": 500.0,
  "total_expenses": 12000.0,
  "total_salary": 24000.0,
  "this_month_sales": 18500.0,
  "this_month_orders": 45,
  "current_month_salary": 24000.0,
  "current_month_paid": 20000.0,
  "current_month_pending": 4000.0,
  "total_salary_paid": 48000.0,
  "net_profit": 33600.0,
  "pending_tables": 3
}
```

---

### Search Orders

```
GET /api/admin/search?q=bill_id_or_customer
```

Searches across `bill_id`, `customer`, and `table` fields (case-insensitive).

---

### Get Expenses

```
GET /api/admin/expenses
```

---

### Add Expense

```
POST /api/admin/expenses
Content-Type: application/json
```

**Request Body:**
```json
{
  "category": "Grocery",
  "description": "Vegetables purchase",
  "amount": 500.0,
  "paid_by": "admin"
}
```

---

### Delete Expense

```
DELETE /api/admin/expenses/<expense_id>
```

**Response:** `{"success": true}` or `(404, {"error": "Expense not found", "code": "NOT_FOUND"})`

---

### Get Staff

```
GET /api/admin/staff
```

---

### Add Staff

```
POST /api/admin/staff
Content-Type: application/json
```

**Request Body:**
```json
{
  "name": "Rajesh Kumar",
  "role": "Waiter",
  "salary": 8000.0,
  "join_date": "01-09-2026"
}
```

---

### Pay Salary

```
POST /api/admin/salary-pay
Content-Type: application/json
```

**Request Body:**
```json
{
  "staff_ids": ["A1B2C3", "D4E5F6"],
  "month": "2026-09",
  "amount": 16000.0,
  "paid_by": "admin"
}
```

---

### Get Salary Payments

```
GET /api/admin/salary-payments
GET /api/admin/salary-history
```

Both return the same data: array of salary payment records.

---

### Get Menu Items

```
GET /api/admin/menu/items
```

---

### Add Menu Item

```
POST /api/admin/menu/items
Content-Type: application/json
```

**Request Body:**
```json
{
  "name": "Mango Lassi",
  "price": 70.0,
  "category": "drinks",
  "available": true
}
```

---

### Update Menu Item

```
PUT /api/admin/menu/items/<item_id>
Content-Type: application/json
```

**Request Body (all fields optional):**
```json
{
  "name": "Updated Name",
  "price": 75.0,
  "category": "drinks",
  "available": false
}
```

---

### Delete Menu Item

```
DELETE /api/admin/menu/items/<item_id>
```

**Response:** `{"success": true}` or `(404, {"error": "Item not found", "code": "NOT_FOUND"})`

---

### Get Menu Categories

```
GET /api/admin/menu/categories
```

---

### Add Menu Category

```
POST /api/admin/menu/categories
Content-Type: application/json
```

**Request Body:**
```json
{
  "id": "soups",
  "name": "Soups",
  "icon": "🍲"
}
```

---

### Delete Menu Category

```
DELETE /api/admin/menu/categories/<cat_id>
```

**Response:** `{"success": true}` or `(404, {"error": "Category not found", "code": "NOT_FOUND"})`

---

### Get Settings

```
GET /api/admin/settings
```

**Response:**
```json
{
  "restaurant_name": "My Restaurant",
  "gst_rate": "5",
  "footer_text": ""
}
```

---

### Update Settings

```
PUT /api/admin/settings
Content-Type: application/json
```

**Request Body (any subset of fields):**
```json
{
  "restaurant_name": "Spice Garden",
  "gst_rate": "5",
  "footer_text": "Thank you for dining with us!"
}
```

---

### Get Inventory

```
GET /api/admin/inventory
```

---

### Add Inventory Item

```
POST /api/admin/inventory
Content-Type: application/json
```

**Request Body:**
```json
{
  "id": "rice",
  "name": "Rice",
  "category": "groceries",
  "quantity": 50,
  "unit": "kg",
  "reorder_level": 20,
  "cost_per_unit": 25.0
}
```

---

### Update Inventory Item

```
PUT /api/admin/inventory/<item_id>
Content-Type: application/json
```

**Request Body (all fields optional):**
```json
{
  "name": "Basmati Rice",
  "quantity": 45,
  "reorder_level": 15
}
```

---

### Delete Inventory Item

```
DELETE /api/admin/inventory/<item_id>
```

**Response:** `{"success": true}` or `(404, {"error": "Inventory item not found", "code": "NOT_FOUND"})`

---

### Get Low-Stock Inventory (Admin)

```
GET /api/admin/inventory/low-stock
```

---

## Chart Endpoints

### Daily Sales Chart

```
GET /api/admin/charts/daily?days=30
```

| Query Param | Default | Description |
|-------------|---------|-------------|
| `days` | 30 | Number of days to include |

**Response:**
```json
{
  "labels": ["01-09", "02-09", ..., "07-09"],
  "data": [1200.0, 980.0, ..., 1450.0]
}
```

---

### Sales by Category

```
GET /api/admin/charts/categories
```

**Response:**
```json
{
  "labels": ["Biryani", "Curry", "Roti", "Drinks"],
  "data": [12500.0, 8400.0, 3200.0, 1800.0]
}
```

---

### Top Selling Items

```
GET /api/admin/charts/top-items
```

**Response:**
```json
{
  "labels": ["Chicken Biryani", "Butter Chicken", "Masala Chai"],
  "data": [4500.0, 3200.0, 1800.0]
}
```

---

### Income vs Expenses

```
GET /api/admin/charts/expenses-income
```

Returns last 6 months of data.

**Response:**
```json
{
  "labels": ["Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"],
  "income": [12000.0, 15000.0, ...],
  "expenses": [5000.0, 6200.0, ...]
}
```

---

## Report Endpoints

### Daily Report

```
GET /api/admin/report/daily?date=07-09-2026
```

| Query Param | Default | Format | Description |
|-------------|---------|--------|-------------|
| `date` | Today | DD-MM-YYYY | Date to generate report for |

**Response:**
```json
{
  "date": "07-09-2026",
  "total_orders": 12,
  "total_sales": 2340.0,
  "avg_order": 195.0,
  "peak_hour": "13:00",
  "top_items": [
    {"name": "Chicken Biryani", "qty": 8}
  ]
}
```

---

## Export Endpoints

### Export Orders

```
GET /api/admin/export/orders?format=csv
GET /api/admin/export/orders?format=json
```

CSV columns: `Bill ID, Date, Table, Customer, Items, Subtotal, GST, Total, Payment Mode`

---

### Export Expenses

```
GET /api/admin/export/expenses?format=csv
GET /api/admin/export/expenses?format=json
```

---

### Export Staff

```
GET /api/admin/export/staff?format=csv
GET /api/admin/export/staff?format=json
```

---

### Export Inventory

```
GET /api/admin/export/inventory?format=csv
GET /api/admin/export/inventory?format=json
```

CSV columns: `ID, Name, Category, Quantity, Unit, Reorder Level, Cost/Unit, Low Stock`

---

## Backup Endpoints

### Create Backup

```
POST /api/admin/backup
```

Creates a ZIP archive containing the SQLite database and legacy JSON files.

**Response:**
```json
{"success": true, "filename": "backup_20260907_143000.zip"}
```

---

### List Backups

```
GET /api/admin/backups
```

**Response:**
```json
[
  {"filename": "backup_20260907_143000.zip", "size": 10240, "date": 1725712200.0},
  {"filename": "backup_20260907_100000.zip", "size": 9800, "date": 1725697200.0}
]
```

---

### Download Backup

```
GET /api/admin/download-backup/<filename>
```

Serves the backup ZIP as a download.

---

### Restore from Backup

```
POST /api/admin/restore
Content-Type: multipart/form-data
```

Or with JSON body:
```
POST /api/admin/restore
Content-Type: application/json

{"filename": "backup_20260907_143000.zip"}
```

---

## Example Requests

### Create a Bill (cURL)

```bash
curl -X POST http://127.0.0.1:5500/api/pay \
  -H "Content-Type: application/json" \
  -d '{
    "table": "T1",
    "customer": "Rahul Sharma",
    "paymentMode": "cash",
    "items": [
      {"id": "chicken_biryani", "qty": 2},
      {"id": "butter_naan", "qty": 4},
      {"id": "masala_chai", "qty": 2}
    ],
    "discount": 10,
    "discountType": "percent"
  }'
```

### Login to Admin (cURL)

```bash
curl -X POST http://127.0.0.1:5500/api/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

### Get Today's Stats (cURL)

```bash
curl http://127.0.0.1:5500/api/admin/stats \
  -H "Authorization: Bearer <token>"
```

### Add a Menu Item (cURL)

```bash
curl -X POST http://127.0.0.1:5500/api/admin/menu/items \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"name": "Mango Lassi", "price": 70, "category": "drinks", "available": true}'
```

### Add an Inventory Item (cURL)

```bash
curl -X POST http://127.0.0.1:5500/api/admin/inventory \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"id": "rice", "name": "Rice", "category": "groceries", "quantity": 50, "unit": "kg", "reorder_level": 20, "cost_per_unit": 25}'
```

### Create a Backup (cURL)

```bash
curl -X POST http://127.0.0.1:5500/api/admin/backup \
  -H "Authorization: Bearer <token>"
```

### Generate KOT (cURL)

```bash
curl -X POST http://127.0.0.1:5500/api/kot \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "A1B2C3D4",
    "table": "T1",
    "customer": "Rahul",
    "items": [
      {"id": "chicken_biryani", "name": "Chicken Biryani", "qty": 2, "special_notes": "Extra spicy"}
    ]
  }'
```
