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
    • CHANGE: Orders page now shows ONLY Menu Items (recipe-based)
    • FIX: & character now displays correctly in category pill buttons
    • NEW: Stock warning when cart quantity would exceed ingredient supply
    • NEW: Increment button blocked with warning if ingredient stock depleted
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
    QComboBox, QTabWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QPixmap, QIcon, QAction

from Sidebar import PawffinatedSidebar
from DbConnection import get_db, close_db, db_info, InventoryDB, get_menu_db

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
DISCOUNT_RATE  = 0.20
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
    "Breakfast":         "🍳",
    "Mains":             "🍽️",
    "Snacks":            "🍿",
    "Desserts":          "🍰",
    "Drinks":            "🥤",
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
class MenuIngredient:
    id:              int
    menu_item_id:    int
    ingredient_name: str
    quantity:        float
    unit:            str


@dataclass
class MenuItem:
    """A recipe-based menu item that deducts ingredients on sale."""
    id:          int
    name:        str
    category:    str
    price:       float
    description: str = ""
    image_path:  Optional[str] = None
    ingredients: list[MenuIngredient] = field(default_factory=list)
    # Populated at load time by POSState
    missing_ingredients:    list[str] = field(default_factory=list)
    outofstock_ingredients: list[str] = field(default_factory=list)

    @property
    def is_locked(self) -> bool:
        return bool(self.outofstock_ingredients)

    @property
    def has_warnings(self) -> bool:
        return bool(self.missing_ingredients)

    @property
    def emoji(self) -> str:
        return CATEGORY_EMOJI.get(self.category, "🍽️")


