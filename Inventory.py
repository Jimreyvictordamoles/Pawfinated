"""
PAWFFINATED – Inventory Management  (PyQt6 Edition)
====================================================
Install:
    pip install PyQt6

Run:
    python pawffinated_inventory_qt.py

─── EXPOSED VARIABLES ──────────────────────────────────────────────────────
    app = InventoryApp(sys.argv)
    win = app.window                        # InventoryWindow

    win.inv.products          → list[InventoryItem]
    win.inv.low_stock_items   → list[InventoryItem]   (stock < threshold)
    win.inv.out_of_stock      → list[InventoryItem]   (stock == 0)
    win.inv.low_stock_count   → int
    win.inv.out_of_stock_count→ int
    win.inv.search_query      → str
    win.inv.filter_status     → str  ("All"|"In Stock"|"Low Stock"|"Out of Stock")
    win.inv.visible_products  → list[InventoryItem]   (after search+filter)

    Signals:
    win.inv.inventory_changed   → pyqtSignal()
    win.inv.item_added          → pyqtSignal(object)   # InventoryItem
    win.inv.item_updated        → pyqtSignal(object)
    win.inv.item_deleted        → pyqtSignal(int)      # item id

─── INVENTORY IMPORT ────────────────────────────────────────────────────────
    GUI            → toolbar "Import" button
    Programmatic:
        win.inv.load_from_query(conn, "SELECT * FROM products")
        win.inv.load_from_csv("/path/to/file.csv")
        win.inv.load_from_list([{"name":…,"category":…,"price":…,"stock":…}, …])

    Expected columns (case-insensitive, flexible aliases):
        id | name | sku | category | stock | unit | price | status | description

─── INTEGRATION WITH POS ─────────────────────────────────────────────────────
    from pawffinated_inventory_qt import InventoryApp, InventoryItem
    from pawffinated_pos_qt import PawffinatedApp

    inv_app = InventoryApp(sys.argv)
    pos_app = PawffinatedApp(sys.argv)

    # Push inventory → POS
    pos_app.window.pos.load_inventory_from_list(
        [vars(i) for i in inv_app.window.inv.products]
    )
"""

from __future__ import annotations
import sys, csv, io, sqlite3, re
from dataclasses import dataclass, field
from typing import Any
from Sidebar import PawffinatedSidebar

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QSizePolicy, QFileDialog,
    QDialog, QLineEdit, QTextEdit, QMessageBox, QComboBox, QSpinBox,
    QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMenu, QStatusBar, QToolBar, QButtonGroup,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize, QTimer, QSortFilterProxyModel
from PyQt6.QtGui import QFont, QColor, QIcon, QAction, QBrush

# ── Palette (matches POS screen) ─────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    sidebar   = "#FFFFFF",
    white     = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_lt = "#E8F4F0",
    warn      = "#E07B39",
    warn_lt   = "#FEF3C7",
    danger    = "#D94F4F",
    danger_lt = "#FEE2E2",
    ok        = "#059669",
    ok_lt     = "#D1FAE5",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    border    = "#E5E7EB",
    row_alt   = "#FAFAF8",
    badge_ok  = "#D1FAE5",
    badge_ok_t= "#065F46",
)

LOW_STOCK_THRESHOLD = 10   # items at or below this are "Low Stock"

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

# ── Domain model ──────────────────────────────────────────────────────────────
@dataclass
class InventoryItem:
    id: int
    name: str
    sku: str
    category: str
    stock: int
    unit: str
    price: float
    description: str = ""

    @property
    def status(self) -> str:
        if self.stock == 0:
            return "Out of Stock"
        if self.stock <= LOW_STOCK_THRESHOLD:
            return "Low Stock"
        return "In Stock"

    @property
    def emoji(self) -> str:
        return CATEGORY_EMOJI.get(self.category, "📦")


# ── Default demo data ─────────────────────────────────────────────────────────
_DEMO: list[InventoryItem] = [
    InventoryItem(1,  "House Blend Beans",  "BNS-HB-01",  "Whole Beans",       45, "kg",    24.00),
    InventoryItem(2,  "Oat Milk (1L)",      "DRY-OAT-02", "Dairy Alt",          8, "units",  5.50),
    InventoryItem(3,  "Blueberry Muffin",   "PST-BM-01",  "Pastries",           0, "units",  3.50),
    InventoryItem(4,  "Vanilla Syrup (1L)", "SYR-VAN-01", "Syrups",            24, "units", 12.50),
    InventoryItem(5,  "Whole Milk (Gallon)","DRY-WM-01",  "Dairy",             12, "units",  4.50),
    InventoryItem(6,  "Classic Latte",      "ESP-CL-01",  "Coffee & Espresso", 42, "cups",   4.50),
    InventoryItem(7,  "Almond Croissant",   "PST-AC-01",  "Pastries",           3, "units",  3.75),
    InventoryItem(8,  "Cold Brew Bags",     "BNS-CB-01",  "Whole Beans",        6, "bags",   9.00),
    InventoryItem(9,  "Choc Chip Cookie",   "PST-CC-01",  "Pastries",          18, "units",  2.50),
    InventoryItem(10, "Matcha Powder",      "SYR-MT-01",  "Syrups",             5, "tins",  14.00),
    InventoryItem(11, "Caramel Sauce",      "SYR-CS-01",  "Syrups",            30, "units",  8.00),
    InventoryItem(12, "Iced Macchiato",     "ESP-IM-01",  "Coffee & Espresso", 28, "cups",   5.25),
]


