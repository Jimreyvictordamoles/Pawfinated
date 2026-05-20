"""
PAWFFINATED – Inventory Management  (PyQt6 + PostgreSQL)
=========================================================
Install:
    pip install PyQt6 psycopg2-binary openpyxl

Run:
    python Inventory.py

Database connection is managed entirely by Db_connection.py.
Configure credentials in pawffinated.env before running.
The products table is created and seeded automatically on first launch.

IMAGE SUPPORT
-------------
• Product images are stored as absolute file paths in products.image_path.
• When adding / editing a product the user can click "Upload Image" to pick
  a PNG/JPG/JPEG/WEBP file.  The file is copied into
      <script_dir>/product_images/<id>_<sanitised_name>.<ext>
  so images travel with the project folder.
• The inventory table shows a 48×48 thumbnail; the category emoji is used
  as a fallback when no image has been set.
• get_product_thumbnail(path, size) — module-level helper that returns a
  QPixmap scaled to `size` (default 48) for reuse in POS, Dashboard, Sales.
"""

from __future__ import annotations

import sys, csv, io, shutil, re as _re
from dataclasses import dataclass, field
from pathlib import Path
from DbConnection import get_db, close_db, db_info, InventoryDB

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QSizePolicy, QFileDialog,
    QDialog, QLineEdit, QTextEdit, QMessageBox, QComboBox, QSpinBox,
    QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMenu, QToolBar, QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QAction, QBrush, QPixmap, QPainter, QPainterPath
from Sidebar import PawffinatedSidebar

# ── Image storage folder ──────────────────────────────────────────────────────
_IMAGES_DIR = Path(__file__).resolve().parent / "product_images"
_IMAGES_DIR.mkdir(exist_ok=True)

# ── Palette ───────────────────────────────────────────────────────────────────
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
    badge_ok  = "#D1FAE5",
    badge_ok_t= "#065F46",
)

LOW_STOCK_THRESHOLD = 10

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

_SUPPORTED_IMAGE_EXTS = "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)"


# ── Public image helper (used by POS, Dashboard, Sales) ──────────────────────

def get_product_thumbnail(image_path: str | None, size: int = 48) -> QPixmap | None:
    """
    Return a square QPixmap scaled to `size` px from `image_path`.
    Returns None if image_path is falsy or the file does not exist.
    The caller should fall back to the category emoji when None is returned.
    """
    if not image_path:
        return None
    p = Path(image_path)
    if not p.exists():
        return None
    pix = QPixmap(str(p))
    if pix.isNull():
        return None
    # Scale to square, cropping to centre
    pix = pix.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    # Centre-crop to exact square
    if pix.width() != size or pix.height() != size:
        x = (pix.width()  - size) // 2
        y = (pix.height() - size) // 2
        pix = pix.copy(x, y, size, size)
    return pix


