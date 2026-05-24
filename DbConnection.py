"""
PAWFFINATED – PostgreSQL Connection Manager  (v2 — Built-in Activity Logging)
==============================================================================
CHANGES in this version:
  • activity_log table added to schema — created automatically on startup.
  • _write_log() shared helper writes to activity_log from any DB class.
  • _log() convenience method on every DB class calls _write_log() with the
    current session user (read from PAWFF_USER_NAME env var set by Login.py).
  • Logging is now AUTOMATIC inside:
      InventoryDB : insert, update, delete, bulk_replace, insert_order
                    + low-stock / out-of-stock alerts after every stock change
      MenuDB      : insert_menu_item, update_menu_item, delete_menu_item
      AuthDB      : authenticate (login + failed login), register, delete_user,
                    update_user, set_admin, update_password,
                    add_user_shift, delete_shift, update_shift
                    + log_access_decision() for AccessControl approve/reject
                    + log_logout() for AccountManagement logout button
      StaffDB     : add_clock_event (Clock In / Clock Out)
  • No other module needs to import anything extra — drop this file in and
    every action is logged automatically.
  • All original public methods and signatures are preserved exactly.
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

_HERE     = Path(__file__).resolve().parent
_ENV_FILE = _HERE / "pawffinated.env"

_SEED_ROWS: list[dict] = []
_TZ = "Asia/Manila"


# ─────────────────────────────────────────────────────────────────────────────
# Schema DDL
# ─────────────────────────────────────────────────────────────────────────────

_RENAME_TABLES = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='products')
    AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='product')
    THEN ALTER TABLE products RENAME TO product; END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='orders')
    AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='sale')
    THEN ALTER TABLE orders RENAME TO sale; END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='order_items')
    AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='sale_item')
    THEN ALTER TABLE order_items RENAME TO sale_item; END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='staff')
    AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='staff_member')
    THEN ALTER TABLE staff RENAME TO staff_member; END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='clock_events')
    AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='clock_event')
    THEN ALTER TABLE clock_events RENAME TO clock_event; END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='shifts')
    AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='shift')
    THEN ALTER TABLE shifts RENAME TO shift; END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='users')
    AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='user_account')
    THEN ALTER TABLE users RENAME TO user_account; END IF;
END$$;
"""

# ── Activity Log ──────────────────────────────────────────────────────────────
_CREATE_ACTIVITY_LOG = """
CREATE TABLE IF NOT EXISTS activity_log (
    id            SERIAL       PRIMARY KEY,
    activity_type TEXT         NOT NULL DEFAULT 'general',
    activity      TEXT         NOT NULL DEFAULT '',
    detail        TEXT                  DEFAULT '',
    staff         TEXT                  DEFAULT '',
    station       TEXT                  DEFAULT '',
    status        TEXT                  DEFAULT 'Completed',
    flagged       BOOLEAN      NOT NULL DEFAULT FALSE,
    recorded_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
"""

# ── Core POS / Inventory ──────────────────────────────────────────────────────
_CREATE_PRODUCT = """
CREATE TABLE IF NOT EXISTS product (
    id          SERIAL          PRIMARY KEY,
    name        TEXT            NOT NULL,
    sku         TEXT            NOT NULL DEFAULT '',
    category    TEXT            NOT NULL DEFAULT 'Other',
    stock       NUMERIC(10, 4)  NOT NULL DEFAULT 0,
    unit        TEXT            NOT NULL DEFAULT 'units',
    price       NUMERIC(10, 2)  NOT NULL DEFAULT 0.00,
    description TEXT                     DEFAULT '',
    image_path  TEXT                     DEFAULT NULL
);
"""

_CREATE_SALE = """
CREATE TABLE IF NOT EXISTS sale (
    id              SERIAL         PRIMARY KEY,
    order_number    INTEGER        NOT NULL,
    order_type      TEXT           NOT NULL DEFAULT 'Dine In',
    customer_name   TEXT           NOT NULL DEFAULT 'Walk-in Customer',
    subtotal        NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    discount_type   TEXT                    DEFAULT 'None',
    discount_amount NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
    total_amount    NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
"""

_CREATE_SALE_ITEM = """
CREATE TABLE IF NOT EXISTS sale_item (
    id          SERIAL         PRIMARY KEY,
    order_id    INTEGER        NOT NULL REFERENCES sale(id) ON DELETE CASCADE,
    product_id  INTEGER        REFERENCES product(id) ON DELETE SET NULL,
    name        TEXT           NOT NULL,
    category    TEXT           NOT NULL DEFAULT 'Other',
    sku         TEXT           NOT NULL DEFAULT '',
    unit_price  NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    quantity    INTEGER        NOT NULL DEFAULT 1,
    subtotal    NUMERIC(10, 2) NOT NULL DEFAULT 0.00
);
"""

# ── Staff ─────────────────────────────────────────────────────────────────────
_CREATE_STAFF_MEMBER = """
CREATE TABLE IF NOT EXISTS staff_member (
    id               SERIAL         PRIMARY KEY,
    name             TEXT           NOT NULL,
    email            TEXT           UNIQUE,
    phone            TEXT,
    role             TEXT           NOT NULL DEFAULT 'Staff',
    avatar           TEXT,
    device           TEXT           DEFAULT 'Mobile',
    started_on       DATE,
    schedule         TEXT           DEFAULT '9:00 AM – 5:30 PM',
    shift_hrs        TEXT           DEFAULT '8.5h',
    role_desc        TEXT           DEFAULT 'Team Member',
    role_detail      TEXT           DEFAULT 'Retail Operations',
    this_week        TEXT           DEFAULT '5 shifts',
    week_sub         TEXT           DEFAULT 'On track',
    last_month       TEXT           DEFAULT '160h',
    month_sub        TEXT           DEFAULT 'Completed',
    hours_worked     TEXT           DEFAULT '0h',
    hours_sub        TEXT           DEFAULT 'This month',
    attendance       TEXT           DEFAULT '100%',
    att_sub          TEXT           DEFAULT 'No absences',
    avg_shift        TEXT           DEFAULT '8.5h',
    avg_sub          TEXT           DEFAULT 'Per shift',
    punctuality_on   TEXT           DEFAULT '20/20',
    punctuality_late TEXT           DEFAULT '0/20',
    punctuality_rating TEXT         DEFAULT 'Excellent',
    completed        TEXT           DEFAULT '20/20',
    adjusted         TEXT           DEFAULT '0/20',
    completed_rating TEXT           DEFAULT 'Excellent',
    mgr_note1        TEXT           DEFAULT 'Reliable',
    mgr_note2        TEXT           DEFAULT 'Punctual',
    mgr_note3        TEXT           DEFAULT 'Professional',
    created_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
"""