# ─────────────────────────────────────────────────────────────────────────────
# Inventory State  ← all variables exposed here
# ─────────────────────────────────────────────────────────────────────────────
class InventoryState(QObject):
    inventory_changed = pyqtSignal()
    item_added        = pyqtSignal(object)
    item_updated      = pyqtSignal(object)
    item_deleted      = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.products: list[InventoryItem] = list(_DEMO)
        self.search_query:  str = ""
        self.filter_status: str = "All"
        self._next_id: int = max(i.id for i in self.products) + 1

    # ── Computed properties ───────────────────────────────────────────────────
    @property
    def low_stock_items(self) -> list[InventoryItem]:
        return [p for p in self.products
                if 0 < p.stock <= LOW_STOCK_THRESHOLD]

    @property
    def out_of_stock(self) -> list[InventoryItem]:
        return [p for p in self.products if p.stock == 0]

    @property
    def low_stock_count(self) -> int:
        return len(self.low_stock_items)

    @property
    def out_of_stock_count(self) -> int:
        return len(self.out_of_stock)

    @property
    def visible_products(self) -> list[InventoryItem]:
        q = self.search_query.lower()
        result = []
        for p in self.products:
            if q and q not in p.name.lower() and q not in p.sku.lower() \
                  and q not in p.category.lower():
                continue
            if self.filter_status != "All" and p.status != self.filter_status:
                continue
            result.append(p)
        return result

    @property
    def total_inventory_value(self) -> float:
        return sum(p.price * p.stock for p in self.products)

    @property
    def categories(self) -> list[str]:
        seen, cats = set(), []
        for p in self.products:
            if p.category not in seen:
                cats.append(p.category)
                seen.add(p.category)
        return cats

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def add_item(self, item: InventoryItem) -> InventoryItem:
        item.id = self._next_id
        self._next_id += 1
        self.products.append(item)
        self.inventory_changed.emit()
        self.item_added.emit(item)
        return item

    def update_item(self, updated: InventoryItem) -> None:
        for i, p in enumerate(self.products):
            if p.id == updated.id:
                self.products[i] = updated
                break
        self.inventory_changed.emit()
        self.item_updated.emit(updated)

    def delete_item(self, item_id: int) -> None:
        self.products = [p for p in self.products if p.id != item_id]
        self.inventory_changed.emit()
        self.item_deleted.emit(item_id)

    def get_by_id(self, item_id: int) -> InventoryItem | None:
        for p in self.products:
            if p.id == item_id:
                return p
        return None

    # ── Loaders ───────────────────────────────────────────────────────────────
    _COL_ALIASES = {
        "id":          ["id", "product_id", "item_id"],
        "name":        ["name", "product_name", "item_name", "title"],
        "sku":         ["sku", "code", "barcode", "product_code", "item_code"],
        "category":    ["category", "cat", "type", "section", "department"],
        "stock":       ["stock", "qty", "quantity", "inventory", "count", "on_hand"],
        "unit":        ["unit", "unit_of_measure", "uom", "units"],
        "price":       ["price", "cost", "unit_price", "amount", "retail_price"],
        "description": ["description", "desc", "details", "note"],
    }

    def _normalize(self, headers: list[str], row: dict | list) -> dict:
        if isinstance(row, (list, tuple)):
            row = dict(zip(headers, row))
        rl = {k.lower().strip(): v for k, v in row.items()}
        out = {"id": None, "name": "", "sku": "", "category": "Other",
               "stock": 0, "unit": "units", "price": 0.0, "description": ""}
        for f, aliases in self._COL_ALIASES.items():
            for a in aliases:
                if a in rl:
                    out[f] = rl[a]
                    break
        return out

    def _rows_to_items(self, headers, rows) -> list[InventoryItem]:
        items, auto_id = [], 1
        for row in rows:
            r = self._normalize(headers, row)
            try:
                pid   = int(r["id"]) if r["id"] is not None else auto_id
                price = float(str(r["price"]).replace("$","").replace(",",""))
                stock = int(r["stock"])
                sku   = str(r["sku"]) or f"SKU-{pid:04d}"
                items.append(InventoryItem(
                    id=pid, name=str(r["name"]), sku=sku,
                    category=str(r["category"]), stock=stock,
                    unit=str(r["unit"]), price=price,
                    description=str(r["description"]),
                ))
                auto_id = pid + 1
            except (ValueError, TypeError):
                continue
        return items

    def load_from_query(self, connection: Any, query: str,
                        params: tuple = ()) -> int:
        """Load from any DB-API 2.0 connection."""
        cur = connection.cursor()
        cur.execute(query, params)
        headers = [d[0].lower() for d in cur.description]
        self.products = self._rows_to_items(headers, cur.fetchall())
        self._next_id = max((p.id for p in self.products), default=0) + 1
        self.inventory_changed.emit()
        return len(self.products)

    def load_from_csv(self, filepath: str) -> int:
        """Load from a CSV file."""
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = [h.lower() for h in (reader.fieldnames or [])]
        self.products = self._rows_to_items(headers, rows)
        self._next_id = max((p.id for p in self.products), default=0) + 1
        self.inventory_changed.emit()
        return len(self.products)

    def load_from_list(self, data: list[dict]) -> int:
        """Load from a list of dicts."""
        headers = list(data[0].keys()) if data else []
        self.products = self._rows_to_items(headers, data)
        self._next_id = max((p.id for p in self.products), default=0) + 1
        self.inventory_changed.emit()
        return len(self.products)


