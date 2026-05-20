"""
db_connection.py – Pawffinated PostgreSQL Connection Manager
=============================================================
CHANGES:
    • products table now has an `image_path` TEXT column (nullable).
    • All product CRUD methods now include image_path.
    • All sales query methods now accept date_from / date_to (str 'YYYY-MM-DD').
    • NEW: StaffDB class for Account Management (staff profiles, clock events).
    • Staff table: id, name, email, phone, role, avatar, device, started_on, schedule, etc.
    • Clock_events table: staff_id, event_type (Clock In/Out), timestamp, device, duration.
"""

from __future__ import annotations

import os
import re
import logging
from datetime import date, timedelta, datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.pool

log = logging.getLogger("pawffinated.db")

_HERE = Path(__file__).resolve().parent
_ENV_FILE = _HERE / "pawffinated.env"

_SEED_ROWS: list[dict] = []

# ── Schema ────────────────────────────────────────────────────────────────────
_CREATE_PRODUCTS = """
CREATE TABLE IF NOT EXISTS products (
    id          SERIAL         PRIMARY KEY,
    name        TEXT           NOT NULL,
    sku         TEXT           NOT NULL DEFAULT '',
    category    TEXT           NOT NULL DEFAULT 'Other',
    stock       INTEGER        NOT NULL DEFAULT 0,
    unit        TEXT           NOT NULL DEFAULT 'units',
    price       NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    description TEXT                    DEFAULT '',
    image_path  TEXT                    DEFAULT NULL
);
"""

_CREATE_ORDERS = """
CREATE TABLE IF NOT EXISTS orders (
    id            SERIAL         PRIMARY KEY,
    order_number  INTEGER        NOT NULL,
    order_type    TEXT           NOT NULL DEFAULT 'Dine In',
    customer_name TEXT           NOT NULL DEFAULT 'Walk-in Customer',
    subtotal      NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    discount_type TEXT                    DEFAULT 'None',
    discount_amount NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    total_amount  NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
"""

_CREATE_ORDER_ITEMS = """
CREATE TABLE IF NOT EXISTS order_items (
    id          SERIAL         PRIMARY KEY,
    order_id    INTEGER        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER        REFERENCES products(id) ON DELETE SET NULL,
    name        TEXT           NOT NULL,
    category    TEXT           NOT NULL DEFAULT 'Other',
    sku         TEXT           NOT NULL DEFAULT '',
    unit_price  NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    quantity    INTEGER        NOT NULL DEFAULT 1,
    subtotal    NUMERIC(10, 2) NOT NULL DEFAULT 0.00
);
"""

# ── Staff Management Schema ───────────────────────────────────────────────────
_CREATE_STAFF = """
CREATE TABLE IF NOT EXISTS staff (
    id              SERIAL         PRIMARY KEY,
    name            TEXT           NOT NULL,
    email           TEXT           UNIQUE,
    phone           TEXT,
    role            TEXT           NOT NULL DEFAULT 'Staff',
    avatar          TEXT,
    device          TEXT           DEFAULT 'Mobile',
    started_on      DATE,
    schedule        TEXT           DEFAULT '9:00 AM – 5:30 PM',
    shift_hrs       TEXT           DEFAULT '8.5h',
    role_desc       TEXT           DEFAULT 'Team Member',
    role_detail     TEXT           DEFAULT 'Retail Operations',
    this_week       TEXT           DEFAULT '5 shifts',
    week_sub        TEXT           DEFAULT 'On track',
    last_month      TEXT           DEFAULT '160h',
    month_sub       TEXT           DEFAULT 'Completed',
    hours_worked    TEXT           DEFAULT '0h',
    hours_sub       TEXT           DEFAULT 'This month',
    attendance      TEXT           DEFAULT '100%',
    att_sub         TEXT           DEFAULT 'No absences',
    avg_shift       TEXT           DEFAULT '8.5h',
    avg_sub         TEXT           DEFAULT 'Per shift',
    punctuality_on  TEXT           DEFAULT '20/20',
    punctuality_late TEXT          DEFAULT '0/20',
    punctuality_rating TEXT         DEFAULT 'Excellent',
    completed       TEXT           DEFAULT '20/20',
    adjusted        TEXT           DEFAULT '0/20',
    completed_rating TEXT          DEFAULT 'Excellent',
    mgr_note1       TEXT           DEFAULT 'Reliable',
    mgr_note2       TEXT           DEFAULT 'Punctual',
    mgr_note3       TEXT           DEFAULT 'Professional',
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
"""

_CREATE_CLOCK_EVENTS = """
CREATE TABLE IF NOT EXISTS clock_events (
    id              SERIAL         PRIMARY KEY,
    staff_id        INTEGER        NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    event_type      TEXT           NOT NULL CHECK (event_type IN ('Clock In', 'Clock Out')),
    timestamp       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    device          TEXT           DEFAULT 'Mobile',
    duration        TEXT           DEFAULT NULL,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
"""

_CREATE_SHIFTS = """
CREATE TABLE IF NOT EXISTS shifts (
    id              SERIAL         PRIMARY KEY,
    staff_id        INTEGER        NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    day             TEXT           NOT NULL,
    time            TEXT           NOT NULL,
    note            TEXT,
    tag             TEXT           DEFAULT 'Scheduled',
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
"""

