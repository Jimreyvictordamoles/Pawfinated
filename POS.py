"""
PAWFFINATED – Point of Sale System  (PyQt6 Edition)
====================================================
Install:
    pip install PyQt6

Run:
    python POS.py

─── CHANGES ─────────────────────────────────────────────────────────────────
    • Currency changed to Philippine Peso (₱)
    • Tax removed; replaced with PWD / Senior Citizen 20% discount
    • Discount tracks Dine In vs Takeout separately in DB
    • Orders + order_items are saved to PostgreSQL on every Charge
    • Sales Monitor and Dashboard now reflect real order data
    • FIX: load_inventory_from_csv() and load_inventory_from_list() now
      save to PostgreSQL via db.bulk_replace() instead of memory-only
"""

from __future__ import annotations
import sys, csv, io
from dataclasses import dataclass, field
from typing import Optional, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QGridLayout, QHBoxLayout, QVBoxLayout, QSizePolicy,
    QButtonGroup, QFileDialog, QDialog, QLineEdit, QTextEdit,
    QMessageBox, QToolBar, QStatusBar, QSplitter, QSpacerItem, QMenu,
    QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QPixmap, QIcon, QAction

from Sidebar import PawffinatedSidebar
from Db_connection import get_db, close_db, db_info, InventoryDB

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    sidebar   = "#FFFFFF",
    card      = "#FFFFFF",
    white     = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_lt = "#E8F4F0",
    warn      = "#E07B39",
    warn_lt   = "#FFF7ED",
    danger    = "#D94F4F",
    danger_lt = "#FEE2E2",
    ok        = "#059669",
    ok_lt     = "#D1FAE5",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    border    = "#E5E7EB",
    purple    = "#7C3AED",
    purple_lt = "#EDE9FE",
)

# PWD / Senior discount rate (Philippine law: 20%)
DISCOUNT_RATE = 0.20
DISCOUNT_TYPES = ["None", "PWD", "Senior Citizen"]

CATEGORY_EMOJI = {
    "Coffee & Espresso": "☕",
    "Cold Beverages":    "🧊",
    "Pastries":          "🥐",
    "Sandwiches":        "🥪",
    "Merchandise":       "🛍️",
    "Dairy":             "🥛",
    "Dairy Alt":         "🌿",
    "Whole Beans":       "☕",
    "Syrups":            "🍯",
}

# ── Domain models ─────────────────────────────────────────────────────────────
@dataclass
class Product:
    id: int
    name: str
    category: str
    price: float
    stock: int
    sku: str = ""
    unit: str = "units"
    description: str = ""


@dataclass
class OrderLine:
    product: Product
    qty: int = 1
    modifiers: list[tuple[str, float]] = field(default_factory=list)

    @property
    def unit_price(self) -> float:
        return self.product.price + sum(v for _, v in self.modifiers)

    @property
    def subtotal(self) -> float:
        return self.unit_price * self.qty


# ── Stylesheets ───────────────────────────────────────────────────────────────
GLOBAL_QSS = f"""
QWidget {{
    font-family: 'Segoe UI', 'SF Pro Display', Helvetica, sans-serif;
    font-size: 13px;
    color: {C['text']};
}}
QMainWindow, #centralWidget {{
    background: {C['bg']};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {C['bg']};
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C['border']};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolBar {{
    background: {C['sidebar']};
    border-bottom: 1px solid {C['border']};
    spacing: 6px;
    padding: 4px 12px;
}}
QStatusBar {{
    background: {C['sidebar']};
    border-top: 1px solid {C['border']};
    color: {C['sub']};
    font-size: 11px;
    padding: 0 12px;
}}
"""

CARD_QSS = f"""
QFrame#productCard {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 10px;
}}
QFrame#productCard:hover {{
    border: 1.5px solid {C['accent']};
}}
"""