# ─────────────────────────────────────────────────────────────────────────────
# UI Helpers
# ─────────────────────────────────────────────────────────────────────────────
def lbl(text="", bold=False, size=13, color=None) -> QLabel:
    w = QLabel(text)
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    w.setFont(f)
    col = color or C["text"]
    w.setStyleSheet(f"color:{col};background:transparent;")
    return w

def hline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setStyleSheet(f"background:{C['border']};max-height:1px;border:none;")
    ln.setFixedHeight(1)
    return ln

def status_badge(status: str) -> QLabel:
    configs = {
        "In Stock":     (C["ok_lt"],     C["ok"],      "In Stock"),
        "Low Stock":    (C["warn_lt"],   C["warn"],    "Low Stock"),
        "Out of Stock": (C["danger_lt"], C["danger"],  "Out of Stock"),
    }
    bg, fg, text = configs.get(status, (C["border"], C["sub"], status))
    w = QLabel(text)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setFixedHeight(24)
    w.setMinimumWidth(90)
    w.setStyleSheet(
        f"background:{bg};color:{fg};border-radius:5px;"
        f"padding:0 10px;font-size:11px;font-weight:700;"
    )
    return w

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

def ghost_btn(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:{C['white']};color:{C['danger']};"
        f"border:1.5px solid {C['danger']};border-radius:7px;"
        f"padding:7px 18px;font-weight:700;font-size:13px;}}"
        f"QPushButton:hover{{background:{C['danger_lt']};}}"
    )
    return b