@dataclass
class OrderLine:
    product:      Optional[Product]  = None   # inventory product
    menu_item:    Optional[MenuItem] = None   # OR menu item
    qty:          int = 1
    modifiers:    list[tuple[str, float]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.product.name if self.product else (self.menu_item.name if self.menu_item else "")

    @property
    def base_price(self) -> float:
        return self.product.price if self.product else (self.menu_item.price if self.menu_item else 0.0)

    @property
    def unit_price(self) -> float:
        return self.base_price + sum(v for _, v in self.modifiers)

    @property
    def subtotal(self) -> float:
        return self.unit_price * self.qty

    @property
    def description(self) -> str:
        if self.product:
            return self.product.description
        if self.menu_item:
            return self.menu_item.description
        return ""

    @property
    def is_menu_item(self) -> bool:
        return self.menu_item is not None


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

MENU_CARD_QSS_AVAILABLE = f"""
QFrame#menuCard {{
    background: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 10px;
}}
QFrame#menuCard:hover {{
    border: 1.5px solid {C['accent']};
}}
"""

MENU_CARD_QSS_LOCKED = f"""
QFrame#menuCard {{
    background: {C['danger_lt']};
    border: 1.5px solid {C['danger']};
    border-radius: 10px;
}}
"""

MENU_CARD_QSS_WARNED = f"""
QFrame#menuCard {{
    background: {C['warn_lt']};
    border: 1.5px solid {C['warn']};
    border-radius: 10px;
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
    charge_completed = pyqtSignal(int, float, str)
    inventory_loaded = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.order_lines:    list[OrderLine] = []
        self.order_number:   int  = 1042
        self.order_type:     str  = "Dine In"
        self.customer_name:  str  = "Walk-in Customer"
        self.discount_type:  str  = "None"

        self.subtotal:        float = 0.0
        self.discount_amount: float = 0.0
        self.total_amount:    float = 0.0

        # Menu items
        self.menu_items:           list[MenuItem] = []
        self.active_menu_category: str = "All"

        self._load_menu_from_db()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _load_menu_from_db(self) -> None:
        try:
            menu_db  = get_menu_db()
            inv_db   = get_db()
            inv_map  = {p["name"].lower(): p for p in inv_db.fetch_all()}
            raw_items = menu_db.fetch_all_menu_items()

            self.menu_items = []
            for r in raw_items:
                ingredients = [
                    MenuIngredient(
                        id=ing["id"],
                        menu_item_id=ing["menu_item_id"],
                        ingredient_name=ing["ingredient_name"],
                        quantity=float(ing["quantity"]),
                        unit=str(ing["unit"]),
                    )
                    for ing in menu_db.fetch_ingredients(r["id"])
                ]

                missing, outofstock = [], []
                for ing in ingredients:
                    key = ing.ingredient_name.lower()
                    if key not in inv_map:
                        missing.append(ing.ingredient_name)
                    elif int(inv_map[key].get("stock", 0)) <= 0:
                        outofstock.append(ing.ingredient_name)

                self.menu_items.append(MenuItem(
                    id=int(r["id"]),
                    name=str(r["name"]),
                    category=str(r["category"]),
                    price=float(r["price"]),
                    description=str(r.get("description", "")),
                    image_path=r.get("image_path"),
                    ingredients=ingredients,
                    missing_ingredients=missing,
                    outofstock_ingredients=outofstock,
                ))
        except Exception as e:
            print(f"[POS] Could not load menu items from DB: {e}")
            self.menu_items = []

    def reload_from_db(self) -> int:
        self._load_menu_from_db()
        self.inventory_loaded.emit(len(self.menu_items))
        return len(self.menu_items)

    # ── Ingredient stock check ────────────────────────────────────────────────

    def _can_add_menu_item(self, item: MenuItem, extra_qty: int = 1) -> list[str]:
        """
        Check if adding `extra_qty` more of `item` would exceed ingredient stock.
        Returns a list of warning strings; empty list means it is safe to add.
        """
        # Sum up ingredient quantities already committed by items in the cart
        cart_usage: dict[str, float] = {}
        for line in self.order_lines:
            if line.menu_item:
                for ing in line.menu_item.ingredients:
                    key = ing.ingredient_name.lower()
                    cart_usage[key] = cart_usage.get(key, 0) + ing.quantity * line.qty

        try:
            inv_map = {
                p["name"].lower(): int(p.get("stock", 0))
                for p in get_db().fetch_all()
            }
        except Exception:
            return []  # Cannot verify — allow optimistically

        warnings = []
        for ing in item.ingredients:
            key = ing.ingredient_name.lower()
            if key in inv_map:
                available  = inv_map[key]
                reserved   = cart_usage.get(key, 0.0)
                needed     = ing.quantity * extra_qty
                if reserved + needed > available:
                    avail_remaining = max(0.0, available - reserved)
                    warnings.append(
                        f"• {ing.ingredient_name}: need {needed:.2f} {ing.unit}, "
                        f"only {avail_remaining:.2f} remaining in stock"
                    )
        return warnings

    # ── Cart helpers ──────────────────────────────────────────────────────────

    def add_menu_item(self, item: MenuItem) -> list[str]:
        """
        Add a menu item to the cart.
        Returns a list of warning strings (empty = success).
        Locked items are rejected immediately.
        """
        if item.is_locked:
            return [f"'{item.name}' is locked — one or more ingredients are out of stock."]

        warnings = self._can_add_menu_item(item, extra_qty=1)
        if warnings:
            return warnings

        for line in self.order_lines:
            if line.menu_item and line.menu_item.id == item.id:
                line.qty += 1
                self._recalc()
                return []
        self.order_lines.append(OrderLine(menu_item=item))
        self._recalc()
        return []

    def increment(self, line: OrderLine) -> list[str]:
        """
        Increment the quantity of an order line by 1.
        Returns warning strings if ingredient stock would be exceeded (empty = ok).
        """
        if line.menu_item:
            warnings = self._can_add_menu_item(line.menu_item, extra_qty=1)
            if warnings:
                return warnings
        if line.product:
            if line.product.stock <= 0:
                return [f"'{line.product.name}' is out of stock."]
            line.product.stock -= 1
        line.qty += 1
        self._recalc()
        return []

    def decrement(self, line: OrderLine) -> None:
        if line.product:
            line.product.stock += 1
        line.qty -= 1
        if line.qty <= 0:
            self.order_lines.remove(line)
        self._recalc()

    def clear_order(self) -> None:
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
        self.discount_type = dtype
        self._recalc()

    def complete_charge(self) -> None:
        n  = self.order_number
        t  = self.total_amount
        dt = self.discount_type

        try:
            db      = get_db()
            menu_db = get_menu_db()

            # 1. Insert order header
            order_id = db.insert_order({
                "order_number":    n,
                "order_type":      self.order_type,
                "customer_name":   self.customer_name,
                "subtotal":        self.subtotal,
                "discount_type":   self.discount_type,
                "discount_amount": self.discount_amount,
                "total_amount":    self.total_amount,
            })

            # 2. Insert order items
            items_payload = []
            for line in self.order_lines:
                if line.product:
                    items_payload.append({
                        "product_id": line.product.id,
                        "name":       line.product.name,
                        "category":   line.product.category,
                        "sku":        line.product.sku,
                        "unit_price": line.unit_price,
                        "quantity":   line.qty,
                        "subtotal":   line.subtotal,
                    })
                elif line.menu_item:
                    items_payload.append({
                        "product_id": None,
                        "name":       line.menu_item.name,
                        "category":   line.menu_item.category,
                        "sku":        "",
                        "unit_price": line.unit_price,
                        "quantity":   line.qty,
                        "subtotal":   line.subtotal,
                    })
            db.insert_order_items(order_id, items_payload)

            # 3. Deduct ingredients for menu items
            for line in self.order_lines:
                if line.menu_item:
                    menu_db.deduct_ingredients(
                        line.menu_item.id, db, qty_ordered=line.qty
                    )

        except Exception as e:
            print(f"[POS] Warning: could not persist order to DB: {e}")

        self.order_lines.clear()
        self.order_number += 1
        self.discount_type = "None"
        self._recalc()
        # Reload menu to refresh lock states after ingredient deduction
        self._load_menu_from_db()
        self.charge_completed.emit(n, t, dt)

    # ── Category helpers ──────────────────────────────────────────────────────

    @property
    def menu_categories(self) -> list[str]:
        cats = ["All"]
        seen = set()
        for m in self.menu_items:
            if m.category not in seen:
                cats.append(m.category)
                seen.add(m.category)
        return cats

    @property
    def filtered_menu_items(self) -> list[MenuItem]:
        if self.active_menu_category == "All":
            return self.menu_items
        return [m for m in self.menu_items if m.category == self.active_menu_category]


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
    # Escape & so Qt doesn't treat it as a mnemonic accelerator character
    display = text.replace("&", "&&")
    btn = QPushButton(display, parent)
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
# Menu Item Card  (Recipe-based)
# ─────────────────────────────────────────────────────────────────────────────
class MenuItemCard(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, item: MenuItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("menuCard")

        if item.is_locked:
            self.setStyleSheet(MENU_CARD_QSS_LOCKED)
            self.setCursor(Qt.CursorShape.ForbiddenCursor)
        elif item.has_warnings:
            self.setStyleSheet(MENU_CARD_QSS_WARNED)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setStyleSheet(MENU_CARD_QSS_AVAILABLE)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setFixedSize(160, 220)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(4)

        # Status badge
        badge_row = QHBoxLayout()
        badge_row.addStretch()
        if self.item.is_locked:
            badge = QLabel("🔒 Unavailable")
            badge.setStyleSheet(
                f"background:{C['danger_lt']};color:{C['danger']};"
                f"border-radius:4px;padding:2px 7px;"
                f"font-size:10px;font-weight:700;border:none;"
            )
        elif self.item.has_warnings:
            badge = QLabel("⚠ Missing")
            badge.setStyleSheet(
                f"background:{C['warn_lt']};color:{C['warn']};"
                f"border-radius:4px;padding:2px 7px;"
                f"font-size:10px;font-weight:700;border:none;"
            )
        else:
            badge = QLabel("✓ Available")
            badge.setStyleSheet(
                f"background:{C['ok_lt']};color:{C['ok']};"
                f"border-radius:4px;padding:2px 7px;"
                f"font-size:10px;font-weight:700;border:none;"
            )
        badge_row.addWidget(badge)
        lay.addLayout(badge_row)

        emoji_lbl = QLabel(self.item.emoji)
        emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emoji_lbl.setStyleSheet(
            "font-size:36px;background:#F0EDE8;border-radius:6px;"
            "padding:8px;border:none;"
        )
        lay.addWidget(emoji_lbl)

        name_lbl = lbl(self.item.name, bold=True, size=11)
        name_lbl.setWordWrap(True)
        lay.addWidget(name_lbl)

        # Ingredients mini-preview
        if self.item.ingredients:
            ing_names = ", ".join(
                i.ingredient_name for i in self.item.ingredients[:2]
            )
            if len(self.item.ingredients) > 2:
                ing_names += f" +{len(self.item.ingredients)-2}"
            ing_lbl = lbl(ing_names, size=9, color=C["sub"])
            ing_lbl.setWordWrap(True)
            lay.addWidget(ing_lbl)

        if self.item.is_locked:
            locked_detail = lbl(
                f"Out of stock: {', '.join(self.item.outofstock_ingredients[:2])}",
                size=9, color=C["danger"]
            )
            locked_detail.setWordWrap(True)
            lay.addWidget(locked_detail)
        elif self.item.has_warnings:
            warn_detail = lbl(
                f"Not in inv: {', '.join(self.item.missing_ingredients[:2])}",
                size=9, color=C["warn"]
            )
            warn_detail.setWordWrap(True)
            lay.addWidget(warn_detail)

        lay.addStretch()
        lay.addWidget(lbl(f"₱{self.item.price:.2f}", bold=True, size=12))

    def mousePressEvent(self, e):
        if not self.item.is_locked:
            self.clicked.emit(self.item)
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
        top.addWidget(lbl(self.line.name, bold=True))
        top.addStretch()
        top.addWidget(lbl(f"₱{self.line.base_price:.2f}", bold=True))
        lay.addLayout(top)

        # Type badge for menu items
        if self.line.is_menu_item:
            type_badge = QLabel("📋 Menu Item")
            type_badge.setStyleSheet(
                f"background:{C['accent_lt']};color:{C['accent']};"
                f"border-radius:4px;padding:1px 6px;font-size:9px;"
                f"font-weight:700;border:none;"
            )
            lay.addWidget(type_badge)

        parts = [self.line.description]
        parts += [f"{m} (+₱{v:.2f})" for m, v in self.line.modifiers]
        desc = ", ".join(p for p in parts if p)
        if desc:
            lay.addWidget(lbl(desc, size=10, color=C["sub"]))

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
# Import Inventory Dialog (kept for DB reload capability)
# ─────────────────────────────────────────────────────────────────────────────
class ImportDialog(QDialog):
    def __init__(self, pos: POSState, parent=None):
        super().__init__(parent)
        self.pos = pos
        self.setWindowTitle("Reload Menu")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumSize(460, 240)
        self.resize(460, 240)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(pal.ColorRole.Window, QColor(C["white"]))
        self.setPalette(pal)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(14)

        lay.addWidget(lbl("Reload Menu & Inventory", bold=True, size=18))
        sub = lbl(
            "Re-fetches all menu items and ingredient stock levels from the database.",
            size=11, color=C["sub"]
        )
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addWidget(hline())

        db_btn = action_btn("🔄  Reload from Database")
        db_btn.setFixedHeight(40)
        db_btn.clicked.connect(self._reload_from_db)
        lay.addWidget(db_btn)

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
                                    f"✅ Loaded {n} menu items from the database.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Database reload failed:\n{e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.pos = POSState()
        self.setWindowTitle("Pawffinated – Point of Sale")
        self.resize(1280, 820)
        self.setMinimumSize(1040, 700)
        self.setStyleSheet(GLOBAL_QSS)
        self._build_toolbar()
        self._build_ui()
        self._build_statusbar()

        self.pos.order_changed.connect(self._refresh_order_panel)
        self.pos.inventory_loaded.connect(self._on_inventory_loaded)
        self.pos.charge_completed.connect(self._on_charge_complete)

        self._refresh_menu_tabs()
        self._refresh_menu_grid()
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

        reload_action = QAction("🔄  Reload Menu", self)
        reload_action.triggered.connect(self._open_import_dialog)
        tb.addAction(reload_action)

        new_order_action = QAction("🆕  New Order", self)
        new_order_action.triggered.connect(self._new_order)
        tb.addAction(new_order_action)

    def _update_db_status_label(self):
        count = len(self.pos.menu_items)
        if count:
            self.db_status_lbl.setText(f"📋  {count} menu items loaded")
            self.db_status_lbl.setStyleSheet(
                f"color:{C['accent']};font-size:11px;"
                f"border:1px solid {C['accent']};border-radius:5px;"
                f"padding:3px 10px;background:{C['accent_lt']};"
            )
        else:
            self.db_status_lbl.setText("⚠  No menu items loaded")
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

        # ── Page header ───────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(28, 18, 28, 14)
        hdr_lay.setSpacing(4)
        hdr_lay.addWidget(lbl("Orders", bold=True, size=20))
        hdr_lay.addWidget(lbl(
            "Tap a menu item to add it to the cart. "
            "Ingredients are auto-deducted from inventory on charge. "
            "A warning is shown if cart quantity would exceed available stock.",
            size=11, color=C["sub"]
        ))
        ma_lay.addWidget(hdr)

        # ── Legend bar ────────────────────────────────────────────────────────
        legend = QWidget()
        legend.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        ll = QHBoxLayout(legend)
        ll.setContentsMargins(28, 6, 28, 6)
        ll.setSpacing(14)
        for color, bg, text in [
            (C["ok"],     C["ok_lt"],     "✓ Available"),
            (C["warn"],   C["warn_lt"],   "⚠ Ingredient not in inventory"),
            (C["danger"], C["danger_lt"], "🔒 Locked — out of stock (cannot add)"),
        ]:
            b = QLabel(text)
            b.setStyleSheet(
                f"background:{bg};color:{color};border-radius:4px;"
                f"padding:2px 8px;font-size:10px;font-weight:600;"
            )
            ll.addWidget(b)
        ll.addStretch()
        ma_lay.addWidget(legend)

        # ── Category pill row ─────────────────────────────────────────────────
        menu_cat_bar = QWidget()
        menu_cat_bar.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        mcb_lay = QVBoxLayout(menu_cat_bar)
        mcb_lay.setContentsMargins(28, 10, 28, 10)
        self.menu_tab_row = QHBoxLayout()
        self.menu_tab_row.setSpacing(6)
        self.menu_tab_group = QButtonGroup(self)
        self.menu_tab_group.setExclusive(True)
        mcb_lay.addLayout(self.menu_tab_row)
        ma_lay.addWidget(menu_cat_bar)

        # ── Menu grid scroll area ─────────────────────────────────────────────
        self.menu_scroll = QScrollArea()
        self.menu_scroll.setWidgetResizable(True)
        self.menu_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.menu_scroll.setStyleSheet(f"background:{C['bg']};border:none;")

        self.menu_grid_container = QWidget()
        self.menu_grid_container.setStyleSheet(f"background:{C['bg']};")
        self.menu_grid_layout = QGridLayout(self.menu_grid_container)
        self.menu_grid_layout.setContentsMargins(20, 16, 20, 16)
        self.menu_grid_layout.setSpacing(12)

        self.menu_scroll.setWidget(self.menu_grid_container)
        ma_lay.addWidget(self.menu_scroll, stretch=1)

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

    # ── Category tabs — Menu ──────────────────────────────────────────────────
    def _refresh_menu_tabs(self):
        for i in reversed(range(self.menu_tab_row.count())):
            item = self.menu_tab_row.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
                self.menu_tab_row.removeItem(item)
        for b in self.menu_tab_group.buttons():
            self.menu_tab_group.removeButton(b)

        for cat in self.pos.menu_categories:
            btn = pill_button(cat, active=(cat == self.pos.active_menu_category))
            self.menu_tab_group.addButton(btn)
            self.menu_tab_row.addWidget(btn)
            btn.clicked.connect(lambda _, c=cat: self._select_menu_category(c))
        self.menu_tab_row.addStretch()

    def _select_menu_category(self, cat: str):
        self.pos.active_menu_category = cat
        self._refresh_menu_grid()

    # ── Menu grid ─────────────────────────────────────────────────────────────
    def _refresh_menu_grid(self):
        while self.menu_grid_layout.count():
            item = self.menu_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        items = self.pos.filtered_menu_items
        if not items:
            empty = lbl(
                "No menu items yet.\nGo to Menu in the sidebar to create recipe-based items.",
                color=C["sub"]
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 60, 0, 0)
            self.menu_grid_layout.addWidget(empty, 0, 0)
            return

        cols = max(1, (self.main_area.width() - 40) // 176)
        for i, item in enumerate(items):
            card = MenuItemCard(item)
            card.clicked.connect(self._on_menu_item_clicked)
            self.menu_grid_layout.addWidget(card, i // cols, i % cols)

        last = len(items)
        fill = cols - (last % cols)
        if fill != cols:
            for j in range(fill):
                sp = QWidget()
                sp.setFixedWidth(160)
                self.menu_grid_layout.addWidget(
                    sp, (last - 1) // cols, (last % cols) + j
                )

    def _on_menu_item_clicked(self, item: MenuItem) -> None:
        if item.is_locked:
            QMessageBox.warning(
                self, "Item Unavailable",
                f"'{item.name}' cannot be added — the following ingredients "
                f"are out of stock:\n\n"
                + "\n".join(f"• {i}" for i in item.outofstock_ingredients)
            )
            return
        warnings = self.pos.add_menu_item(item)
        if warnings:
            QMessageBox.warning(
                self, "⚠ Insufficient Ingredient Stock",
                f"Cannot add '{item.name}' — cart quantity would exceed available stock:\n\n"
                + "\n".join(warnings)
                + "\n\nPlease reduce the quantity or restock the ingredient."
            )

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._refresh_menu_grid)

    # ── Order panel refresh ───────────────────────────────────────────────────
    def _refresh_order_panel(self):
        self.order_title.setText(f"Order #{self.pos.order_number}")
        self.customer_lbl.setText(self.pos.customer_name)

        while self.order_lines_layout.count() > 1:
            item = self.order_lines_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.pos.order_lines:
            empty = label("No items yet.\nTap a menu item to add.", color=C['sub'])
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 30, 0, 0)
            self.order_lines_layout.insertWidget(0, empty)
        else:
            for i, line in enumerate(self.pos.order_lines):
                lw = OrderLineWidget(line)
                lw.inc_clicked.connect(self._on_increment)
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

        # Discount selector
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

    # ── Increment handler (with ingredient stock warning) ─────────────────────
    def _on_increment(self, line: OrderLine) -> None:
        warnings = self.pos.increment(line)
        if warnings:
            QMessageBox.warning(
                self, "⚠ Insufficient Ingredient Stock",
                f"Cannot add more '{line.name}' — cart quantity would exceed stock:\n\n"
                + "\n".join(warnings)
                + "\n\nPlease restock the ingredient before adding more."
            )

    # ── Actions ───────────────────────────────────────────────────────────────
    def _charge(self):
        if not self.pos.order_lines:
            QMessageBox.warning(self, "Empty Order", "Add items before charging.")
            return

        # Show ingredients that will be deducted for menu items
        menu_lines = [l for l in self.pos.order_lines if l.is_menu_item]
        deduct_preview = ""
        if menu_lines:
            lines = []
            for ml in menu_lines:
                for ing in ml.menu_item.ingredients:
                    lines.append(
                        f"  • {ing.ingredient_name}: "
                        f"−{ing.quantity * ml.qty:.2f} {ing.unit}"
                    )
            deduct_preview = (
                f"\n\n📋 Ingredients to deduct from inventory:\n"
                + "\n".join(lines)
            )

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
            f"Total: ₱{self.pos.total_amount:.2f}"
            f"{deduct_preview}\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.pos.complete_charge()
            self._refresh_menu_tabs()
            self._refresh_menu_grid()

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
            "─" * 38,
        ]
        for l in self.pos.order_lines:
            lines.append(f"{l.name:27s}  x{l.qty}  ₱{l.subtotal:>8.2f}")
        lines += [
            "─" * 38,
            f"{'Subtotal':32s}  ₱{self.pos.subtotal:>8.2f}",
        ]
        if self.pos.discount_type != "None":
            lines.append(
                f"{self.pos.discount_type + ' Discount (20%)':32s}"
                f"  −₱{self.pos.discount_amount:>7.2f}"
            )
        lines.append(f"{'TOTAL':32s}  ₱{self.pos.total_amount:>8.2f}")
        QMessageBox.information(self, "Receipt", "\n".join(lines))

    def _open_import_dialog(self):
        dlg = ImportDialog(self.pos, self)
        dlg.exec()
        self._refresh_menu_tabs()
        self._refresh_menu_grid()
        self._update_db_status_label()

    def _on_inventory_loaded(self, count: int):
        self._update_db_status_label()
        self._refresh_menu_tabs()
        self._refresh_menu_grid()
        self._flash(f"✅ Menu updated — {count} items loaded.")

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