ORDER_QSS = f"""
QWidget#orderPanel {{
    background: {C['white']};
    border-left: 1px solid {C['border']};
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# POS State
# ─────────────────────────────────────────────────────────────────────────────
class POSState(QObject):
    order_changed    = pyqtSignal()
    charge_completed = pyqtSignal(int, float, str)   # order#, total, discount_type
    inventory_loaded = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.order_lines:    list[OrderLine] = []
        self.order_number:   int  = 1042
        self.order_type:     str  = "Dine In"
        self.customer_name:  str  = "Walk-in Customer"
        self.discount_type:  str  = "None"   # "None" | "PWD" | "Senior Citizen"

        self.subtotal:        float = 0.0
        self.discount_amount: float = 0.0
        self.total_amount:    float = 0.0

        self.products:        list[Product] = []
        self.active_category: str = "All Items"

        self._load_from_db()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _rows_to_products(self, rows: list[dict]) -> list[Product]:
        products = []
        for r in rows:
            try:
                products.append(Product(
                    id=int(r["id"]),
                    name=str(r["name"]),
                    category=str(r.get("category", "Other")),
                    price=float(r.get("price", 0.0)),
                    stock=int(r.get("stock", 0)),
                    sku=str(r.get("sku", "")),
                    unit=str(r.get("unit", "units")),
                    description=str(r.get("description", "")),
                ))
            except (ValueError, TypeError):
                continue
        return products

    def _load_from_db(self) -> None:
        try:
            db   = get_db()
            rows = db.fetch_all()
            self.products = self._rows_to_products(rows)
            self.active_category = "All Items"
            print(f"[POS] Loaded {len(self.products)} products from database.")
        except Exception as e:
            print(f"[POS] Could not load products from DB: {e}")
            self.products = []

    def reload_from_db(self) -> int:
        self._load_from_db()
        self.inventory_loaded.emit(len(self.products))
        return len(self.products)

    # ── Cart helpers ──────────────────────────────────────────────────────────

    def add_product(self, product: Product) -> None:
        if product.stock <= 0:
            return
        product.stock -= 1
        for line in self.order_lines:
            if line.product.id == product.id:
                line.qty += 1
                self._recalc()
                return
        self.order_lines.append(OrderLine(product=product))
        self._recalc()

    def increment(self, line: OrderLine) -> None:
        if line.product.stock <= 0:
            return
        line.product.stock -= 1
        line.qty += 1
        self._recalc()

    def decrement(self, line: OrderLine) -> None:
        line.product.stock += 1
        line.qty -= 1
        if line.qty <= 0:
            self.order_lines.remove(line)
        self._recalc()

    def clear_order(self) -> None:
        for line in self.order_lines:
            line.product.stock += line.qty
        self.order_lines.clear()
        self.discount_type = "None"
        self._recalc()

    def _recalc(self) -> None:
        self.subtotal = sum(l.subtotal for l in self.order_lines)
        if self.discount_type != "None":
            self.discount_amount = self.subtotal * DISCOUNT_RATE
        else:
            self.discount_amount = 0.0
        self.total_amount = self.subtotal - self.discount_amount
        self.order_changed.emit()

    def set_discount(self, dtype: str) -> None:
        """Set discount type: 'None', 'PWD', or 'Senior Citizen'."""
        self.discount_type = dtype
        self._recalc()

    def complete_charge(self) -> None:
        """
        Finalise the order:
          1. Save order header + line items to PostgreSQL.
          2. Update product stock in DB.
          3. Clear cart, advance order number.
          4. Emit charge_completed.
        """
        n  = self.order_number
        t  = self.total_amount
        dt = self.discount_type

        try:
            db = get_db()

            # 1. Insert order header
            order_id = db.insert_order({
                "order_number":   n,
                "order_type":     self.order_type,
                "customer_name":  self.customer_name,
                "subtotal":       self.subtotal,
                "discount_type":  self.discount_type,
                "discount_amount": self.discount_amount,
                "total_amount":   self.total_amount,
            })

            # 2. Insert order items
            items = [
                {
                    "product_id": line.product.id,
                    "name":       line.product.name,
                    "category":   line.product.category,
                    "sku":        line.product.sku,
                    "unit_price": line.unit_price,
                    "quantity":   line.qty,
                    "subtotal":   line.subtotal,
                }
                for line in self.order_lines
            ]
            db.insert_order_items(order_id, items)

            # 3. Update stock in DB
            for line in self.order_lines:
                p = line.product
                db.update({
                    "id": p.id, "name": p.name, "sku": p.sku,
                    "category": p.category, "stock": p.stock,
                    "unit": p.unit, "price": p.price,
                    "description": p.description,
                })

        except Exception as e:
            print(f"[POS] Warning: could not persist order to DB: {e}")

        self.order_lines.clear()
        self.order_number += 1
        self.discount_type = "None"
        self._recalc()
        self.charge_completed.emit(n, t, dt)

    # ── CSV / list loaders ────────────────────────────────────────────────────
    _COL_ALIASES = {
        "id":          ["id", "product_id", "item_id"],
        "name":        ["name", "product_name", "item_name", "title"],
        "category":    ["category", "cat", "type", "section"],
        "price":       ["price", "cost", "unit_price", "amount"],
        "stock":       ["stock", "qty", "quantity", "inventory", "count", "available"],
        "sku":         ["sku", "code", "barcode", "product_code"],
        "unit":        ["unit", "unit_of_measure", "uom", "units"],
        "description": ["description", "desc", "details", "note", "size"],
    }

    def _normalize_row(self, headers: list[str], row: dict | list) -> dict:
        if isinstance(row, (list, tuple)):
            row = dict(zip(headers, row))
        row_lower = {k.lower().strip(): v for k, v in row.items()}
        out = {"id": None, "name": "", "category": "Other",
               "price": 0.0, "stock": 0, "sku": "", "unit": "units",
               "description": ""}
        for field_name, aliases in self._COL_ALIASES.items():
            for alias in aliases:
                if alias in row_lower:
                    out[field_name] = row_lower[alias]
                    break
        return out

    def _rows_to_clean_dicts(self, headers: list[str], rows: list) -> list[dict]:
        """Normalize raw rows into clean dicts ready for db.bulk_replace()."""
        clean = []
        for row in rows:
            r = self._normalize_row(headers, row)
            try:
                if not r["name"]:
                    continue
                clean.append({
                    "name":        str(r["name"]),
                    "sku":         str(r.get("sku", "") or ""),
                    "category":    str(r["category"]),
                    "stock":       int(float(str(r["stock"]) or 0)),
                    "unit":        str(r.get("unit", "units") or "units"),
                    "price":       float(
                        str(r["price"]).replace("₱", "").replace(",", "") or 0
                    ),
                    "description": str(r.get("description", "") or ""),
                })
            except (ValueError, TypeError):
                continue
        return clean

    def load_inventory_from_csv(self, filepath: str) -> int:
        """
        Load products from a CSV file and SAVE them to PostgreSQL.
        After saving, reload from DB so the POS reflects actual DB state.
        """
        with open(filepath, newline="", encoding="utf-8") as f:
            reader  = csv.DictReader(f)
            rows    = list(reader)
            headers = [h.lower() for h in (reader.fieldnames or [])]

        clean = self._rows_to_clean_dicts(headers, rows)

        if not clean:
            return 0

        # ── FIX: save to PostgreSQL (was memory-only before) ─────────────────
        db = get_db()
        n  = db.bulk_replace(clean)

        # Reload from DB so product list matches what's actually in PostgreSQL
        self._load_from_db()
        self.inventory_loaded.emit(len(self.products))
        return n

    def load_inventory_from_list(self, data: list[dict]) -> int:
        """
        Load products from a list of dicts and SAVE them to PostgreSQL.
        After saving, reload from DB so the POS reflects actual DB state.
        """
        if not data:
            return 0

        headers = list(data[0].keys())
        clean   = self._rows_to_clean_dicts(headers, data)

        if not clean:
            return 0

        # ── FIX: save to PostgreSQL (was memory-only before) ─────────────────
        db = get_db()
        n  = db.bulk_replace(clean)

        # Reload from DB so product list matches what's actually in PostgreSQL
        self._load_from_db()
        self.inventory_loaded.emit(len(self.products))
        return n

    @property
    def categories(self) -> list[str]:
        cats = ["All Items"]
        seen = set()
        for p in self.products:
            if p.category not in seen:
                cats.append(p.category)
                seen.add(p.category)
        return cats

    @property
    def filtered_products(self) -> list[Product]:
        if self.active_category == "All Items":
            return self.products
        return [p for p in self.products if p.category == self.active_category]


# ─────────────────────────────────────────────────────────────────────────────
# UI Helpers
# ─────────────────────────────────────────────────────────────────────────────
def lbl(text="", bold=False, size=13, color=None, parent=None) -> QLabel:
    w = QLabel(text, parent)
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    w.setFont(f)
    w.setStyleSheet(f"color:{color or C['text']};background:transparent;")
    return w

label = lbl


def hline(parent=None) -> QFrame:
    ln = QFrame(parent)
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setStyleSheet(f"background:{C['border']};max-height:1px;border:none;")
    ln.setFixedHeight(1)
    return ln


def action_btn(text: str, color=None, hover=None) -> QPushButton:
    bg = color or C["accent"]
    hv = hover or "#245f4a"
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:white;border-radius:7px;"
        f"padding:7px 18px;font-weight:700;font-size:13px;border:none;}}"
        f"QPushButton:hover{{background:{hv};}}"
        f"QPushButton:pressed{{background:{hv};}}"
    )
    return b


def status_badge(stock: int) -> QLabel:
    if stock == 0:
        bg, fg, text = C["danger_lt"], C["danger"], "Out of Stock"
    elif stock <= 5:
        bg, fg, text = C["warn_lt"], C["warn"], f"{stock} left"
    else:
        bg, fg, text = C["ok_lt"], C["ok"], f"{stock} in stock"
    w = QLabel(text)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(
        f"background:{bg};color:{fg};border-radius:4px;"
        f"padding:2px 7px;font-size:10px;font-weight:700;border:none;"
    )
    return w


def pill_button(text: str, active=False, parent=None) -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setCheckable(True)
    btn.setChecked(active)
    btn.setFlat(True)
    _style_pill(btn)
    btn.toggled.connect(lambda: _style_pill(btn))
    return btn


def _style_pill(btn: QPushButton):
    if btn.isChecked():
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {C['accent']}; color: white;
                border-radius: 6px; padding: 5px 14px;
                font-weight: 600; border: none;
            }}""")
    else:
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {C['border']}; color: {C['text']};
                border-radius: 6px; padding: 5px 14px; border: none;
            }}
            QPushButton:hover {{ background: #D1D5DB; }}""")


# ─────────────────────────────────────────────────────────────────────────────
# Product Card
# ─────────────────────────────────────────────────────────────────────────────
class ProductCard(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, product: Product, parent=None):
        super().__init__(parent)
        self.product = product
        self.setObjectName("productCard")
        self.setStyleSheet(CARD_QSS)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if product.stock > 0
            else Qt.CursorShape.ForbiddenCursor
        )
        self.setFixedSize(160, 200)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(4)

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge_row.addWidget(status_badge(self.product.stock))
        lay.addLayout(badge_row)

        emoji_lbl = QLabel(CATEGORY_EMOJI.get(self.product.category, "🍽️"))
        emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emoji_lbl.setStyleSheet(
            "font-size:36px;background:#F0EDE8;border-radius:6px;"
            "padding:8px;border:none;"
        )
        lay.addWidget(emoji_lbl)

        name_lbl = lbl(self.product.name, bold=True, size=11)
        name_lbl.setWordWrap(True)
        lay.addWidget(name_lbl)

        lay.addWidget(lbl(self.product.description, size=10, color=C["sub"]))

        lay.addStretch()
        lay.addWidget(lbl(f"₱{self.product.price:.2f}", bold=True, size=12))

    def mousePressEvent(self, e):
        if self.product.stock > 0:
            self.clicked.emit(self.product)
        super().mousePressEvent(e)


# ─────────────────────────────────────────────────────────────────────────────
# Order Line Widget
# ─────────────────────────────────────────────────────────────────────────────
class OrderLineWidget(QWidget):
    inc_clicked = pyqtSignal(object)
    dec_clicked = pyqtSignal(object)

    def __init__(self, line: OrderLine, parent=None):
        super().__init__(parent)
        self.line = line
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(3)

        top = QHBoxLayout()
        top.addWidget(lbl(self.line.product.name, bold=True))
        top.addStretch()
        top.addWidget(lbl(f"₱{self.line.product.price:.2f}", bold=True))
        lay.addLayout(top)

        parts = [self.line.product.description]
        parts += [f"{m} (+₱{v:.2f})" for m, v in self.line.modifiers]
        desc = ", ".join(p for p in parts if p)
        if desc:
            lay.addWidget(lbl(desc, size=10, color=C["sub"]))

        p = self.line.product
        if 0 < p.stock <= 3:
            lay.addWidget(lbl(
                f"⚠ Only {p.stock} remaining in stock",
                size=10, color=C["warn"]
            ))

        qty_row = QHBoxLayout()
        qty_row.setSpacing(6)

        def qty_btn(txt) -> QPushButton:
            b = QPushButton(txt)
            b.setFixedSize(26, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background:{C['border']};border-radius:5px;
                    font-weight:700;font-size:14px;border:none;
                }}
                QPushButton:hover {{ background:#D1D5DB; }}
            """)
            return b

        btn_dec = qty_btn("−")
        btn_inc = qty_btn("+")
        qty_lbl = lbl(str(self.line.qty), bold=True)
        qty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qty_lbl.setFixedWidth(28)

        btn_dec.clicked.connect(lambda: self.dec_clicked.emit(self.line))
        btn_inc.clicked.connect(lambda: self.inc_clicked.emit(self.line))

        qty_row.addWidget(btn_dec)
        qty_row.addWidget(qty_lbl)
        qty_row.addWidget(btn_inc)
        qty_row.addStretch()
        qty_row.addWidget(lbl(
            f"₱{self.line.subtotal:.2f}", bold=True, color=C["accent"]
        ))
        lay.addLayout(qty_row)


# ─────────────────────────────────────────────────────────────────────────────
# Import Inventory Dialog
# ─────────────────────────────────────────────────────────────────────────────
class ImportDialog(QDialog):
    def __init__(self, pos: POSState, parent=None):
        super().__init__(parent)
        self.pos = pos
        self.setWindowTitle("Import / Reload Inventory")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumSize(580, 480)
        self.resize(580, 480)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(pal.ColorRole.Window, QColor(C["white"]))
        self.setPalette(pal)
        self.setStyleSheet(f"""
            QFrame#section {{
                border: 1.5px solid {C['border']};
                border-radius: 12px;
                background: {C['bg']};
            }}
        """)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(14)

        lay.addWidget(lbl("Import / Reload Inventory", bold=True, size=18))
        sub = lbl(
            "Reload live products from the database, or load from a CSV file.\n"
            "⚠  Importing via CSV replaces ALL existing inventory in the database.",
            size=11, color=C["sub"]
        )
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addWidget(hline())

        def make_section(icon, title, hint, highlight=False):
            box = QFrame()
            box.setObjectName("section")
            if highlight:
                box.setStyleSheet(
                    f"QFrame#section{{border:1.5px solid {C['accent']};"
                    f"border-radius:12px;background:{C['accent_lt']};}}"
                )
            bl = QVBoxLayout(box)
            bl.setContentsMargins(20, 14, 20, 14)
            bl.setSpacing(8)
            top = QHBoxLayout()
            top.addWidget(lbl(icon, size=15))
            top.addWidget(lbl(title, bold=True, size=13))
            top.addStretch()
            bl.addLayout(top)
            hint_lbl = lbl(hint, size=10, color=C["sub"])
            hint_lbl.setWordWrap(True)
            bl.addWidget(hint_lbl)
            return box, bl

        db_box, db_bl = make_section(
            "🐘", "Reload from PostgreSQL Database",
            "Re-fetches all products from the connected pawffinated database.",
            highlight=True,
        )
        db_btn = action_btn("Reload from Database")
        db_btn.setFixedHeight(36)
        db_btn.clicked.connect(self._reload_from_db)
        db_bl.addWidget(db_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(db_box)

        csv_box, csv_bl = make_section(
            "📄", "From CSV File",
            "Columns: name, sku, category, price, stock, unit, description  "
            "— saves directly to PostgreSQL."
        )
        csv_btn = action_btn("Browse CSV…", color=C["sub"], hover="#4B5563")
        csv_btn.setFixedHeight(36)
        csv_btn.clicked.connect(self._import_csv)
        csv_bl.addWidget(csv_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(csv_box)

        paste_box, paste_bl = make_section(
            "📋", "Paste CSV Data",
            "Open your CSV in Notepad, select all (Ctrl+A), copy, paste below.  "
            "— saves directly to PostgreSQL."
        )
        self.paste_edit = QTextEdit()
        self.paste_edit.setPlaceholderText(
            "name,category,price,stock,description\n"
            "Classic Latte,Coffee & Espresso,4.50,42,12 oz"
        )
        self.paste_edit.setFixedHeight(70)
        self.paste_edit.setStyleSheet(
            f"QTextEdit{{border:1.5px solid {C['border']};border-radius:8px;"
            f"padding:6px 8px;background:{C['white']};font-size:12px;"
            f"font-family:'Consolas','Courier New',monospace;}}"
        )
        paste_bl.addWidget(self.paste_edit)
        paste_btn = action_btn("Import Pasted Data", color=C["sub"], hover="#4B5563")
        paste_btn.setFixedHeight(36)
        paste_btn.clicked.connect(self._import_paste)
        paste_bl.addWidget(paste_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(paste_box)

        lay.addStretch()

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedSize(90, 34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{C['border']};color:{C['text']};"
            f"border-radius:8px;font-size:13px;font-weight:600;border:none;}}"
            f"QPushButton:hover{{background:#D1D5DB;}}"
        )
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        lay.addLayout(close_row)

    def _reload_from_db(self):
        try:
            n = self.pos.reload_from_db()
            QMessageBox.information(self, "Success",
                                    f"✅ Loaded {n} products from the database.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Database reload failed:\n{e}")

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV", "", "CSV (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            n = self.pos.load_inventory_from_csv(path)
            QMessageBox.information(
                self, "Success",
                f"✅ Loaded {n} products from CSV and saved to PostgreSQL."
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load CSV:\n{e}")

    def _import_paste(self):
        text = self.paste_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Nothing to Import",
                                "Paste some CSV data into the box first.")
            return
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows   = list(reader)
            if not rows:
                QMessageBox.warning(self, "Empty Data",
                                    "No rows found — check your column headers.")
                return
            n = self.pos.load_inventory_from_list(rows)
            QMessageBox.information(
                self, "Success",
                f"✅ Loaded {n} products from pasted data and saved to PostgreSQL."
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Parse error:\n{e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.pos = POSState()
        self.setWindowTitle("Pawffinated – Point of Sale")
        self.resize(1240, 800)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(GLOBAL_QSS)
        self._build_toolbar()
        self._build_ui()
        self._build_statusbar()

        self.pos.order_changed.connect(self._refresh_order_panel)
        self.pos.inventory_loaded.connect(self._on_inventory_loaded)
        self.pos.charge_completed.connect(self._on_charge_complete)

        self._refresh_category_tabs()
        self._refresh_product_grid()
        self._refresh_order_panel()

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))

        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self.db_status_lbl = QLabel()
        self._update_db_status_label()
        tb.addWidget(self.db_status_lbl)

        import_action = QAction("📦  Import / Reload", self)
        import_action.triggered.connect(self._open_import_dialog)
        tb.addAction(import_action)

        new_order_action = QAction("🆕  New Order", self)
        new_order_action.triggered.connect(self._new_order)
        tb.addAction(new_order_action)

    def _update_db_status_label(self):
        count = len(self.pos.products)
        if count:
            self.db_status_lbl.setText(f"🐘  {count} products loaded")
            self.db_status_lbl.setStyleSheet(
                f"color:{C['accent']};font-size:11px;"
                f"border:1px solid {C['accent']};border-radius:5px;"
                f"padding:3px 10px;background:{C['accent_lt']};"
            )
        else:
            self.db_status_lbl.setText("⚠  No products loaded")
            self.db_status_lbl.setStyleSheet(
                f"color:{C['warn']};font-size:11px;"
                f"border:1px solid {C['warn']};border-radius:5px;"
                f"padding:3px 10px;background:{C['warn_lt']};"
            )

    # ── Central UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(PawffinatedSidebar(active_page="Order"))
        self._build_main_area(root)
        self._build_order_panel(root)

    def _build_main_area(self, parent_layout):
        self.main_area = QWidget()
        self.main_area.setStyleSheet(f"background:{C['bg']};")
        ma_lay = QVBoxLayout(self.main_area)
        ma_lay.setContentsMargins(0, 0, 0, 0)
        ma_lay.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(28, 18, 28, 0)
        hdr_lay.setSpacing(4)
        hdr_lay.addWidget(lbl("Orders", bold=True, size=20))
        hdr_lay.addWidget(lbl(
            "Tap items to add to cart. Stock is tracked in real time.",
            size=11, color=C["sub"]
        ))

        self.tab_row = QHBoxLayout()
        self.tab_row.setSpacing(6)
        self.tab_row.setContentsMargins(0, 10, 0, 12)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        hdr_lay.addLayout(self.tab_row)
        ma_lay.addWidget(hdr)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"background:{C['bg']};border:none;")

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet(f"background:{C['bg']};")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(20, 16, 20, 16)
        self.grid_layout.setSpacing(12)

        self.scroll.setWidget(self.grid_container)
        ma_lay.addWidget(self.scroll)
        parent_layout.addWidget(self.main_area, stretch=1)

    # ── Order panel ───────────────────────────────────────────────────────────
    def _build_order_panel(self, parent_layout):
        self.order_panel = QWidget()
        self.order_panel.setObjectName("orderPanel")
        self.order_panel.setFixedWidth(320)
        self.order_panel.setStyleSheet(ORDER_QSS)

        op_lay = QVBoxLayout(self.order_panel)
        op_lay.setContentsMargins(0, 0, 0, 0)
        op_lay.setSpacing(0)

        # Header
        op_hdr = QWidget()
        op_hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        oh_lay = QVBoxLayout(op_hdr)
        oh_lay.setContentsMargins(18, 14, 18, 0)
        oh_lay.setSpacing(6)

        top_row = QHBoxLayout()
        self.order_title = lbl(f"Order #{self.pos.order_number}", bold=True, size=16)
        menu_btn = QPushButton("⋮")
        menu_btn.setFlat(True)
        menu_btn.setFixedSize(28, 28)
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.setStyleSheet(
            f"QPushButton{{border:none;background:transparent;"
            f"color:{C['sub']};font-size:18px;font-weight:700;}}"
            f"QPushButton:hover{{background:{C['bg']};border-radius:5px;}}"
        )
        menu_btn.clicked.connect(self._order_context_menu)
        top_row.addWidget(self.order_title)
        top_row.addStretch()
        top_row.addWidget(menu_btn)
        oh_lay.addLayout(top_row)

        self.customer_lbl = lbl(self.pos.customer_name, size=10, color=C["sub"])
        oh_lay.addWidget(self.customer_lbl)

        # Order type toggle
        type_row = QHBoxLayout()
        type_row.setSpacing(0)
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        for ot in ["Dine In", "Takeout", "Delivery"]:
            b = QPushButton(ot)
            b.setCheckable(True)
            b.setChecked(ot == self.pos.order_type)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(32)
            b.setStyleSheet(self._type_btn_qss(ot == self.pos.order_type))
            b.toggled.connect(lambda checked, btn=b, t=ot:
                              self._set_order_type(t, btn, checked))
            self.type_group.addButton(b)
            type_row.addWidget(b)
        oh_lay.addLayout(type_row)
        oh_lay.addSpacing(6)
        op_lay.addWidget(op_hdr)

        # Scrollable order lines
        self.order_scroll = QScrollArea()
        self.order_scroll.setWidgetResizable(True)
        self.order_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.order_scroll.setStyleSheet("border:none;background:white;")
        self.order_lines_widget = QWidget()
        self.order_lines_widget.setStyleSheet("background:white;")
        self.order_lines_layout = QVBoxLayout(self.order_lines_widget)
        self.order_lines_layout.setContentsMargins(0, 0, 0, 0)
        self.order_lines_layout.setSpacing(0)
        self.order_lines_layout.addStretch()
        self.order_scroll.setWidget(self.order_lines_widget)
        op_lay.addWidget(self.order_scroll, stretch=1)

        # Footer
        self.order_footer = QWidget()
        self.order_footer.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        self.footer_lay = QVBoxLayout(self.order_footer)
        self.footer_lay.setContentsMargins(18, 12, 18, 16)
        self.footer_lay.setSpacing(6)
        op_lay.addWidget(self.order_footer)

        parent_layout.addWidget(self.order_panel)

    def _type_btn_qss(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton{{background:{C['white']};color:{C['text']};"
                f"border:1px solid {C['border']};font-weight:700;"
                f"padding:0 10px;border-radius:0;}}"
            )
        return (
            f"QPushButton{{background:{C['border']};color:{C['sub']};"
            f"border:none;padding:0 10px;border-radius:0;}}"
            f"QPushButton:hover{{background:#D1D5DB;}}"
        )

    def _set_order_type(self, ot: str, btn: QPushButton, checked: bool):
        if checked:
            self.pos.order_type = ot
            for b in self.type_group.buttons():
                b.setStyleSheet(self._type_btn_qss(b is btn))

    # ── Category tabs ─────────────────────────────────────────────────────────
    def _refresh_category_tabs(self):
        for i in reversed(range(self.tab_row.count())):
            item = self.tab_row.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
                self.tab_row.removeItem(item)
        for b in self.tab_group.buttons():
            self.tab_group.removeButton(b)

        for cat in self.pos.categories:
            btn = pill_button(cat, active=(cat == self.pos.active_category))
            self.tab_group.addButton(btn)
            self.tab_row.addWidget(btn)
            btn.clicked.connect(lambda _, c=cat: self._select_category(c))
        self.tab_row.addStretch()

    def _select_category(self, cat: str):
        self.pos.active_category = cat
        self._refresh_product_grid()

    # ── Product grid ──────────────────────────────────────────────────────────
    def _refresh_product_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        products = self.pos.filtered_products

        if not products:
            empty = lbl(
                "No products found.\nClick '📦 Import / Reload' to load from the database.",
                color=C["sub"]
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 60, 0, 0)
            self.grid_layout.addWidget(empty, 0, 0)
            return

        cols = max(1, (self.main_area.width() - 40) // 176)
        for i, prod in enumerate(products):
            pc = ProductCard(prod)
            pc.clicked.connect(self._on_product_clicked)
            self.grid_layout.addWidget(pc, i // cols, i % cols)

        last      = len(products)
        fill_cols = cols - (last % cols)
        if fill_cols != cols:
            for j in range(fill_cols):
                spacer = QWidget()
                spacer.setFixedWidth(160)
                self.grid_layout.addWidget(
                    spacer, (last - 1) // cols, (last % cols) + j
                )

    def _on_product_clicked(self, product: Product) -> None:
        self.pos.add_product(product)
        self._refresh_product_grid()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._refresh_product_grid)

    # ── Order panel refresh ───────────────────────────────────────────────────
    def _refresh_order_panel(self):
        self.order_title.setText(f"Order #{self.pos.order_number}")
        self.customer_lbl.setText(self.pos.customer_name)

        while self.order_lines_layout.count() > 1:
            item = self.order_lines_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.pos.order_lines:
            empty = label("No items yet.\nTap a product to add.", color=C['sub'])
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 30, 0, 0)
            self.order_lines_layout.insertWidget(0, empty)
        else:
            for i, line in enumerate(self.pos.order_lines):
                lw = OrderLineWidget(line)
                lw.inc_clicked.connect(self.pos.increment)
                lw.dec_clicked.connect(self.pos.decrement)
                self.order_lines_layout.insertWidget(i, lw)
                if i < len(self.pos.order_lines) - 1:
                    self.order_lines_layout.insertWidget(i + 1, hline())

        # Rebuild footer
        for i in reversed(range(self.footer_lay.count())):
            item = self.footer_lay.takeAt(i)
            if item.widget():
                item.widget().deleteLater()

        def summary_row(label_text, value, bold=False, big=False,
                        label_color=None, value_color=None):
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            row.setSpacing(8)
            l_color = label_color or (C["text"] if big else C["sub"])
            v_color = value_color or C["text"]
            l_w = lbl(label_text, bold=bold or big,
                      size=15 if big else 12, color=l_color)
            v_w = lbl(f"₱{value:.2f}", bold=bold or big,
                      size=15 if big else 12, color=v_color)
            v_w.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            row.addWidget(l_w)
            row.addStretch()
            row.addWidget(v_w)
            wrap = QWidget()
            wrap.setStyleSheet("background:transparent;")
            wrap.setMinimumHeight(28 if big else 22)
            wrap.setLayout(row)
            self.footer_lay.addWidget(wrap)

        summary_row("Subtotal", self.pos.subtotal)

        # ── Discount selector (PWD / Senior Citizen) ──────────────────────────
        disc_outer = QWidget()
        disc_outer.setStyleSheet(
            f"background:{C['purple_lt']};border-radius:8px;"
        )
        disc_inner = QVBoxLayout(disc_outer)
        disc_inner.setContentsMargins(10, 8, 10, 8)
        disc_inner.setSpacing(6)

        disc_title_row = QHBoxLayout()
        disc_title_row.addWidget(
            lbl("Discount", bold=True, size=11, color=C["purple"])
        )
        disc_title_row.addWidget(
            lbl("PWD / Senior Citizen (20%)", size=10, color=C["purple"])
        )
        disc_title_row.addStretch()
        disc_inner.addLayout(disc_title_row)

        disc_btn_row = QHBoxLayout()
        disc_btn_row.setSpacing(6)
        disc_group = QButtonGroup(disc_outer)
        disc_group.setExclusive(True)

        for dtype in DISCOUNT_TYPES:
            btn = QPushButton(dtype)
            btn.setCheckable(True)
            btn.setChecked(dtype == self.pos.discount_type)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            active = dtype == self.pos.discount_type
            btn.setStyleSheet(self._disc_btn_qss(active))
            btn.toggled.connect(
                lambda checked, b=btn, d=dtype: self._on_discount_toggled(d, b, checked)
            )
            disc_group.addButton(btn)
            disc_btn_row.addWidget(btn)
        disc_inner.addLayout(disc_btn_row)

        if self.pos.discount_type != "None":
            disc_val_row = QHBoxLayout()
            disc_val_row.addWidget(
                lbl(f"−20% ({self.pos.discount_type})", size=11, color=C["purple"])
            )
            disc_val_row.addStretch()
            disc_val_row.addWidget(
                lbl(f"−₱{self.pos.discount_amount:.2f}", bold=True,
                    size=12, color=C["purple"])
            )
            disc_inner.addLayout(disc_val_row)

        self.footer_lay.addWidget(disc_outer)

        self.footer_lay.addWidget(hline())
        summary_row("Total", self.pos.total_amount, big=True,
                    value_color=C["accent"])

        charge_btn = QPushButton(f"  Charge  ₱{self.pos.total_amount:.2f}  ")
        charge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        charge_btn.setFixedHeight(48)
        charge_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C['accent']}; color: white;
                border-radius: 8px; font-size: 15px; font-weight: 700;
                border: none;
            }}
            QPushButton:hover {{ background: #245f4a; }}
            QPushButton:pressed {{ background: #1a4a38; }}
        """)
        charge_btn.clicked.connect(self._charge)
        self.footer_lay.addWidget(charge_btn)

        disc_info = ""
        if self.pos.discount_type != "None":
            disc_info = f"  |  {self.pos.discount_type}: −₱{self.pos.discount_amount:.2f}"

        self.status_items.setText(
            f"Items: {sum(l.qty for l in self.pos.order_lines)}  |  "
            f"Subtotal: ₱{self.pos.subtotal:.2f}"
            f"{disc_info}  |  "
            f"Total: ₱{self.pos.total_amount:.2f}"
        )

    def _disc_btn_qss(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton{{background:{C['purple']};color:white;"
                f"border-radius:5px;padding:2px 10px;"
                f"font-weight:700;font-size:11px;border:none;}}"
            )
        return (
            f"QPushButton{{background:transparent;color:{C['purple']};"
            f"border:1px solid {C['purple']};border-radius:5px;"
            f"padding:2px 10px;font-size:11px;}}"
            f"QPushButton:hover{{background:{C['purple_lt']};}}"
        )

    def _on_discount_toggled(self, dtype: str, btn: QPushButton, checked: bool):
        if checked:
            self.pos.set_discount(dtype)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _charge(self):
        if not self.pos.order_lines:
            QMessageBox.warning(self, "Empty Order", "Add items before charging.")
            return

        disc_line = ""
        if self.pos.discount_type != "None":
            disc_line = (
                f"\nDiscount ({self.pos.discount_type}, 20%): "
                f"−₱{self.pos.discount_amount:.2f}"
            )

        reply = QMessageBox.question(
            self, "Confirm Charge",
            f"{self.pos.order_type} – Order #{self.pos.order_number}\n"
            f"Customer: {self.pos.customer_name}\n\n"
            f"Subtotal: ₱{self.pos.subtotal:.2f}"
            f"{disc_line}\n"
            f"Total: ₱{self.pos.total_amount:.2f}\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.pos.complete_charge()
            self._refresh_product_grid()

    def _on_charge_complete(self, order_num: int, total: float, discount_type: str):
        disc_msg = ""
        if discount_type != "None":
            disc_msg = f"\n🪪 {discount_type} discount applied."
        QMessageBox.information(
            self, "Payment Successful",
            f"✅ Order #{order_num} charged ₱{total:.2f}"
            f"{disc_msg}\nThank you, have a great day!"
        )

    def _new_order(self):
        if self.pos.order_lines:
            r = QMessageBox.question(
                self, "New Order",
                "Clear current order and start fresh?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        self.pos.clear_order()
        self._refresh_product_grid()

    def _order_context_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{C['white']};border:1px solid {C['border']};"
            f"border-radius:8px;padding:4px;}}"
            f"QMenu::item{{padding:8px 20px;border-radius:4px;}}"
            f"QMenu::item:selected{{background:{C['accent_lt']};}}"
        )
        menu.addAction("Clear Order",     self._clear_order_from_menu)
        menu.addAction("Change Customer", self._change_customer)
        menu.addSeparator()
        menu.addAction("Print Receipt",   self._print_receipt)
        menu.exec(self.cursor().pos())

    def _clear_order_from_menu(self):
        self.pos.clear_order()
        self._refresh_product_grid()

    def _change_customer(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Change Customer")
        dlg.setFixedSize(320, 130)
        dlg.setAutoFillBackground(True)
        pal = dlg.palette()
        pal.setColor(pal.ColorRole.Window, QColor(C["white"]))
        dlg.setPalette(pal)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(lbl("Customer Name:", bold=True))
        entry = QLineEdit(self.pos.customer_name)
        entry.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:7px;"
            f"padding:7px 10px;background:{C['bg']};font-size:13px;"
        )
        lay.addWidget(entry)
        save_btn = action_btn("Save")
        save_btn.clicked.connect(lambda: (
            setattr(self.pos, "customer_name",
                    entry.text().strip() or "Walk-in Customer"),
            self._refresh_order_panel(),
            dlg.accept(),
        ))
        lay.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def _print_receipt(self):
        if not self.pos.order_lines:
            QMessageBox.information(self, "Receipt", "No items to print.")
            return
        lines = [
            f"PAWFFINATED  –  Order #{self.pos.order_number}",
            f"Type: {self.pos.order_type}",
            f"Customer: {self.pos.customer_name}",
            "─" * 36,
        ]
        for l in self.pos.order_lines:
            lines.append(f"{l.product.name:25s}  x{l.qty}  ₱{l.subtotal:>8.2f}")
        lines += [
            "─" * 36,
            f"{'Subtotal':30s}  ₱{self.pos.subtotal:>8.2f}",
        ]
        if self.pos.discount_type != "None":
            lines.append(
                f"{self.pos.discount_type + ' Discount (20%)':30s}"
                f"  −₱{self.pos.discount_amount:>7.2f}"
            )
        lines.append(f"{'TOTAL':30s}  ₱{self.pos.total_amount:>8.2f}")
        QMessageBox.information(self, "Receipt", "\n".join(lines))

    def _open_import_dialog(self):
        dlg = ImportDialog(self.pos, self)
        dlg.exec()
        self._refresh_category_tabs()
        self._refresh_product_grid()
        self._update_db_status_label()

    def _on_inventory_loaded(self, count: int):
        self._update_db_status_label()
        self._refresh_category_tabs()
        self._refresh_product_grid()
        self._flash(f"✅ Inventory updated — {count} products loaded.")

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        sb = self.statusBar()
        self.status_items = QLabel()
        self.status_msg   = QLabel()
        self.status_msg.setStyleSheet(f"color:{C['accent']};font-weight:600;")
        sb.addWidget(self.status_items)
        sb.addPermanentWidget(self.status_msg)

    def _flash(self, msg: str, ms: int = 4000):
        self.status_msg.setText(msg)
        QTimer.singleShot(ms, lambda: self.status_msg.setText(""))


# ─────────────────────────────────────────────────────────────────────────────
# App entry point
# ─────────────────────────────────────────────────────────────────────────────
class PawffinatedApp(QApplication):
    def __init__(self, argv=None):
        super().__init__(argv or sys.argv)
        self.setApplicationName("Pawffinated POS")
        self.window = MainWindow()

    def run(self):
        self.window.show()
        return self.exec()


if __name__ == "__main__":
    app = PawffinatedApp(sys.argv)
    sys.exit(app.run())