def _rounded_pixmap(pix: QPixmap, radius: int = 8) -> QPixmap:
    """Return a copy of `pix` with rounded corners."""
    size   = pix.size()
    result = QPixmap(size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    return result


def _save_product_image(src: str, item_id: int, item_name: str) -> str:
    """
    Copy `src` into product_images/ with a deterministic name.
    Returns the destination absolute path as a string.
    """
    ext  = Path(src).suffix.lower() or ".jpg"
    safe = _re.sub(r"[^\w\-]", "_", item_name.lower())[:40]
    dest = _IMAGES_DIR / f"{item_id}_{safe}{ext}"
    shutil.copy2(src, dest)
    return str(dest)


# ─────────────────────────────────────────────────────────────────────────────
# Domain model
# ─────────────────────────────────────────────────────────────────────────────
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
    image_path: str | None = None          # ← NEW

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

    def thumbnail(self, size: int = 48) -> QPixmap | None:
        """Convenience wrapper around get_product_thumbnail."""
        return get_product_thumbnail(self.image_path, size)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "name":        self.name,
            "sku":         self.sku,
            "category":    self.category,
            "stock":       self.stock,
            "unit":        self.unit,
            "price":       self.price,
            "description": self.description,
            "image_path":  self.image_path,    # ← NEW
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InventoryItem":
        return cls(
            id=int(d["id"]),
            name=str(d["name"]),
            sku=str(d.get("sku") or ""),
            category=str(d.get("category") or "Other"),
            stock=int(d.get("stock") or 0),
            unit=str(d.get("unit") or "units"),
            price=float(d.get("price") or 0.0),
            description=str(d.get("description") or ""),
            image_path=d.get("image_path") or None,   # ← NEW
        )


# ─────────────────────────────────────────────────────────────────────────────
# Inventory State
# ─────────────────────────────────────────────────────────────────────────────
class InventoryState(QObject):
    inventory_changed = pyqtSignal()
    item_added        = pyqtSignal(object)
    item_updated      = pyqtSignal(object)
    item_deleted      = pyqtSignal(int)

    def __init__(self, db: InventoryDB):
        super().__init__()
        self.db = db
        self.search_query:  str = ""
        self.filter_status: str = "All"
        self.products: list[InventoryItem] = self._load_from_db()

    def _load_from_db(self) -> list[InventoryItem]:
        return [InventoryItem.from_dict(r) for r in self.db.fetch_all()]

    def _reload(self) -> None:
        self.products = self._load_from_db()

    @property
    def low_stock_items(self) -> list[InventoryItem]:
        return [p for p in self.products if 0 < p.stock <= LOW_STOCK_THRESHOLD]

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

    def add_item(self, item: InventoryItem) -> InventoryItem:
        new_id = self.db.insert(item.to_dict())
        item.id = new_id
        # If a pending image exists with id=0, move it to the real id
        if item.image_path and "_0_" in item.image_path:
            try:
                new_path = _save_product_image(item.image_path, new_id, item.name)
                Path(item.image_path).unlink(missing_ok=True)
                item.image_path = new_path
                self.db.update(item.to_dict())
            except Exception:
                pass
        self._reload()
        self.inventory_changed.emit()
        real = self.get_by_id(new_id)
        self.item_added.emit(real or item)
        return real or item

    def update_item(self, updated: InventoryItem) -> None:
        self.db.update(updated.to_dict())
        self._reload()
        self.inventory_changed.emit()
        self.item_updated.emit(updated)

    def delete_item(self, item_id: int) -> None:
        # Optionally remove orphaned image file
        item = self.get_by_id(item_id)
        if item and item.image_path:
            try:
                Path(item.image_path).unlink(missing_ok=True)
            except Exception:
                pass
        self.db.delete(item_id)
        self._reload()
        self.inventory_changed.emit()
        self.item_deleted.emit(item_id)

    def get_by_id(self, item_id: int) -> InventoryItem | None:
        for p in self.products:
            if p.id == item_id:
                return p
        return None

    _COL_ALIASES = {
        "name":        ["name", "product_name", "item_name", "title"],
        "sku":         ["sku", "code", "barcode", "product_code", "item_code"],
        "category":    ["category", "cat", "type", "section", "department"],
        "stock":       ["stock", "qty", "quantity", "inventory", "count", "on_hand"],
        "unit":        ["unit", "unit_of_measure", "uom", "units"],
        "price":       ["price", "cost", "unit_price", "amount", "retail_price"],
        "description": ["description", "desc", "details", "note"],
        "image_path":  ["image_path", "image", "photo", "picture", "img"],
    }

    def _normalize(self, row: dict) -> dict:
        rl = {k.lower().strip(): str(v).strip() if v is not None else ""
              for k, v in row.items()}
        out = {"name": "", "sku": "", "category": "Other",
               "stock": 0, "unit": "units", "price": 0.0,
               "description": "", "image_path": None}
        for f, aliases in self._COL_ALIASES.items():
            for a in aliases:
                if a in rl:
                    out[f] = rl[a] or None
                    break
        return out

    def _dicts_to_clean(self, rows: list[dict]) -> list[dict]:
        clean = []
        for row in rows:
            r = self._normalize(row)
            try:
                price = float(str(r["price"]).replace("$", "").replace(",", "") or 0)
                stock = int(float(str(r["stock"]) or 0))
                if not r["name"]:
                    continue
                clean.append({
                    "name":        str(r["name"]),
                    "sku":         str(r["sku"] or ""),
                    "category":    str(r["category"]),
                    "stock":       stock,
                    "unit":        str(r["unit"]),
                    "price":       price,
                    "description": str(r["description"] or ""),
                    "image_path":  r["image_path"],
                })
            except (ValueError, TypeError):
                continue
        return clean

    def load_from_csv(self, filepath: str) -> int:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        clean = self._dicts_to_clean(rows)
        n = self.db.bulk_replace(clean)
        self._reload()
        self.inventory_changed.emit()
        return n

    def load_from_excel(self, filepath: str) -> int:
        import openpyxl
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return 0
        headers = [str(c).lower().strip() if c is not None else "" for c in rows[0]]
        dicts = [
            {headers[i]: (row[i] if i < len(row) else None) for i in range(len(headers))}
            for row in rows[1:]
            if any(cell is not None for cell in row)
        ]
        clean = self._dicts_to_clean(dicts)
        n = self.db.bulk_replace(clean)
        self._reload()
        self.inventory_changed.emit()
        return n

    def load_from_list(self, data: list[dict]) -> int:
        clean = self._dicts_to_clean(data)
        n = self.db.bulk_replace(clean)
        self._reload()
        self.inventory_changed.emit()
        return n


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


def status_badge(status: str) -> QLabel:
    configs = {
        "In Stock":     (C["ok_lt"],     C["ok"],     "In Stock"),
        "Low Stock":    (C["warn_lt"],   C["warn"],   "Low Stock"),
        "Out of Stock": (C["danger_lt"], C["danger"], "Out of Stock"),
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


# ─────────────────────────────────────────────────────────────────────────────
# Add / Edit Item Dialog  ← IMAGE UPLOAD ADDED
# ─────────────────────────────────────────────────────────────────────────────
class ItemDialog(QDialog):
    def __init__(self, inv: InventoryState,
                 item: InventoryItem | None = None, parent=None):
        super().__init__(parent)
        self.inv  = inv
        self.item = item
        # Tracks the *source* path chosen this session (not yet copied).
        # None  → no change / no image
        # ""    → user explicitly removed the image
        # path  → new file selected
        self._pending_image_src: str | None = None
        self.setWindowTitle("Edit Item" if item else "Add Item")
        self.setMinimumWidth(480)
        # Cap height so the dialog always fits even on 768-px screens.
        # The scroll area inside handles overflow gracefully.
        from PyQt6.QtGui import QGuiApplication
        screen_h = QGuiApplication.primaryScreen().availableGeometry().height()
        self.setMaximumHeight(min(680, screen_h - 80))
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(pal.ColorRole.Window, QColor(C["white"]))
        self.setPalette(pal)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        # Outer layout: title + scrollable form + pinned footer
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Title bar (always visible, never scrolls) ──────────────────────
        title_bar = QWidget()
        title_bar.setStyleSheet(f"background:{C['white']};")
        tb_lay = QVBoxLayout(title_bar)
        tb_lay.setContentsMargins(28, 20, 28, 12)
        tb_lay.setSpacing(0)
        tb_lay.addWidget(lbl("Edit Item" if self.item else "Add New Item", bold=True, size=16))
        outer.addWidget(title_bar)
        outer.addWidget(hline())

        # ── Scrollable form area ───────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{background:{C['white']};border:none;}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )

        form_widget = QWidget()
        form_widget.setStyleSheet(f"background:{C['white']};")
        lay = QVBoxLayout(form_widget)
        lay.setContentsMargins(28, 16, 28, 16)
        lay.setSpacing(12)

        def field_row(label_text, widget):
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
        self.f_name = field_row("Product Name *", QLineEdit(p.name if p else ""))
        self.f_sku  = field_row("SKU",            QLineEdit(p.sku  if p else ""))

        cat_w = QComboBox()
        cat_w.setEditable(True)
        known = ["Coffee & Espresso", "Cold Beverages", "Pastries", "Sandwiches",
                 "Merchandise", "Dairy", "Dairy Alt", "Whole Beans", "Syrups"]
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

        price_col = QVBoxLayout()
        price_col.setSpacing(4)
        price_col.addWidget(lbl("Unit Price (₱)", size=11, color=C["sub"]))
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
        lay.addLayout(price_col)

        self.f_desc = field_row("Description (optional)",
                                QLineEdit(p.description if p else ""))

        # ── Image upload section ───────────────────────────────────────────
        lay.addWidget(hline())
        lay.addWidget(lbl("Product Image", size=11, color=C["sub"]))

        img_row = QHBoxLayout()
        img_row.setSpacing(12)

        # Preview thumbnail (72×72 — slightly smaller to save vertical space)
        self.img_preview = QLabel()
        self.img_preview.setFixedSize(72, 72)
        self.img_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setStyleSheet(
            f"border:1.5px solid {C['border']};border-radius:10px;"
            f"background:{C['bg']};font-size:26px;"
        )
        img_row.addWidget(self.img_preview)

        img_btn_col = QVBoxLayout()
        img_btn_col.setSpacing(6)

        self.img_name_lbl = lbl("No image set", size=10, color=C["sub"])
        self.img_name_lbl.setWordWrap(True)
        img_btn_col.addWidget(self.img_name_lbl)

        upload_btn = QPushButton("📷  Upload Image")
        upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        upload_btn.setFixedHeight(32)
        upload_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent_lt']};color:{C['accent']};"
            f"border:1.5px solid {C['accent']};border-radius:7px;"
            f"padding:0 14px;font-weight:700;font-size:12px;}}"
            f"QPushButton:hover{{background:{C['accent']};color:white;}}"
        )
        upload_btn.clicked.connect(self._pick_image)
        img_btn_col.addWidget(upload_btn)

        self.remove_img_btn = QPushButton("✕  Remove Image")
        self.remove_img_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_img_btn.setFixedHeight(24)
        self.remove_img_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['danger']};"
            f"border:none;font-size:11px;font-weight:600;padding:0;}}"
            f"QPushButton:hover{{text-decoration:underline;}}"
        )
        self.remove_img_btn.clicked.connect(self._remove_image)
        img_btn_col.addWidget(self.remove_img_btn)
        img_btn_col.addStretch()

        img_row.addLayout(img_btn_col)
        lay.addLayout(img_row)

        # Populate preview with existing image (edit mode)
        self._refresh_image_preview(p.image_path if p else None)

        scroll.setWidget(form_widget)
        outer.addWidget(scroll, stretch=1)

        # ── Pinned footer — always visible at bottom ───────────────────────
        footer = QWidget()
        footer.setStyleSheet(
            f"background:{C['white']};"
            f"border-top:1px solid {C['border']};"
        )
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(28, 12, 28, 14)
        footer_lay.addStretch()

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

        footer_lay.addWidget(cancel)
        footer_lay.addSpacing(8)
        footer_lay.addWidget(save)
        outer.addWidget(footer)

    # ── Image helpers ─────────────────────────────────────────────────────────

    def _refresh_image_preview(self, path: str | None):
        """Update the 80×80 preview widget."""
        pix = get_product_thumbnail(path, 80)
        if pix:
            self.img_preview.setPixmap(_rounded_pixmap(pix, 10))
            self.img_preview.setText("")
            fname = Path(path).name if path else ""
            self.img_name_lbl.setText(fname)
            self.remove_img_btn.setVisible(True)
        else:
            # Show category emoji fallback
            cat = self.f_cat.currentText() if hasattr(self, "f_cat") else "Other"
            self.img_preview.setText(CATEGORY_EMOJI.get(cat, "📦"))
            self.img_name_lbl.setText("No image set")
            self.remove_img_btn.setVisible(False)

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Product Image", "", _SUPPORTED_IMAGE_EXTS
        )
        if not path:
            return
        self._pending_image_src = path
        self._refresh_image_preview(path)

    def _remove_image(self):
        self._pending_image_src = ""   # empty string = "remove"
        self._refresh_image_preview(None)

    # ── Save ──────────────────────────────────────────────────────────────────
    def _save(self):
        name = self.f_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Product name is required.")
            return
        sku = self.f_sku.text().strip() or \
              f"SKU-{self.item.id if self.item else '?':04}"

        # Resolve final image path
        existing_path = self.item.image_path if self.item else None
        if self._pending_image_src is None:
            # No change
            final_image = existing_path
        elif self._pending_image_src == "":
            # User removed image
            if existing_path:
                try:
                    Path(existing_path).unlink(missing_ok=True)
                except Exception:
                    pass
            final_image = None
        else:
            # New image chosen — we need the real id to name the file.
            # For NEW items (id=0) we'll use a temp name; add_item() fixes it up.
            item_id = self.item.id if self.item else 0
            try:
                final_image = _save_product_image(self._pending_image_src, item_id, name)
                # Remove old image if different
                if existing_path and existing_path != final_image:
                    try:
                        Path(existing_path).unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception as exc:
                QMessageBox.warning(self, "Image Error",
                                    f"Could not save image:\n{exc}\nItem saved without image.")
                final_image = existing_path

        new_item = InventoryItem(
            id=self.item.id if self.item else 0,
            name=name,
            sku=sku,
            category=self.f_cat.currentText(),
            stock=self.f_stock.value(),
            unit=self.f_unit.text().strip() or "units",
            price=self.f_price.value(),
            description=self.f_desc.text().strip(),
            image_path=final_image,
        )
        if self.item:
            self.inv.update_item(new_item)
        else:
            self.inv.add_item(new_item)
        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Import Dialog  (unchanged except image_path pass-through in _normalize)