_CREATE_CLOCK_EVENT = """
CREATE TABLE IF NOT EXISTS clock_event (
    id          SERIAL      PRIMARY KEY,
    staff_id    INTEGER     NOT NULL REFERENCES staff_member(id) ON DELETE CASCADE,
    user_id     INTEGER     REFERENCES user_account(id) ON DELETE SET NULL,
    event_type  TEXT        NOT NULL CHECK (event_type IN ('Clock In', 'Clock Out')),
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    device      TEXT        DEFAULT 'Mobile',
    duration    TEXT        DEFAULT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_MIGRATE_CLOCK_EVENT = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'clock_event' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE clock_event
            ADD COLUMN user_id INTEGER REFERENCES user_account(id) ON DELETE SET NULL;
    END IF;
END$$;
"""

_CREATE_SHIFT = """
CREATE TABLE IF NOT EXISTS shift (
    id          SERIAL      PRIMARY KEY,
    staff_id    INTEGER     NOT NULL REFERENCES staff_member(id) ON DELETE CASCADE,
    day         TEXT        NOT NULL,
    time        TEXT        NOT NULL,
    note        TEXT,
    tag         TEXT        DEFAULT 'Scheduled',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# ── User Accounts ─────────────────────────────────────────────────────────────
_CREATE_USER_ACCOUNT = """
CREATE TABLE IF NOT EXISTS user_account (
    id          SERIAL      PRIMARY KEY,
    first_name  TEXT        NOT NULL,
    last_name   TEXT        NOT NULL,
    email       TEXT        NOT NULL UNIQUE,
    password    TEXT        NOT NULL,
    role        TEXT        NOT NULL DEFAULT 'Barista',
    station     TEXT        NOT NULL DEFAULT 'Front Counter',
    is_admin    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# ── Menu ──────────────────────────────────────────────────────────────────────
_CREATE_MENU_ITEMS = """
CREATE TABLE IF NOT EXISTS menu_items (
    id          SERIAL         PRIMARY KEY,
    name        TEXT           NOT NULL,
    category    TEXT           NOT NULL DEFAULT 'Other',
    price       NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    description TEXT                    DEFAULT '',
    image_path  TEXT                    DEFAULT NULL,
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);
"""

_CREATE_MENU_INGREDIENTS = """
CREATE TABLE IF NOT EXISTS menu_ingredients (
    id              SERIAL         PRIMARY KEY,
    menu_item_id    INTEGER        NOT NULL
                        REFERENCES menu_items(id) ON DELETE CASCADE,
    ingredient_name TEXT           NOT NULL,
    quantity        NUMERIC(10, 4) NOT NULL DEFAULT 1,
    unit            TEXT           NOT NULL DEFAULT 'units'
);
"""

_SEED_ADMIN = {
    "first_name": "Admin",
    "last_name":  "User",
    "email":      "admin@pawffinated.com",
    "password":   "admin123",
    "role":       "Administrator",
    "station":    "Back Office",
    "is_admin":   True,
}


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_dates(date_from, date_to, days=1):
    if date_from and date_to:
        return date_from, date_to
    today = date.today()
    return (today - timedelta(days=days - 1)).isoformat(), today.isoformat()


def _prev_period(date_from, date_to):
    d_from = date.fromisoformat(date_from)
    d_to   = date.fromisoformat(date_to)
    n_days = (d_to - d_from).days + 1
    prev_to   = d_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=n_days - 1)
    return prev_from.isoformat(), prev_to.isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Config / DSN
# ─────────────────────────────────────────────────────────────────────────────

def _load_env_file(path: Path = _ENV_FILE) -> None:
    if not path.exists():
        return
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
        return url
    host   = os.environ.get("DB_HOST", "localhost")
    port   = os.environ.get("DB_PORT", "5432")
    name   = os.environ.get("DB_NAME", "pawffinated")
    user   = os.environ.get("DB_USER", "postgres")
    passwd = os.environ.get("DB_PASS", "")
    return f"postgresql://{user}:{passwd}@{host}:{port}/{name}"


def _redact(dsn: str) -> str:
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", dsn)


# ─────────────────────────────────────────────────────────────────────────────
# Pooled connection context manager
# ─────────────────────────────────────────────────────────────────────────────

class _PooledConnection:
    def __init__(self, pool):
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


