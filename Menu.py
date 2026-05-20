"""
PAWFFINATED – Menu Management  (PyQt6 + PostgreSQL)
=====================================================
Features:
    • Create / edit / delete menu items with name, category, price, description
    • Each menu item has an ingredient list (name + qty + unit)
    • Ingredients are matched against inventory products by name
    • Warning badge if any ingredient is not found in inventory
    • Lock badge + red state if any matched ingredient is out of stock
    • Menu items that are locked cannot be added to POS cart

FIX:
    • & in category names now displays correctly (escaped as && for Qt mnemonics)
    • Each card now shows "Can make: N" based on current ingredient stock levels
    • Warning is shown when ingredient stock would be exceeded by an order

Tables used:
    menu_items        — id, name, category, price, description, image_path
    menu_ingredients  — id, menu_item_id, ingredient_name, quantity, unit

Run standalone:
    python Menu.py
"""

from __future__ import annotations

import sys
import math
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QSizePolicy, QDialog, QLineEdit,
    QMessageBox, QComboBox, QDoubleSpinBox, QScrollArea, QToolBar,
    QGridLayout, QSpinBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QAction

from DbConnection import get_db, close_db, db_info, MenuDB, get_menu_db
from Sidebar import PawffinatedSidebar

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
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
    purple    = "#7C3AED",
    purple_lt = "#EDE9FE",
)

CATEGORY_EMOJI = {
    "Coffee & Espresso": "☕",
    "Cold Beverages":    "🧊",
    "Pastries":          "🥐",
    "Sandwiches":        "🥪",
    "Breakfast":         "🍳",
    "Mains":             "🍽️",
    "Snacks":            "🍿",
    "Desserts":          "🍰",
    "Drinks":            "🥤",
    "Merchandise":       "🛍️",
}


# ─────────────────────────────────────────────────────────────────────────────
# Domain models
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MenuIngredient:
    id:              int
    menu_item_id:    int
    ingredient_name: str
    quantity:        float
    unit:            str


@dataclass
class MenuItem:
    id:          int
    name:        str
    category:    str
    price:       float
    description: str = ""
    image_path:  Optional[str] = None
    ingredients: list[MenuIngredient] = field(default_factory=list)

    # ── Availability helpers (populated by MenuState) ────────────────────────
    missing_ingredients:    list[str] = field(default_factory=list)
    outofstock_ingredients: list[str] = field(default_factory=list)
    # Maximum units that can be made given current stock (None = unconstrained)
    max_can_make:           Optional[int] = field(default=None)

    @property
    def has_warnings(self) -> bool:
        return bool(self.missing_ingredients)

    @property
    def is_locked(self) -> bool:
        return bool(self.outofstock_ingredients)

    @property
    def emoji(self) -> str:
        return CATEGORY_EMOJI.get(self.category, "🍽️")

    @property
    def availability_label(self) -> str:
        if self.is_locked:
            return "Unavailable"
        if self.has_warnings:
            return "⚠ Ingredients Missing"
        return "Available"