# ─────────────────────────────────────────────────────────────────────────────
class ImportDialog(QDialog):
    def __init__(self, inv, parent=None):
        super().__init__(parent)
        self.inv = inv
        self.setWindowTitle("Import Inventory")
        
        # Use Dialog flags to ensure it acts as a child of the Main Window
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        
        # Styling
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
        
        # Build layout elements cleanly
        self._build()

    def showEvent(self, event):
        """ Runs right before the window becomes visible on screen. """
        super().showEvent(event)
        
        # 1. Force the exact dimensions now that the widgets are stable
        self.setMinimumSize(580, 520)
        self.resize(580, 520)
        
        # 2. Force center it onto the parent window (InventoryWindow)
        if self.parentWidget():
            p_geo = self.parentWidget().geometry()
            d_geo = self.frameGeometry()
            # Position the dialog center to match the parent window center
            d_geo.moveCenter(p_geo.center())
            self.move(d_geo.topLeft())

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(16) 

        lay.addWidget(lbl("Import Inventory", bold=True, size=18))
        sub = lbl(
            "Load products from a CSV file, Excel spreadsheet, or pasted data.\n"
            "⚠  Importing replaces all existing inventory rows.",
            size=11, color=C["sub"]
        )
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addWidget(hline())

        def make_section(icon, title, hint):
            box = QFrame()
            box.setObjectName("section")
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

        # CSV Section
        csv_box, csv_bl = make_section(
            "📄", "From CSV File",
            "Accepted columns: name, sku, category, stock, unit, price, description, image_path"
        )
        csv_btn = action_btn("Browse CSV File…")
        csv_btn.setFixedHeight(36)
        csv_btn.clicked.connect(self._import_csv)
        csv_bl.addWidget(csv_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(csv_box)

        # Excel Section
        xl_box, xl_bl = make_section(
            "📊", "From Excel File",
            "First row must be column headers. Reads the first sheet only."
        )
        xl_btn = action_btn("Browse Excel File…")
        xl_btn.setFixedHeight(36)
        xl_btn.clicked.connect(self._import_excel)
        xl_bl.addWidget(xl_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(xl_box)

        # Paste Section
        paste_box, paste_bl = make_section(
            "📋", "Paste CSV Data",
            "Open your CSV in Notepad, select all (Ctrl+A), copy (Ctrl+C), paste below."
        )
        self.paste_edit = QTextEdit()
        self.paste_edit.setPlaceholderText(
            "name,category,price,stock,unit\n"
            "House Blend Beans,Whole Beans,24.00,45,kg"
        )
        self.paste_edit.setFixedHeight(80)
        self.paste_edit.setStyleSheet(
            f"border:1.5px solid {C['border']};border-radius:8px;"
            f"padding:6px 8px;background:{C['white']};font-size:12px;"
            f"font-family:'Consolas','Courier New',monospace;"
        )
        paste_bl.addWidget(self.paste_edit)
        paste_btn = action_btn("Import Pasted Data")
        paste_btn.setFixedHeight(36)
        paste_btn.clicked.connect(self._import_paste)
        paste_bl.addWidget(paste_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(paste_box)

        # Soft stretch keeps elements naturally uncompressed
        lay.addStretch(1)

        # Close Button Row
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

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*)"
        )
        if not path: return
        try:
            n = self.inv.load_from_csv(path)
            QMessageBox.information(self, "Import Successful", f"✅  {n} items loaded from CSV.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", f"Could not read CSV file:\n{e}")

    def _import_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel File", "", "Excel Files (*.xlsx *.xls);;All Files (*)"
        )
        if not path: return
        try:
            n = self.inv.load_from_excel(path)
            QMessageBox.information(self, "Import Successful", f"✅  {n} items loaded from Excel.")
            self.accept()
        except ImportError:
            QMessageBox.critical(
                self, "Missing Library",
                "openpyxl is required to read Excel files.\n\nRun this in your terminal:\n    pip install openpyxl"
            )
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", f"Could not read Excel file:\n{e}")

    def _import_paste(self):
        text = self.paste_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Nothing to Import", "Paste some CSV data into the box first.")
            return
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
            if not rows:
                QMessageBox.warning(self, "Empty Data", "No rows found — check your column headers.")
                return
            n = self.inv.load_from_list(rows)
            QMessageBox.information(self, "Import Successful", f"✅  {n} items loaded from pasted data.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", f"Could not parse data:\n{e}")