# ─────────────────────────────────────────────────────────────────────────────
# Add / Edit Item Dialog
# ─────────────────────────────────────────────────────────────────────────────
class ItemDialog(QDialog):
    def __init__(self, inv: InventoryState,
                 item: InventoryItem | None = None, parent=None):
        super().__init__(parent)
        self.inv  = inv
        self.item = item
        self.setWindowTitle("Edit Item" if item else "Add Item")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"background:{C['white']};")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        title = "Edit Item" if self.item else "Add New Item"
        lay.addWidget(lbl(title, bold=True, size=16))
        lay.addWidget(hline())

        def field_row(label_text: str, widget: QWidget):
            row = QVBoxLayout()
            row.setSpacing(4)
            row.addWidget(lbl(label_text, size=11, color=C["sub"]))
            widget.setStyleSheet(
                f"border:1px solid {C['border']};border-radius:7px;"
                f"padding:7px 10px;background:{C['bg']};font-size:13px;"
            )
            row.addWidget(widget)
            lay.addLayout(row)
            return widget

        p = self.item
        self.f_name  = field_row("Product Name *", QLineEdit(p.name if p else ""))
        self.f_sku   = field_row("SKU",            QLineEdit(p.sku  if p else ""))

        # Category combo
        cat_w = QComboBox()
        cat_w.setEditable(True)
        known = ["Coffee & Espresso","Cold Beverages","Pastries","Sandwiches",
                 "Merchandise","Dairy","Dairy Alt","Whole Beans","Syrups"]
        for c in self.inv.categories:
            if c not in known:
                known.append(c)
        cat_w.addItems(known)
        if p:
            idx = cat_w.findText(p.category)
            if idx >= 0:
                cat_w.setCurrentIndex(idx)
        cat_w.setStyleSheet(
            f"QComboBox{{border:1px solid {C['border']};border-radius:7px;"
            f"padding:7px 10px;background:{C['bg']};font-size:13px;}}"
            f"QComboBox::drop-down{{border:none;width:24px;}}"
        )
        cat_lay = QVBoxLayout()
        cat_lay.setSpacing(4)
        cat_lay.addWidget(lbl("Category", size=11, color=C["sub"]))
        cat_lay.addWidget(cat_w)
        lay.addLayout(cat_lay)
        self.f_cat = cat_w

        # Stock + Unit row
        su_row = QHBoxLayout()
        su_row.setSpacing(12)

        stock_col = QVBoxLayout()
        stock_col.setSpacing(4)
        stock_col.addWidget(lbl("Stock", size=11, color=C["sub"]))
        self.f_stock = QSpinBox()
        self.f_stock.setRange(0, 99999)
        self.f_stock.setValue(p.stock if p else 0)
        self.f_stock.setStyleSheet(
            f"QSpinBox{{border:1px solid {C['border']};border-radius:7px;"
            f"padding:7px 10px;background:{C['bg']};font-size:13px;}}"
        )
        stock_col.addWidget(self.f_stock)
        su_row.addLayout(stock_col)

        unit_col = QVBoxLayout()
        unit_col.setSpacing(4)
        unit_col.addWidget(lbl("Unit", size=11, color=C["sub"]))
        self.f_unit = QLineEdit(p.unit if p else "units")
        self.f_unit.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:7px;"
            f"padding:7px 10px;background:{C['bg']};font-size:13px;"
        )
        unit_col.addWidget(self.f_unit)
        su_row.addLayout(unit_col)
        lay.addLayout(su_row)

        # Price
        price_col = QVBoxLayout()
        price_col.setSpacing(4)
        price_col.addWidget(lbl("Unit Price ($)", size=11, color=C["sub"]))
        self.f_price = QDoubleSpinBox()
        self.f_price.setRange(0, 99999)
        self.f_price.setDecimals(2)
        self.f_price.setPrefix("$ ")
        self.f_price.setValue(p.price if p else 0.0)
        self.f_price.setStyleSheet(
            f"QDoubleSpinBox{{border:1px solid {C['border']};border-radius:7px;"
            f"padding:7px 10px;background:{C['bg']};font-size:13px;}}"
        )
        price_col.addWidget(self.f_price)
        lay.addLayout(price_col)

        self.f_desc = field_row("Description (optional)",
                                QLineEdit(p.description if p else ""))

        lay.addWidget(hline())

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton{{background:{C['border']};color:{C['text']};"
            f"border-radius:7px;padding:7px 18px;font-weight:600;border:none;}}"
            f"QPushButton:hover{{background:#D1D5DB;}}"
        )
        cancel.clicked.connect(self.reject)
        save = action_btn("Save Item")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        lay.addLayout(btn_row)

    def _save(self):
        name = self.f_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Product name is required.")
            return
        sku = self.f_sku.text().strip() or \
              f"SKU-{self.item.id if self.item else '?':04}"
        new_item = InventoryItem(
            id=self.item.id if self.item else 0,
            name=name, sku=sku,
            category=self.f_cat.currentText(),
            stock=self.f_stock.value(),
            unit=self.f_unit.text().strip() or "units",
            price=self.f_price.value(),
            description=self.f_desc.text().strip(),
        )
        if self.item:
            self.inv.update_item(new_item)
        else:
            self.inv.add_item(new_item)
        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Import Dialog (same pattern as POS)
# ─────────────────────────────────────────────────────────────────────────────
class ImportDialog(QDialog):
    def __init__(self, inv: InventoryState, parent=None):
        super().__init__(parent)
        self.inv = inv
        self.setWindowTitle("Import Inventory")
        self.setMinimumSize(580, 480)
        self.setStyleSheet(f"background:{C['white']};")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)

        lay.addWidget(lbl("Import Inventory", bold=True, size=16))
        lay.addWidget(lbl("Replace or merge the current inventory from an external source.",
                          color=C["sub"]))
        lay.addWidget(hline())

        def section(title, subtitle, content_fn):
            box = QFrame()
            box.setStyleSheet(
                f"QFrame{{border:1px solid {C['border']};"
                f"border-radius:10px;background:{C['bg']};}}"
            )
            bl = QVBoxLayout(box)
            bl.setContentsMargins(16, 14, 16, 14)
            bl.setSpacing(8)
            bl.addWidget(lbl(title, bold=True, size=12))
            bl.addWidget(lbl(subtitle, size=10, color=C["sub"]))
            content_fn(bl)
            lay.addWidget(box)

        # ── CSV file ──
        def csv_content(bl):
            b = action_btn("📄  Browse CSV File…")
            b.clicked.connect(self._import_csv)
            bl.addWidget(b, alignment=Qt.AlignmentFlag.AlignLeft)
        section("From CSV File",
                "Columns: id, name, sku, category, stock, unit, price, description",
                csv_content)

        # ── SQLite + query ──
        def sql_content(bl):
            db_row = QHBoxLayout()
            self.db_path = QLineEdit()
            self.db_path.setPlaceholderText("Path to .db / .sqlite file…")
            self.db_path.setStyleSheet(
                f"border:1px solid {C['border']};border-radius:6px;"
                f"padding:6px 10px;background:{C['white']};font-size:12px;"
            )
            browse = QPushButton("Browse…")
            browse.setCursor(Qt.CursorShape.PointingHandCursor)
            browse.setStyleSheet(
                f"QPushButton{{background:{C['border']};color:{C['text']};"
                f"border-radius:6px;padding:6px 14px;border:none;}}"
                f"QPushButton:hover{{background:#D1D5DB;}}"
            )
            browse.clicked.connect(self._browse_db)
            db_row.addWidget(self.db_path)
            db_row.addWidget(browse)
            bl.addLayout(db_row)

            bl.addWidget(lbl("SQL Query:", size=11))
            self.query_edit = QTextEdit()
            self.query_edit.setText("SELECT * FROM products")
            self.query_edit.setFixedHeight(64)
            self.query_edit.setStyleSheet(
                f"border:1px solid {C['border']};border-radius:6px;"
                f"padding:4px;background:{C['white']};font-size:12px;"
            )
            bl.addWidget(self.query_edit)

            run = action_btn("🗄️  Run Query & Import")
            run.clicked.connect(self._import_sql)
            bl.addWidget(run, alignment=Qt.AlignmentFlag.AlignLeft)
        section("From SQLite Database + Query",
                "Connect any SQLite database and run a custom SELECT query.",
                sql_content)

        # ── Paste CSV ──
        def paste_content(bl):
            self.paste_edit = QTextEdit()
            self.paste_edit.setPlaceholderText(
                "name,category,price,stock,unit\n"
                "House Blend Beans,Whole Beans,24.00,45,kg"
            )
            self.paste_edit.setFixedHeight(72)
            self.paste_edit.setStyleSheet(
                f"border:1px solid {C['border']};border-radius:6px;"
                f"padding:4px;background:{C['white']};font-size:12px;"
            )
            bl.addWidget(self.paste_edit)
            b = action_btn("📋  Import Pasted CSV")
            b.clicked.connect(self._import_paste)
            bl.addWidget(b, alignment=Qt.AlignmentFlag.AlignLeft)
        section("Paste CSV Data",
                "Paste raw CSV text directly — useful for quick one-off imports.",
                paste_content)

        lay.addStretch()
        close = QPushButton("Close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton{{background:{C['border']};color:{C['text']};"
            f"border-radius:7px;padding:7px 20px;font-weight:600;border:none;}}"
        )
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def _browse_db(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Select Database", "",
            "SQLite (*.db *.sqlite *.sqlite3);;All (*)"
        )
        if p:
            self.db_path.setText(p)

    def _import_csv(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Select CSV", "", "CSV (*.csv);;All (*)"
        )
        if not p:
            return
        try:
            n = self.inv.load_from_csv(p)
            QMessageBox.information(self, "Success",
                                    f"✅  Loaded {n} items from CSV.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"CSV import failed:\n{e}")

    def _import_sql(self):
        db  = self.db_path.text().strip()
        qry = self.query_edit.toPlainText().strip()
        if not db or not qry:
            QMessageBox.warning(self, "Missing", "Provide a DB path and query.")
            return
        try:
            conn = sqlite3.connect(db)
            n    = self.inv.load_from_query(conn, qry)
            conn.close()
            QMessageBox.information(self, "Success",
                                    f"✅  Loaded {n} items from database.")
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
            n = self.inv.load_from_list(rows)
            QMessageBox.information(self, "Success",
                                    f"✅  Loaded {n} items from pasted data.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Parse error:\n{e}")


# ─────────────────────────────────────────────────────────────────────────────
# Inventory Table
# ─────────────────────────────────────────────────────────────────────────────
COLUMNS = ["", "Product", "Category", "In Stock", "Unit Price", "Status", "Actions"]
COL_IDX = {c: i for i, c in enumerate(COLUMNS)}


class InventoryTable(QTableWidget):
    row_action = pyqtSignal(str, int)   # ("edit"|"delete", item_id)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHorizontalHeaderLabels(COLUMNS)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSortingEnabled(True)
        self.setStyleSheet(self._qss())

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 52)
        self.setColumnWidth(6, 80)

    def _qss(self):
        return f"""
        QTableWidget {{
            background: {C['white']};
            border: none;
            outline: none;
            font-size: 13px;
        }}
        QTableWidget::item {{
            padding: 0 8px;
            border-bottom: 1px solid {C['border']};
            color: {C['text']};
        }}
        QTableWidget::item:selected {{
            background: {C['accent_lt']};
            color: {C['text']};
        }}
        QHeaderView::section {{
            background: {C['bg']};
            color: {C['sub']};
            font-size: 11px;
            font-weight: 600;
            padding: 8px 10px;
            border: none;
            border-bottom: 1.5px solid {C['border']};
        }}
        QScrollBar:vertical {{
            background: {C['bg']};
            width: 6px;
        }}
        QScrollBar::handle:vertical {{
            background: {C['border']};
            border-radius: 3px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """

    def populate(self, items: list[InventoryItem]):
        self.setSortingEnabled(False)
        self.setRowCount(0)
        for item in items:
            r = self.rowCount()
            self.insertRow(r)
            self.setRowHeight(r, 64)

            # ── Col 0: emoji thumbnail ──
            em = QLabel(item.emoji)
            em.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em.setStyleSheet(
                f"font-size:26px;background:#F0EDE8;"
                f"border-radius:8px;margin:8px;padding:4px;"
            )
            self.setCellWidget(r, 0, em)

            # ── Col 1: name + SKU ──
            name_w = QWidget()
            name_w.setStyleSheet("background:transparent;")
            nl = QVBoxLayout(name_w)
            nl.setContentsMargins(8, 0, 0, 0)
            nl.setSpacing(2)
            n_lbl = lbl(item.name, bold=True, size=13)
            s_lbl = lbl(f"SKU: {item.sku}", size=10, color=C["sub"])
            nl.addWidget(n_lbl)
            nl.addWidget(s_lbl)
            self.setCellWidget(r, 1, name_w)

            # ── Col 2: category ──
            cat = QTableWidgetItem(item.category)
            cat.setForeground(QBrush(QColor(C["sub"])))
            self.setItem(r, 2, cat)

            # ── Col 3: stock ──
            stock_w = QWidget()
            stock_w.setStyleSheet("background:transparent;")
            sl = QHBoxLayout(stock_w)
            sl.setContentsMargins(8, 0, 8, 0)
            color = C["danger"] if item.stock == 0 else \
                    C["warn"]   if item.stock <= LOW_STOCK_THRESHOLD else C["text"]
            sl.addWidget(lbl(f"{item.stock} {item.unit}", color=color, bold=(item.stock <= LOW_STOCK_THRESHOLD)))
            self.setCellWidget(r, 3, stock_w)

            # ── Col 4: price ──
            price = QTableWidgetItem(f"${item.price:.2f}")
            price.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            )
            self.setItem(r, 4, price)

            # ── Col 5: status badge ──
            badge_w = QWidget()
            badge_w.setStyleSheet("background:transparent;")
            bl = QHBoxLayout(badge_w)
            bl.setContentsMargins(8, 0, 8, 0)
            bl.addWidget(status_badge(item.status))
            bl.addStretch()
            self.setCellWidget(r, 5, badge_w)

            # ── Col 6: actions "⋯" ──
            dots_btn = QPushButton("···")
            dots_btn.setFixedSize(40, 32)
            dots_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            dots_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C['sub']};"
                f"border:none;font-size:18px;font-weight:700;}}"
                f"QPushButton:hover{{background:{C['bg']};border-radius:6px;}}"
            )
            dots_btn.clicked.connect(
                lambda _, iid=item.id: self._show_row_menu(iid)
            )
            act_w = QWidget()
            act_w.setStyleSheet("background:transparent;")
            al = QHBoxLayout(act_w)
            al.setContentsMargins(4, 0, 4, 0)
            al.addWidget(dots_btn, alignment=Qt.AlignmentFlag.AlignCenter)
            self.setCellWidget(r, 6, act_w)

            # Store item id in hidden data
            self.setItem(r, 0, QTableWidgetItem(str(item.id)))
            self.item(r, 0).setData(Qt.ItemDataRole.UserRole, item.id)

        self.setSortingEnabled(True)

    def _show_row_menu(self, item_id: int):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{C['white']};border:1px solid {C['border']};"
            f"border-radius:8px;padding:4px;}}"
            f"QMenu::item{{padding:8px 20px;border-radius:4px;}}"
            f"QMenu::item:selected{{background:{C['accent_lt']};}}"
        )
        edit_act   = menu.addAction("✏️  Edit Item")
        menu.addSeparator()
        delete_act = menu.addAction("🗑️  Delete Item")
        delete_act.setForeground(QColor(C["danger"]))
        chosen = menu.exec(self.cursor().pos())
        if chosen == edit_act:
            self.row_action.emit("edit", item_id)
        elif chosen == delete_act:
            self.row_action.emit("delete", item_id)