# ─────────────────────────────────────────────────────────────────────────────
# Menu State
# ─────────────────────────────────────────────────────────────────────────────
class MenuState(QObject):
    menu_changed = pyqtSignal()

    def __init__(self, menu_db: MenuDB):
        super().__init__()
        self.menu_db         = menu_db
        self.inv_db          = get_db()
        self.items:          list[MenuItem] = []
        self.active_category = "All"
        self._reload()

    # ── Load ──────────────────────────────────────────────────────────────────
    def _reload(self) -> None:
        raw_items    = self.menu_db.fetch_all_menu_items()
        inv_products = {p["name"].lower(): p for p in self.inv_db.fetch_all()}

        self.items = []
        for r in raw_items:
            ingredients = [
                MenuIngredient(
                    id=ing["id"],
                    menu_item_id=ing["menu_item_id"],
                    ingredient_name=ing["ingredient_name"],
                    quantity=float(ing["quantity"]),
                    unit=str(ing["unit"]),
                )
                for ing in self.menu_db.fetch_ingredients(r["id"])
            ]

            missing    = []
            outofstock = []
            max_can_make: Optional[int] = None  # track limiting ingredient

            for ing in ingredients:
                key = ing.ingredient_name.lower()
                if key not in inv_products:
                    missing.append(ing.ingredient_name)
                else:
                    stock = int(inv_products[key].get("stock", 0))
                    if stock <= 0:
                        outofstock.append(ing.ingredient_name)
                    else:
                        # How many of this item can we make from this ingredient?
                        if ing.quantity > 0:
                            can_from_this = int(stock // ing.quantity)
                        else:
                            can_from_this = stock
                        if max_can_make is None:
                            max_can_make = can_from_this
                        else:
                            max_can_make = min(max_can_make, can_from_this)

            # If any ingredient is out of stock, max is 0
            if outofstock:
                max_can_make = 0

            self.items.append(MenuItem(
                id=r["id"],
                name=r["name"],
                category=r["category"],
                price=float(r["price"]),
                description=r.get("description", ""),
                image_path=r.get("image_path"),
                ingredients=ingredients,
                missing_ingredients=missing,
                outofstock_ingredients=outofstock,
                max_can_make=max_can_make,
            ))

    def reload(self) -> None:
        self._reload()
        self.menu_changed.emit()

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def add_item(self, item_dict: dict, ingredients: list[dict]) -> int:
        new_id = self.menu_db.insert_menu_item(item_dict)
        self.menu_db.replace_ingredients(new_id, ingredients)
        self.reload()
        return new_id

    def update_item(self, item_dict: dict, ingredients: list[dict]) -> None:
        self.menu_db.update_menu_item(item_dict)
        self.menu_db.replace_ingredients(item_dict["id"], ingredients)
        self.reload()

    def delete_item(self, item_id: int) -> None:
        self.menu_db.delete_menu_item(item_id)
        self.reload()

    # ── Filters ───────────────────────────────────────────────────────────────
    @property
    def categories(self) -> list[str]:
        cats, seen = ["All"], set()
        for item in self.items:
            if item.category not in seen:
                cats.append(item.category)
                seen.add(item.category)
        return cats

    @property
    def filtered_items(self) -> list[MenuItem]:
        if self.active_category == "All":
            return self.items
        return [i for i in self.items if i.category == self.active_category]


# ─────────────────────────────────────────────────────────────────────────────
# UI Helpers
# ─────────────────────────────────────────────────────────────────────────────
def lbl(text="", bold=False, size=13, color=None) -> QLabel:
    w = QLabel(text)
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    w.setFont(f)
    w.setStyleSheet(f"color:{color or C['text']};background:transparent;")
    return w


def hline() -> QFrame:
    ln = QFrame()
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


def pill_button(text: str, active=False) -> QPushButton:
    # Escape & so Qt does not interpret it as a keyboard mnemonic accelerator
    display = text.replace("&", "&&")
    btn = QPushButton(display)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setCheckable(True)
    btn.setChecked(active)
    btn.setFlat(True)
    _style_pill(btn)
    btn.toggled.connect(lambda: _style_pill(btn))
    return btn


def _style_pill(btn: QPushButton):
    if btn.isChecked():
        btn.setStyleSheet(f"""QPushButton{{background:{C['accent']};color:white;
            border-radius:6px;padding:5px 14px;font-weight:600;border:none;}}""")
    else:
        btn.setStyleSheet(f"""QPushButton{{background:{C['border']};color:{C['text']};
            border-radius:6px;padding:5px 14px;border:none;}}
            QPushButton:hover{{background:#D1D5DB;}}""")


# ─────────────────────────────────────────────────────────────────────────────
# Ingredient Row Widget (used inside ItemDialog)
# ─────────────────────────────────────────────────────────────────────────────
class IngredientRow(QWidget):
    remove_clicked = pyqtSignal(object)

    def __init__(self, ingredient: dict | None = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(6)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ingredient name…")
        self.name_edit.setFixedHeight(30)
        self.name_edit.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:0 8px;background:{C['bg']};font-size:12px;"
        )

        self.qty_spin = QDoubleSpinBox()
        self.qty_spin.setRange(0.01, 99999)
        self.qty_spin.setDecimals(2)
        self.qty_spin.setValue(1.0)
        self.qty_spin.setFixedWidth(80)
        self.qty_spin.setFixedHeight(30)
        self.qty_spin.setStyleSheet(
            f"QDoubleSpinBox{{border:1px solid {C['border']};border-radius:6px;"
            f"padding:0 6px;background:{C['bg']};font-size:12px;}}"
        )

        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("unit")
        self.unit_edit.setFixedWidth(70)
        self.unit_edit.setFixedHeight(30)
        self.unit_edit.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:0 8px;background:{C['bg']};font-size:12px;"
        )

        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(28, 28)
        rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rm_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['danger']};"
            f"border:none;font-size:14px;font-weight:700;}}"
            f"QPushButton:hover{{color:#b91c1c;}}"
        )
        rm_btn.clicked.connect(lambda: self.remove_clicked.emit(self))

        lay.addWidget(self.name_edit, stretch=2)
        lay.addWidget(self.qty_spin)
        lay.addWidget(self.unit_edit)
        lay.addWidget(rm_btn)

        if ingredient:
            self.name_edit.setText(str(ingredient.get("ingredient_name", "")))
            self.qty_spin.setValue(float(ingredient.get("quantity", 1.0)))
            self.unit_edit.setText(str(ingredient.get("unit", "")))

    def to_dict(self) -> dict:
        return {
            "ingredient_name": self.name_edit.text().strip(),
            "quantity":        self.qty_spin.value(),
            "unit":            self.unit_edit.text().strip() or "units",
        }

    def is_valid(self) -> bool:
        return bool(self.name_edit.text().strip())