# ─────────────────────────────────────────────────────────────────────────────
# Inventory Table  ← thumbnail in column 0 instead of plain emoji label
# ─────────────────────────────────────────────────────────────────────────────
COLUMNS = ["", "Product", "Category", "In Stock", "Unit Price", "Status", "Actions"]


class InventoryTable(QTableWidget):
    row_action = pyqtSignal(str, int)

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
        self.setColumnWidth(0, 68)
        self.setColumnWidth(6, 80)

    def _qss(self) -> str:
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
            self.setRowHeight(r, 68)

            # ── Col 0: product image or emoji fallback ──────────────────
            thumb_pix = item.thumbnail(48)
            if thumb_pix:
                img_lbl = QLabel()
                img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_lbl.setPixmap(_rounded_pixmap(thumb_pix, 8))
                img_lbl.setStyleSheet("background:transparent;margin:10px;")
            else:
                img_lbl = QLabel(item.emoji)
                img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_lbl.setStyleSheet(
                    "font-size:26px;background:#F0EDE8;"
                    "border-radius:8px;margin:8px;padding:4px;"
                )
            self.setCellWidget(r, 0, img_lbl)

            id_cell = QTableWidgetItem(str(item.id))
            id_cell.setData(Qt.ItemDataRole.UserRole, item.id)
            self.setItem(r, 0, id_cell)

            name_w = QWidget()
            name_w.setStyleSheet("background:transparent;")
            nl = QVBoxLayout(name_w)
            nl.setContentsMargins(8, 0, 0, 0)
            nl.setSpacing(2)
            nl.addWidget(lbl(item.name, bold=True, size=13))
            nl.addWidget(lbl(f"SKU: {item.sku}", size=10, color=C["sub"]))
            self.setCellWidget(r, 1, name_w)

            cat = QTableWidgetItem(item.category)
            cat.setForeground(QBrush(QColor(C["sub"])))
            self.setItem(r, 2, cat)

            stock_w = QWidget()
            stock_w.setStyleSheet("background:transparent;")
            sl = QHBoxLayout(stock_w)
            sl.setContentsMargins(8, 0, 8, 0)
            color = (C["danger"] if item.stock == 0
                     else C["warn"] if item.stock <= LOW_STOCK_THRESHOLD
                     else C["text"])
            sl.addWidget(lbl(f"{item.stock} {item.unit}",
                             color=color, bold=(item.stock <= LOW_STOCK_THRESHOLD)))
            self.setCellWidget(r, 3, stock_w)

            price = QTableWidgetItem(f"₱{item.price:.2f}")
            price.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
            self.setItem(r, 4, price)

            badge_w = QWidget()
            badge_w.setStyleSheet("background:transparent;")
            bl = QHBoxLayout(badge_w)
            bl.setContentsMargins(8, 0, 8, 0)
            bl.addWidget(status_badge(item.status))
            bl.addStretch()
            self.setCellWidget(r, 5, badge_w)

            dots = QPushButton("···")
            dots.setFixedSize(40, 32)
            dots.setCursor(Qt.CursorShape.PointingHandCursor)
            dots.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C['sub']};"
                f"border:none;font-size:18px;font-weight:700;}}"
                f"QPushButton:hover{{background:{C['bg']};border-radius:6px;}}"
            )
            dots.clicked.connect(lambda _, iid=item.id: self._show_row_menu(iid))
            act_w = QWidget()
            act_w.setStyleSheet("background:transparent;")
            al = QHBoxLayout(act_w)
            al.setContentsMargins(4, 0, 4, 0)
            al.addWidget(dots, alignment=Qt.AlignmentFlag.AlignCenter)
            self.setCellWidget(r, 6, act_w)

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
    def __init__(self, db: InventoryDB):
        super().__init__()
        self.inv = InventoryState(db)
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

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        upd = QAction("✏️  Update Item", self)
        upd.triggered.connect(self._update_selected)
        tb.addAction(upd)

        dele = QAction("🗑️  Delete Item", self)
        dele.triggered.connect(self._delete_selected)
        tb.addAction(dele)

        add_btn = action_btn("＋  Add Item")
        add_btn.setFixedHeight(34)
        add_btn.clicked.connect(self._add_item)
        tb.addWidget(add_btn)

        tb.addSeparator()

        imp = QAction("📦  Import", self)
        imp.triggered.connect(self._open_import)
        tb.addAction(imp)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(PawffinatedSidebar(active_page="Inventory"))

        main = QWidget()
        main.setStyleSheet(f"background:{C['bg']};")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        self._build_header(ml)
        self._build_stats_bar(ml)
        self._build_table_section(ml)

        root.addWidget(main, stretch=1)

    def _build_header(self, parent):
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 14)
        hl.setSpacing(4)
        hl.addWidget(lbl("Inventory", bold=True, size=20))
        hl.addWidget(lbl(
            "Monitor stock levels and manage product catalog in real time.",
            size=11, color=C["sub"]
        ))
        parent.addWidget(hdr)

    def _build_stats_bar(self, parent):
        self.stats_bar = QWidget()
        self.stats_bar.setStyleSheet(f"background:{C['white']};")
        self.stats_lay = QHBoxLayout(self.stats_bar)
        self.stats_lay.setContentsMargins(28, 16, 28, 16)
        self.stats_lay.setSpacing(48)
        self.stats_lay.addStretch()
        parent.addWidget(self.stats_bar)

    def _refresh_stats(self):
        while self.stats_lay.count():
            item = self.stats_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def stat_card(number, sub_text, badge_text, badge_color, badge_bg):
            col = QVBoxLayout()
            col.setSpacing(4)
            bdg = QLabel(badge_text)
            bdg.setStyleSheet(
                f"background:{badge_bg};color:{badge_color};"
                f"border-radius:5px;padding:2px 10px;"
                f"font-size:10px;font-weight:700;"
            )
            col.addWidget(bdg, alignment=Qt.AlignmentFlag.AlignLeft)
            col.addWidget(lbl(str(number), bold=True, size=28))
            col.addWidget(lbl(sub_text, size=10, color=C["sub"]))
            w = QWidget()
            w.setLayout(col)
            return w

        self.stats_lay.addWidget(
            stat_card(self.inv.low_stock_count, "Below minimum threshold",
                      "Needs Review", C["warn"], C["warn_lt"])
        )
        self.stats_lay.addWidget(
            stat_card(self.inv.out_of_stock_count, "Lost revenue potential",
                      "Restock Needed", C["danger"], C["danger_lt"])
        )

        val_col = QVBoxLayout()
        val_col.setSpacing(4)
        val_col.addWidget(lbl("Total Value", size=10, color=C["sub"]))
        val_col.addWidget(lbl(f"₱{self.inv.total_inventory_value:,.2f}",
                              bold=True, size=22))
        val_col.addWidget(lbl(f"{len(self.inv.products)} products",
                              size=10, color=C["sub"]))
        vw = QWidget()
        vw.setLayout(val_col)
        self.stats_lay.addWidget(vw)
        self.stats_lay.addStretch()

    def _build_table_section(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 16)
        wl.setSpacing(12)

        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(lbl("Current Inventory", bold=True, size=15))
        title_col.addWidget(lbl("View and manage all items currently in stock.",
                                size=10, color=C["sub"]))
        top.addLayout(title_col)
        top.addStretch()

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

    def _build_statusbar(self):
        self.status_lbl = QLabel()
        self.status_msg = QLabel()
        self.status_msg.setStyleSheet(f"color:{C['accent']};font-weight:600;")
        self.statusBar().addWidget(self.status_lbl)
        self.statusBar().addPermanentWidget(self.status_msg)

    def _refresh(self):
        self._refresh_stats()
        items = self.inv.visible_products
        self.table.populate(items)
        self.status_lbl.setText(
            f"Showing {len(items)} of {len(self.inv.products)} items  |  "
            f"Low stock: {self.inv.low_stock_count}  |  "
            f"Out of stock: {self.inv.out_of_stock_count}  |  "
            f"Total value: ₱{self.inv.total_inventory_value:,.2f}"
        )

    def _on_search(self, text: str):
        self.inv.search_query = text
        self._refresh()

    def _on_filter(self, status: str):
        self.inv.filter_status = status
        self._refresh()

    def _add_item(self):
        ItemDialog(self.inv, parent=self).exec()

    def _update_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "No Selection",
                                    "Click a row in the table first.")
            return
        cell = self.table.item(rows[0].row(), 0)
        if not cell:
            return
        item = self.inv.get_by_id(cell.data(Qt.ItemDataRole.UserRole))
        if item:
            ItemDialog(self.inv, item, parent=self).exec()

    def _delete_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "No Selection",
                                    "Click a row in the table first.")
            return
        cell = self.table.item(rows[0].row(), 0)
        if not cell:
            return
        item = self.inv.get_by_id(cell.data(Qt.ItemDataRole.UserRole))
        if not item:
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete '{item.name}' from inventory?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.inv.delete_item(item.id)
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
                f"Delete '{item.name}'?\nThis cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.inv.delete_item(item_id)
                self._flash(f"Deleted {item.name}.")

    def _open_import(self):
        ImportDialog(self.inv, parent=self).exec()

    def _flash(self, msg: str, ms: int = 4000):
        self.status_msg.setText(msg)
        QTimer.singleShot(ms, lambda: self.status_msg.setText(""))


# ─────────────────────────────────────────────────────────────────────────────
# App entry point
# ─────────────────────────────────────────────────────────────────────────────
class InventoryApp(QApplication):
    def __init__(self, argv=None):
        super().__init__(argv or sys.argv)
        self.setApplicationName("Pawffinated Inventory")
        try:
            self.db = get_db()
        except ConnectionError as exc:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Database Connection Failed")
            msg.setText("Pawffinated could not connect to the database.")
            msg.setDetailedText(str(exc))
            msg.exec()
            sys.exit(1)
        self.window = InventoryWindow(self.db)

    def run(self):
        self.window.show()
        self.window.statusBar().showMessage(f"  🔌  {db_info()}", 0)
        result = self.exec()
        close_db()
        return result


if __name__ == "__main__":
    app = InventoryApp(sys.argv)
    sys.exit(app.run())
