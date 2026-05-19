"""
db_connection.py – Pawffinated PostgreSQL Connection Manager
=============================================================
CHANGES:
    • products table now has an `image_path` TEXT column (nullable).
      Existing rows get NULL; the column is added automatically via ALTER TABLE
      if the DB was created before this version.
    • All product CRUD methods (fetch_all, fetch_by_id, insert, update,
      bulk_replace, _seed) now include image_path.
    • _params() and _normalise() updated accordingly.
    • All sales query methods now accept date_from / date_to (str 'YYYY-MM-DD')
      instead of a rolling `days` integer — queries are now accurate to the day.
    • get_sales_log() extended with per-product order-type breakdown
      (dine_in_qty, takeout_qty, delivery_qty) and discount info
      (discounted_orders, discount_types).
    • Previous-period comparison in get_sales_summary() is now symmetric —
      it mirrors the same number of days immediately before date_from.
    • Backward-compat `days` fallback kept on all methods.
"""

from __future__ import annotations

import os
import re
import logging
from datetime import date, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.pool

log = logging.getLogger("pawffinated.db")

_HERE     = Path(__file__).resolve().parent
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
    today  = date.today()
    d_to   = today
    d_from = today - timedelta(days=days - 1)
    return d_from.isoformat(), d_to.isoformat()


def _prev_period(date_from: str, date_to: str) -> tuple[str, str]:
    """Return the immediately preceding period of the same length."""
    d_from = date.fromisoformat(date_from)
    d_to   = date.fromisoformat(date_to)
    n_days = (d_to - d_from).days + 1
    prev_to   = d_from - timedelta(days=1)
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
        key   = key.strip()
        value = value.split("#", 1)[0].strip().strip("'\"")
        os.environ.setdefault(key, value)


def _build_dsn() -> str:
    _load_env_file()
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        log.info("Connecting via DATABASE_URL → %s", _redact(url))
        return url
    host   = os.environ.get("DB_HOST", "localhost")
    port   = os.environ.get("DB_PORT", "5432")
    name   = os.environ.get("DB_NAME", "pawffinated")
    user   = os.environ.get("DB_USER", "postgres")
    passwd = os.environ.get("DB_PASS", "")
    dsn    = f"postgresql://{user}:{passwd}@{host}:{port}/{name}"
    log.info("Connecting via config keys → %s", _redact(dsn))
    return dsn


def _redact(dsn: str) -> str:
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", dsn)


# ─────────────────────────────────────────────────────────────────────────────
# InventoryDB
# ─────────────────────────────────────────────────────────────────────────────

class InventoryDB:
    """
    PostgreSQL persistence layer for Pawffinated.

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
        self._dsn      = dsn
        self._safe_dsn = _redact(dsn)
        self._pool     = self._make_pool()
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
        log.debug("INSERT order id=%s  number=%s", new_id, order.get("order_number"))
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
                gross_sales      = float(row[0])
                total_orders     = int(row[1])
                total_discounts  = float(row[2])
                pwd_senior_count = int(row[3])
                dine_in_count    = int(row[4])
                takeout_count    = int(row[5])
                delivery_count   = int(row[6])

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
        change = ((gross_sales - prev_sales) / prev_sales * 100) if prev_sales > 0 else 0.0

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
        result  = {"Dine In": 0, "Takeout": 0, "Delivery": 0}
        revenue = {"Dine In": 0.0, "Takeout": 0.0, "Delivery": 0.0}
        for ot, cnt, rev in rows:
            if ot in result:
                result[ot]  = int(cnt)
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
        # image_path is stored as an absolute filesystem path or NULL
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
    # image_path stays as str | None — no cast needed
    return row


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────

_instance: InventoryDB | None = None


def get_db(dsn: str | None = None) -> InventoryDB:
    global _instance
    if _instance is None:
        resolved_dsn = dsn or _build_dsn()
        _instance = InventoryDB(resolved_dsn)
    return _instance


def close_db() -> None:
    global _instance
    if _instance is not None:
        _instance.close()
        _instance = None


def db_info() -> str:
    _load_env_file()
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return f"PostgreSQL  {_redact(url)}"
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "pawffinated")
    user = os.environ.get("DB_USER", "postgres")
    return f"PostgreSQL  {user}@{host}:{port}/{name}"