# ── Users / Login Table ───────────────────────────────────────────────────────
_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL         PRIMARY KEY,
    first_name      TEXT           NOT NULL,
    last_name       TEXT           NOT NULL,
    email           TEXT           NOT NULL UNIQUE,
    password        TEXT           NOT NULL,
    role            TEXT           NOT NULL DEFAULT 'Barista',
    station         TEXT           NOT NULL DEFAULT 'Front Counter',
    is_admin        BOOLEAN        NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
"""

# ── Seed admin account (inserted once if table is empty) ─────────────────────
_SEED_ADMIN = {
    "first_name": "Admin",
    "last_name":  "User",
    "email":      "admin@pawffinated.com",
    "password":   "admin123",
    "role":       "Administrator",
    "station":    "Back Office",
    "is_admin":   True,
}

# ── Timezone ──────────────────────────────────────────────────────────────────
_TZ = "Asia/Manila"


# ── Date helpers ──────────────────────────────────────────────────────────────

def _resolve_dates(
    date_from: str | None,
    date_to:   str | None,
    days:      int = 1,
) -> tuple[str, str]:
    """
    Return (date_from_str, date_to_str) as 'YYYY-MM-DD'.
    If explicit date strings are provided, use them.
    Otherwise fall back to the last `days` days ending today.
    """
    if date_from and date_to:
        return date_from, date_to
    today = date.today()
    d_to = today
    d_from = today - timedelta(days=days - 1)
    return d_from.isoformat(), d_to.isoformat()


def _prev_period(date_from: str, date_to: str) -> tuple[str, str]:
    """Return the immediately preceding period of the same length."""
    d_from = date.fromisoformat(date_from)
    d_to = date.fromisoformat(date_to)
    n_days = (d_to - d_from).days + 1
    prev_to = d_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=n_days - 1)
    return prev_from.isoformat(), prev_to.isoformat()


# ── Config loading ────────────────────────────────────────────────────────────

def _load_env_file(path: Path = _ENV_FILE) -> None:
    if not path.exists():
        log.debug("No config file at %s — relying on environment variables.", path)
        return
    log.info("Loading config from %s", path)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip("'\"")
        os.environ.setdefault(key, value)


def _build_dsn() -> str:
    _load_env_file()
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        log.info("Connecting via DATABASE_URL → %s", _redact(url))
        return url
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "pawffinated")
    user = os.environ.get("DB_USER", "postgres")
    passwd = os.environ.get("DB_PASS", "")
    dsn = f"postgresql://{user}:{passwd}@{host}:{port}/{name}"
    log.info("Connecting via config keys → %s", _redact(dsn))
    return dsn


def _redact(dsn: str) -> str:
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", dsn)


# ─────────────────────────────────────────────────────────────────────────────
# InventoryDB
# ─────────────────────────────────────────────────────────────────────────────

class InventoryDB:
    """
    PostgreSQL persistence layer for Pawffinated (Inventory & POS).

    Public API — Products
    ---------------------
    fetch_all()                                   → list[dict]
    fetch_by_id(item_id)                          → dict | None
    insert(item_dict)                             → int
    update(item_dict)                             → None
    delete(item_id)                               → None
    bulk_replace(list[dict])                      → int

    Public API — Dashboard helpers
    --------------------------------
    get_low_stock_count()                         → int
    get_out_of_stock_count()                      → int
    get_total_inventory_value()                   → float
    get_alerts()                                  → list[dict]

    Public API — Orders (POS → DB)
    --------------------------------
    insert_order(order_dict)                      → int
    insert_order_items(order_id, items)           → None

    Public API — Sales / Dashboard reads
    -----------------------------------------
    get_sales_summary(date_from, date_to)         → dict
    get_top_sellers(date_from, date_to, limit)    → list[dict]
    get_hourly_sales(date_from, date_to)          → list[dict]
    get_hourly_snapshot(date_from, date_to)       → list[dict]  (alias)
    get_sales_log(date_from, date_to)             → list[dict]  ← includes order-type + discount
    get_recent_orders(limit)                      → list[dict]
    get_order_type_breakdown(date_from, date_to)  → dict
    get_discount_summary(date_from, date_to)      → dict
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._safe_dsn = _redact(dsn)
        self._pool = self._make_pool()
        self._ensure_schema()

    # ── Pool ──────────────────────────────────────────────────────────────────

    def _make_pool(self) -> psycopg2.pool.ThreadedConnectionPool:
        try:
            pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=5, dsn=self._dsn,
            )
            log.info("Connection pool created → %s", self._safe_dsn)
            return pool
        except psycopg2.OperationalError as exc:
            log.error("Could not connect to PostgreSQL: %s", exc)
            raise ConnectionError(
                f"Cannot connect to the database.\n\n"
                f"Connection: {self._safe_dsn}\n\n"
                f"Check that:\n"
                f"  • PostgreSQL is running\n"
                f"  • Credentials in pawffinated.env are correct\n"
                f"  • Firewall allows port 5432\n\n"
                f"Original error: {exc}"
            ) from exc

    def _conn(self):
        return _PooledConnection(self._pool)

    # ── Schema ────────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_PRODUCTS)
                cur.execute(_CREATE_ORDERS)
                cur.execute(_CREATE_ORDER_ITEMS)
                cur.execute("""
                    DO $$
                    BEGIN
                        -- discount_type column
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='orders' AND column_name='discount_type'
                        ) THEN
                            ALTER TABLE orders ADD COLUMN discount_type TEXT DEFAULT 'None';
                        END IF;
                        -- discount_amount column
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='orders' AND column_name='discount_amount'
                        ) THEN
                            ALTER TABLE orders ADD COLUMN discount_amount NUMERIC(10,2) DEFAULT 0.00;
                        END IF;
                        -- image_path column (new)
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='products' AND column_name='image_path'
                        ) THEN
                            ALTER TABLE products ADD COLUMN image_path TEXT DEFAULT NULL;
                        END IF;
                    END$$;
                """)
                cur.execute("SELECT COUNT(*) FROM products")
                count = cur.fetchone()[0]
            conn.commit()
        if count == 0:
            log.info("Empty products table — inserting seed data.")
            self._seed()

    def _seed(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO products
                        (name, sku, category, stock, unit, price, description, image_path)
                    VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s, %(image_path)s)
                    """,
                    _SEED_ROWS, page_size=100,
                )
            conn.commit()

    # ─────────────────────────────────────────────────────────────────────────
    # Products — CRUD
    # ─────────────────────────────────────────────────────────────────────────

    def fetch_all(self) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, sku, category, stock, unit, price, description, image_path "
                    "FROM products ORDER BY id"
                )
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    def fetch_by_id(self, item_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, sku, category, stock, unit, price, description, image_path "
                    "FROM products WHERE id = %s",
                    (item_id,),
                )
                row = cur.fetchone()
        return _normalise(dict(row)) if row else None

    def insert(self, item: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO products
                        (name, sku, category, stock, unit, price, description, image_path)
                    VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s, %(image_path)s)
                    RETURNING id
                    """,
                    _params(item),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        log.debug("INSERT product id=%s  name=%s", new_id, item.get("name"))
        return new_id

    def update(self, item: dict) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE products
                       SET name        = %(name)s,
                           sku         = %(sku)s,
                           category    = %(category)s,
                           stock       = %(stock)s,
                           unit        = %(unit)s,
                           price       = %(price)s,
                           description = %(description)s,
                           image_path  = %(image_path)s
                     WHERE id = %(id)s
                    """,
                    {**_params(item), "id": item["id"]},
                )
            conn.commit()
        log.debug("UPDATE product id=%s", item.get("id"))

    def delete(self, item_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM products WHERE id = %s", (item_id,))
            conn.commit()
        log.debug("DELETE product id=%s", item_id)

    def bulk_replace(self, items: list[dict]) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM products")
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO products
                        (name, sku, category, stock, unit, price, description, image_path)
                    VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s, %(image_path)s)
                    """,
                    [_params(i) for i in items], page_size=100,
                )
            conn.commit()
        log.info("bulk_replace: inserted %d rows", len(items))
        return len(items)

    def execute_query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    # ─────────────────────────────────────────────────────────────────────────
    # Dashboard helpers
    # ─────────────────────────────────────────────────────────────────────────

    def get_low_stock_count(self) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM products WHERE stock > 0 AND stock <= 10"
                )
                return cur.fetchone()[0]

    def get_out_of_stock_count(self) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM products WHERE stock = 0")
                return cur.fetchone()[0]

    def get_total_inventory_value(self) -> float:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(SUM(stock * price), 0) FROM products"
                )
                return float(cur.fetchone()[0])

    def get_alerts(self, low_stock_threshold: int = 10) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT name, category, stock FROM products "
                    "WHERE stock <= %s ORDER BY stock ASC",
                    (low_stock_threshold,)
                )
                rows = cur.fetchall()
        alerts = []
        for r in rows:
            if r["stock"] == 0:
                alerts.append({
                    "name": r["name"], "category": r["category"],
                    "stock": r["stock"], "label": "Out of stock",
                    "severity": "danger",
                })
            else:
                alerts.append({
                    "name": r["name"], "category": r["category"],
                    "stock": r["stock"], "label": f"{r['stock']} left",
                    "severity": "warn",
                })
        return alerts

    # ─────────────────────────────────────────────────────────────────────────
    # Orders — POS writes
    # ─────────────────────────────────────────────────────────────────────────

    def insert_order(self, order: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO orders
                        (order_number, order_type, customer_name,
                         subtotal, discount_type, discount_amount, total_amount)
                    VALUES
                        (%(order_number)s, %(order_type)s, %(customer_name)s,
                         %(subtotal)s, %(discount_type)s, %(discount_amount)s,
                         %(total_amount)s)
                    RETURNING id
                    """,
                    {
                        "order_number":    int(order["order_number"]),
                        "order_type":      str(order["order_type"]),
                        "customer_name":   str(order["customer_name"]),
                        "subtotal":        float(order["subtotal"]),
                        "discount_type":   str(order.get("discount_type", "None")),
                        "discount_amount": float(order.get("discount_amount", 0.0)),
                        "total_amount":    float(order["total_amount"]),
                    },
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        log.debug("INSERT order id=%s  number=%s",
                  new_id, order.get("order_number"))
        return new_id

    def insert_order_items(self, order_id: int, items: list[dict]) -> None:
        rows = [
            {
                "order_id":   order_id,
                "product_id": item.get("product_id"),
                "name":       str(item["name"]),
                "category":   str(item.get("category", "Other")),
                "sku":        str(item.get("sku", "")),
                "unit_price": float(item["unit_price"]),
                "quantity":   int(item["quantity"]),
                "subtotal":   float(item["subtotal"]),
            }
            for item in items
        ]
        with self._conn() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO order_items
                        (order_id, product_id, name, category, sku,
                         unit_price, quantity, subtotal)
                    VALUES
                        (%(order_id)s, %(product_id)s, %(name)s, %(category)s,
                         %(sku)s, %(unit_price)s, %(quantity)s, %(subtotal)s)
                    """,
                    rows, page_size=100,
                )
            conn.commit()
        log.debug("INSERT %d order_items for order_id=%s", len(rows), order_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Sales / Dashboard reads — DATE-RANGE ACCURATE
    # ─────────────────────────────────────────────────────────────────────────

    def get_sales_summary(
        self,
        date_from: str | None = None,
        date_to:   str | None = None,
        days:      int = 1,
    ) -> dict:
        """
        Return KPI summary for the given date range.
        Uses DATE() in Manila timezone so "Yesterday" is exactly yesterday.

        Returns:
            gross_sales, total_orders, avg_ticket, sales_change (%),
            yesterday (prev-period total), total_discounts, pwd_senior_count,
            dine_in_count, takeout_count, delivery_count
        """
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        p_from, p_to = _prev_period(d_from, d_to)

        with self._conn() as conn:
            with conn.cursor() as cur:
                # ── Current period ────────────────────────────────────────
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(total_amount),    0) AS gross_sales,
                        COUNT(*)                          AS total_orders,
                        COALESCE(SUM(discount_amount), 0) AS total_discounts,
                        COUNT(CASE WHEN discount_type NOT IN ('None','') THEN 1 END)
                                                          AS pwd_senior_count,
                        COUNT(CASE WHEN order_type = 'Dine In'  THEN 1 END) AS dine_in_count,
                        COUNT(CASE WHEN order_type = 'Takeout'  THEN 1 END) AS takeout_count,
                        COUNT(CASE WHEN order_type = 'Delivery' THEN 1 END) AS delivery_count
                    FROM orders
                    WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s
                    """,
                    (_TZ, d_from, d_to)
                )
                row = cur.fetchone()
                gross_sales = float(row[0])
                total_orders = int(row[1])
                total_discounts = float(row[2])
                pwd_senior_count = int(row[3])
                dine_in_count = int(row[4])
                takeout_count = int(row[5])
                delivery_count = int(row[6])

                # ── Previous period (for delta %) ─────────────────────────
                cur.execute(
                    """
                    SELECT COALESCE(SUM(total_amount), 0)
                    FROM orders
                    WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s
                    """,
                    (_TZ, p_from, p_to)
                )
                prev_sales = float(cur.fetchone()[0])

        avg_ticket = gross_sales / total_orders if total_orders else 0.0
        change = ((gross_sales - prev_sales) / prev_sales *
                  100) if prev_sales > 0 else 0.0

        return {
            "gross_sales":        gross_sales,
            "total_orders":       total_orders,
            "avg_ticket":         avg_ticket,
            "sales_change":       round(change, 1),
            "yesterday":          prev_sales,
            "total_discounts":    total_discounts,
            "pwd_senior_count":   pwd_senior_count,
            "dine_in_count":      dine_in_count,
            "takeout_count":      takeout_count,
            "delivery_count":     delivery_count,
        }

    def get_top_sellers(
        self,
        date_from: str | None = None,
        date_to:   str | None = None,
        days:      int = 1,
        limit:     int = 4,
    ) -> list[dict]:
        """Return top-selling products by units sold for the date range.
        Includes image_path by joining against the products table."""
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        oi.name,
                        oi.category,
                        SUM(oi.quantity)  AS units_sold,
                        SUM(oi.subtotal)  AS revenue,
                        MAX(p.image_path) AS image_path
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    LEFT JOIN products p ON p.id = oi.product_id
                    WHERE DATE(o.created_at AT TIME ZONE %s) BETWEEN %s AND %s
                    GROUP BY oi.name, oi.category
                    ORDER BY units_sold DESC
                    LIMIT %s
                    """,
                    (_TZ, d_from, d_to, limit)
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_hourly_sales(
        self,
        date_from: str | None = None,
        date_to:   str | None = None,
        days:      int = 1,
    ) -> list[dict]:
        """Return revenue grouped by hour (Manila time) for the date range."""
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        TO_CHAR(created_at AT TIME ZONE %s, 'HH12 AM') AS hour,
                        SUM(total_amount)                               AS revenue
                    FROM orders
                    WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s
                    GROUP BY hour
                    ORDER BY MIN(created_at)
                    """,
                    (_TZ, _TZ, d_from, d_to)
                )
                rows = cur.fetchall()
        return [{"hour": r["hour"].strip(), "revenue": float(r["revenue"])}
                for r in rows]

    def get_hourly_snapshot(
        self,
        date_from: str | None = None,
        date_to:   str | None = None,
        days:      int = 1,
    ) -> list[dict]:
        """Alias used by Sales Monitor. Delegates to get_hourly_sales."""
        return self.get_hourly_sales(date_from=date_from, date_to=date_to, days=days)

    def get_sales_log(
        self,
        date_from: str | None = None,
        date_to:   str | None = None,
        days:      int = 1,
    ) -> list[dict]:
        """
        Return per-product sales breakdown for the date range.

        Each dict now includes:
            name, sku, category,
            unit_sales, unit_price,
            gross_revenue, ingredient_cost (35%), profit_per_item (65%), total_profit,
            dine_in_qty    — units sold via Dine In orders
            takeout_qty    — units sold via Takeout orders
            delivery_qty   — units sold via Delivery orders
            discounted_orders — count of orders that had a PWD/Senior discount
            discount_types — comma-separated unique discount type labels (e.g. "PWD, Senior")
            image_path     — product image path (from products table, may be NULL)
        """
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        oi.name,
                        oi.sku,
                        oi.category,
                        SUM(oi.quantity)                                         AS unit_sales,
                        AVG(oi.unit_price)                                       AS unit_price,
                        SUM(oi.subtotal)                                         AS gross_revenue,
                        ROUND(AVG(oi.unit_price) * 0.35, 2)                     AS ingredient_cost,
                        ROUND(AVG(oi.unit_price) * 0.65, 2)                     AS profit_per_item,
                        ROUND(SUM(oi.subtotal)   * 0.65, 2)                     AS total_profit,
                        -- order-type breakdown
                        COALESCE(SUM(CASE WHEN o.order_type = 'Dine In'
                                         THEN oi.quantity ELSE 0 END), 0)       AS dine_in_qty,
                        COALESCE(SUM(CASE WHEN o.order_type = 'Takeout'
                                         THEN oi.quantity ELSE 0 END), 0)       AS takeout_qty,
                        COALESCE(SUM(CASE WHEN o.order_type = 'Delivery'
                                         THEN oi.quantity ELSE 0 END), 0)       AS delivery_qty,
                        -- discount info
                        COUNT(CASE WHEN o.discount_type NOT IN ('None', '')
                                   THEN 1 END)                                   AS discounted_orders,
                        COALESCE(
                            STRING_AGG(DISTINCT
                                CASE WHEN o.discount_type NOT IN ('None', '')
                                     THEN o.discount_type END,
                                ', ' ORDER BY
                                CASE WHEN o.discount_type NOT IN ('None', '')
                                     THEN o.discount_type END),
                            '')                                                  AS discount_types,
                        -- product image (latest path wins if product was renamed)
                        MAX(p.image_path)                                        AS image_path
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    LEFT JOIN products p ON p.id = oi.product_id
                    WHERE DATE(o.created_at AT TIME ZONE %s) BETWEEN %s AND %s
                    GROUP BY oi.name, oi.sku, oi.category
                    ORDER BY unit_sales DESC
                    """,
                    (_TZ, d_from, d_to)
                )
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    def get_recent_orders(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        o.id, o.order_number, o.order_type,
                        o.customer_name, o.subtotal,
                        o.discount_type, o.discount_amount,
                        o.total_amount, o.created_at
                    FROM orders o
                    ORDER BY o.created_at DESC
                    LIMIT %s
                    """,
                    (limit,)
                )
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    def get_order_type_breakdown(
        self,
        date_from: str | None = None,
        date_to:   str | None = None,
        days:      int = 1,
    ) -> dict:
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        order_type,
                        COUNT(*) AS cnt,
                        COALESCE(SUM(total_amount), 0) AS revenue
                    FROM orders
                    WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s
                    GROUP BY order_type
                    """,
                    (_TZ, d_from, d_to)
                )
                rows = cur.fetchall()
        result = {"Dine In": 0, "Takeout": 0, "Delivery": 0}
        revenue = {"Dine In": 0.0, "Takeout": 0.0, "Delivery": 0.0}
        for ot, cnt, rev in rows:
            if ot in result:
                result[ot] = int(cnt)
                revenue[ot] = float(rev)
        return {"counts": result, "revenue": revenue}

    def get_discount_summary(
        self,
        date_from: str | None = None,
        date_to:   str | None = None,
        days:      int = 1,
    ) -> dict:
        """Return PWD and Senior Citizen discount totals for the date range."""
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        discount_type,
                        COUNT(*) AS cnt,
                        COALESCE(SUM(discount_amount), 0) AS total_disc
                    FROM orders
                    WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s
                      AND discount_type NOT IN ('None', '')
                    GROUP BY discount_type
                    """,
                    (_TZ, d_from, d_to)
                )
                rows = cur.fetchall()
        result = {}
        for dtype, cnt, total in rows:
            result[dtype] = {"count": int(cnt), "total": float(total)}
        return result

    def has_orders(self) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT EXISTS(SELECT 1 FROM orders LIMIT 1)")
                return cur.fetchone()[0]

    def close(self) -> None:
        self._pool.closeall()
        log.info("Connection pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# StaffDB — Account Management & Time Tracking
# ─────────────────────────────────────────────────────────────────────────────

class StaffDB:
    """
    PostgreSQL persistence layer for Staff Management (Account Management).

    Public API — Staff Profiles
    ----------------------------
    get_staff(staff_id)                           → dict | None
    insert_staff(staff_dict)                      → int
    update_staff(staff_dict)                      → None
    get_all_staff()                               → list[dict]

    Public API — Clock Events
    --------------------------
    add_clock_event(staff_id, event_type, device, duration)  → None
    get_clock_log(staff_id)                       → list[dict]
    get_last_clock_event(staff_id)                → dict | None
    update_clock_out_duration(staff_id, duration) → None

    Public API — Schedule
    ---------------------
    get_staff_schedule(staff_id)                  → list[dict]
    add_shift(staff_id, day, time, note, tag)     → int
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._safe_dsn = _redact(dsn)
        self._pool = self._make_pool()
        self._ensure_schema()

    # ── Pool ──────────────────────────────────────────────────────────────────

    def _make_pool(self) -> psycopg2.pool.ThreadedConnectionPool:
        try:
            pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=5, dsn=self._dsn,
            )
            log.info("StaffDB pool created → %s", self._safe_dsn)
            return pool
        except psycopg2.OperationalError as exc:
            log.error("Could not connect to PostgreSQL: %s", exc)
            raise ConnectionError(
                f"Cannot connect to the database.\n\n"
                f"Connection: {self._safe_dsn}\n\n"
                f"Check that:\n"
                f"  • PostgreSQL is running\n"
                f"  • Credentials in pawffinated.env are correct\n"
                f"  • Firewall allows port 5432\n\n"
                f"Original error: {exc}"
            ) from exc

    def _conn(self):
        return _PooledConnection(self._pool)

    # ── Schema ────────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_STAFF)
                cur.execute(_CREATE_CLOCK_EVENTS)
                cur.execute(_CREATE_SHIFTS)
                cur.execute("SELECT COUNT(*) FROM staff")
                count = cur.fetchone()[0]
            conn.commit()

        if count == 0:
            log.info("Empty staff table — inserting demo staff.")
            self._seed_staff()

    def _seed_staff(self) -> None:
        """Insert default demo staff member."""
        demo_staff = {
            "name": "John Doe",
            "email": "john@pawffinated.local",
            "phone": "+63-999-123-4567",
            "role": "Staff",
            "avatar": "👤",
            "device": "Mobile",
            "started_on": str(date.today() - timedelta(days=30)),
            "schedule": "9:00 AM – 5:30 PM",
            "shift_hrs": "8.5h",
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staff
                        (name, email, phone, role, avatar, device, started_on, schedule, shift_hrs)
                    VALUES
                        (%(name)s, %(email)s, %(phone)s, %(role)s, %(avatar)s,
                         %(device)s, %(started_on)s, %(schedule)s, %(shift_hrs)s)
                    """,
                    demo_staff,
                )
            conn.commit()
        log.info("Seeded demo staff member.")

    # ─────────────────────────────────────────────────────────────────────────
    # Staff — CRUD
    # ─────────────────────────────────────────────────────────────────────────

    def get_staff(self, staff_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, name, email, phone, role, avatar, device, started_on,
                           schedule, shift_hrs, role_desc, role_detail,
                           this_week, week_sub, last_month, month_sub,
                           hours_worked, hours_sub, attendance, att_sub,
                           avg_shift, avg_sub, punctuality_on, punctuality_late,
                           punctuality_rating, completed, adjusted, completed_rating,
                           mgr_note1, mgr_note2, mgr_note3, created_at, updated_at
                    FROM staff WHERE id = %s
                    """,
                    (staff_id,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_all_staff(self) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, email, phone, role, device FROM staff ORDER BY id")
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def insert_staff(self, staff: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staff
                        (name, email, phone, role, avatar, device, started_on)
                    VALUES
                        (%(name)s, %(email)s, %(phone)s, %(role)s, %(avatar)s, %(device)s, %(started_on)s)
                    RETURNING id
                    """,
                    {
                        "name":       staff.get("name", ""),
                        "email":      staff.get("email"),
                        "phone":      staff.get("phone"),
                        "role":       staff.get("role", "Staff"),
                        "avatar":     staff.get("avatar", "👤"),
                        "device":     staff.get("device", "Mobile"),
                        "started_on": staff.get("started_on", str(date.today())),
                    },
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        log.debug("INSERT staff id=%s  name=%s", new_id, staff.get("name"))
        return new_id

    def update_staff(self, staff: dict) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staff
                       SET name = %(name)s,
                           email = %(email)s,
                           phone = %(phone)s,
                           role = %(role)s,
                           device = %(device)s,
                           updated_at = NOW()
                     WHERE id = %(id)s
                    """,
                    {
                        "id":    staff["id"],
                        "name":  staff.get("name", ""),
                        "email": staff.get("email"),
                        "phone": staff.get("phone"),
                        "role":  staff.get("role", "Staff"),
                        "device": staff.get("device", "Mobile"),
                    },
                )
            conn.commit()
        log.debug("UPDATE staff id=%s", staff.get("id"))

    # ─────────────────────────────────────────────────────────────────────────
    # Clock Events
    # ─────────────────────────────────────────────────────────────────────────

    def add_clock_event(self, staff_id: int, event_type: str, device: str, duration: str = None) -> None:
        """
        Insert a clock event (Clock In or Clock Out).

        Args:
            staff_id: Staff member ID
            event_type: "Clock In" or "Clock Out"
            device: Device name (e.g., "Mobile", "Front desk device")
            duration: Optional duration string (e.g., "2h 30m") — typically for Clock Out
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO clock_events
                        (staff_id, event_type, device, duration, timestamp)
                    VALUES
                        (%s, %s, %s, %s, NOW() AT TIME ZONE %s)
                    """,
                    (staff_id, event_type, device, duration, _TZ),
                )
            conn.commit()
        log.debug("INSERT clock_event staff_id=%s  event=%s",
                  staff_id, event_type)

    def get_clock_log(self, staff_id: int) -> list[dict]:
        """Retrieve all clock events for a staff member (most recent first)."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, staff_id, event_type, timestamp, device, duration, created_at
                    FROM clock_events
                    WHERE staff_id = %s
                    ORDER BY timestamp DESC
                    """,
                    (staff_id,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_last_clock_event(self, staff_id: int) -> dict | None:
        """Get the most recent clock event for a staff member."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, staff_id, event_type, timestamp, device, duration, created_at
                    FROM clock_events
                    WHERE staff_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (staff_id,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def update_clock_out_duration(self, staff_id: int, duration: str) -> None:
        """
        Update the duration of the most recent Clock In event.
        This is called when the user clicks Clock Out.
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE clock_events
                       SET duration = %s
                     WHERE staff_id = %s
                       AND event_type = 'Clock In'
                       AND id = (
                           SELECT id FROM clock_events
                           WHERE staff_id = %s AND event_type = 'Clock In'
                           ORDER BY timestamp DESC LIMIT 1
                       )
                    """,
                    (duration, staff_id, staff_id),
                )
            conn.commit()
        log.debug("UPDATE clock_out_duration staff_id=%s  duration=%s",
                  staff_id, duration)

    # ─────────────────────────────────────────────────────────────────────────
    # Schedule / Shifts
    # ─────────────────────────────────────────────────────────────────────────

    def get_staff_schedule(self, staff_id: int) -> list[dict]:
        """Retrieve scheduled shifts for a staff member."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, staff_id, day, time, note, tag, created_at
                    FROM shifts
                    WHERE staff_id = %s
                    ORDER BY id
                    """,
                    (staff_id,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def add_shift(self, staff_id: int, day: str, time: str, note: str = None, tag: str = "Scheduled") -> int:
        """Add a shift to the staff member's schedule."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shifts
                        (staff_id, day, time, note, tag)
                    VALUES
                        (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (staff_id, day, time, note, tag),
                )
                shift_id = cur.fetchone()[0]
            conn.commit()
        log.debug("INSERT shift id=%s  staff_id=%s  day=%s",
                  shift_id, staff_id, day)
        return shift_id

    def close(self) -> None:
        self._pool.closeall()
        log.info("StaffDB connection pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

class _PooledConnection:
    def __init__(self, pool: psycopg2.pool.ThreadedConnectionPool) -> None:
        self._pool = pool
        self._conn = None

    def __enter__(self):
        self._conn = self._pool.getconn()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            try:
                self._conn.rollback()
            except Exception:
                pass
            log.error("DB error — rolled back: %s", exc_val)
        self._pool.putconn(self._conn)
        return False


def _params(item: dict) -> dict:
    """Normalise a product dict → safe DB params including image_path."""
    return {
        "name":        str(item.get("name", "")),
        "sku":         str(item.get("sku", "")),
        "category":    str(item.get("category", "Other")),
        "stock":       int(item.get("stock", 0)),
        "unit":        str(item.get("unit", "units")),
        "price":       float(item.get("price", 0.0)),
        "description": str(item.get("description", "")),
        "image_path":  item.get("image_path") or None,
    }


def _normalise(row: dict) -> dict:
    """Cast NUMERIC columns → float, integer columns → int."""
    for key in ("price", "unit_price", "subtotal", "total_amount",
                "discount_amount", "gross_revenue", "ingredient_cost",
                "profit_per_item", "total_profit", "revenue", "avg_ticket"):
        if key in row and row[key] is not None:
            row[key] = float(row[key])
    for key in ("unit_sales", "units_sold", "quantity", "total_orders",
                "dine_in_qty", "takeout_qty", "delivery_qty",
                "discounted_orders"):
        if key in row and row[key] is not None:
            row[key] = int(row[key])
    return row


# ─────────────────────────────────────────────────────────────────────────────
# AuthDB  — users table (login / register / admin check)
# ─────────────────────────────────────────────────────────────────────────────

class AuthDB:
    """
    Manages the `users` table used for Login and Registration.

    Public API
    ----------
    authenticate(email, password) → dict | None
        Returns the user row (without password) if credentials match, else None.

    register(first, last, email, password, role, station) → int
        Inserts a new user and returns their id.
        Raises ValueError if the email already exists.

    email_exists(email) → bool
        Returns True if a user with that email is already registered.

    is_admin(email) → bool
        Returns True if the user's is_admin flag is set.

    get_all_users() → list[dict]
        Returns all user rows (no passwords).
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._safe_dsn = _redact(dsn)
        self._pool = self._make_pool()
        self._ensure_schema()

    def _make_pool(self) -> psycopg2.pool.ThreadedConnectionPool:
        try:
            pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=5, dsn=self._dsn,
            )
            log.info("AuthDB pool created → %s", self._safe_dsn)
            return pool
        except psycopg2.OperationalError as exc:
            log.error("AuthDB could not connect: %s", exc)
            raise ConnectionError(
                f"Cannot connect to the database.\n\nConnection: {self._safe_dsn}\n\n"
                f"Original error: {exc}"
            ) from exc

    def _conn(self):
        return _PooledConnection(self._pool)

    def _ensure_schema(self) -> None:
        """Create the users table if it doesn't exist, then seed admin if empty."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_USERS)
                cur.execute("SELECT COUNT(*) FROM users")
                count = cur.fetchone()[0]
            conn.commit()
        if count == 0:
            log.info("users table is empty — seeding default admin account.")
            self._seed_admin()

    def _seed_admin(self) -> None:
        a = _SEED_ADMIN
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users
                        (first_name, last_name, email, password, role, station, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    """,
                    (a["first_name"], a["last_name"], a["email"],
                     a["password"], a["role"], a["station"], a["is_admin"]),
                )
            conn.commit()

    # ── Public API ────────────────────────────────────────────────────────────

    def authenticate(self, email: str, password: str) -> dict | None:
        """
        Return user dict (no password field) if credentials are correct, else None.
        Comparison is case-insensitive on email.
        """
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, first_name, last_name, email, role, station, is_admin
                    FROM users
                    WHERE LOWER(email) = LOWER(%s) AND password = %s
                    """,
                    (email.strip(), password),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def email_exists(self, email: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM users WHERE LOWER(email) = LOWER(%s)",
                    (email.strip(),),
                )
                return cur.fetchone() is not None

    def register(
        self,
        first_name: str,
        last_name:  str,
        email:      str,
        password:   str,
        role:       str,
        station:    str,
    ) -> int:
        """
        Insert a new non-admin user.
        Raises ValueError if the email is already registered.
        Returns the new user's id.
        """
        if self.email_exists(email):
            raise ValueError(f"Email '{email}' is already registered.")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users
                        (first_name, last_name, email, password, role, station, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s, FALSE)
                    RETURNING id
                    """,
                    (first_name.strip(), last_name.strip(), email.strip().lower(),
                     password, role, station),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        log.info("Registered new user id=%s  email=%s  role=%s", new_id, email, role)
        return new_id

    def is_admin(self, email: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT is_admin FROM users WHERE LOWER(email) = LOWER(%s)",
                    (email.strip(),),
                )
                row = cur.fetchone()
        return bool(row[0]) if row else False

    def get_all_users(self) -> list[dict]:
        """Return all users without the password column."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, first_name, last_name, email,
                           role, station, is_admin, created_at
                    FROM users
                    ORDER BY id
                    """
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._pool.closeall()
        log.info("AuthDB connection pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singletons
# ─────────────────────────────────────────────────────────────────────────────

_instance_inv:   InventoryDB | None = None
_instance_staff: StaffDB     | None = None
_instance_auth:  AuthDB      | None = None


def get_db(dsn: str | None = None) -> InventoryDB:
    """Get or create the InventoryDB singleton."""
    global _instance_inv
    if _instance_inv is None:
        resolved_dsn = dsn or _build_dsn()
        _instance_inv = InventoryDB(resolved_dsn)
    return _instance_inv


def get_staff_db(dsn: str | None = None) -> StaffDB:
    """Get or create the StaffDB singleton."""
    global _instance_staff
    if _instance_staff is None:
        resolved_dsn = dsn or _build_dsn()
        _instance_staff = StaffDB(resolved_dsn)
    return _instance_staff


def get_auth_db(dsn: str | None = None) -> AuthDB:
    """Get or create the AuthDB singleton (users table)."""
    global _instance_auth
    if _instance_auth is None:
        resolved_dsn = dsn or _build_dsn()
        _instance_auth = AuthDB(resolved_dsn)
    return _instance_auth


def close_db() -> None:
    """Close all database connections."""
    global _instance_inv, _instance_staff, _instance_auth
    if _instance_inv is not None:
        _instance_inv.close()
        _instance_inv = None
    if _instance_staff is not None:
        _instance_staff.close()
        _instance_staff = None
    if _instance_auth is not None:
        _instance_auth.close()
        _instance_auth = None


def db_info() -> str:
    """Return database connection info string."""
    _load_env_file()
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return f"PostgreSQL  {_redact(url)}"
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "pawffinated")
    user = os.environ.get("DB_USER", "postgres")
    return f"PostgreSQL  {user}@{host}:{port}/{name}"