def _make_pool(dsn: str, label: str):
    try:
        pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=5, dsn=dsn)
        log.info("%s pool created → %s", label, _redact(dsn))
        return pool
    except psycopg2.OperationalError as exc:
        raise ConnectionError(
            f"Cannot connect to the database.\n\n"
            f"Connection: {_redact(dsn)}\n\nOriginal error: {exc}"
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Shared activity-log writer  (used by every DB class internally)
# ─────────────────────────────────────────────────────────────────────────────

def _write_log(
    pool,
    activity_type: str,
    activity: str,
    detail: str = "",
    staff: str = "",
    station: str = "",
    status: str = "Completed",
    flagged: bool = False,
) -> None:
    """
    Write one row to activity_log.  Failures are silently swallowed so that
    a logging hiccup never breaks normal POS / inventory operations.
    """
    try:
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO activity_log
                        (activity_type, activity, detail, staff,
                         station, status, flagged, recorded_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s,
                            NOW() AT TIME ZONE %s)
                    """,
                    (activity_type, activity, detail, staff,
                     station, status, flagged, _TZ),
                )
            conn.commit()
        finally:
            pool.putconn(conn)
    except Exception as exc:
        log.debug("activity_log write skipped: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Session helpers  (reads env vars set by Login.py at login time)
# ─────────────────────────────────────────────────────────────────────────────

def _session_staff() -> str:
    """Full name of the currently logged-in user, or 'System'."""
    return os.environ.get("PAWFF_USER_NAME", "").strip() or "System"


def _session_station() -> str:
    """Role of the current user used as the station label."""
    return os.environ.get("PAWFF_USER_ROLE", "").strip() or "System"


# ─────────────────────────────────────────────────────────────────────────────
# Column normalisers
# ─────────────────────────────────────────────────────────────────────────────

def _params(item: dict) -> dict:
    return {
        "name":        str(item.get("name", "")),
        "sku":         str(item.get("sku", "")),
        "category":    str(item.get("category", "Other")),
        "stock":       float(item.get("stock", 0)),
        "unit":        str(item.get("unit", "units")),
        "price":       float(item.get("price", 0.0)),
        "description": str(item.get("description", "")),
        "image_path":  item.get("image_path") or None,
    }


def _normalise(row: dict) -> dict:
    for key in (
        "price", "unit_price", "subtotal", "total_amount",
        "discount_amount", "gross_revenue", "ingredient_cost",
        "profit_per_item", "total_profit", "revenue", "avg_ticket", "stock",
    ):
        if key in row and row[key] is not None:
            row[key] = float(row[key])
    for key in (
        "unit_sales", "units_sold", "quantity", "total_orders",
        "dine_in_qty", "takeout_qty", "delivery_qty", "discounted_orders",
    ):
        if key in row and row[key] is not None:
            row[key] = int(row[key])
    return row


# ─────────────────────────────────────────────────────────────────────────────
# InventoryDB
# ─────────────────────────────────────────────────────────────────────────────

class InventoryDB:
    """
    PostgreSQL persistence for Products, POS orders, and Sales analytics.
    Activity logging is built-in — every write method logs to activity_log.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn  = dsn
        self._pool = _make_pool(dsn, "InventoryDB")
        self._ensure_schema()

    def _conn(self):
        return _PooledConnection(self._pool)

    def _log(self, activity_type, activity, detail="",
             status="Completed", flagged=False):
        """Log an event using the current session's staff name."""
        _write_log(self._pool, activity_type, activity, detail,
                   staff=_session_staff(), station=_session_station(),
                   status=status, flagged=flagged)

    # ── Schema ────────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_RENAME_TABLES)
                cur.execute(_CREATE_ACTIVITY_LOG)   # ← new
                cur.execute(_CREATE_PRODUCT)
                cur.execute(_CREATE_SALE)
                cur.execute(_CREATE_SALE_ITEM)
                cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='sale' AND column_name='discount_type'
                        ) THEN
                            ALTER TABLE sale ADD COLUMN discount_type TEXT DEFAULT 'None';
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='sale' AND column_name='discount_amount'
                        ) THEN
                            ALTER TABLE sale ADD COLUMN discount_amount NUMERIC(10,2) DEFAULT 0.00;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='product' AND column_name='image_path'
                        ) THEN
                            ALTER TABLE product ADD COLUMN image_path TEXT DEFAULT NULL;
                        END IF;
                    END$$;
                """)
                cur.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'product'
                              AND column_name = 'stock'
                              AND data_type = 'integer'
                        ) THEN
                            ALTER TABLE product
                                ALTER COLUMN stock TYPE NUMERIC(10, 4)
                                USING stock::NUMERIC(10, 4);
                        END IF;
                    END$$;
                """)
                cur.execute("SELECT COUNT(*) FROM product")
                count = cur.fetchone()[0]
            conn.commit()
        if count == 0:
            log.info("Empty products table — inserting seed data.")
            self._seed()

    def _seed(self) -> None:
        if not _SEED_ROWS:
            return
        with self._conn() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    """INSERT INTO product
                        (name, sku, category, stock, unit, price, description, image_path)
                       VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s, %(image_path)s)""",
                    _SEED_ROWS, page_size=100,
                )
            conn.commit()

    # ── Products CRUD ─────────────────────────────────────────────────────────

    def fetch_all(self) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, sku, category, stock, unit, price, "
                    "description, image_path FROM product ORDER BY id"
                )
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    def fetch_by_id(self, item_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, sku, category, stock, unit, price, "
                    "description, image_path FROM product WHERE id = %s",
                    (item_id,),
                )
                row = cur.fetchone()
        return _normalise(dict(row)) if row else None

    def insert(self, item: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO product
                        (name, sku, category, stock, unit, price, description, image_path)
                       VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s, %(image_path)s)
                       RETURNING id""",
                    _params(item),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        log.debug("INSERT product id=%s  name=%s", new_id, item.get("name"))

        # ── Log: inventory added ──────────────────────────────────────────────
        stock = float(item.get("stock", 0))
        self._log(
            "inventory",
            f"Inventory added — {item.get('name', '')}",
            f"Added with stock: {stock:g} {item.get('unit', 'units')} · "
            f"Category: {item.get('category', 'Other')} · "
            f"Price: ₱{float(item.get('price', 0)):.2f}",
            status="Added",
        )
        # Immediately flag if low / out of stock
        self._stock_alert(item.get("name", ""), stock, item.get("unit", "units"))
        return new_id

    def update(self, item: dict) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE product
                       SET name=%(name)s, sku=%(sku)s, category=%(category)s,
                           stock=%(stock)s, unit=%(unit)s, price=%(price)s,
                           description=%(description)s, image_path=%(image_path)s
                       WHERE id=%(id)s""",
                    {**_params(item), "id": item["id"]},
                )
            conn.commit()
        log.debug("UPDATE product id=%s", item.get("id"))

        # ── Log: inventory updated ────────────────────────────────────────────
        stock = float(item.get("stock", 0))
        self._log(
            "inventory",
            f"Inventory updated — {item.get('name', '')}",
            f"Stock: {stock:g} {item.get('unit', 'units')} · "
            f"Price: ₱{float(item.get('price', 0)):.2f} · "
            f"Category: {item.get('category', 'Other')}",
            status="Updated",
        )
        self._stock_alert(item.get("name", ""), stock, item.get("unit", "units"))

    def delete(self, item_id: int) -> None:
        # Capture name before deletion so we can log it
        item = self.fetch_by_id(item_id)
        name = item["name"] if item else f"ID {item_id}"

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM product WHERE id = %s", (item_id,))
            conn.commit()
        log.debug("DELETE product id=%s", item_id)

        # ── Log: inventory deleted ────────────────────────────────────────────
        self._log(
            "inventory",
            f"Inventory deleted — {name}",
            f"Item removed from inventory by {_session_staff()}",
            status="Deleted",
            flagged=True,
        )

    def _stock_alert(self, name: str, stock: float, unit: str) -> None:
        """Emit a low-stock or out-of-stock log entry when stock is critical."""
        if stock <= 0:
            self._log(
                "inventory",
                f"Out of stock — {name}",
                f"{name} has reached 0 {unit} — restock required immediately",
                status="Out of Stock",
                flagged=True,
            )
        elif stock <= 10:
            self._log(
                "inventory",
                f"Low stock alert — {name}",
                f"{name} is running low: only {stock:g} {unit} remaining",
                status="Low Stock",
                flagged=True,
            )

    def bulk_replace(self, items: list[dict]) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM product")
                psycopg2.extras.execute_batch(
                    cur,
                    """INSERT INTO product
                        (name, sku, category, stock, unit, price, description, image_path)
                       VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s, %(image_path)s)""",
                    [_params(i) for i in items], page_size=100,
                )
            conn.commit()
        log.info("bulk_replace: inserted %d rows", len(items))

        self._log(
            "inventory",
            f"Inventory bulk import — {len(items)} items",
            f"All inventory replaced via import — {len(items)} items loaded",
            status="Updated",
        )
        return len(items)

    def execute_query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    # ── Dashboard helpers ─────────────────────────────────────────────────────

    def get_low_stock_count(self) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM product WHERE stock > 0 AND stock <= 10")
                return cur.fetchone()[0]

    def get_out_of_stock_count(self) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM product WHERE stock = 0")
                return cur.fetchone()[0]

    def get_total_inventory_value(self) -> float:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(SUM(stock * price), 0) FROM product")
                return float(cur.fetchone()[0])

    def get_alerts(self, low_stock_threshold: int = 10) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT name, category, stock FROM product "
                    "WHERE stock <= %s ORDER BY stock ASC",
                    (low_stock_threshold,)
                )
                rows = cur.fetchall()
        alerts = []
        for r in rows:
            s = float(r["stock"])
            if s == 0:
                alerts.append({"name": r["name"], "category": r["category"],
                                "stock": s, "label": "Out of stock", "severity": "danger"})
            else:
                alerts.append({"name": r["name"], "category": r["category"],
                                "stock": s, "label": f"{s:.4g} left", "severity": "warn"})
        return alerts

    # ── POS writes ────────────────────────────────────────────────────────────

    def insert_order(self, order: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sale
                        (order_number, order_type, customer_name,
                         subtotal, discount_type, discount_amount, total_amount)
                       VALUES
                        (%(order_number)s, %(order_type)s, %(customer_name)s,
                         %(subtotal)s, %(discount_type)s, %(discount_amount)s,
                         %(total_amount)s)
                       RETURNING id""",
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

        # ── Log: POS order ────────────────────────────────────────────────────
        disc_type = order.get("discount_type", "None")
        disc_amt  = float(order.get("discount_amount", 0.0))
        flagged   = disc_type not in ("None", "") and disc_amt > 0
        disc_str  = f" · {disc_type} −₱{disc_amt:.2f}" if flagged else ""
        self._log(
            "order",
            f"Order #{order['order_number']} — {order['order_type']}",
            f"Customer: {order['customer_name']} · "
            f"Total: ₱{float(order['total_amount']):.2f}{disc_str}",
            status="Review" if flagged else "Completed",
            flagged=flagged,
        )
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
                    """INSERT INTO sale_item
                        (order_id, product_id, name, category, sku,
                         unit_price, quantity, subtotal)
                       VALUES
                        (%(order_id)s, %(product_id)s, %(name)s, %(category)s,
                         %(sku)s, %(unit_price)s, %(quantity)s, %(subtotal)s)""",
                    rows, page_size=100,
                )
            conn.commit()
        log.debug("INSERT %d sale_items for order_id=%s", len(rows), order_id)

    def has_orders(self) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT EXISTS(SELECT 1 FROM sale LIMIT 1)")
                return cur.fetchone()[0]

    # ── Sales reads ───────────────────────────────────────────────────────────

    def get_sales_summary(self, date_from=None, date_to=None, days=1) -> dict:
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        p_from, p_to = _prev_period(d_from, d_to)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT
                        COALESCE(SUM(total_amount),    0),
                        COUNT(*),
                        COALESCE(SUM(discount_amount), 0),
                        COUNT(CASE WHEN discount_type NOT IN ('None','') THEN 1 END),
                        COUNT(CASE WHEN order_type = 'Dine In'  THEN 1 END),
                        COUNT(CASE WHEN order_type = 'Takeout'  THEN 1 END),
                        COUNT(CASE WHEN order_type = 'Delivery' THEN 1 END)
                    FROM sale
                    WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s""",
                    (_TZ, d_from, d_to),
                )
                row = cur.fetchone()
                gross_sales      = float(row[0])
                total_orders     = int(row[1])
                total_discounts  = float(row[2])
                pwd_senior_count = int(row[3])
                dine_in_count    = int(row[4])
                takeout_count    = int(row[5])
                delivery_count   = int(row[6])
                cur.execute(
                    "SELECT COALESCE(SUM(total_amount), 0) FROM sale "
                    "WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s",
                    (_TZ, p_from, p_to),
                )
                prev_sales = float(cur.fetchone()[0])
        avg_ticket = gross_sales / total_orders if total_orders else 0.0
        change     = ((gross_sales - prev_sales) / prev_sales * 100) if prev_sales > 0 else 0.0
        return {
            "gross_sales": gross_sales, "total_orders": total_orders,
            "avg_ticket": avg_ticket, "sales_change": round(change, 1),
            "yesterday": prev_sales, "total_discounts": total_discounts,
            "pwd_senior_count": pwd_senior_count,
            "dine_in_count": dine_in_count, "takeout_count": takeout_count,
            "delivery_count": delivery_count,
        }

    def get_top_sellers(self, date_from=None, date_to=None, days=1, limit=4) -> list[dict]:
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT oi.name, oi.category,
                              SUM(oi.quantity)  AS units_sold,
                              SUM(oi.subtotal)  AS revenue,
                              MAX(p.image_path) AS image_path
                       FROM sale_item oi
                       JOIN sale o ON o.id = oi.order_id
                       LEFT JOIN product p ON p.id = oi.product_id
                       WHERE DATE(o.created_at AT TIME ZONE %s) BETWEEN %s AND %s
                       GROUP BY oi.name, oi.category
                       ORDER BY units_sold DESC LIMIT %s""",
                    (_TZ, d_from, d_to, limit),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_hourly_sales(self, date_from=None, date_to=None, days=1) -> list[dict]:
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT TO_CHAR(created_at AT TIME ZONE %s, 'HH12 AM') AS hour,
                              SUM(total_amount) AS revenue
                       FROM sale
                       WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s
                       GROUP BY hour ORDER BY MIN(created_at)""",
                    (_TZ, _TZ, d_from, d_to),
                )
                rows = cur.fetchall()
        return [{"hour": r["hour"].strip(), "revenue": float(r["revenue"])} for r in rows]

    def get_hourly_snapshot(self, date_from=None, date_to=None, days=1) -> list[dict]:
        return self.get_hourly_sales(date_from=date_from, date_to=date_to, days=days)

    def get_sales_log(self, date_from=None, date_to=None, days=1) -> list[dict]:
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT
                        oi.name, oi.sku, oi.category,
                        SUM(oi.quantity)                                         AS unit_sales,
                        AVG(oi.unit_price)                                       AS unit_price,
                        SUM(oi.subtotal)                                         AS gross_revenue,
                        ROUND(AVG(oi.unit_price) * 0.35, 2)                     AS ingredient_cost,
                        ROUND(AVG(oi.unit_price) * 0.65, 2)                     AS profit_per_item,
                        ROUND(SUM(oi.subtotal)   * 0.65, 2)                     AS total_profit,
                        COALESCE(SUM(CASE WHEN o.order_type='Dine In'
                                    THEN oi.quantity ELSE 0 END),0)              AS dine_in_qty,
                        COALESCE(SUM(CASE WHEN o.order_type='Takeout'
                                    THEN oi.quantity ELSE 0 END),0)              AS takeout_qty,
                        COALESCE(SUM(CASE WHEN o.order_type='Delivery'
                                    THEN oi.quantity ELSE 0 END),0)              AS delivery_qty,
                        COUNT(CASE WHEN o.discount_type NOT IN ('None','')
                                   THEN 1 END)                                   AS discounted_orders,
                        COALESCE(STRING_AGG(DISTINCT
                            CASE WHEN o.discount_type NOT IN ('None','')
                                 THEN o.discount_type END,
                            ', ' ORDER BY
                            CASE WHEN o.discount_type NOT IN ('None','')
                                 THEN o.discount_type END),'')                   AS discount_types,
                        MAX(p.image_path)                                        AS image_path
                    FROM sale_item oi
                    JOIN sale o ON o.id = oi.order_id
                    LEFT JOIN product p ON p.id = oi.product_id
                    WHERE DATE(o.created_at AT TIME ZONE %s) BETWEEN %s AND %s
                    GROUP BY oi.name, oi.sku, oi.category
                    ORDER BY unit_sales DESC""",
                    (_TZ, d_from, d_to),
                )
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    def get_recent_orders(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, order_number, order_type, customer_name, subtotal,
                              discount_type, discount_amount, total_amount, created_at
                       FROM sale ORDER BY created_at DESC LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    def get_order_type_breakdown(self, date_from=None, date_to=None, days=1) -> dict:
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT order_type, COUNT(*), COALESCE(SUM(total_amount),0)
                       FROM sale
                       WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s
                       GROUP BY order_type""",
                    (_TZ, d_from, d_to),
                )
                rows = cur.fetchall()
        counts  = {"Dine In": 0, "Takeout": 0, "Delivery": 0}
        revenue = {"Dine In": 0.0, "Takeout": 0.0, "Delivery": 0.0}
        for ot, cnt, rev in rows:
            if ot in counts:
                counts[ot]  = int(cnt)
                revenue[ot] = float(rev)
        return {"counts": counts, "revenue": revenue}

    def get_discount_summary(self, date_from=None, date_to=None, days=1) -> dict:
        d_from, d_to = _resolve_dates(date_from, date_to, days)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT discount_type, COUNT(*), COALESCE(SUM(discount_amount),0)
                       FROM sale
                       WHERE DATE(created_at AT TIME ZONE %s) BETWEEN %s AND %s
                         AND discount_type NOT IN ('None','')
                       GROUP BY discount_type""",
                    (_TZ, d_from, d_to),
                )
                rows = cur.fetchall()
        return {dtype: {"count": int(cnt), "total": float(total)} for dtype, cnt, total in rows}

    def close(self) -> None:
        self._pool.closeall()
        log.info("InventoryDB pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# StaffDB
# ─────────────────────────────────────────────────────────────────────────────

class StaffDB:
    """
    PostgreSQL persistence for Staff Management and Time Tracking.
    Clock In / Clock Out events are automatically written to activity_log.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn  = dsn
        self._pool = _make_pool(dsn, "StaffDB")
        self._ensure_schema()

    def _conn(self):
        return _PooledConnection(self._pool)

    def _log(self, activity_type, activity, detail="",
             status="Completed", flagged=False):
        _write_log(self._pool, activity_type, activity, detail,
                   staff=_session_staff(), station=_session_station(),
                   status=status, flagged=flagged)

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_ACTIVITY_LOG)
                cur.execute(_CREATE_STAFF_MEMBER)
                cur.execute(_CREATE_CLOCK_EVENT)
                cur.execute(_MIGRATE_CLOCK_EVENT)
                cur.execute(_CREATE_SHIFT)
                cur.execute("SELECT COUNT(*) FROM staff_member")
                count = cur.fetchone()[0]
            conn.commit()
        if count == 0:
            log.info("Empty staff table — inserting demo staff.")
            self._seed_staff()

    def _seed_staff(self) -> None:
        demo = {
            "name": "John Doe", "email": "john@pawffinated.local",
            "phone": "+63-999-123-4567", "role": "Staff",
            "avatar": "👤", "device": "Mobile",
            "started_on": str(date.today() - timedelta(days=30)),
            "schedule": "9:00 AM – 5:30 PM", "shift_hrs": "8.5h",
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO staff_member
                        (name,email,phone,role,avatar,device,started_on,schedule,shift_hrs)
                       VALUES
                        (%(name)s,%(email)s,%(phone)s,%(role)s,%(avatar)s,
                         %(device)s,%(started_on)s,%(schedule)s,%(shift_hrs)s)""",
                    demo,
                )
            conn.commit()
        log.info("Seeded demo staff member.")

    # ── Staff CRUD ────────────────────────────────────────────────────────────

    def get_all_staff(self) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, email, phone, role, device "
                    "FROM staff_member ORDER BY id"
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_staff(self, staff_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, name, email, phone, role, avatar, device, started_on,
                              schedule, shift_hrs, role_desc, role_detail,
                              this_week, week_sub, last_month, month_sub,
                              hours_worked, hours_sub, attendance, att_sub,
                              avg_shift, avg_sub, punctuality_on, punctuality_late,
                              punctuality_rating, completed, adjusted, completed_rating,
                              mgr_note1, mgr_note2, mgr_note3, created_at, updated_at
                       FROM staff_member WHERE id = %s""",
                    (staff_id,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def insert_staff(self, staff: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO staff_member
                        (name,email,phone,role,avatar,device,started_on)
                       VALUES
                        (%(name)s,%(email)s,%(phone)s,%(role)s,%(avatar)s,
                         %(device)s,%(started_on)s)
                       RETURNING id""",
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
        log.debug("INSERT staff_member id=%s  name=%s", new_id, staff.get("name"))
        return new_id

    def update_staff(self, staff: dict) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE staff_member
                       SET name=%(name)s, email=%(email)s, phone=%(phone)s,
                           role=%(role)s, device=%(device)s, updated_at=NOW()
                       WHERE id=%(id)s""",
                    {
                        "id":     staff["id"],
                        "name":   staff.get("name", ""),
                        "email":  staff.get("email"),
                        "phone":  staff.get("phone"),
                        "role":   staff.get("role", "Staff"),
                        "device": staff.get("device", "Mobile"),
                    },
                )
            conn.commit()
        log.debug("UPDATE staff_member id=%s", staff.get("id"))

    # ── Clock events ──────────────────────────────────────────────────────────

    def add_clock_event(self, staff_id, event_type, device,
                        duration=None, user_id=None) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO clock_event
                        (staff_id, user_id, event_type, device, duration, timestamp)
                       VALUES (%s, %s, %s, %s, %s, NOW() AT TIME ZONE %s)""",
                    (staff_id, user_id, event_type, device, duration, _TZ),
                )
            conn.commit()
        log.debug("INSERT clock_event staff_id=%s event=%s", staff_id, event_type)

        # ── Log: clock in / clock out ─────────────────────────────────────────
        staff_name = _session_staff()
        is_in      = (event_type == "Clock In")
        detail     = f"{event_type} · Device: {device}"
        if duration:
            detail += f" · Duration: {duration}"
        self._log(
            "clock",
            f"{event_type} — {staff_name}",
            detail,
            status="Login" if is_in else "Logout",
        )

    def get_clock_log(self, staff_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT ce.id, ce.staff_id, ce.user_id, ce.event_type,
                              ce.timestamp, ce.device, ce.duration, ce.created_at,
                              u.first_name, u.last_name,
                              u.email AS user_email, u.role AS user_role,
                              u.station AS user_station
                       FROM clock_event ce
                       LEFT JOIN user_account u ON u.id = ce.user_id
                       WHERE ce.staff_id = %s ORDER BY ce.timestamp DESC""",
                    (staff_id,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_clock_log_by_user(self, user_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT ce.id, ce.staff_id, ce.user_id, ce.event_type,
                              ce.timestamp, ce.device, ce.duration, ce.created_at,
                              u.first_name, u.last_name,
                              u.email AS user_email, u.role AS user_role,
                              u.station AS user_station
                       FROM clock_event ce
                       LEFT JOIN user_account u ON u.id = ce.user_id
                       WHERE ce.user_id = %s ORDER BY ce.timestamp DESC""",
                    (user_id,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_last_clock_event(self, staff_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, staff_id, user_id, event_type, timestamp,
                              device, duration, created_at
                       FROM clock_event WHERE staff_id = %s
                       ORDER BY timestamp DESC LIMIT 1""",
                    (staff_id,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_last_clock_event_by_user(self, user_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, staff_id, user_id, event_type, timestamp,
                              device, duration, created_at
                       FROM clock_event WHERE user_id = %s
                       ORDER BY timestamp DESC LIMIT 1""",
                    (user_id,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def update_clock_out_duration(self, staff_id: int, duration: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE clock_event SET duration = %s
                       WHERE staff_id = %s AND event_type = 'Clock In'
                         AND id = (
                             SELECT id FROM clock_event
                             WHERE staff_id = %s AND event_type = 'Clock In'
                             ORDER BY timestamp DESC LIMIT 1
                         )""",
                    (duration, staff_id, staff_id),
                )
            conn.commit()
        log.debug("UPDATE clock_out_duration staff_id=%s  duration=%s", staff_id, duration)

    # ── Schedule ──────────────────────────────────────────────────────────────

    def get_staff_schedule(self, staff_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, staff_id, day, time, note, tag, created_at "
                    "FROM shift WHERE staff_id = %s ORDER BY id",
                    (staff_id,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def add_shift(self, staff_id, day, time, note=None, tag="Scheduled") -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO shift (staff_id, day, time, note, tag) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (staff_id, day, time, note, tag),
                )
                shift_id = cur.fetchone()[0]
            conn.commit()
        log.debug("INSERT shift id=%s  staff_id=%s  day=%s", shift_id, staff_id, day)
        return shift_id

    def close(self) -> None:
        self._pool.closeall()
        log.info("StaffDB pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# AuthDB
# ─────────────────────────────────────────────────────────────────────────────

class AuthDB:
    """
    Manages user_account: login, registration, and admin management.
    Login, logout, register, delete, edit, shift add/delete/edit, and
    access-control decisions are all automatically logged to activity_log.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn  = dsn
        self._pool = _make_pool(dsn, "AuthDB")
        self._ensure_schema()

    def _conn(self):
        return _PooledConnection(self._pool)

    def _log(self, activity_type, activity, detail="",
             staff="", station="", status="Completed", flagged=False):
        _write_log(
            self._pool, activity_type, activity, detail,
            staff=staff or _session_staff(),
            station=station or _session_station(),
            status=status, flagged=flagged,
        )

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_ACTIVITY_LOG)
                cur.execute(_CREATE_USER_ACCOUNT)
                cur.execute("SELECT COUNT(*) FROM user_account")
                count = cur.fetchone()[0]
            conn.commit()
        if count == 0:
            log.info("user_account table empty — seeding default admin.")
            self._seed_admin()

    def _seed_admin(self) -> None:
        a = _SEED_ADMIN
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user_account
                        (first_name,last_name,email,password,role,station,is_admin)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (email) DO NOTHING""",
                    (a["first_name"], a["last_name"], a["email"],
                     a["password"], a["role"], a["station"], a["is_admin"]),
                )
            conn.commit()

    # ── Core ──────────────────────────────────────────────────────────────────

    def authenticate(self, email: str, password: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, first_name, last_name, email, role, station, is_admin
                       FROM user_account
                       WHERE LOWER(email) = LOWER(%s) AND password = %s""",
                    (email.strip(), password),
                )
                row = cur.fetchone()
        user = dict(row) if row else None

        # ── Log: login success or failure ─────────────────────────────────────
        if user:
            full = f"{user['first_name']} {user['last_name']}"
            self._log(
                "login",
                f"Login — {full}",
                f"Logged into Pawffinated system · Role: {user['role']} · "
                f"Station: {user['station']}",
                staff=full,
                station=user["station"],
                status="Login",
            )
        else:
            self._log(
                "login",
                f"Failed login attempt — {email}",
                f"Invalid credentials entered for {email}",
                staff=email,
                station="Login Screen",
                status="Review",
                flagged=True,
            )
        return user

    def email_exists(self, email: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM user_account WHERE LOWER(email) = LOWER(%s)",
                    (email.strip(),),
                )
                return cur.fetchone() is not None

    def register(self, first_name, last_name, email, password, role, station) -> int:
        if self.email_exists(email):
            raise ValueError(f"Email '{email}' is already registered.")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user_account
                        (first_name,last_name,email,password,role,station,is_admin)
                       VALUES (%s,%s,%s,%s,%s,%s,FALSE) RETURNING id""",
                    (first_name.strip(), last_name.strip(),
                     email.strip().lower(), password, role, station),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        log.info("Registered user id=%s  email=%s  role=%s", new_id, email, role)

        # ── Log: new account ──────────────────────────────────────────────────
        full = f"{first_name.strip()} {last_name.strip()}"
        self._log(
            "user",
            f"New account registered — {full}",
            f"Role: {role} · Station: {station} · Email: {email}",
            staff=full,
            station=station,
            status="Success",
        )
        return new_id

    def is_admin(self, email: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT is_admin FROM user_account WHERE LOWER(email) = LOWER(%s)",
                    (email.strip(),),
                )
                row = cur.fetchone()
        return bool(row[0]) if row else False

    def get_all_users(self) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, first_name, last_name, email, "
                    "role, station, is_admin, created_at "
                    "FROM user_account ORDER BY id"
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ── Admin helpers ─────────────────────────────────────────────────────────

    def update_user(self, user_id: int, **fields) -> None:
        allowed = {"first_name", "last_name", "email", "role", "station", "is_admin"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown user fields: {bad}")
        if not fields:
            return
        set_clause = ", ".join(f"{k} = %({k})s" for k in fields)
        fields["uid"] = user_id
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE user_account SET {set_clause} WHERE id = %(uid)s", fields
                )
            conn.commit()
        log.info("UPDATE user id=%s  fields=%s", user_id, list(fields.keys()))

        # ── Log: user edited ──────────────────────────────────────────────────
        changed = ", ".join(f"{k}={v}" for k, v in fields.items() if k != "uid")
        self._log(
            "staff",
            f"User edited — ID {user_id}",
            f"Fields updated: {changed} · By: {_session_staff()}",
            status="Updated",
        )

    def update_user_role(self, user_id: int, role: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_account SET role = %s WHERE id = %s", (role, user_id)
                )
            conn.commit()
        log.info("UPDATE user role  id=%s  role=%s", user_id, role)
        self._log(
            "staff",
            f"User role updated — ID {user_id}",
            f"Role changed to: {role} · By: {_session_staff()}",
            status="Updated",
        )

    def update_user_station(self, user_id: int, station: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_account SET station = %s WHERE id = %s",
                    (station, user_id)
                )
            conn.commit()
        log.info("UPDATE user station  id=%s  station=%s", user_id, station)

    def set_admin(self, user_id: int, is_admin: bool) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_account SET is_admin = %s WHERE id = %s",
                    (is_admin, user_id)
                )
            conn.commit()
        log.info("SET admin  id=%s  is_admin=%s", user_id, is_admin)
        verb = "granted" if is_admin else "revoked"
        self._log(
            "access",
            f"Admin privilege {verb} — ID {user_id}",
            f"Administrator access {verb} by {_session_staff()}",
            status="Approved" if is_admin else "Rejected",
            flagged=not is_admin,
        )

    def update_password(self, user_id: int, new_password: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_account SET password = %s WHERE id = %s",
                    (new_password, user_id)
                )
            conn.commit()
        log.info("UPDATE password  id=%s", user_id)
        self._log(
            "staff",
            f"Password reset — ID {user_id}",
            f"Password changed by {_session_staff()}",
            status="Updated",
        )

    def delete_user(self, user_id: int) -> None:
        # Capture details before deletion
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT first_name, last_name, email, role "
                    "FROM user_account WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        name = (f"{row['first_name']} {row['last_name']}" if row else f"ID {user_id}")
        role = row["role"] if row else "—"

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_account WHERE id = %s", (user_id,))
            conn.commit()
        log.info("DELETE user id=%s", user_id)

        # ── Log: user deleted ─────────────────────────────────────────────────
        self._log(
            "staff",
            f"User deleted — {name}",
            f"User account deleted by {_session_staff()} · Role was: {role}",
            status="Deleted",
            flagged=True,
        )

    # ── Shift helpers ─────────────────────────────────────────────────────────

    def get_user_shifts(self, user_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT s.id, s.staff_id, s.day, s.time, s.note, s.tag, s.created_at
                       FROM shift s
                       JOIN staff_member st ON st.id = s.staff_id
                       JOIN user_account u  ON LOWER(u.email) = LOWER(st.email)
                       WHERE u.id = %s ORDER BY s.id""",
                    (user_id,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def add_user_shift(self, user_id, day, time, note=None, tag="Scheduled") -> int | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT st.id FROM staff_member st
                       JOIN user_account u ON LOWER(u.email) = LOWER(st.email)
                       WHERE u.id = %s LIMIT 1""",
                    (user_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                staff_id = row[0]
                cur.execute(
                    "INSERT INTO shift (staff_id, day, time, note, tag) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (staff_id, day, time, note, tag),
                )
                shift_id = cur.fetchone()[0]
            conn.commit()
        log.info("INSERT shift id=%s  user_id=%s  day=%s", shift_id, user_id, day)

        # ── Log: shift added ──────────────────────────────────────────────────
        self._log(
            "staff",
            f"Shift added — User ID {user_id}",
            f"Day: {day} · Time: {time} · Tag: {tag} · Added by {_session_staff()}",
            status="Added",
        )
        return shift_id

    def delete_shift(self, shift_id: int) -> None:
        # Capture details before deletion
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT day, time, tag FROM shift WHERE id = %s", (shift_id,))
                row = cur.fetchone()
        day  = row["day"]  if row else "?"
        time = row["time"] if row else "?"

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM shift WHERE id = %s", (shift_id,))
            conn.commit()
        log.info("DELETE shift id=%s", shift_id)

        # ── Log: shift deleted ────────────────────────────────────────────────
        self._log(
            "staff",
            f"Shift deleted — {day} at {time}",
            f"Shift removed by {_session_staff()}",
            status="Deleted",
            flagged=True,
        )

    def update_shift(self, shift_id, day, time, note=None, tag="Scheduled") -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE shift SET day=%s, time=%s, note=%s, tag=%s WHERE id=%s",
                    (day, time, note, tag, shift_id),
                )
            conn.commit()
        log.info("UPDATE shift id=%s", shift_id)

        # ── Log: shift updated ────────────────────────────────────────────────
        self._log(
            "staff",
            f"Shift updated — {day} at {time}",
            f"Shift edited by {_session_staff()} · Tag: {tag}",
            status="Updated",
        )

    # ── Access-control helpers (called from AccessControl.py) ─────────────────

    def log_access_decision(self, user_name: str, user_role: str,
                             action: str, operator: str = "") -> None:
        """
        Log an approve / reject decision from the Access Control panel.
        Call this from AccessControl.py after _commit_act():
            get_auth_db().log_access_decision(req['name'], req['role'], action, _USER_NAME)
        """
        is_approved = (action == "approved")
        self._log(
            "access",
            f"Access {action} — {user_name}",
            f"Access request {action} by {operator or _session_staff()} · "
            f"Role: {user_role}",
            staff=operator or _session_staff(),
            station="Access Control",
            status="Approved" if is_approved else "Rejected",
            flagged=not is_approved,
        )

    def log_logout(self, user_name: str, station: str = "") -> None:
        """
        Call this from AccountManagement._log_out() before closing the window.
            get_auth_db().log_logout(_USER_NAME, _USER_ROLE)
        """
        self._log(
            "logout",
            f"Logout — {user_name}",
            "Logged out of Pawffinated system",
            staff=user_name,
            station=station or _session_station(),
            status="Logout",
        )

    def close(self) -> None:
        self._pool.closeall()
        log.info("AuthDB pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# MenuDB
# ─────────────────────────────────────────────────────────────────────────────

class MenuDB:
    """
    PostgreSQL persistence for Menu Items and their Ingredients.
    Add / update / delete menu items are automatically logged to activity_log.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn  = dsn
        self._pool = _make_pool(dsn, "MenuDB")
        self._ensure_schema()

    def _conn(self):
        return _PooledConnection(self._pool)

    def _log(self, activity_type, activity, detail="",
             status="Completed", flagged=False):
        _write_log(self._pool, activity_type, activity, detail,
                   staff=_session_staff(), station=_session_station(),
                   status=status, flagged=flagged)

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_ACTIVITY_LOG)
                cur.execute(_CREATE_MENU_ITEMS)
                cur.execute(_CREATE_MENU_INGREDIENTS)
            conn.commit()
        log.info("MenuDB schema ready.")

    # ── Menu items CRUD ───────────────────────────────────────────────────────

    def fetch_all_menu_items(self) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, category, price, description, image_path "
                    "FROM menu_items ORDER BY id"
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def fetch_menu_item(self, item_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, category, price, description, image_path "
                    "FROM menu_items WHERE id = %s",
                    (item_id,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def insert_menu_item(self, item: dict) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO menu_items
                        (name, category, price, description, image_path)
                       VALUES
                        (%(name)s, %(category)s, %(price)s, %(description)s, %(image_path)s)
                       RETURNING id""",
                    {
                        "name":        str(item.get("name", "")),
                        "category":    str(item.get("category", "Other")),
                        "price":       float(item.get("price", 0.0)),
                        "description": str(item.get("description", "")),
                        "image_path":  item.get("image_path") or None,
                    },
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        log.debug("INSERT menu_item id=%s  name=%s", new_id, item.get("name"))

        # ── Log: menu item added ──────────────────────────────────────────────
        self._log(
            "menu",
            f"Menu item added — {item.get('name', '')}",
            f"Category: {item.get('category', 'Other')} · "
            f"Price: ₱{float(item.get('price', 0)):.2f} · "
            f"Added by {_session_staff()}",
            status="Added",
        )
        return new_id

    def update_menu_item(self, item: dict) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE menu_items
                       SET name=%(name)s, category=%(category)s, price=%(price)s,
                           description=%(description)s, image_path=%(image_path)s,
                           updated_at=NOW()
                       WHERE id=%(id)s""",
                    {
                        "id":          int(item["id"]),
                        "name":        str(item.get("name", "")),
                        "category":    str(item.get("category", "Other")),
                        "price":       float(item.get("price", 0.0)),
                        "description": str(item.get("description", "")),
                        "image_path":  item.get("image_path") or None,
                    },
                )
            conn.commit()
        log.debug("UPDATE menu_item id=%s", item.get("id"))

        # ── Log: menu item updated ────────────────────────────────────────────
        self._log(
            "menu",
            f"Menu item updated — {item.get('name', '')}",
            f"Category: {item.get('category', 'Other')} · "
            f"Price: ₱{float(item.get('price', 0)):.2f} · "
            f"Updated by {_session_staff()}",
            status="Updated",
        )

    def delete_menu_item(self, item_id: int) -> None:
        # Capture name before deletion
        item = self.fetch_menu_item(item_id)
        name = item["name"] if item else f"ID {item_id}"

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM menu_items WHERE id = %s", (item_id,))
            conn.commit()
        log.debug("DELETE menu_item id=%s", item_id)

        # ── Log: menu item deleted ────────────────────────────────────────────
        self._log(
            "menu",
            f"Menu item deleted — {name}",
            f"Item removed from menu by {_session_staff()}",
            status="Deleted",
            flagged=True,
        )

    # ── Ingredients ───────────────────────────────────────────────────────────

    def fetch_ingredients(self, menu_item_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, menu_item_id, ingredient_name, quantity, unit "
                    "FROM menu_ingredients WHERE menu_item_id = %s ORDER BY id",
                    (menu_item_id,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def replace_ingredients(self, menu_item_id: int, ingredients: list[dict]) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM menu_ingredients WHERE menu_item_id = %s",
                    (menu_item_id,),
                )
                if ingredients:
                    psycopg2.extras.execute_batch(
                        cur,
                        """INSERT INTO menu_ingredients
                            (menu_item_id, ingredient_name, quantity, unit)
                           VALUES (%s, %s, %s, %s)""",
                        [
                            (menu_item_id,
                             str(ing.get("ingredient_name", "")),
                             float(ing.get("quantity", 1.0)),
                             str(ing.get("unit", "units")))
                            for ing in ingredients
                            if ing.get("ingredient_name", "").strip()
                        ],
                        page_size=100,
                    )
            conn.commit()
        log.debug("replace_ingredients menu_item_id=%s  count=%d",
                  menu_item_id, len(ingredients))

    # ── POS helpers ───────────────────────────────────────────────────────────

    def get_locked_item_ids(self, inv_db: InventoryDB) -> set[int]:
        inv_products = {
            p["name"].lower(): float(p.get("stock", 0))
            for p in inv_db.fetch_all()
        }
        locked = set()
        for item in self.fetch_all_menu_items():
            for ing in self.fetch_ingredients(item["id"]):
                stock = inv_products.get(ing["ingredient_name"].lower())
                if stock is not None and stock <= 0:
                    locked.add(item["id"])
                    break
        return locked

    def deduct_ingredients(self, menu_item_id, inv_db: InventoryDB,
                           qty_ordered: int = 1) -> None:
        """
        Deduct ingredient quantities from inventory when a menu item is sold.
        Stock updates call inv_db.update() which already writes its own log row.
        """
        ingredients  = self.fetch_ingredients(menu_item_id)
        inv_products = {p["name"].lower(): p for p in inv_db.fetch_all()}
        for ing in ingredients:
            key = ing["ingredient_name"].lower()
            if key not in inv_products:
                continue
            prod      = inv_products[key]
            deduct    = float(ing["quantity"]) * float(qty_ordered)
            new_stock = max(0.0, float(prod["stock"]) - deduct)
            new_stock = round(new_stock, 4)
            inv_db.update({
                "id":          prod["id"],
                "name":        prod["name"],
                "sku":         prod.get("sku", ""),
                "category":    prod.get("category", "Other"),
                "stock":       new_stock,
                "unit":        prod.get("unit", "units"),
                "price":       prod.get("price", 0.0),
                "description": prod.get("description", ""),
                "image_path":  prod.get("image_path"),
            })
            log.debug("deduct_ingredients: %s  −%.4f → stock=%.4f",
                      prod["name"], deduct, new_stock)

    def close(self) -> None:
        self._pool.closeall()
        log.info("MenuDB pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singletons
# ─────────────────────────────────────────────────────────────────────────────

_instance_inv:   InventoryDB | None = None
_instance_staff: StaffDB     | None = None
_instance_auth:  AuthDB      | None = None
_instance_menu:  MenuDB      | None = None


def get_db(dsn: str | None = None) -> InventoryDB:
    global _instance_inv
    if _instance_inv is None:
        _instance_inv = InventoryDB(dsn or _build_dsn())
    return _instance_inv


def get_staff_db(dsn: str | None = None) -> StaffDB:
    global _instance_staff
    if _instance_staff is None:
        _instance_staff = StaffDB(dsn or _build_dsn())
    return _instance_staff


def get_auth_db(dsn: str | None = None) -> AuthDB:
    global _instance_auth
    if _instance_auth is None:
        _instance_auth = AuthDB(dsn or _build_dsn())
    return _instance_auth


def get_menu_db(dsn: str | None = None) -> MenuDB:
    global _instance_menu
    if _instance_menu is None:
        _instance_menu = MenuDB(dsn or _build_dsn())
    return _instance_menu


def close_db() -> None:
    global _instance_inv, _instance_staff, _instance_auth, _instance_menu
    for attr in ("_instance_inv", "_instance_staff",
                 "_instance_auth", "_instance_menu"):
        inst = globals()[attr]
        if inst is not None:
            inst.close()
            globals()[attr] = None


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