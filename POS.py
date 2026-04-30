"""
PAWFFINATED – Point of Sale System  (PyQt6 Edition)
====================================================
Install:
    pip install PyQt6

Run:
    python pawffinated_pos_qt.py

─── EXPOSED VARIABLES (access from outside) ────────────────────────────────
    app  = PawffinatedApp(sys.argv)
    win  = app.window                        # main POS window

    win.pos.order_lines          → list[OrderLine]
    win.pos.subtotal             → float
    win.pos.tax_amount           → float
    win.pos.total_amount         → float
    win.pos.order_number         → int
    win.pos.order_type           → str  ("Dine In" | "Takeout" | "Delivery")
    win.pos.customer_name        → str
    win.pos.products             → list[Product]
    win.pos.active_category      → str

    win.pos.order_changed        → pyqtSignal  (emitted on every cart change)
    win.pos.charge_completed     → pyqtSignal(int, float)  (order#, total)

─── INVENTORY IMPORT ────────────────────────────────────────────────────────
    From the GUI  → click "Import Inventory" button (toolbar)
    Programmatic  → win.pos.load_inventory_from_query(conn, query)
                    win.pos.load_inventory_from_csv("path/to/file.csv")
                    win.pos.load_inventory_from_list([ {...}, ... ])

    Expected columns (case-insensitive, flexible aliases):
        id | name | category | price | stock | description

    SQLite example:
        import sqlite3, sys
        from PyQt6.QtWidgets import QApplication
        from pawffinated_pos_qt import PawffinatedApp, MainWindow

        conn = sqlite3.connect("cafe.db")
        app  = PawffinatedApp(sys.argv)
        win  = app.window
        win.pos.load_inventory_from_query(conn, "SELECT * FROM products")
        win.show()
        sys.exit(app.exec())
"""

from __future__ import annotations
import sys, csv, io, sqlite3
from dataclasses import dataclass, field
from typing import Optional, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QGridLayout, QHBoxLayout, QVBoxLayout, QSizePolicy,
    QButtonGroup, QFileDialog, QDialog, QLineEdit, QTextEdit,
    QMessageBox, QToolBar, QStatusBar, QSplitter, QSpacerItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QPixmap, QIcon, QAction

from Sidebar import PawffinatedSidebar

# ── Palette ──────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    sidebar   = "#FFFFFF",
    card      = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_lt = "#E8F4F0",
    warn      = "#E07B39",
    danger    = "#D94F4F",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    border    = "#E5E7EB",
    white     = "#FFFFFF",
    badge_ok  = "#D1FAE5",
    badge_ok_t= "#065F46",
)

TAX_RATE = 0.085

CATEGORY_EMOJI = {
    "Coffee & Espresso": "☕",
    "Cold Beverages":    "🧊",
    "Pastries":          "🥐",
    "Sandwiches":        "🥪",
    "Merchandise":       "🛍️",
}

# ── Domain models ─────────────────────────────────────────────────────────────
@dataclass
class Product:
    id: int
    name: str
    category: str
    price: float
    stock: int
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


# ── Default demo inventory ────────────────────────────────────────────────────
DEFAULT_PRODUCTS: list[Product] = [
    Product(1,  "Classic Latte",       "Coffee & Espresso", 4.50, 42, "12 oz"),
    Product(2,  "Almond Croissant",    "Pastries",          3.75,  3, "Bakery"),
    Product(3,  "Iced Macchiato",      "Coffee & Espresso", 5.25, 28, "16 oz"),
    Product(4,  "Turkey Avocado",      "Sandwiches",        8.50,  0, "Sandwiches"),
    Product(5,  "Choc Chip Cookie",    "Pastries",          2.50, 18, "Bakery"),
    Product(6,  "House Blend Beans",   "Merchandise",      16.00, 15, "1 lb Bag"),
    Product(7,  "Matcha Latte",        "Coffee & Espresso", 5.00, 56, "12 oz"),
    Product(8,  "Blueberry Muffin",    "Pastries",          3.50,  5, "Bakery"),
    Product(9,  "Cold Brew",           "Cold Beverages",    4.75, 22, "16 oz"),
    Product(10, "Vanilla Frappé",      "Cold Beverages",    5.50, 10, "16 oz"),
    Product(11, "Bagel & Cream Cheese","Sandwiches",        6.00,  8, "Sandwiches"),
    Product(12, "Cinnamon Roll",       "Pastries",          4.00, 12, "Bakery"),
]


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

