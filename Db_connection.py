"""
db_connection.py – Pawffinated PostgreSQL Connection Manager
=============================================================
The single file responsible for connecting to PostgreSQL.
Every other module imports from here — never from database_pg.py directly.

On startup, it looks for connection details in this order:
  1. An explicit DSN passed to get_db()
  2. The environment variable  DATABASE_URL
  3. A config file             pawffinated.env  (next to this script)
  4. Individual fallback defaults (localhost / pawffinated / postgres)

Usage (everywhere else in the app)
-----------------------------------
    from db_connection import get_db, close_db, db_info

    db   = get_db()    # call once — returns the shared InventoryDB instance
    info = db_info()   # e.g. "PostgreSQL  pawff_user@192.168.1.10:5432/pawffinated"
    close_db()         # call once on application exit

pawffinated.env  (place next to this file, never commit to version control)
-----------------------------------------------------------------------------
Option A — full DSN (simplest):
    DATABASE_URL = postgresql://pawff_user:secret@192.168.1.10:5432/pawffinated

Option B — individual keys:
    DB_HOST = 192.168.1.10
    DB_PORT = 5432
    DB_NAME = pawffinated
    DB_USER = pawff_user
    DB_PASS = secret

Rules:
  - Lines starting with # are comments.
  - Inline comments are supported:  DB_PORT = 5432  # default pg port
  - Surrounding quotes are stripped from values.
  - Keys already in the environment are NOT overwritten, so environment
    variables always win over the file (useful for Docker / CI).
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.pool

log = logging.getLogger("pawffinated.db")

_HERE     = Path(__file__).resolve().parent
_ENV_FILE = _HERE / "pawffinated.env"

# ── Seed data — inserted once when the table is empty ────────────────────────
_SEED_ROWS: list[dict] = []
#_SEED_ROWS: list[dict] = [
#    {"name": "House Blend Beans",  "sku": "BNS-HB-01",  "category": "Whole Beans",      "stock": 45, "unit": "kg",    "price": 24.00, "description": ""},
#    {"name": "Oat Milk (1L)",      "sku": "DRY-OAT-02", "category": "Dairy Alt",         "stock":  8, "unit": "units", "price":  5.50, "description": ""},
#    {"name": "Blueberry Muffin",   "sku": "PST-BM-01",  "category": "Pastries",          "stock":  0, "unit": "units", "price":  3.50, "description": ""},
#    {"name": "Vanilla Syrup (1L)", "sku": "SYR-VAN-01", "category": "Syrups",            "stock": 24, "unit": "units", "price": 12.50, "description": ""},
#    {"name": "Whole Milk (Gallon)","sku": "DRY-WM-01",  "category": "Dairy",             "stock": 12, "unit": "units", "price":  4.50, "description": ""},
#    {"name": "Classic Latte",      "sku": "ESP-CL-01",  "category": "Coffee & Espresso", "stock": 42, "unit": "cups",  "price":  4.50, "description": ""},
#    {"name": "Almond Croissant",   "sku": "PST-AC-01",  "category": "Pastries",          "stock":  3, "unit": "units", "price":  3.75, "description": ""},
#    {"name": "Cold Brew Bags",     "sku": "BNS-CB-01",  "category": "Whole Beans",       "stock":  6, "unit": "bags",  "price":  9.00, "description": ""},
#    {"name": "Choc Chip Cookie",   "sku": "PST-CC-01",  "category": "Pastries",          "stock": 18, "unit": "units", "price":  2.50, "description": ""},
#    {"name": "Matcha Powder",      "sku": "SYR-MT-01",  "category": "Syrups",            "stock":  5, "unit": "tins",  "price": 14.00, "description": ""},
#    {"name": "Caramel Sauce",      "sku": "SYR-CS-01",  "category": "Syrups",            "stock": 30, "unit": "units", "price":  8.00, "description": ""},
#    {"name": "Iced Macchiato",     "sku": "ESP-IM-01",  "category": "Coffee & Espresso", "stock": 28, "unit": "cups",  "price":  5.25, "description": ""},
#]

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS products (
    id          SERIAL         PRIMARY KEY,
    name        TEXT           NOT NULL,
    sku         TEXT           NOT NULL DEFAULT '',
    category    TEXT           NOT NULL DEFAULT 'Other',
    stock       INTEGER        NOT NULL DEFAULT 0,
    unit        TEXT           NOT NULL DEFAULT 'units',
    price       NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    description TEXT                    DEFAULT ''
);
"""