# ─────────────────────────────────────────────────────────────────────────────
# Ingredient Detail Popup
# ─────────────────────────────────────────────────────────────────────────────
class IngredientDetailDialog(QDialog):
    """Read-only popup listing all ingredients and their inventory status."""

    def __init__(self, item: MenuItem, inv_products: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{item.name} — Ingredients")
        self.setMinimumWidth(460)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(pal.ColorRole.Window, QColor(C["white"]))
        self.setPalette(pal)
        self._build(item, inv_products)

    def _build(self, item: MenuItem, inv_products: dict):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        # Header
        title_row = QHBoxLayout()
        title_row.addWidget(lbl(item.emoji, size=22))
        title_col = QVBoxLayout()
        title_col.addWidget(lbl(item.name, bold=True, size=14))
        title_col.addWidget(lbl(item.category, size=10, color=C["sub"]))
        title_row.addLayout(title_col)
        title_row.addStretch()

        # Max can make badge
        if item.max_can_make is not None:
            if item.max_can_make == 0:
                cap_badge = QLabel("🔒 Cannot make")
                cap_badge.setStyleSheet(
                    f"background:{C['danger_lt']};color:{C['danger']};"
                    f"border-radius:5px;padding:3px 10px;font-size:11px;font-weight:700;"
                )
            elif item.max_can_make <= 3:
                cap_badge = QLabel(f"⚠ Can make: {item.max_can_make}")
                cap_badge.setStyleSheet(
                    f"background:{C['warn_lt']};color:{C['warn']};"
                    f"border-radius:5px;padding:3px 10px;font-size:11px;font-weight:700;"
                )
            else:
                cap_badge = QLabel(f"✓ Can make: {item.max_can_make}")
                cap_badge.setStyleSheet(
                    f"background:{C['ok_lt']};color:{C['ok']};"
                    f"border-radius:5px;padding:3px 10px;font-size:11px;font-weight:700;"
                )
            title_row.addWidget(cap_badge)

        lay.addLayout(title_row)
        lay.addWidget(hline())

        if not item.ingredients:
            lay.addWidget(lbl("No ingredients defined.", size=11, color=C["sub"]))
        else:
            # Column headers
            hdr = QHBoxLayout()
            hdr.addWidget(lbl("Ingredient", size=10, color=C["sub"]), stretch=3)
            hdr.addWidget(lbl("Qty", size=10, color=C["sub"]))
            hdr.addWidget(lbl("Unit", size=10, color=C["sub"]))
            hdr.addWidget(lbl("In Stock", size=10, color=C["sub"]))
            hdr.addWidget(lbl("Can Make", size=10, color=C["sub"]))
            hdr.addWidget(lbl("Status", size=10, color=C["sub"]))
            lay.addLayout(hdr)
            lay.addWidget(hline())

            for ing in item.ingredients:
                key = ing.ingredient_name.lower()
                row = QHBoxLayout()
                row.addWidget(lbl(ing.ingredient_name, size=11), stretch=3)
                row.addWidget(lbl(f"{ing.quantity:g}", size=11))
                row.addWidget(lbl(ing.unit, size=11, color=C["sub"]))

                if key not in inv_products:
                    stock_lbl    = lbl("—", size=11, color=C["sub"])
                    can_make_lbl = lbl("?", size=11, color=C["sub"])
                    status_lbl   = QLabel("⚠ Not found")
                    status_lbl.setStyleSheet(
                        f"background:{C['warn_lt']};color:{C['warn']};"
                        f"border-radius:4px;padding:1px 6px;font-size:10px;font-weight:700;"
                    )
                elif int(inv_products[key].get("stock", 0)) <= 0:
                    stock_lbl    = lbl("0", size=11, color=C["danger"])
                    can_make_lbl = lbl("0", size=11, color=C["danger"])
                    status_lbl   = QLabel("🔒 Out of stock")
                    status_lbl.setStyleSheet(
                        f"background:{C['danger_lt']};color:{C['danger']};"
                        f"border-radius:4px;padding:1px 6px;font-size:10px;font-weight:700;"
                    )
                else:
                    stock_val = int(inv_products[key].get("stock", 0))
                    can_make  = int(stock_val // ing.quantity) if ing.quantity > 0 else stock_val
                    stock_lbl = lbl(str(stock_val), size=11, color=C["ok"])

                    if can_make <= 3:
                        can_make_lbl = lbl(str(can_make), size=11, color=C["warn"], bold=True)
                    else:
                        can_make_lbl = lbl(str(can_make), size=11, color=C["ok"])

                    status_lbl = QLabel("✓ OK")
                    status_lbl.setStyleSheet(
                        f"background:{C['ok_lt']};color:{C['ok']};"
                        f"border-radius:4px;padding:1px 6px;font-size:10px;font-weight:700;"
                    )

                row.addWidget(stock_lbl)
                row.addWidget(can_make_lbl)
                row.addWidget(status_lbl)
                lay.addLayout(row)

        lay.addWidget(hline())
        close_btn = action_btn("Close")
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)


# ─────────────────────────────────────────────────────────────────────────────
# Add / Edit Menu Item Dialog
# ─────────────────────────────────────────────────────────────────────────────
class MenuItemDialog(QDialog):
    def __init__(self, state: MenuState, item: MenuItem | None = None, parent=None):
        super().__init__(parent)
        self.state = state
        self.item  = item
        self.setWindowTitle("Edit Menu Item" if item else "Add Menu Item")
        self.setMinimumWidth(520)
        self.setMinimumHeight(580)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(pal.ColorRole.Window, QColor(C["white"]))
        self.setPalette(pal)
        self._ingredient_rows: list[IngredientRow] = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Title bar
        title_bar = QWidget()
        title_bar.setStyleSheet(f"background:{C['white']};")
        tb = QVBoxLayout(title_bar)
        tb.setContentsMargins(28, 20, 28, 12)
        tb.addWidget(lbl("Edit Menu Item" if self.item else "Add Menu Item",
                         bold=True, size=16))
        outer.addWidget(title_bar)
        outer.addWidget(hline())

        # Scrollable form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{background:{C['white']};border:none;}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:6px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )

        form_w = QWidget()
        form_w.setStyleSheet(f"background:{C['white']};")
        self.form_lay = QVBoxLayout(form_w)
        self.form_lay.setContentsMargins(28, 16, 28, 20)
        self.form_lay.setSpacing(12)

        def field(label_text, widget):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(lbl(label_text, size=11, color=C["sub"]))
            widget.setStyleSheet(
                f"border:1px solid {C['border']};border-radius:7px;"
                f"padding:7px 10px;background:{C['bg']};font-size:13px;"
            )
            col.addWidget(widget)
            self.form_lay.addLayout(col)
            return widget

        p = self.item
        self.f_name  = field("Item Name *", QLineEdit(p.name if p else ""))
        self.f_desc  = field("Description", QLineEdit(p.description if p else ""))

        # Category
        cat_col = QVBoxLayout(); cat_col.setSpacing(4)
        cat_col.addWidget(lbl("Category", size=11, color=C["sub"]))
        self.f_cat = QComboBox()
        self.f_cat.setEditable(True)
        for c in list(CATEGORY_EMOJI.keys()) + [
            cat for cat in self.state.categories if cat != "All"
            and cat not in CATEGORY_EMOJI
        ]:
            if self.f_cat.findText(c) < 0:
                self.f_cat.addItem(c)
        if p:
            idx = self.f_cat.findText(p.category)
            if idx >= 0:
                self.f_cat.setCurrentIndex(idx)
        self.f_cat.setStyleSheet(
            f"QComboBox{{border:1px solid {C['border']};border-radius:7px;"
            f"padding:7px 10px;background:{C['bg']};font-size:13px;}}"
            f"QComboBox::drop-down{{border:none;width:24px;}}"
        )
        cat_col.addWidget(self.f_cat)
        self.form_lay.addLayout(cat_col)

        # Price
        price_col = QVBoxLayout(); price_col.setSpacing(4)
        price_col.addWidget(lbl("Price (₱)", size=11, color=C["sub"]))
        self.f_price = QDoubleSpinBox()
        self.f_price.setRange(0, 99999)
        self.f_price.setDecimals(2)
        self.f_price.setPrefix("₱ ")
        self.f_price.setValue(p.price if p else 0.0)
        self.f_price.setStyleSheet(
            f"QDoubleSpinBox{{border:1px solid {C['border']};border-radius:7px;"
            f"padding:7px 10px;background:{C['bg']};font-size:13px;}}"
        )
        price_col.addWidget(self.f_price)
        self.form_lay.addLayout(price_col)

        # Ingredients section
        self.form_lay.addWidget(hline())
        ing_hdr = QHBoxLayout()
        ing_hdr.addWidget(lbl("Ingredients / Recipe", bold=True, size=13))
        ing_hdr.addStretch()
        add_ing_btn = QPushButton("＋ Add Ingredient")
        add_ing_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_ing_btn.setFixedHeight(28)
        add_ing_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent_lt']};color:{C['accent']};"
            f"border:1.5px solid {C['accent']};border-radius:6px;"
            f"padding:0 12px;font-weight:700;font-size:11px;}}"
            f"QPushButton:hover{{background:{C['accent']};color:white;}}"
        )
        add_ing_btn.clicked.connect(self._add_ingredient_row)
        ing_hdr.addWidget(add_ing_btn)
        self.form_lay.addLayout(ing_hdr)

        hint = lbl(
            "⚠  Ingredients not found in Inventory will show a warning.\n"
            "Items with out-of-stock ingredients will be locked in POS.\n"
            "Orders exceeding ingredient stock will trigger a warning.",
            size=10, color=C["sub"]
        )
        hint.setWordWrap(True)
        self.form_lay.addWidget(hint)

        # Column headers for ingredient rows
        col_hdr = QHBoxLayout()
        col_hdr.setSpacing(6)
        col_hdr.addWidget(lbl("Ingredient Name", size=10, color=C["sub"]), stretch=2)
        col_hdr.addWidget(lbl("Qty", size=10, color=C["sub"]))
        col_hdr.addWidget(lbl("Unit", size=10, color=C["sub"]))
        col_hdr.addSpacing(34)
        self.form_lay.addLayout(col_hdr)

        # Container for ingredient rows
        self.ing_container = QWidget()
        self.ing_container.setStyleSheet("background:transparent;")
        self.ing_layout = QVBoxLayout(self.ing_container)
        self.ing_layout.setContentsMargins(0, 0, 0, 0)
        self.ing_layout.setSpacing(4)
        self.form_lay.addWidget(self.ing_container)

        # Populate existing ingredients in edit mode
        if p and p.ingredients:
            for ing in p.ingredients:
                self._add_ingredient_row({
                    "ingredient_name": ing.ingredient_name,
                    "quantity":        ing.quantity,
                    "unit":            ing.unit,
                })
        else:
            self._add_ingredient_row()

        scroll.setWidget(form_w)
        outer.addWidget(scroll, stretch=1)

        # Footer
        footer = QWidget()
        footer.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(28, 12, 28, 14)
        fl.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setFixedHeight(36)
        cancel.setStyleSheet(
            f"QPushButton{{background:{C['border']};color:{C['text']};"
            f"border-radius:7px;padding:0 20px;font-weight:600;font-size:13px;border:none;}}"
            f"QPushButton:hover{{background:#D1D5DB;}}"
        )
        cancel.clicked.connect(self.reject)

        save = action_btn("Save Item")
        save.setFixedHeight(36)
        save.clicked.connect(self._save)

        fl.addWidget(cancel)
        fl.addSpacing(8)
        fl.addWidget(save)
        outer.addWidget(footer)

    def _add_ingredient_row(self, ingredient: dict | None = None):
        row = IngredientRow(ingredient)
        row.remove_clicked.connect(self._remove_ingredient_row)
        self._ingredient_rows.append(row)
        self.ing_layout.addWidget(row)

    def _remove_ingredient_row(self, row: IngredientRow):
        self._ingredient_rows.remove(row)
        self.ing_layout.removeWidget(row)
        row.deleteLater()

    def _save(self):
        name = self.f_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Item name is required.")
            return

        item_dict = {
            "name":        name,
            "category":    self.f_cat.currentText().strip() or "Other",
            "price":       self.f_price.value(),
            "description": self.f_desc.text().strip(),
        }

        ingredients = [
            r.to_dict() for r in self._ingredient_rows if r.is_valid()
        ]

        if self.item:
            item_dict["id"] = self.item.id
            self.state.update_item(item_dict, ingredients)
        else:
            self.state.add_item(item_dict, ingredients)

        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Menu Item Card — now shows "Can make: N" capacity badge