# ─────────────────────────────────────────────────────────────────────────────
# Main Inventory Window
# ─────────────────────────────────────────────────────────────────────────────
class InventoryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.inv = InventoryState()
        self.setWindowTitle("Pawffinated – Inventory Management")
        self.resize(1200, 780)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(
            f"QMainWindow, #central{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
            f"QToolBar{{background:{C['sidebar']};"
            f"border-bottom:1px solid {C['border']};padding:4px 16px;spacing:8px;}}"
            f"QStatusBar{{background:{C['sidebar']};"
            f"border-top:1px solid {C['border']};color:{C['sub']};font-size:11px;padding:0 12px;}}"
        )
        self._build_toolbar()
        self._build_ui()
        self._build_statusbar()
        self.inv.inventory_changed.connect(self._refresh)
        self._refresh()

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(
            f"font-weight:800;font-size:14px;color:{C['accent']};"
        )
        tb.addWidget(logo)

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        tb.addWidget(spacer)

        # Update Item
        upd = QAction("✏️  Update Item", self)
        upd.triggered.connect(self._update_selected)
        tb.addAction(upd)

        # Delete Item
        dele = QAction("🗑️  Delete Item", self)
        dele.triggered.connect(self._delete_selected)
        tb.addAction(dele)

        # Add Item
        add_btn_w = action_btn("＋  Add Item")
        add_btn_w.setFixedHeight(34)
        add_btn_w.clicked.connect(self._add_item)
        tb.addWidget(add_btn_w)

        tb.addSeparator()

        imp = QAction("📦  Import", self)
        imp.triggered.connect(self._open_import)
        tb.addAction(imp)

    # ── Central UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(PawffinatedSidebar(active_page="Inventory"))

        # Main content
        main = QWidget()
        main.setStyleSheet(f"background:{C['bg']};")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        self._build_header(ml)
        self._build_stats_bar(ml)
        self._build_table_section(ml)

        root.addWidget(main, stretch=1)

    # ── Page header ───────────────────────────────────────────────────────────
    def _build_header(self, parent):
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 14)
        hl.setSpacing(4)
        hl.addWidget(lbl("Inventory", bold=True, size=20))
        hl.addWidget(lbl("Monitor stock levels and manage product catalog in real time.",
                         size=11, color=C["sub"]))
        parent.addWidget(hdr)

    # ── Stats bar ─────────────────────────────────────────────────────────────
    def _build_stats_bar(self, parent):
        self.stats_bar = QWidget()
        self.stats_bar.setStyleSheet(f"background:{C['white']};")
        self.stats_lay = QHBoxLayout(self.stats_bar)
        self.stats_lay.setContentsMargins(28, 16, 28, 16)
        self.stats_lay.setSpacing(48)
        self.stats_lay.addStretch()
        parent.addWidget(self.stats_bar)

    def _refresh_stats(self):
        # Clear
        while self.stats_lay.count():
            item = self.stats_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def stat_card(number: int, sub: str,
                      badge_text: str, badge_color: str, badge_bg: str):
            col = QVBoxLayout()
            col.setSpacing(4)
            bdg = QLabel(badge_text)
            bdg.setStyleSheet(
                f"background:{badge_bg};color:{badge_color};"
                f"border-radius:5px;padding:2px 10px;"
                f"font-size:10px;font-weight:700;"
            )
            col.addWidget(bdg, alignment=Qt.AlignmentFlag.AlignLeft)
            num = lbl(str(number), bold=True, size=28)
            col.addWidget(num)
            col.addWidget(lbl(sub, size=10, color=C["sub"]))
            w = QWidget()
            w.setLayout(col)
            return w

        ls = self.inv.low_stock_count
        os_ = self.inv.out_of_stock_count

        self.stats_lay.addWidget(
            stat_card(ls, "Below minimum threshold",
                      "Needs review", C["warn"], C["warn_lt"])
        )
        self.stats_lay.addWidget(
            stat_card(os_, "Lost revenue potential",
                      "Restock Needed", C["danger"], C["danger_lt"])
        )
        val_col = QVBoxLayout()
        val_col.setSpacing(4)
        val_col.addWidget(lbl("Total Value", size=10, color=C["sub"]))
        val_col.addWidget(lbl(f"${self.inv.total_inventory_value:,.2f}",
                              bold=True, size=22))
        val_col.addWidget(lbl(f"{len(self.inv.products)} products",
                              size=10, color=C["sub"]))
        vw = QWidget()
        vw.setLayout(val_col)
        self.stats_lay.addWidget(vw)
        self.stats_lay.addStretch()

    # ── Table section ─────────────────────────────────────────────────────────
    def _build_table_section(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 16)
        wl.setSpacing(12)

        # Title + search/filter row
        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(lbl("Current Inventory", bold=True, size=15))
        title_col.addWidget(lbl("View and manage all items currently in stock.",
                                size=10, color=C["sub"]))
        top.addLayout(title_col)
        top.addStretch()

        # Search
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  Search products…")
        self.search_box.setFixedWidth(220)
        self.search_box.setFixedHeight(34)
        self.search_box.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:8px;"
            f"padding:0 12px;background:{C['white']};font-size:12px;"
        )
        self.search_box.textChanged.connect(self._on_search)
        top.addWidget(self.search_box)

        # Filter button → dropdown
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "In Stock", "Low Stock", "Out of Stock"])
        self.filter_combo.setFixedHeight(34)
        self.filter_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_combo.setStyleSheet(
            f"QComboBox{{border:1px solid {C['border']};border-radius:8px;"
            f"padding:0 12px;background:{C['white']};font-size:12px;min-width:120px;}}"
            f"QComboBox::drop-down{{border:none;width:24px;}}"
            f"QComboBox QAbstractItemView{{border:1px solid {C['border']};"
            f"selection-background-color:{C['accent_lt']};}}"
        )
        self.filter_combo.currentTextChanged.connect(self._on_filter)
        top.addWidget(self.filter_combo)

        wl.addLayout(top)

        # Table
        self.table = InventoryTable()
        self.table.row_action.connect(self._handle_row_action)
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:12px;"
            f"border:1px solid {C['border']};}}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.table)
        wl.addWidget(card)

        parent.addWidget(wrap, stretch=1)

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        self.status_lbl = QLabel()
        self.status_msg = QLabel()
        self.status_msg.setStyleSheet(f"color:{C['accent']};font-weight:600;")
        self.statusBar().addWidget(self.status_lbl)
        self.statusBar().addPermanentWidget(self.status_msg)

    # ── Refresh ───────────────────────────────────────────────────────────────
    def _refresh(self):
        self._refresh_stats()
        items = self.inv.visible_products
        self.table.populate(items)
        self.status_lbl.setText(
            f"Showing {len(items)} of {len(self.inv.products)} items  |  "
            f"Low stock: {self.inv.low_stock_count}  |  "
            f"Out of stock: {self.inv.out_of_stock_count}  |  "
            f"Total value: ${self.inv.total_inventory_value:,.2f}"
        )

    # ── Search / filter ───────────────────────────────────────────────────────
    def _on_search(self, text: str):
        self.inv.search_query = text
        self._refresh()

    def _on_filter(self, status: str):
        self.inv.filter_status = status
        self._refresh()

    # ── CRUD actions ──────────────────────────────────────────────────────────
    def _add_item(self):
        dlg = ItemDialog(self.inv, parent=self)
        dlg.exec()

    def _update_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "No Selection",
                                    "Click a row in the table first.")
            return
        r = rows[0].row()
        item_id_cell = self.table.item(r, 0)
        if not item_id_cell:
            return
        iid  = item_id_cell.data(Qt.ItemDataRole.UserRole)
        item = self.inv.get_by_id(iid)
        if item:
            ItemDialog(self.inv, item, parent=self).exec()

    def _delete_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "No Selection",
                                    "Click a row in the table first.")
            return
        r = rows[0].row()
        item_id_cell = self.table.item(r, 0)
        if not item_id_cell:
            return
        iid  = item_id_cell.data(Qt.ItemDataRole.UserRole)
        item = self.inv.get_by_id(iid)
        if not item:
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {item.name} from inventory?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.inv.delete_item(iid)
            self._flash(f"Deleted {item.name}.")

    def _handle_row_action(self, action: str, item_id: int):
        item = self.inv.get_by_id(item_id)
        if not item:
            return
        if action == "edit":
            ItemDialog(self.inv, item, parent=self).exec()
        elif action == "delete":
            reply = QMessageBox.question(
                self, "Confirm Delete",
                f"Delete {item.name}?\nThis cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.inv.delete_item(item_id)
                self._flash(f"Deleted {item.name}.")

    def _open_import(self):
        dlg = ImportDialog(self.inv, parent=self)
        dlg.exec()

    def _flash(self, msg: str, ms: int = 4000):
        self.status_msg.setText(msg)
        QTimer.singleShot(ms, lambda: self.status_msg.setText(""))


# ─────────────────────────────────────────────────────────────────────────────
# App entry point
# ─────────────────────────────────────────────────────────────────────────────
class InventoryApp(QApplication):
    """Thin wrapper — exposes .window for scripting."""
    def __init__(self, argv=None):
        super().__init__(argv or sys.argv)
        self.setApplicationName("Pawffinated Inventory")
        self.window = InventoryWindow()

    def run(self):
        self.window.show()
        return self.exec()


if __name__ == "__main__":
    app = InventoryApp(sys.argv)
    sys.exit(app.run())