# ─────────────────────────────────────────────────────────────────────────────
# Config loading
# ─────────────────────────────────────────────────────────────────────────────

def _load_env_file(path: Path = _ENV_FILE) -> None:
    """
    Parse pawffinated.env and push KEY=VALUE pairs into os.environ.
    Existing env vars are never overwritten (env always wins over the file).
    """
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
        value = value.split("#", 1)[0].strip().strip("'\"")  # strip inline comments & quotes
        os.environ.setdefault(key, value)
        log.debug("  env ← %s", key)


def _build_dsn() -> str:
    """
    Resolve the PostgreSQL DSN from the environment (after loading the config
    file).  Priority:

      DATABASE_URL  (full DSN string)
        └─ else ─→  DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASS
    """
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
    """Return the DSN with the password replaced by *** for safe logging."""
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", dsn)


# ─────────────────────────────────────────────────────────────────────────────
# InventoryDB — the class the rest of the app uses
# ─────────────────────────────────────────────────────────────────────────────

class InventoryDB:
    """
    PostgreSQL persistence layer for Pawffinated.

    Wraps a ThreadedConnectionPool (min=1, max=5) so multiple Qt threads
    can safely read from the database at the same time.

    Public API
    ----------
    fetch_all()                     → list[dict]
    fetch_by_id(item_id)            → dict | None
    insert(item_dict)               → int   (new id)
    update(item_dict)               → None
    delete(item_id)                 → None
    bulk_replace(list[dict])        → int   (rows inserted)
    execute_query(sql, params)      → list[dict]
    close()                         → None
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
                minconn=1,
                maxconn=5,
                dsn=self._dsn,
            )
            log.info("Connection pool created → %s", self._safe_dsn)
            return pool
        except psycopg2.OperationalError as exc:
            log.error("Could not connect to PostgreSQL: %s", exc)
            raise ConnectionError(
                f"Cannot connect to the database.\n\n"
                f"Connection: {self._safe_dsn}\n\n"
                f"Check that:\n"
                f"  • PostgreSQL is running on the server\n"
                f"  • The host / port / credentials in pawffinated.env are correct\n"
                f"  • The server firewall allows connections on port 5432\n\n"
                f"Original error: {exc}"
            ) from exc

    def _conn(self):
        """Context manager: borrow a connection from the pool, return it after."""
        return _PooledConnection(self._pool)

    # ── Schema ────────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        """Create the products table and seed it if it is empty."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_TABLE)
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
                        (name, sku, category, stock, unit, price, description)
                    VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s)
                    """,
                    _SEED_ROWS,
                    page_size=100,
                )
            conn.commit()

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch_all(self) -> list[dict]:
        """Return every product as a list of plain dicts, ordered by id."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, sku, category, stock, unit, price, description "
                    "FROM products ORDER BY id"
                )
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    def fetch_by_id(self, item_id: int) -> dict | None:
        """Return one product dict or None if not found."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, sku, category, stock, unit, price, description "
                    "FROM products WHERE id = %s",
                    (item_id,),
                )
                row = cur.fetchone()
        return _normalise(dict(row)) if row else None

    def insert(self, item: dict) -> int:
        """Insert a new product and return the database-assigned id."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO products
                        (name, sku, category, stock, unit, price, description)
                    VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s)
                    RETURNING id
                    """,
                    _params(item),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        log.debug("INSERT product id=%s  name=%s", new_id, item.get("name"))
        return new_id

    def update(self, item: dict) -> None:
        """Update an existing product.  item['id'] must be set."""
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
                           description = %(description)s
                     WHERE id = %(id)s
                    """,
                    {**_params(item), "id": item["id"]},
                )
            conn.commit()
        log.debug("UPDATE product id=%s", item.get("id"))

    def delete(self, item_id: int) -> None:
        """Delete a product by id."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM products WHERE id = %s", (item_id,))
            conn.commit()
        log.debug("DELETE product id=%s", item_id)

    def bulk_replace(self, items: list[dict]) -> int:
        """
        Delete all products and insert *items* in a single transaction.
        Used by the import flow (CSV / paste / external DB query).
        Returns the number of rows inserted.
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM products")
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    INSERT INTO products
                        (name, sku, category, stock, unit, price, description)
                    VALUES
                        (%(name)s, %(sku)s, %(category)s, %(stock)s,
                         %(unit)s, %(price)s, %(description)s)
                    """,
                    [_params(i) for i in items],
                    page_size=100,
                )
            conn.commit()
        log.info("bulk_replace: inserted %d rows", len(items))
        return len(items)

    def execute_query(self, sql: str, params: tuple = ()) -> list[dict]:
        """
        Run an arbitrary SELECT and return rows as dicts.
        Used by the 'Import from external database' dialog.
        Note: use %s placeholders in your SQL, not ? or :name.
        """
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_normalise(dict(r)) for r in rows]

    def close(self) -> None:
        """Close all connections in the pool.  Call once on application exit."""
        self._pool.closeall()
        log.info("Connection pool closed.")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

class _PooledConnection:
    """
    Context manager that borrows a connection from the pool on __enter__
    and returns it (without closing it) on __exit__.

    Usage:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
            conn.commit()
    """
    def __init__(self, pool: psycopg2.pool.ThreadedConnectionPool) -> None:
        self._pool = pool
        self._conn = None

    def __enter__(self):
        self._conn = self._pool.getconn()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # Roll back so the connection goes back to the pool in a clean state
            try:
                self._conn.rollback()
            except Exception:
                pass
            log.error("DB error — rolled back: %s", exc_val)
        self._pool.putconn(self._conn)
        return False   # re-raise any exception


def _params(item: dict) -> dict:
    """Sanitise and type-cast an item dict into safe SQL parameter values."""
    return {
        "name":        str(item.get("name", "")),
        "sku":         str(item.get("sku", "")),
        "category":    str(item.get("category", "Other")),
        "stock":       int(item.get("stock", 0)),
        "unit":        str(item.get("unit", "units")),
        "price":       float(item.get("price", 0.0)),
        "description": str(item.get("description", "")),
    }


def _normalise(row: dict) -> dict:
    """
    Cast NUMERIC(10,2) price → float.
    psycopg2 returns NUMERIC columns as decimal.Decimal;
    InventoryItem expects a plain Python float.
    """
    if "price" in row and row["price"] is not None:
        row["price"] = float(row["price"])
    return row


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton — what the rest of the app calls
# ─────────────────────────────────────────────────────────────────────────────

_instance: InventoryDB | None = None


def get_db(dsn: str | None = None) -> InventoryDB:
    """
    Return the shared InventoryDB instance, creating it on the first call.

    Parameters
    ----------
    dsn : str | None
        Optional DSN override — only honoured on the very first call.
        After that the cached instance is returned regardless.
        Useful for tests:  get_db("postgresql://...test_db")
    """
    global _instance
    if _instance is None:
        resolved_dsn = dsn or _build_dsn()
        _instance = InventoryDB(resolved_dsn)
    return _instance


def close_db() -> None:
    """Close the shared connection pool.  Call once on application exit."""
    global _instance
    if _instance is not None:
        _instance.close()
        _instance = None


def db_info() -> str:
    """
    Return a short human-readable string describing the active connection.
    Safe to display in a status bar or About dialog.

    Example output:
        "PostgreSQL  pawff_user@192.168.1.10:5432/pawffinated"
    """
    _load_env_file()

    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return f"PostgreSQL  {_redact(url)}"

    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "pawffinated")
    user = os.environ.get("DB_USER", "postgres")
    return f"PostgreSQL  {user}@{host}:{port}/{name}"