# ─────────────────────────────────────────────────────────────────────────────
class MenuItemCard(QFrame):
    edit_clicked      = pyqtSignal(object)
    delete_clicked    = pyqtSignal(object)
    details_requested = pyqtSignal(object)

    def __init__(self, item: MenuItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("menuCard")
        self.setFixedSize(210, 280)
        locked = item.is_locked
        warned = item.has_warnings

        border_color = (C["danger"] if locked
                        else C["warn"] if warned
                        else C["border"])
        bg_color = (C["danger_lt"] if locked
                    else C["warn_lt"] if warned
                    else C["white"])

        self.setStyleSheet(f"""
            QFrame#menuCard {{
                background:{bg_color};
                border:1.5px solid {border_color};
                border-radius:10px;
            }}
        """)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(4)

        # ── Top row: availability badge + capacity badge ───────────────────
        badge_row = QHBoxLayout()
        badge_row.setSpacing(4)

        if self.item.is_locked:
            avail_badge = QLabel("🔒 Unavailable")
            avail_badge.setStyleSheet(
                f"background:{C['danger_lt']};color:{C['danger']};"
                f"border-radius:4px;padding:2px 6px;font-size:9px;font-weight:700;"
            )
        elif self.item.has_warnings:
            avail_badge = QLabel("⚠ Missing")
            avail_badge.setStyleSheet(
                f"background:{C['warn_lt']};color:{C['warn']};"
                f"border-radius:4px;padding:2px 6px;font-size:9px;font-weight:700;"
            )
        else:
            avail_badge = QLabel("✓ Available")
            avail_badge.setStyleSheet(
                f"background:{C['ok_lt']};color:{C['ok']};"
                f"border-radius:4px;padding:2px 6px;font-size:9px;font-weight:700;"
            )
        badge_row.addWidget(avail_badge)
        badge_row.addStretch()

        # Capacity badge — how many can currently be made
        if self.item.max_can_make is not None and not self.item.is_locked:
            if self.item.max_can_make == 0:
                cap_label = "Can make: 0"
                cap_style = (
                    f"background:{C['danger_lt']};color:{C['danger']};"
                    f"border-radius:4px;padding:2px 6px;font-size:9px;font-weight:700;"
                )
            elif self.item.max_can_make <= 3:
                cap_label = f"Can make: {self.item.max_can_make}"
                cap_style = (
                    f"background:{C['warn_lt']};color:{C['warn']};"
                    f"border-radius:4px;padding:2px 6px;font-size:9px;font-weight:700;"
                )
            else:
                cap_label = f"Can make: {self.item.max_can_make}"
                cap_style = (
                    f"background:{C['ok_lt']};color:{C['ok']};"
                    f"border-radius:4px;padding:2px 6px;font-size:9px;font-weight:700;"
                )
            cap_badge = QLabel(cap_label)
            cap_badge.setStyleSheet(cap_style)
            badge_row.addWidget(cap_badge)

        lay.addLayout(badge_row)

        # Emoji
        emoji_lbl = QLabel(self.item.emoji)
        emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emoji_lbl.setStyleSheet(
            "font-size:36px;background:#F0EDE8;border-radius:6px;"
            "padding:8px;border:none;"
        )
        lay.addWidget(emoji_lbl)

        # Name
        name_lbl = lbl(self.item.name, bold=True, size=12)
        name_lbl.setWordWrap(True)
        lay.addWidget(name_lbl)

        # Category
        lay.addWidget(lbl(self.item.category, size=10, color=C["sub"]))

        # Ingredients count — clickable to show detail
        ing_count = len(self.item.ingredients)
        ing_color = (C["danger"] if self.item.is_locked
                     else C["warn"] if self.item.has_warnings
                     else C["sub"])
        ing_btn = QPushButton(
            f"{ing_count} ingredient{'s' if ing_count != 1 else ''} ▸"
        )
        ing_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ing_btn.setFlat(True)
        ing_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{ing_color};"
            f"font-size:10px;border:none;text-align:left;padding:0;}}"
            f"QPushButton:hover{{color:{C['accent']};text-decoration:underline;}}"
        )
        ing_btn.clicked.connect(lambda: self.details_requested.emit(self.item))
        lay.addWidget(ing_btn)

        # Low-stock warning detail
        if self.item.is_locked:
            detail = lbl(
                f"Out of stock: {', '.join(self.item.outofstock_ingredients[:2])}",
                size=9, color=C["danger"]
            )
            detail.setWordWrap(True)
            lay.addWidget(detail)
        elif self.item.has_warnings:
            detail = lbl(
                f"Not in inv: {', '.join(self.item.missing_ingredients[:2])}",
                size=9, color=C["warn"]
            )
            detail.setWordWrap(True)
            lay.addWidget(detail)
        elif self.item.max_can_make is not None and self.item.max_can_make <= 5:
            detail = lbl(
                f"⚠ Low stock — only {self.item.max_can_make} servings left",
                size=9, color=C["warn"]
            )
            detail.setWordWrap(True)
            lay.addWidget(detail)

        lay.addStretch()

        # Price + action buttons
        bottom = QHBoxLayout()
        bottom.addWidget(lbl(f"₱{self.item.price:.2f}", bold=True, size=12,
                             color=C["accent"]))
        bottom.addStretch()

        edit_btn = QPushButton("✏")
        edit_btn.setFixedSize(28, 28)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent_lt']};color:{C['accent']};"
            f"border-radius:5px;border:none;font-size:14px;}}"
            f"QPushButton:hover{{background:{C['accent']};color:white;}}"
        )
        edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.item))

        del_btn = QPushButton("🗑")
        del_btn.setFixedSize(28, 28)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(
            f"QPushButton{{background:{C['danger_lt']};color:{C['danger']};"
            f"border-radius:5px;border:none;font-size:14px;}}"
            f"QPushButton:hover{{background:{C['danger']};color:white;}}"
        )
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.item))

        bottom.addWidget(edit_btn)
        bottom.addSpacing(4)
        bottom.addWidget(del_btn)
        lay.addLayout(bottom)