SIDEBAR_QSS = f"""
QWidget#sidebar {{
    background: {C['sidebar']};
    border-right: 1px solid {C['border']};
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
# POS State Object  ← all exposed variables live here
# ─────────────────────────────────────────────────────────────────────────────
class POSState(QObject):
    """
    Central state for the POS.  All important data is a plain attribute
    so external code can read/write directly:

        state.total_amount   → float
        state.order_lines    → list[OrderLine]
        state.products       → list[Product]
        etc.
    """

    # Signals
    order_changed    = pyqtSignal()               # emitted on every cart mutation
    charge_completed = pyqtSignal(int, float)     # (order_number, total)
    inventory_loaded = pyqtSignal(int)            # number of products loaded

    def __init__(self):
        super().__init__()
        # ── Cart state ───────────────────────────────────────
        self.order_lines:   list[OrderLine] = []
        self.order_number:  int  = 1042
        self.order_type:    str  = "Dine In"
        self.customer_name: str  = "Walk-in Customer"

        # ── Computed (updated by _recalc) ────────────────────
        self.subtotal:    float = 0.0
        self.tax_amount:  float = 0.0
        self.total_amount:float = 0.0

        # ── Inventory ────────────────────────────────────────
        self.products:         list[Product] = list(DEFAULT_PRODUCTS)
        self.active_category:  str = "All Items"

    # ── Cart helpers ──────────────────────────────────────────────────────────
    def add_product(self, product: Product) -> None:
        if product.stock == 0:
            return
        for line in self.order_lines:
            if line.product.id == product.id:
                line.qty += 1
                self._recalc()
                return
        self.order_lines.append(OrderLine(product=product))
        self._recalc()

    def increment(self, line: OrderLine) -> None:
        line.qty += 1
        self._recalc()

    def decrement(self, line: OrderLine) -> None:
        line.qty -= 1
        if line.qty <= 0:
            self.order_lines.remove(line)
        self._recalc()

    def clear_order(self) -> None:
        self.order_lines.clear()
        self._recalc()

    def _recalc(self) -> None:
        self.subtotal     = sum(l.subtotal for l in self.order_lines)
        self.tax_amount   = self.subtotal * TAX_RATE
        self.total_amount = self.subtotal + self.tax_amount
        self.order_changed.emit()

    def complete_charge(self) -> None:
        n = self.order_number
        t = self.total_amount
        self.order_lines.clear()
        self.order_number += 1
        self._recalc()
        self.charge_completed.emit(n, t)

    # ── Inventory loaders ─────────────────────────────────────────────────────
    _COL_ALIASES = {
        "id": ["id", "product_id", "item_id"],
        "name": ["name", "product_name", "item_name", "title"],
        "category": ["category", "cat", "type", "section"],
        "price": ["price", "cost", "unit_price", "amount"],
        "stock": ["stock", "qty", "quantity", "inventory", "count", "available"],
        "description": ["description", "desc", "details", "note", "size"],
    }

    def _normalize_row(self, headers: list[str], row: dict | list) -> dict:
        """Map flexible column names → standard field names."""
        if isinstance(row, (list, tuple)):
            row = dict(zip(headers, row))
        row_lower = {k.lower().strip(): v for k, v in row.items()}
        out = {"id": None, "name": "", "category": "Other",
               "price": 0.0, "stock": 0, "description": ""}
        for field_name, aliases in self._COL_ALIASES.items():
            for alias in aliases:
                if alias in row_lower:
                    out[field_name] = row_lower[alias]
                    break
        return out

    def _rows_to_products(self, headers: list[str],
                          rows: list) -> list[Product]:
        products = []
        for i, row in enumerate(rows):
            r = self._normalize_row(headers, row)
            try:
                pid   = int(r["id"]) if r["id"] is not None else i + 1
                price = float(str(r["price"]).replace("$", "").replace(",", ""))
                stock = int(r["stock"])
                products.append(Product(
                    id=pid, name=str(r["name"]),
                    category=str(r["category"]),
                    price=price, stock=stock,
                    description=str(r["description"]),
                ))
            except (ValueError, TypeError):
                continue
        return products

    def load_inventory_from_query(self, connection: Any,
                                   query: str,
                                   params: tuple = ()) -> int:
        """
        Load products from any DB-API 2.0 connection.

        Example:
            import sqlite3
            conn = sqlite3.connect("cafe.db")
            n = state.load_inventory_from_query(conn, "SELECT * FROM menu")
        """
        cursor = connection.cursor()
        cursor.execute(query, params)
        headers = [d[0].lower() for d in cursor.description]
        rows    = cursor.fetchall()
        self.products = self._rows_to_products(headers, rows)
        self.active_category = "All Items"
        self.inventory_loaded.emit(len(self.products))
        return len(self.products)

    def load_inventory_from_csv(self, filepath: str) -> int:
        """
        Load products from a CSV file.

        Example:
            state.load_inventory_from_csv("/data/menu.csv")
        """
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows   = list(reader)
            headers = [h.lower() for h in (reader.fieldnames or [])]
        self.products = self._rows_to_products(headers, rows)
        self.active_category = "All Items"
        self.inventory_loaded.emit(len(self.products))
        return len(self.products)

    def load_inventory_from_list(self, data: list[dict]) -> int:
        """
        Load products from a list of dicts.

        Example:
            state.load_inventory_from_list([
                {"name": "Espresso", "category": "Coffee", "price": 3.00, "stock": 99},
            ])
        """
        headers = list(data[0].keys()) if data else []
        self.products = self._rows_to_products(headers, data)
        self.active_category = "All Items"
        self.inventory_loaded.emit(len(self.products))
        return len(self.products)

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
def label(text="", bold=False, size=13, color=C['text'],
          parent=None) -> QLabel:
    lbl = QLabel(text, parent)
    f   = QFont("Segoe UI", size)
    f.setBold(bold)
    lbl.setFont(f)
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    return lbl


def hline(parent=None) -> QFrame:
    ln = QFrame(parent)
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setStyleSheet(f"background: {C['border']}; max-height: 1px;")
    return ln


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
                font-weight: 600;
            }}""")
    else:
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {C['border']}; color: {C['text']};
                border-radius: 6px; padding: 5px 14px;
            }}
            QPushButton:hover {{
                background: #D1D5DB;
            }}""")


# ─────────────────────────────────────────────────────────────────────────────
# Product Card
# ─────────────────────────────────────────────────────────────────────────────
class ProductCard(QFrame):
    clicked = pyqtSignal(object)   # emits Product

    def __init__(self, product: Product, parent=None):
        super().__init__(parent)
        self.product = product
        self.setObjectName("productCard")
        self.setStyleSheet(CARD_QSS)
        self.setCursor(Qt.CursorShape.PointingHandCursor
                       if product.stock > 0
                       else Qt.CursorShape.ForbiddenCursor)
        self.setFixedSize(160, 200)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(4)

        # Badge row
        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge = QLabel()
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.product.stock == 0:
            badge.setText("Out of stock")
            badge.setStyleSheet(f"background:{C['danger']};color:white;"
                                f"border-radius:4px;padding:2px 7px;font-size:10px;font-weight:600;")
        elif self.product.stock <= 5:
            badge.setText(f"{self.product.stock} left")
            badge.setStyleSheet(f"background:{C['warn']};color:white;"
                                f"border-radius:4px;padding:2px 7px;font-size:10px;font-weight:600;")
        else:
            badge.setText(f"{self.product.stock} in stock")
            badge.setStyleSheet(f"background:{C['badge_ok']};color:{C['badge_ok_t']};"
                                f"border-radius:4px;padding:2px 7px;font-size:10px;")
        badge_row.addWidget(badge)
        lay.addLayout(badge_row)

        # Emoji thumbnail
        emoji_lbl = QLabel(CATEGORY_EMOJI.get(self.product.category, "🍽️"))
        emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emoji_lbl.setStyleSheet(f"font-size:36px;background:#F0EDE8;"
                                f"border-radius:6px;padding:8px;")
        lay.addWidget(emoji_lbl)

        # Name
        name_lbl = label(self.product.name, bold=True, size=11)
        name_lbl.setWordWrap(True)
        lay.addWidget(name_lbl)

        # Description
        lay.addWidget(label(self.product.description, size=10, color=C['sub']))

        # Price
        lay.addStretch()
        lay.addWidget(label(f"${self.product.price:.2f}", bold=True, size=12))

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

        # Name + price row
        top = QHBoxLayout()
        top.addWidget(label(self.line.product.name, bold=True))
        top.addStretch()
        top.addWidget(label(f"${self.line.product.price:.2f}", bold=True))
        lay.addLayout(top)

        # Description / modifiers
        parts = [self.line.product.description]
        parts += [f"{m} (+${v:.2f})" for m, v in self.line.modifiers]
        desc = ", ".join(p for p in parts if p)
        if desc:
            lay.addWidget(label(desc, size=10, color=C['sub']))

        # Stock warning
        p = self.line.product
        if 0 < p.stock <= 5:
            lay.addWidget(label(f"⚠ Stock warning: {p.stock} remaining",
                                size=10, color=C['warn']))

        # Qty row
        qty_row = QHBoxLayout()
        qty_row.setSpacing(6)

        def qty_btn(txt) -> QPushButton:
            b = QPushButton(txt)
            b.setFixedSize(26, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background:{C['border']}; border-radius:5px;
                    font-weight:700; font-size:14px;
                }}
                QPushButton:hover {{ background:#D1D5DB; }}
            """)
            return b

        btn_dec = qty_btn("−")
        btn_inc = qty_btn("+")
        qty_lbl = label(str(self.line.qty), bold=True)
        qty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qty_lbl.setFixedWidth(28)

        btn_dec.clicked.connect(lambda: self.dec_clicked.emit(self.line))
        btn_inc.clicked.connect(lambda: self.inc_clicked.emit(self.line))

        qty_row.addWidget(btn_dec)
        qty_row.addWidget(qty_lbl)
        qty_row.addWidget(btn_inc)
        qty_row.addStretch()

        # Line subtotal
        qty_row.addWidget(label(f"${self.line.subtotal:.2f}", bold=True,
                                color=C['accent']))
        lay.addLayout(qty_row)