# ─────────────────────────────────────────────────────────────────────────────
# Main Menu Window
# ─────────────────────────────────────────────────────────────────────────────
class MenuWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.menu_db = get_menu_db()
        self.state   = MenuState(self.menu_db)
        self.setWindowTitle("Pawffinated – Menu Management")
        self.resize(1200, 780)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(f"""
            QMainWindow, #centralWidget {{ background:{C['bg']}; }}
            QWidget {{ font-family:'Segoe UI',Helvetica,sans-serif; }}
            QToolBar {{
                background:{C['white']};
                border-bottom:1px solid {C['border']};
                padding:4px 16px; spacing:8px;
            }}
            QStatusBar {{
                background:{C['white']};
                border-top:1px solid {C['border']};
                color:{C['sub']}; font-size:11px; padding:0 12px;
            }}
            QScrollArea {{ border:none; background:transparent; }}
            QScrollBar:vertical {{
                background:{C['bg']}; width:6px; margin:0;
            }}
            QScrollBar::handle:vertical {{
                background:{C['border']}; border-radius:3px; min-height:30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        self._build_toolbar()
        self._build_ui()
        self._build_statusbar()
        self.state.menu_changed.connect(self._refresh)
        self._refresh()

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        refresh_act = QAction("🔄  Refresh", self)
        refresh_act.triggered.connect(lambda: self.state.reload())
        tb.addAction(refresh_act)

        add_btn = action_btn("＋  Add Menu Item")
        add_btn.setFixedHeight(34)
        add_btn.clicked.connect(self._add_item)
        tb.addWidget(add_btn)

    # ── Central UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(PawffinatedSidebar(active_page="Menu"))
        self._build_main_area(root)

    def _build_main_area(self, parent_layout):
        self.main_area = QWidget()
        self.main_area.setStyleSheet(f"background:{C['bg']};")
        ma = QVBoxLayout(self.main_area)
        ma.setContentsMargins(0, 0, 0, 0)
        ma.setSpacing(0)

        # ── Page header ───────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 0)
        hl.setSpacing(4)

        title_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.addWidget(lbl("Menu", bold=True, size=20))
        title_col.addWidget(lbl(
            "Build and manage menu items with ingredient recipes. "
            "Each card shows how many servings can currently be made. "
            "Locked items (🔒) have out-of-stock ingredients and cannot be ordered.",
            size=11, color=C["sub"]
        ))
        title_row.addLayout(title_col)
        title_row.addStretch()
        add_hdr_btn = action_btn("＋  Add Menu Item")
        add_hdr_btn.setFixedHeight(34)
        add_hdr_btn.clicked.connect(self._add_item)
        title_row.addWidget(add_hdr_btn)
        hl.addLayout(title_row)

        # Category filter tabs
        self.tab_row = QHBoxLayout()
        self.tab_row.setSpacing(6)
        self.tab_row.setContentsMargins(0, 10, 0, 12)
        self._tab_buttons: dict[str, QPushButton] = {}
        hl.addLayout(self.tab_row)
        ma.addWidget(hdr)

        # ── Legend bar ────────────────────────────────────────────────────────
        legend = QWidget()
        legend.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        ll = QHBoxLayout(legend)
        ll.setContentsMargins(28, 8, 28, 8)
        ll.setSpacing(20)
        for color, bg, text in [
            (C["ok"],     C["ok_lt"],     "✓ Available — all ingredients in stock"),
            (C["warn"],   C["warn_lt"],   "⚠ Warning — ingredient not in inventory"),
            (C["danger"], C["danger_lt"], "🔒 Locked — ingredient out of stock (cannot order)"),
        ]:
            badge = QLabel(text)
            badge.setStyleSheet(
                f"background:{bg};color:{color};border-radius:4px;"
                f"padding:3px 10px;font-size:10px;font-weight:600;"
            )
            ll.addWidget(badge)
        ll.addStretch()
        ma.addWidget(legend)

        # ── Scroll area for cards ─────────────────────────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"background:{C['bg']};border:none;")

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet(f"background:{C['bg']};")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(24, 20, 24, 20)
        self.grid_layout.setSpacing(14)

        self.scroll.setWidget(self.grid_container)
        ma.addWidget(self.scroll, stretch=1)

        parent_layout.addWidget(self.main_area, stretch=1)

    # ── Statusbar ─────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        self.status_lbl = QLabel()
        self.status_msg = QLabel()
        self.status_msg.setStyleSheet(f"color:{C['accent']};font-weight:600;")
        self.statusBar().addWidget(self.status_lbl)
        self.statusBar().addPermanentWidget(self.status_msg)

    # ── Refresh ───────────────────────────────────────────────────────────────
    def _refresh(self):
        self._refresh_tabs()
        self._refresh_grid()
        items  = self.state.items
        locked = sum(1 for i in items if i.is_locked)
        warned = sum(1 for i in items if i.has_warnings and not i.is_locked)
        low    = sum(1 for i in items if not i.is_locked and not i.has_warnings
                     and i.max_can_make is not None and i.max_can_make <= 5)
        self.status_lbl.setText(
            f"Total items: {len(items)}  |  "
            f"Available: {len(items) - locked - warned}  |  "
            f"Low stock: {low}  |  "
            f"Warnings: {warned}  |  Locked: {locked}"
        )

    def _refresh_tabs(self):
        for i in reversed(range(self.tab_row.count())):
            item = self.tab_row.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
                self.tab_row.removeItem(item)
        self._tab_buttons.clear()

        for cat in self.state.categories:
            btn = pill_button(cat, active=(cat == self.state.active_category))
            self._tab_buttons[cat] = btn
            self.tab_row.addWidget(btn)
            btn.clicked.connect(lambda _, c=cat: self._select_category(c))
        self.tab_row.addStretch()

    def _select_category(self, cat: str):
        self.state.active_category = cat
        self._refresh_grid()

    def _refresh_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        items = self.state.filtered_items
        if not items:
            empty = lbl(
                "No menu items yet.\nClick '＋ Add Menu Item' to create one.",
                color=C["sub"]
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 60, 0, 0)
            self.grid_layout.addWidget(empty, 0, 0)
            return

        cols = max(1, (self.main_area.width() - 48) // 228)
        self._inv_products = {
            p["name"].lower(): p
            for p in self.state.inv_db.fetch_all()
        }
        for i, item in enumerate(items):
            card = MenuItemCard(item)
            card.edit_clicked.connect(self._edit_item)
            card.delete_clicked.connect(self._delete_item)
            card.details_requested.connect(self._show_ingredient_detail)
            self.grid_layout.addWidget(card, i // cols, i % cols)

        last = len(items)
        fill = cols - (last % cols)
        if fill != cols:
            for j in range(fill):
                sp = QWidget()
                sp.setFixedWidth(210)
                self.grid_layout.addWidget(sp, (last - 1) // cols, (last % cols) + j)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._refresh_grid)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _add_item(self):
        MenuItemDialog(self.state, parent=self).exec()

    def _edit_item(self, item: MenuItem):
        MenuItemDialog(self.state, item, parent=self).exec()

    def _delete_item(self, item: MenuItem):
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete '{item.name}' from the menu?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.state.delete_item(item.id)
            self._flash(f"Deleted '{item.name}'.")

    def _show_ingredient_detail(self, item: MenuItem):
        inv = getattr(self, "_inv_products", {})
        IngredientDetailDialog(item, inv, parent=self).exec()

    def _flash(self, msg: str, ms: int = 4000):
        self.status_msg.setText(msg)
        QTimer.singleShot(ms, lambda: self.status_msg.setText(""))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
class MenuApp(QApplication):
    def __init__(self, argv=None):
        super().__init__(argv or sys.argv)
        self.setApplicationName("Pawffinated Menu")

    def run(self):
        try:
            get_menu_db()
        except ConnectionError as exc:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Database Connection Failed")
            msg.setText("Could not connect to the database.")
            msg.setDetailedText(str(exc))
            msg.exec()
            sys.exit(1)
        self.window = MenuWindow()
        self.window.show()
        result = self.exec()
        close_db()
        return result


if __name__ == "__main__":
    app = MenuApp(sys.argv)
    sys.exit(app.run())