# ─────────────────────────────────────────────────────────────────────────────
# Import Inventory Dialog
# ─────────────────────────────────────────────────────────────────────────────
class ImportDialog(QDialog):
    def __init__(self, pos: POSState, parent=None):
        super().__init__(parent)
        self.pos = pos
        self.setWindowTitle("Import Inventory")
        self.setMinimumSize(560, 420)
        self.setStyleSheet(f"background:{C['white']};")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(24, 20, 24, 20)

        lay.addWidget(label("Import Inventory", bold=True, size=16))
        lay.addWidget(label("Choose a source to replace the current product list.",
                            color=C['sub']))
        lay.addWidget(hline())

        # ── CSV ──
        csv_box = QFrame()
        csv_box.setStyleSheet(f"border:1px solid {C['border']};border-radius:8px;")
        csv_lay = QVBoxLayout(csv_box)
        csv_lay.addWidget(label("📄  From CSV File", bold=True))
        csv_lay.addWidget(label("Columns: id, name, category, price, stock, description",
                                size=10, color=C['sub']))
        csv_btn = QPushButton("Browse CSV…")
        csv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        csv_btn.setStyleSheet(self._btn_qss())
        csv_btn.clicked.connect(self._import_csv)
        csv_lay.addWidget(csv_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(csv_box)

        # ── SQL Query ──
        sql_box = QFrame()
        sql_box.setStyleSheet(f"border:1px solid {C['border']};border-radius:8px;")
        sql_lay = QVBoxLayout(sql_box)
        sql_lay.addWidget(label("🗄️  From SQLite Database + Query", bold=True))

        db_row = QHBoxLayout()
        self.db_path = QLineEdit()
        self.db_path.setPlaceholderText("Path to .db file…")
        self.db_path.setStyleSheet(self._input_qss())
        db_browse = QPushButton("Browse…")
        db_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        db_browse.setStyleSheet(self._btn_qss(secondary=True))
        db_browse.clicked.connect(self._browse_db)
        db_row.addWidget(self.db_path)
        db_row.addWidget(db_browse)
        sql_lay.addLayout(db_row)

        sql_lay.addWidget(label("SQL Query:", size=11))
        self.query_edit = QTextEdit()
        self.query_edit.setPlaceholderText("SELECT id, name, category, price, stock, description FROM products")
        self.query_edit.setText("SELECT * FROM products")
        self.query_edit.setFixedHeight(70)
        self.query_edit.setStyleSheet(self._input_qss())
        sql_lay.addWidget(self.query_edit)

        run_btn = QPushButton("Run Query & Import")
        run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        run_btn.setStyleSheet(self._btn_qss())
        run_btn.clicked.connect(self._import_sql)
        sql_lay.addWidget(run_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(sql_box)

        # ── Paste JSON/CSV ──
        paste_box = QFrame()
        paste_box.setStyleSheet(f"border:1px solid {C['border']};border-radius:8px;")
        paste_lay = QVBoxLayout(paste_box)
        paste_lay.addWidget(label("📋  Paste CSV Data", bold=True))
        self.paste_edit = QTextEdit()
        self.paste_edit.setPlaceholderText(
            "name,category,price,stock,description\n"
            "Classic Latte,Coffee & Espresso,4.50,42,12 oz")
        self.paste_edit.setFixedHeight(80)
        self.paste_edit.setStyleSheet(self._input_qss())
        paste_lay.addWidget(self.paste_edit)
        paste_btn = QPushButton("Import Pasted CSV")
        paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        paste_btn.setStyleSheet(self._btn_qss())
        paste_btn.clicked.connect(self._import_paste)
        paste_lay.addWidget(paste_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(paste_box)

        lay.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(self._btn_qss(secondary=True))
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _btn_qss(self, secondary=False):
        bg = C['border'] if secondary else C['accent']
        fg = C['text']   if secondary else "white"
        return (f"QPushButton {{ background:{bg}; color:{fg};"
                f"border-radius:6px; padding:6px 16px; font-weight:600; border:none;}}"
                f"QPushButton:hover {{ opacity:0.85; }}")

    def _input_qss(self):
        return (f"QLineEdit, QTextEdit {{"
                f"border:1px solid {C['border']}; border-radius:6px;"
                f"padding:5px 8px; background:{C['bg']}; }}")

    def _browse_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select SQLite DB", "",
                                              "SQLite (*.db *.sqlite *.sqlite3);;All Files (*)")
        if path:
            self.db_path.setText(path)

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "",
                                              "CSV (*.csv);;All Files (*)")
        if not path:
            return
        try:
            n = self.pos.load_inventory_from_csv(path)
            QMessageBox.information(self, "Success", f"✅ Loaded {n} products from CSV.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load CSV:\n{e}")

    def _import_sql(self):
        db  = self.db_path.text().strip()
        qry = self.query_edit.toPlainText().strip()
        if not db or not qry:
            QMessageBox.warning(self, "Missing Info", "Please provide a DB path and query.")
            return
        try:
            conn = sqlite3.connect(db)
            n    = self.pos.load_inventory_from_query(conn, qry)
            conn.close()
            QMessageBox.information(self, "Success", f"✅ Loaded {n} products from database.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Query failed:\n{e}")

    def _import_paste(self):
        text = self.paste_edit.toPlainText().strip()
        if not text:
            return
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows   = list(reader)
            n = self.pos.load_inventory_from_list(rows)
            QMessageBox.information(self, "Success", f"✅ Loaded {n} products from pasted data.")
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

        # Wire signals
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

        lbl = QLabel("  🐾  PAWFFINATED  ")
        lbl.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(lbl)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        import_action = QAction("📦  Import Inventory", self)
        import_action.setToolTip("Load products from CSV or SQL database")
        import_action.triggered.connect(self._open_import_dialog)
        tb.addAction(import_action)

        new_order_action = QAction("🆕  New Order", self)
        new_order_action.triggered.connect(self._new_order)
        tb.addAction(new_order_action)

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

    # ── Main area ─────────────────────────────────────────────────────────────
    def _build_main_area(self, parent_layout):
        self.main_area = QWidget()
        self.main_area.setStyleSheet(f"background:{C['bg']};")
        ma_lay = QVBoxLayout(self.main_area)
        ma_lay.setContentsMargins(0, 0, 0, 0)
        ma_lay.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(24, 16, 24, 0)
        hdr_lay.setSpacing(4)
        hdr_lay.addWidget(label("Orders", bold=True, size=18))
        hdr_lay.addWidget(label("Tap items, track stock, and prepare the cart before checkout.",
                                size=10, color=C['sub']))

        # Category tabs
        self.tab_row = QHBoxLayout()
        self.tab_row.setSpacing(6)
        self.tab_row.setContentsMargins(0, 10, 0, 12)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        hdr_lay.addLayout(self.tab_row)

        ma_lay.addWidget(hdr)

        # Scroll area for product grid
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
        op_hdr.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        oh_lay = QVBoxLayout(op_hdr)
        oh_lay.setContentsMargins(18, 14, 18, 0)

        top_row = QHBoxLayout()
        self.order_title = label(f"Order #{self.pos.order_number}", bold=True, size=16)
        menu_btn = QPushButton("⋮")
        menu_btn.setFlat(True)
        menu_btn.setFixedSize(28, 28)
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.clicked.connect(self._order_context_menu)
        top_row.addWidget(self.order_title)
        top_row.addStretch()
        top_row.addWidget(menu_btn)
        oh_lay.addLayout(top_row)

        self.customer_lbl = label(self.pos.customer_name, size=10, color=C['sub'])
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
        self.order_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self.order_footer.setStyleSheet(f"background:{C['white']};border-top:1px solid {C['border']};")
        self.footer_lay = QVBoxLayout(self.order_footer)
        self.footer_lay.setContentsMargins(18, 12, 18, 16)
        self.footer_lay.setSpacing(6)
        op_lay.addWidget(self.order_footer)

        parent_layout.addWidget(self.order_panel)

    def _type_btn_qss(self, active):
        if active:
            return (f"QPushButton{{background:{C['white']};color:{C['text']};"
                    f"border:1px solid {C['border']};font-weight:700;padding:0 10px;}}")
        return (f"QPushButton{{background:{C['border']};color:{C['sub']};"
                f"border:none;padding:0 10px;}}"
                f"QPushButton:hover{{background:#D1D5DB;}}")

    def _set_order_type(self, ot, btn, checked):
        if checked:
            self.pos.order_type = ot
            for b in self.type_group.buttons():
                b.setStyleSheet(self._type_btn_qss(b is btn))

    # ── Category tabs ─────────────────────────────────────────────────────────
    def _refresh_category_tabs(self):
        # Clear old buttons
        for i in reversed(range(self.tab_row.count())):
            item = self.tab_row.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
                self.tab_row.removeItem(item)
        # Remove all from group
        for b in self.tab_group.buttons():
            self.tab_group.removeButton(b)

        for cat in self.pos.categories:
            btn = pill_button(cat, active=(cat == self.pos.active_category))
            self.tab_group.addButton(btn)
            self.tab_row.addWidget(btn)
            btn.clicked.connect(lambda _, c=cat, b=btn: self._select_category(c))
        self.tab_row.addStretch()

    def _select_category(self, cat: str):
        self.pos.active_category = cat
        self._refresh_product_grid()

    # ── Product grid ──────────────────────────────────────────────────────────
    def _refresh_product_grid(self):
        # Clear
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cols = max(1, (self.main_area.width() - 40) // 176)
        for i, prod in enumerate(self.pos.filtered_products):
            card = ProductCard(prod)
            card.clicked.connect(self.pos.add_product)
            self.grid_layout.addWidget(card, i // cols, i % cols)

        # Fill remaining columns so cards left-align
        if self.pos.filtered_products:
            last = len(self.pos.filtered_products)
            fill_cols = cols - (last % cols)
            if fill_cols != cols:
                for j in range(fill_cols):
                    spacer = QWidget()
                    spacer.setFixedWidth(160)
                    self.grid_layout.addWidget(spacer,
                                               (last - 1) // cols,
                                               (last % cols) + j)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._refresh_product_grid)

    # ── Order panel refresh ───────────────────────────────────────────────────
    def _refresh_order_panel(self):
        # Update header
        self.order_title.setText(f"Order #{self.pos.order_number}")
        self.customer_lbl.setText(self.pos.customer_name)

        # Clear line widgets
        while self.order_lines_layout.count() > 1:   # keep the stretch
            item = self.order_lines_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.pos.order_lines:
            empty = label("No items yet.\nTap a product to add.",
                          color=C['sub'])
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

        def summary_row(lbl_text, value, bold=False, big=False):
            row = QHBoxLayout()
            row.addWidget(label(lbl_text, bold=bold or big,
                                size=14 if big else 12))
            row.addStretch()
            row.addWidget(label(f"${value:.2f}", bold=bold or big,
                                size=14 if big else 12,
                                color=C['text']))
            self.footer_lay.addLayout(row)

        summary_row("Subtotal", self.pos.subtotal)
        summary_row(f"Tax ({TAX_RATE*100:.1f}%)", self.pos.tax_amount)
        self.footer_lay.addWidget(hline())
        summary_row("Total", self.pos.total_amount, big=True)

        charge_btn = QPushButton(f"  Charge  ${self.pos.total_amount:.2f}  ")
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

        # Update status bar
        self.status_items.setText(
            f"Items: {sum(l.qty for l in self.pos.order_lines)}  |  "
            f"Subtotal: ${self.pos.subtotal:.2f}  |  "
            f"Tax: ${self.pos.tax_amount:.2f}  |  "
            f"Total: ${self.pos.total_amount:.2f}"
        )

    # ── Actions ───────────────────────────────────────────────────────────────
    def _charge(self):
        if not self.pos.order_lines:
            QMessageBox.warning(self, "Empty Order", "Add items before charging.")
            return
        reply = QMessageBox.question(
            self, "Confirm Charge",
            f"{self.pos.order_type} – Order #{self.pos.order_number}\n"
            f"Customer: {self.pos.customer_name}\n\n"
            f"Total: ${self.pos.total_amount:.2f}\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.pos.complete_charge()

    def _on_charge_complete(self, order_num: int, total: float):
        QMessageBox.information(self, "Payment Successful",
                                f"✅ Order #{order_num} charged ${total:.2f}\n"
                                "Thank you, have a great day!")

    def _new_order(self):
        if self.pos.order_lines:
            r = QMessageBox.question(self, "New Order",
                                     "Clear current order and start fresh?",
                                     QMessageBox.StandardButton.Yes |
                                     QMessageBox.StandardButton.Cancel)
            if r != QMessageBox.StandardButton.Yes:
                return
        self.pos.clear_order()

    def _order_context_menu(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Clear Order",     self.pos.clear_order)
        menu.addAction("Change Customer", self._change_customer)
        menu.addSeparator()
        menu.addAction("Print Receipt",   self._print_receipt)
        menu.exec(self.cursor().pos())

    def _change_customer(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Change Customer")
        dlg.setFixedSize(320, 130)
        dlg.setStyleSheet(f"background:{C['white']};")
        lay = QVBoxLayout(dlg)
        lay.addWidget(label("Customer Name:", bold=True))
        entry = QLineEdit(self.pos.customer_name)
        entry.setStyleSheet(f"border:1px solid {C['border']};border-radius:6px;"
                            f"padding:6px;background:{C['bg']};")
        lay.addWidget(entry)
        btn = QPushButton("Save")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"background:{C['accent']};color:white;border-radius:6px;"
                          f"padding:7px 20px;font-weight:700;border:none;")
        btn.clicked.connect(lambda: (
            setattr(self.pos, 'customer_name',
                    entry.text().strip() or "Walk-in Customer"),
            self._refresh_order_panel(),
            dlg.accept(),
        ))
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def _print_receipt(self):
        if not self.pos.order_lines:
            QMessageBox.information(self, "Receipt", "No items to print.")
            return
        lines = [f"PAWFFINATED  –  Order #{self.pos.order_number}",
                 f"Type: {self.pos.order_type}",
                 f"Customer: {self.pos.customer_name}",
                 "─" * 36]
        for l in self.pos.order_lines:
            lines.append(f"{l.product.name:25s}  x{l.qty}  ${l.subtotal:>7.2f}")
        lines += ["─" * 36,
                  f"{'Subtotal':30s}  ${self.pos.subtotal:>7.2f}",
                  f"{'Tax':30s}  ${self.pos.tax_amount:>7.2f}",
                  f"{'TOTAL':30s}  ${self.pos.total_amount:>7.2f}"]
        QMessageBox.information(self, "Receipt", "\n".join(lines))

    def _open_import_dialog(self):
        dlg = ImportDialog(self.pos, self)
        dlg.exec()
        # After import, refresh UI
        self._refresh_category_tabs()
        self._refresh_product_grid()

    def _on_inventory_loaded(self, count: int):
        self.status_bar_msg.setText(f"Inventory updated — {count} products loaded.")
        QTimer.singleShot(4000, lambda: self.status_bar_msg.setText(""))

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        sb = self.statusBar()
        self.status_items = QLabel()
        self.status_bar_msg = QLabel()
        self.status_bar_msg.setStyleSheet(f"color:{C['accent']};font-weight:600;")
        sb.addWidget(self.status_items)
        sb.addPermanentWidget(self.status_bar_msg)


# ─────────────────────────────────────────────────────────────────────────────
# App entry point
# ─────────────────────────────────────────────────────────────────────────────
class PawffinatedApp(QApplication):
    """Thin wrapper around QApplication that exposes .window for easy access."""
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