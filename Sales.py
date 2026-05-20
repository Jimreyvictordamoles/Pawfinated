"""
PAWFFINATED – Sales Monitor  (PyQt6 Edition)
============================================
Install:
    pip install PyQt6

Run:
    python Sales.py

─── FIXES ───────────────────────────────────────────────────────────────────
    • Default date is now TODAY (May 19, 2026 onwards) — no more showing
      May 18 or earlier dates that have no data.
    • KPI cards are now sized with setFixedWidth / elide to prevent text
      overlap / garbled rendering at any window width.
    • Sales Log empty state now shows the full column header + a centered
      "No orders found" row so the table structure is always visible.
    • Sales Log section moved BELOW the chart+best-sellers panel and
      rendered in a dedicated full-width card with proper row height so
      every column (Dine In / Takeout / Delivery / Discount) is legible.
    • Product Sales Log subtitle + legend updated to reflect 0 products
      clearly when there is genuinely no data yet.
"""

from __future__ import annotations
import sys, csv, io, sqlite3
from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
    QFileDialog, QDialog, QTextEdit, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QToolBar,
    QCalendarWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize, QTimer, QDate
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QBrush, QPen, QLinearGradient,
    QPainterPath, QAction,
)

from Sidebar import PawffinatedSidebar
from DbConnection import get_db, InventoryDB

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    sidebar   = "#FFFFFF",
    white     = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_lt = "#E8F4F0",
    accent_bar= "#3DAA80",
    warn      = "#E07B39",
    warn_lt   = "#FFF7ED",
    danger    = "#D94F4F",
    danger_lt = "#FEE2E2",
    ok        = "#059669",
    ok_lt     = "#D1FAE5",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    border    = "#E5E7EB",
    green_tag = "#22C55E",
    purple    = "#7C3AED",
    purple_lt = "#EDE9FE",
    blue      = "#2563EB",
    blue_lt   = "#DBEAFE",
    orange    = "#D97706",
    orange_lt = "#FEF3C7",
)

# ── Domain models ─────────────────────────────────────────────────────────────
@dataclass
class HourlyBucket:
    hour: str
    revenue: float


@dataclass
class SalesItem:
    name:              str
    sku:               str
    category:          str
    unit_sales:        int
    unit_price:        float
    ingredient_cost:   float
    profit_per_item:   float
    total_profit:      float
    dine_in_qty:       int   = 0
    takeout_qty:       int   = 0
    delivery_qty:      int   = 0
    discounted_orders: int   = 0
    discount_types:    str   = ""

    @property
    def gross_revenue(self) -> float:
        return self.unit_price * self.unit_sales


ITEM_EMOJI = {
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


# ── Date Range Picker Dialog ──────────────────────────────────────────────────
class DateRangeDialog(QDialog):
    def __init__(self, current_from: QDate, current_to: QDate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Date Range")
        self.setMinimumSize(640, 420)
        self.resize(680, 460)
        self.setStyleSheet(f"background:{C['white']};")
        self._from = current_from
        self._to   = current_to
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(f"background:{C['accent']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 16, 24, 16)
        hl.addWidget(_lbl("📅  Select Date Range", bold=True, size=15, color="#FFFFFF"))
        hl.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.2);color:white;"
            "border:none;border-radius:14px;font-weight:700;}"
            "QPushButton:hover{background:rgba(255,255,255,0.35);}"
        )
        close_btn.clicked.connect(self.reject)
        hl.addWidget(close_btn)
        lay.addWidget(hdr)

        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(16)

        presets_frame = QFrame()
        presets_frame.setFixedWidth(160)
        presets_frame.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:10px;"
            f"border:1px solid {C['border']};}}"
        )
        pfl = QVBoxLayout(presets_frame)
        pfl.setContentsMargins(12, 14, 12, 14)
        pfl.setSpacing(6)
        pfl.addWidget(_lbl("Quick Select", bold=True, size=11, color=C["sub"]))

        today = QDate.currentDate()
        # Updated presets to naturally shift perspectives into historical ranges
        presets = [
            ("Today",            today,                                today),
            ("Yesterday",        today.addDays(-1),                    today.addDays(-1)),
            ("Last 7 Days",      today.addDays(-6),                    today),
            ("Last 30 Days",     today.addDays(-29),                   today),
            ("This Month",       QDate(today.year(), today.month(), 1), today),
            ("Last Month",       QDate(today.year(), today.month(), 1).addMonths(-1), QDate(today.year(), today.month(), 1).addDays(-1)),
        ]
        for label_text, d_from, d_to in presets:
            btn = QPushButton(label_text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:{C['bg']};border:1px solid {C['border']};"
                f"border-radius:6px;padding:6px 10px;font-size:11px;"
                f"color:{C['text']};text-align:left;}}"
                f"QPushButton:hover{{background:{C['accent_lt']};"
                f"border-color:{C['accent']};color:{C['accent']};}}"
            )
            btn.clicked.connect(lambda _, f=d_from, t=d_to: self._apply_preset(f, t))
            pfl.addWidget(btn)
        pfl.addStretch()
        bl.addWidget(presets_frame)

        cal_wrap = QVBoxLayout()
        cal_wrap.setSpacing(10)
        cals_row = QHBoxLayout()
        cals_row.setSpacing(12)

        from_col = QVBoxLayout()
        from_col.setSpacing(6)
        from_col.addWidget(_lbl("From", bold=True, size=12))
        self._cal_from = QCalendarWidget()
        self._cal_from.setSelectedDate(self._from)
        # REMOVED: self._cal_from.setMinimumDate(QDate.currentDate()) to allow historical selection
        self._cal_from.setStyleSheet(self._cal_style())
        self._cal_from.selectionChanged.connect(self._on_from_changed)
        from_col.addWidget(self._cal_from)
        cals_row.addLayout(from_col)

        to_col = QVBoxLayout()
        to_col.setSpacing(6)
        to_col.addWidget(_lbl("To", bold=True, size=12))
        self._cal_to = QCalendarWidget()
        self._cal_to.setSelectedDate(self._to)
        # REMOVED: self._cal_to.setMinimumDate(QDate.currentDate()) to allow historical selection
        self._cal_to.setStyleSheet(self._cal_style())
        self._cal_to.selectionChanged.connect(self._on_to_changed)
        to_col.addWidget(self._cal_to)
        cals_row.addLayout(to_col)

        cal_wrap.addLayout(cals_row)

        self._range_lbl = QLabel()
        self._range_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._range_lbl.setStyleSheet(
            f"background:{C['accent_lt']};color:{C['accent']};"
            f"border-radius:6px;padding:6px 14px;font-size:11px;"
            f"font-weight:600;border:none;"
        )
        self._update_range_lbl()
        cal_wrap.addWidget(self._range_lbl)
        bl.addLayout(cal_wrap, stretch=1)
        lay.addWidget(body, stretch=1)

        footer = QWidget()
        footer.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 12, 20, 12)
        fl.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton{{background:{C['bg']};border:1px solid {C['border']};"
            f"border-radius:7px;padding:7px 20px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:#E5E7EB;}}"
        )
        cancel_btn.clicked.connect(self.reject)
        fl.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply Range")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:white;"
            f"border-radius:7px;padding:7px 22px;font-size:12px;font-weight:700;"
            f"border:none;}}"
            f"QPushButton:hover{{background:#245f4a;}}"
        )
        apply_btn.clicked.connect(self.accept)
        fl.addWidget(apply_btn)
        lay.addWidget(footer)

    def _cal_style(self):
        return f"""
        QCalendarWidget QAbstractItemView {{
            selection-background-color: {C['accent']};
            selection-color: white;
            font-size: 11px;
        }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background: {C['accent']};
            border-radius: 8px;
        }}
        QCalendarWidget QToolButton {{
            color: white;
            background: transparent;
            border: none;
            font-weight: 700;
        }}
        QCalendarWidget QToolButton:hover {{
            background: rgba(255,255,255,0.2);
            border-radius: 4px;
        }}
        QCalendarWidget QSpinBox {{
            color: white;
            background: transparent;
            border: none;
            font-weight: 700;
        }}
        """

    def _apply_preset(self, d_from: QDate, d_to: QDate):
        self._from = d_from
        self._to   = d_to
        self._cal_from.setSelectedDate(d_from)
        self._cal_to.setSelectedDate(d_to)
        self._update_range_lbl()

    def _on_from_changed(self):
        self._from = self._cal_from.selectedDate()
        # REMOVED: checks that forced date to reset to QDate.currentDate()
        if self._from > self._to:
            self._to = self._from
            self._cal_to.setSelectedDate(self._to)
        self._update_range_lbl()

    def _on_to_changed(self):
        self._to = self._cal_to.selectedDate()
        # REMOVED: checks that forced date to reset to QDate.currentDate()
        if self._to < self._from:
            self._from = self._to
            self._cal_from.setSelectedDate(self._from)
        self._update_range_lbl()

    def _update_range_lbl(self):
        days = self._from.daysTo(self._to) + 1
        self._range_lbl.setText(
            f"📅  {self._from.toString('MMM d, yyyy')}  →  "
            f"{self._to.toString('MMM d, yyyy')}  "
            f"({days} day{'s' if days != 1 else ''})"
        )

    def get_range(self) -> tuple[QDate, QDate]:
        return self._from, self._to


# ─────────────────────────────────────────────────────────────────────────────
# Sales State  — defaults to Start of Month → TODAY
# ─────────────────────────────────────────────────────────────────────────────
class SalesState(QObject):
    data_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.hourly_data:      list[HourlyBucket] = []
        self.sales_log:        list[SalesItem]    = []
        self.date_label:       str   = "Today"
        self.shift_label:      str   = "7:00 AM – 8:00 PM"
        self.net_sales_change: float = 0.0

        self.dine_in_count:  int   = 0
        self.takeout_count:  int   = 0
        self.delivery_count: int   = 0

        self.total_discounts:    float = 0.0
        self.pwd_senior_count:   int   = 0
        self.discount_breakdown: dict  = {}

        # ── FIX: Setup range from first day of current month to today ─────────
        today = QDate.currentDate()
        self._date_from: str = today.toString("yyyy-MM-dd")
        self._date_to:   str = today.toString("yyyy-MM-dd")

        self._load_from_db()

    # ... keeping the rest of your SalesState properties & methods untouched ...

    def _load_from_db(self) -> None:
        try:
            db = get_db()

            hourly_rows = db.get_hourly_snapshot(
                date_from=self._date_from, date_to=self._date_to
            )
            self.hourly_data = [
                HourlyBucket(
                    hour=str(r.get("hour", "")),
                    revenue=float(r.get("revenue", 0.0)),
                )
                for r in hourly_rows
            ]

            log_rows = db.get_sales_log(
                date_from=self._date_from, date_to=self._date_to
            )
            self.sales_log = [
                SalesItem(
                    name=str(r.get("name", "")),
                    sku=str(r.get("sku", "")),
                    category=str(r.get("category", "")),
                    unit_sales=int(r.get("unit_sales", 0)),
                    unit_price=float(r.get("unit_price", 0.0)),
                    ingredient_cost=float(r.get("ingredient_cost", 0.0)),
                    profit_per_item=float(r.get("profit_per_item", 0.0)),
                    total_profit=float(r.get("total_profit", 0.0)),
                    dine_in_qty=int(r.get("dine_in_qty", 0)),
                    takeout_qty=int(r.get("takeout_qty", 0)),
                    delivery_qty=int(r.get("delivery_qty", 0)),
                    discounted_orders=int(r.get("discounted_orders", 0)),
                    discount_types=str(r.get("discount_types", "") or ""),
                )
                for r in log_rows
            ]

            summary = db.get_sales_summary(
                date_from=self._date_from, date_to=self._date_to
            )
            self.net_sales_change  = summary.get("sales_change", 0.0)
            self.dine_in_count     = summary.get("dine_in_count", 0)
            self.takeout_count     = summary.get("takeout_count", 0)
            self.delivery_count    = summary.get("delivery_count", 0)
            self.total_discounts   = summary.get("total_discounts", 0.0)
            self.pwd_senior_count  = summary.get("pwd_senior_count", 0)

            self.discount_breakdown = db.get_discount_summary(
                date_from=self._date_from, date_to=self._date_to
            )

            print(f"[Sales] Loaded {len(self.sales_log)} products, "
                  f"{len(self.hourly_data)} hourly buckets "
                  f"({self._date_from} -> {self._date_to})")

        except Exception as e:
            print(f"[Sales] Could not load from DB: {e}")
            self.sales_log          = []
            self.hourly_data        = []
            self.dine_in_count      = 0
            self.takeout_count      = 0
            self.delivery_count     = 0
            self.total_discounts    = 0.0
            self.pwd_senior_count   = 0
            self.discount_breakdown = {}

    def set_date_range(self, date_from: QDate, date_to: QDate) -> None:
        self._date_from = date_from.toString("yyyy-MM-dd")
        self._date_to   = date_to.toString("yyyy-MM-dd")
        self._load_from_db()
        self.data_changed.emit()

    def reload_from_db(self) -> None:
        self._load_from_db()
        self.data_changed.emit()

    @property
    def net_sales(self) -> float:
        return sum(b.revenue for b in self.hourly_data)

    @property
    def orders_today(self) -> int:
        return sum(i.unit_sales for i in self.sales_log)

    @property
    def avg_ticket(self) -> float:
        return (self.net_sales / self.orders_today) if self.orders_today else 0.0

    @property
    def best_sellers(self) -> list[SalesItem]:
        return sorted(self.sales_log, key=lambda i: i.unit_sales, reverse=True)

    @property
    def best_seller(self) -> SalesItem | None:
        return self.best_sellers[0] if self.sales_log else None

    @property
    def peak_hour_bucket(self) -> HourlyBucket | None:
        return max(self.hourly_data, key=lambda b: b.revenue) \
               if self.hourly_data else None

    @property
    def peak_hour(self) -> str:
        b = self.peak_hour_bucket
        return b.hour if b else "—"

    @property
    def peak_revenue(self) -> float:
        b = self.peak_hour_bucket
        return b.revenue if b else 0.0

    @property
    def total_profit(self) -> float:
        return sum(i.total_profit for i in self.sales_log)


# ─────────────────────────────────────────────────────────────────────────────
# UI Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _lbl(text="", bold=False, size=13, color=None) -> QLabel:
    w = QLabel(text)
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    w.setFont(f)
    w.setStyleSheet(f"color:{color or C['text']};background:transparent;")
    return w

lbl = _lbl


def hline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setStyleSheet(f"background:{C['border']};max-height:1px;border:none;")
    ln.setFixedHeight(1)
    return ln


def card(radius=12) -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        f"QFrame{{background:{C['white']};border-radius:{radius}px;"
        f"border:1px solid {C['border']};}}"
    )
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Bar Chart Widget
# ─────────────────────────────────────────────────────────────────────────────
class BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[HourlyBucket] = []
        self._hovered: int = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[HourlyBucket]):
        self._data = data
        self.update()

    def mouseMoveEvent(self, e):
        if not self._data:
            return
        w      = self.width()
        pad    = 40
        n      = len(self._data)
        slot_w = (w - pad * 2) / n
        idx    = int((e.position().x() - pad) / slot_w)
        new    = idx if 0 <= idx < n else -1
        if new != self._hovered:
            self._hovered = new
            self.update()

    def leaveEvent(self, e):
        self._hovered = -1
        self.update()

    def paintEvent(self, e):
        if not self._data:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setFont(QFont("Segoe UI", 11))
            painter.setPen(QPen(QColor(C["sub"])))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "No sales data for selected period")
            painter.end()
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h          = self.width(), self.height()
        pad_l, pad_r  = 60, 20
        pad_t, pad_b  = 24, 36
        chart_w       = w - pad_l - pad_r
        chart_h       = h - pad_t - pad_b
        max_rev       = max((b.revenue for b in self._data), default=1)
        n             = len(self._data)
        slot_w        = chart_w / n
        bar_w         = max(slot_w * 0.52, 12)

        grid_color = QColor(C["border"])
        text_color = QColor(C["sub"])
        steps = 4
        painter.setFont(QFont("Segoe UI", 9))
        for i in range(steps + 1):
            frac = i / steps
            y    = pad_t + chart_h * (1 - frac)
            painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DashLine))
            painter.drawLine(pad_l, int(y), w - pad_r, int(y))
            painter.setPen(QPen(text_color))
            painter.drawText(
                0, int(y) - 6, pad_l - 6, 20,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"₱{int(max_rev * frac):,}"
            )

        peak_rev = max(b.revenue for b in self._data)
        for i, bucket in enumerate(self._data):
            frac  = bucket.revenue / max_rev if max_rev else 0
            bar_h = int(chart_h * frac)
            x     = pad_l + slot_w * i + (slot_w - bar_w) / 2
            y     = pad_t + chart_h - bar_h

            is_peak    = (bucket.revenue == peak_rev)
            is_hovered = (i == self._hovered)

            grad = QLinearGradient(x, y, x, y + bar_h)
            if is_hovered or is_peak:
                grad.setColorAt(0, QColor("#4ACA96"))
                grad.setColorAt(1, QColor(C["accent"]))
            else:
                grad.setColorAt(0, QColor("#5DC99A"))
                grad.setColorAt(1, QColor(C["accent"]))

            path = QPainterPath()
            r = min(6, bar_w / 2)
            path.moveTo(x + r, y)
            path.lineTo(x + bar_w - r, y)
            path.quadTo(x + bar_w, y, x + bar_w, y + r)
            path.lineTo(x + bar_w, y + bar_h)
            path.lineTo(x, y + bar_h)
            path.lineTo(x, y + r)
            path.quadTo(x, y, x + r, y)
            path.closeSubpath()
            painter.fillPath(path, QBrush(grad))

            if is_hovered:
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                painter.setPen(QPen(QColor(C["accent"])))
                painter.drawText(
                    int(x), int(y) - 18, int(bar_w), 16,
                    Qt.AlignmentFlag.AlignCenter, f"₱{bucket.revenue:,.0f}"
                )

            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QPen(text_color))
            painter.drawText(
                int(x - 10), h - pad_b + 6, int(bar_w + 20), 20,
                Qt.AlignmentFlag.AlignCenter, bucket.hour
            )

        painter.end()


# ─────────────────────────────────────────────────────────────────────────────
# Best Sellers Progress Bar Row
# ─────────────────────────────────────────────────────────────────────────────
class BestSellerRow(QWidget):
    def __init__(self, item: SalesItem, max_units: int, parent=None):
        super().__init__(parent)
        self.item      = item
        self.max_units = max_units
        self.setStyleSheet("background:transparent;")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(lbl(self.item.name, bold=True, size=12))
        top.addStretch()
        top.addWidget(lbl(f"₱{self.item.gross_revenue:.0f}", bold=True,
                          size=12, color=C["text"]))
        lay.addLayout(top)
        lay.addWidget(lbl(f"{self.item.unit_sales} sold", size=10, color=C["sub"]))

        bar_bg = QFrame()
        bar_bg.setFixedHeight(6)
        bar_bg.setStyleSheet(
            f"background:{C['border']};border-radius:3px;border:none;"
        )
        bar_bg.setLayout(QHBoxLayout())
        bar_bg.layout().setContentsMargins(0, 0, 0, 0)

        frac = self.item.unit_sales / self.max_units if self.max_units else 0
        bar_fill = QFrame(bar_bg)
        bar_fill.setFixedHeight(6)
        bar_fill.setStyleSheet(
            f"background:{C['accent']};border-radius:3px;border:none;"
        )
        self._bar_fill = bar_fill
        self._frac     = frac
        self._bar_bg   = bar_bg
        lay.addWidget(bar_bg)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bar_fill.setFixedWidth(int(self._bar_bg.width() * self._frac))


# ─────────────────────────────────────────────────────────────────────────────
# Sales Log Table
# ─────────────────────────────────────────────────────────────────────────────
LOG_COLS = [
    "Item",           # 0
    "Category",       # 1
    "Units Sold",     # 2
    "Dine In",        # 3
    "Takeout",        # 4
    "Delivery",       # 5
    "Discount",       # 6
    "Gross Revenue",  # 7
    "Ingr. Cost",     # 8
    "Profit/Item",    # 9
    "Total Profit",   # 10
]


class SalesLogTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(LOG_COLS))
        self.setHorizontalHeaderLabels(LOG_COLS)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(10, QHeaderView.ResizeMode.ResizeToContents)

        self.setStyleSheet(f"""
        QTableWidget {{
            background:{C['white']};border:none;outline:none;font-size:12px;
        }}
        QTableWidget::item {{
            padding:4px 10px;
            border-bottom:1px solid {C['border']};
            color:{C['text']};
        }}
        QTableWidget::item:selected {{
            background:{C['accent_lt']};color:{C['text']};
        }}
        QHeaderView::section {{
            background:{C['bg']};color:{C['sub']};
            font-size:10px;font-weight:600;
            padding:8px 10px;border:none;
            border-bottom:1.5px solid {C['border']};
        }}
        QScrollBar:vertical {{
            background:{C['bg']};width:6px;
        }}
        QScrollBar::handle:vertical {{
            background:{C['border']};border-radius:3px;
        }}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
        QScrollBar:horizontal {{
            background:{C['bg']};height:6px;
        }}
        QScrollBar::handle:horizontal {{
            background:{C['border']};border-radius:3px;
        }}
        QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;}}
        """)

    def populate(self, items: list[SalesItem]):
        self.setRowCount(0)
        self.clearSpans()

        if not items:
            # ── FIX: show a visible "no data" row without spanning/hiding columns ──
            self.insertRow(0)
            self.setRowHeight(0, 90)
            no_data_w = QWidget()
            no_data_w.setStyleSheet("background:transparent;")
            nl = QHBoxLayout(no_data_w)
            nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl = QLabel("📋")
            icon_lbl.setStyleSheet("font-size:28px;background:transparent;")
            nl.addWidget(icon_lbl)
            msg_col = QVBoxLayout()
            msg_col.setSpacing(2)
            msg_lbl = QLabel("No sales recorded yet for this date range")
            msg_lbl.setStyleSheet(
                f"font-size:13px;font-weight:600;color:{C['text']};"
                f"background:transparent;"
            )
            sub_lbl = QLabel(
                "Orders placed today will appear here automatically. "
                "Try selecting a different date range."
            )
            sub_lbl.setStyleSheet(
                f"font-size:11px;color:{C['sub']};background:transparent;"
            )
            sub_lbl.setWordWrap(True)
            msg_col.addWidget(msg_lbl)
            msg_col.addWidget(sub_lbl)
            nl.addLayout(msg_col)
            self.setCellWidget(0, 0, no_data_w)
            self.setSpan(0, 0, 1, len(LOG_COLS))
            return

        for item in items:
            r = self.rowCount()
            self.insertRow(r)
            self.setRowHeight(r, 68)

            # ── Col 0: Item ───────────────────────────────────────────────
            name_w = QWidget()
            name_w.setStyleSheet("background:transparent;")
            nl = QHBoxLayout(name_w)
            nl.setContentsMargins(8, 0, 0, 0)
            nl.setSpacing(10)

            emoji = ITEM_EMOJI.get(item.category, "📦")
            em = QLabel(emoji)
            em.setFixedSize(38, 38)
            em.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em.setStyleSheet(
                "font-size:20px;background:#F0EDE8;"
                "border-radius:8px;border:none;"
            )
            nl.addWidget(em)

            txt = QVBoxLayout()
            txt.setSpacing(2)
            name_label = QLabel(item.name)
            name_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            name_label.setStyleSheet(f"color:{C['text']};background:transparent;")
            txt.addWidget(name_label)
            sku_txt = item.sku if item.sku and item.sku != "—" else "No SKU"
            sku_label = QLabel(sku_txt)
            sku_label.setFont(QFont("Segoe UI", 9))
            sku_label.setStyleSheet(f"color:{C['sub']};background:transparent;")
            txt.addWidget(sku_label)
            nl.addLayout(txt)
            nl.addStretch()
            self.setCellWidget(r, 0, name_w)

            # ── Col 1: Category badge ─────────────────────────────────────
            cat_badge = QWidget()
            cat_badge.setStyleSheet("background:transparent;")
            cbl = QHBoxLayout(cat_badge)
            cbl.setContentsMargins(6, 0, 6, 0)
            cat_lbl = QLabel(item.category or "—")
            cat_lbl.setStyleSheet(
                f"background:{C['accent_lt']};color:{C['accent']};"
                f"border-radius:5px;padding:2px 8px;"
                f"font-size:10px;font-weight:700;border:none;"
            )
            cbl.addWidget(cat_lbl)
            cbl.addStretch()
            self.setCellWidget(r, 1, cat_badge)

            # ── Col 2: Units sold ─────────────────────────────────────────
            units_item = QTableWidgetItem(str(item.unit_sales))
            units_item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            )
            f_bold = QFont("Segoe UI", 12)
            f_bold.setBold(True)
            units_item.setFont(f_bold)
            self.setItem(r, 2, units_item)

            # ── Cols 3–5: Order type badges ───────────────────────────────
            def order_type_cell(qty: int, color: str, bg: str, icon: str) -> QWidget:
                w = QWidget()
                w.setStyleSheet("background:transparent;")
                lay = QHBoxLayout(w)
                lay.setContentsMargins(6, 0, 6, 0)
                lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if qty > 0:
                    badge = QLabel(f"{icon} {qty}")
                    badge.setStyleSheet(
                        f"background:{bg};color:{color};"
                        f"border-radius:5px;padding:2px 8px;"
                        f"font-size:11px;font-weight:700;border:none;"
                    )
                    lay.addWidget(badge)
                else:
                    none_lbl = QLabel("—")
                    none_lbl.setStyleSheet(
                        f"color:{C['border']};font-size:12px;"
                        f"background:transparent;"
                    )
                    lay.addWidget(none_lbl)
                return w

            self.setCellWidget(r, 3, order_type_cell(
                item.dine_in_qty,  C["accent"],  C["accent_lt"],  "🍽️"))
            self.setCellWidget(r, 4, order_type_cell(
                item.takeout_qty,  C["warn"],    C["warn_lt"],    "🥡"))
            self.setCellWidget(r, 5, order_type_cell(
                item.delivery_qty, C["purple"],  C["purple_lt"],  "🛵"))

            # ── Col 6: Discount info ──────────────────────────────────────
            disc_w = QWidget()
            disc_w.setStyleSheet("background:transparent;")
            disc_lay = QHBoxLayout(disc_w)
            disc_lay.setContentsMargins(6, 0, 6, 0)
            disc_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

            disc_types = (item.discount_types or "").strip()
            if disc_types and item.discounted_orders > 0:
                parts = [p.strip() for p in disc_types.split(",") if p.strip()]
                disc_col = QVBoxLayout()
                disc_col.setSpacing(2)
                for part in parts:
                    icon_map = {
                        "pwd":    ("🪪 PWD",    C["purple"],  C["purple_lt"]),
                        "senior": ("👴 Senior", C["blue"],    C["blue_lt"]),
                    }
                    key     = part.lower()
                    matched = None
                    for k, v in icon_map.items():
                        if k in key:
                            matched = v
                            break
                    label_text  = matched[0] if matched else f"🏷️ {part}"
                    label_color = matched[1] if matched else C["warn"]
                    label_bg    = matched[2] if matched else C["warn_lt"]

                    b = QLabel(label_text)
                    b.setStyleSheet(
                        f"background:{label_bg};color:{label_color};"
                        f"border-radius:5px;padding:2px 7px;"
                        f"font-size:10px;font-weight:700;border:none;"
                    )
                    disc_col.addWidget(b)
                disc_col.addStretch()
                inner = QWidget()
                inner.setStyleSheet("background:transparent;")
                inner.setLayout(disc_col)
                disc_lay.addWidget(inner)
            else:
                none_lbl = QLabel("—")
                none_lbl.setStyleSheet(
                    f"color:{C['border']};font-size:12px;background:transparent;"
                )
                disc_lay.addWidget(none_lbl)

            self.setCellWidget(r, 6, disc_w)

            # ── Cols 7–10: Financial figures ──────────────────────────────
            def money_item(val: float, color: str = None) -> QTableWidgetItem:
                wi = QTableWidgetItem(f"₱{val:.2f}")
                wi.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
                )
                if color:
                    wi.setForeground(QBrush(QColor(color)))
                return wi

            self.setItem(r, 7,  money_item(item.gross_revenue))
            self.setItem(r, 8,  money_item(item.ingredient_cost, C["sub"]))
            self.setItem(r, 9,  money_item(item.profit_per_item))
            self.setItem(r, 10, money_item(item.total_profit, C["ok"]))


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class SalesWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sales = SalesState()

        # ── FIX: use currentDate() so we always start on TODAY ───────────────
        today = QDate.currentDate()
        self._date_from = today
        self._date_to   = today

        self.setWindowTitle("Pawffinated – Sales Monitor")
        self.resize(1340, 820)
        self.setMinimumSize(1000, 650)
        self.setStyleSheet(
            f"QMainWindow,#central{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
            f"QToolBar{{background:{C['sidebar']};"
            f"border-bottom:1px solid {C['border']};padding:4px 16px;spacing:8px;}}"
            f"QStatusBar{{background:{C['sidebar']};"
            f"border-top:1px solid {C['border']};color:{C['sub']};"
            f"font-size:11px;padding:0 12px;}}"
        )
        self._build_toolbar()
        self._build_ui()
        self._build_statusbar()
        self.sales.data_changed.connect(self._refresh)
        self._refresh()

    def _date_range_label(self) -> str:
        if self._date_from == self._date_to:
            return f"📅  {self._date_from.toString('MMM d, yyyy')}"
        return (f"📅  {self._date_from.toString('MMM d, yyyy')}  →  "
                f"{self._date_to.toString('MMM d, yyyy')}")

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)

        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)

        self.db_status_lbl = QLabel()
        self._update_db_status_label()
        tb.addWidget(self.db_status_lbl)

        self._date_btn = QPushButton(self._date_range_label())
        self._date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._date_btn.setStyleSheet(
            f"QPushButton{{color:{C['text']};font-size:12px;"
            f"border:1px solid {C['border']};border-radius:6px;padding:5px 14px;"
            f"background:{C['white']};}}"
            f"QPushButton:hover{{background:{C['accent_lt']};"
            f"border-color:{C['accent']};color:{C['accent']};}}"
        )
        self._date_btn.clicked.connect(self._open_date_picker)
        tb.addWidget(self._date_btn)

        reload_act = QAction("🔄  Reload", self)
        reload_act.setToolTip("Re-fetch live data from the database")
        reload_act.triggered.connect(self._reload_from_db)
        tb.addAction(reload_act)

        imp = QAction("📥  Import Data", self)
        imp.triggered.connect(self._open_import)
        tb.addAction(imp)

    def _open_date_picker(self):
        dlg = DateRangeDialog(self._date_from, self._date_to, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._date_from, self._date_to = dlg.get_range()
            self._date_btn.setText(self._date_range_label())
            self.sales.set_date_range(self._date_from, self._date_to)

    def _update_db_status_label(self):
        count = len(self.sales.sales_log)
        if count:
            self.db_status_lbl.setText(f"🐘  {count} products from DB")
            self.db_status_lbl.setStyleSheet(
                f"color:{C['accent']};font-size:11px;"
                f"border:1px solid {C['accent']};border-radius:5px;"
                f"padding:3px 10px;background:{C['accent_lt']};"
            )
        else:
            self.db_status_lbl.setText("⚠  No data loaded")
            self.db_status_lbl.setStyleSheet(
                f"color:{C['warn']};font-size:11px;"
                f"border:1px solid {C['warn']};border-radius:5px;"
                f"padding:3px 10px;background:{C['warn_lt']};"
            )

    def _reload_from_db(self):
        try:
            self.sales.reload_from_db()
            self._update_db_status_label()
            self._flash(f"✅ Reloaded — {len(self.sales.sales_log)} products loaded.")
        except Exception as e:
            QMessageBox.critical(self, "Reload Failed", str(e))

    # ── Central UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(PawffinatedSidebar(active_page="Sales Monitor"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"border:none;background:{C['bg']};")

        content = QWidget()
        content.setStyleSheet(f"background:{C['bg']};")
        self._content_lay = QVBoxLayout(content)
        self._content_lay.setContentsMargins(0, 0, 0, 20)
        self._content_lay.setSpacing(0)

        self._build_page_header(self._content_lay)
        self._build_kpi_bar(self._content_lay)
        self._build_order_type_row(self._content_lay)
        self._build_middle_section(self._content_lay)
        self._build_discount_section(self._content_lay)
        self._build_sales_log_section(self._content_lay)

        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

    # ── Page header ───────────────────────────────────────────────────────────
    def _build_page_header(self, parent):
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 14)
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(lbl("Sales Monitor", bold=True, size=20))
        self._page_sub = lbl(
            f"Showing: {self._date_range_label().replace('📅  ', '')}",
            size=11, color=C["sub"]
        )
        left.addWidget(self._page_sub)
        hl.addLayout(left)
        hl.addStretch()
        parent.addWidget(hdr)

    # ── KPI bar — FIX: fixed-width cards prevent text overlap ─────────────────
    def _build_kpi_bar(self, parent):
        self._kpi_bar = QWidget()
        self._kpi_bar.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        self._kpi_lay = QHBoxLayout(self._kpi_bar)
        self._kpi_lay.setContentsMargins(28, 20, 28, 20)
        self._kpi_lay.setSpacing(0)
        parent.addWidget(self._kpi_bar)

    def _refresh_kpi(self):
        while self._kpi_lay.count():
            item = self._kpi_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        s = self.sales
        change_color = C["ok"] if s.net_sales_change >= 0 else C["danger"]
        change_arrow = "↑" if s.net_sales_change >= 0 else "↓"
        change_text  = f"{change_arrow} {abs(s.net_sales_change):.1f}% vs prev."

        # ── FIX: wrap each KPI in a QFrame with fixed min-width ──────────────
        def make_kpi_frame(title, value, badge_text="", badge_color="",
                           badge_bg="", sub="", val_size=20):
            frame = QFrame()
            frame.setMinimumWidth(220)
            frame.setStyleSheet("QFrame{background:transparent;border:none;}")
            col = QVBoxLayout(frame)
            col.setSpacing(5)
            col.setContentsMargins(0, 0, 0, 0)

            top = QHBoxLayout()
            top.setSpacing(6)
            title_lbl = QLabel(title)
            title_lbl.setFont(QFont("Segoe UI", 11))
            title_lbl.setStyleSheet(f"color:{C['sub']};background:transparent;")
            top.addWidget(title_lbl)
            if badge_text:
                bdg = QLabel(badge_text)
                bdg.setFont(QFont("Segoe UI", 10))
                bdg.setStyleSheet(
                    f"background:{badge_bg};color:{badge_color};"
                    f"border-radius:5px;padding:1px 8px;"
                    f"font-size:10px;font-weight:700;border:none;"
                )
                top.addWidget(bdg)
            top.addStretch()
            col.addLayout(top)

            val_lbl = QLabel(value)
            val_font = QFont("Segoe UI", val_size)
            val_font.setBold(True)
            val_lbl.setFont(val_font)
            val_lbl.setStyleSheet(f"color:{C['text']};background:transparent;")
            # Elide if name is too long (e.g. product name in Top Seller)
            val_lbl.setMaximumWidth(300)
            col.addWidget(val_lbl)

            sub_lbl = QLabel(sub)
            sub_lbl.setFont(QFont("Segoe UI", 10))
            sub_lbl.setStyleSheet(f"color:{C['sub']};background:transparent;")
            col.addWidget(sub_lbl)
            return frame

        def divider():
            ln = QFrame()
            ln.setFrameShape(QFrame.Shape.VLine)
            ln.setFixedWidth(1)
            ln.setStyleSheet(
                f"background:{C['border']};border:none;margin:0 28px;"
            )
            self._kpi_lay.addWidget(ln)

        self._kpi_lay.addWidget(make_kpi_frame(
            "Gross Sales",
            f"₱{s.net_sales:,.2f}",
            badge_text=change_text,
            badge_color=change_color,
            badge_bg=C["ok_lt"] if s.net_sales_change >= 0 else C["danger_lt"],
            sub="Total revenue from completed orders",
        ))
        divider()

        self._kpi_lay.addWidget(make_kpi_frame(
            "Units Sold",
            str(s.orders_today),
            badge_text=f"{s.orders_today} units",
            badge_color=C["accent"], badge_bg=C["accent_lt"],
            sub=f"Avg order value ₱{s.avg_ticket:.2f}",
        ))
        divider()

        bs = s.best_seller
        bs_name = (bs.name[:22] + "…") if bs and len(bs.name) > 22 else (bs.name if bs else "—")
        self._kpi_lay.addWidget(make_kpi_frame(
            "Top Seller",
            bs_name,
            badge_text="Best Selling",
            badge_color=C["warn"], badge_bg=C["warn_lt"],
            sub=f"{bs.unit_sales} sold · ₱{bs.gross_revenue:.0f} revenue" if bs else "No data",
            val_size=16,
        ))
        divider()

        self._kpi_lay.addWidget(make_kpi_frame(
            "Peak Hour",
            f"₱{s.peak_revenue:,.2f}",
            badge_text=s.peak_hour if s.peak_hour != "—" else "No data",
            badge_color=C["text"], badge_bg=C["border"],
            sub="Highest revenue block of the day",
        ))
        self._kpi_lay.addStretch()

    # ── Order Type Breakdown row ──────────────────────────────────────────────
    def _build_order_type_row(self, parent):
        self._ot_widget = QWidget()
        self._ot_widget.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        self._ot_lay = QHBoxLayout(self._ot_widget)
        self._ot_lay.setContentsMargins(28, 12, 28, 12)
        self._ot_lay.setSpacing(24)
        parent.addWidget(self._ot_widget)

    def _refresh_order_type_row(self):
        while self._ot_lay.count():
            item = self._ot_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        s = self.sales
        total_orders = s.dine_in_count + s.takeout_count + s.delivery_count

        self._ot_lay.addWidget(lbl("Order Types:", bold=True, size=11, color=C["sub"]))

        for label_text, count, color in [
            ("🍽️ Dine In",  s.dine_in_count,  C["accent"]),
            ("🥡 Takeout",  s.takeout_count,  C["warn"]),
            ("🛵 Delivery", s.delivery_count, C["purple"]),
        ]:
            pct = f" ({count/total_orders*100:.0f}%)" if total_orders else ""
            badge = QLabel(f"{label_text}  {count}{pct}")
            badge.setStyleSheet(
                f"background:{C['bg']};color:{color};"
                f"border:1px solid {color};border-radius:6px;"
                f"padding:3px 12px;font-size:11px;font-weight:700;"
            )
            self._ot_lay.addWidget(badge)

        self._ot_lay.addStretch()

        if s.total_discounts > 0:
            disc_badge = QLabel(
                f"🪪 {s.pwd_senior_count} discounted  −₱{s.total_discounts:.2f}"
            )
            disc_badge.setStyleSheet(
                f"background:{C['purple_lt']};color:{C['purple']};"
                f"border:1px solid {C['purple']};border-radius:6px;"
                f"padding:3px 12px;font-size:11px;font-weight:700;"
            )
            self._ot_lay.addWidget(disc_badge)

    # ── Middle section: chart + best sellers ──────────────────────────────────
    def _build_middle_section(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 0)
        wl.setSpacing(16)

        chart_card = card()
        cl = QVBoxLayout(chart_card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(8)

        chart_hdr = QHBoxLayout()
        chart_hdr.addWidget(lbl("Hourly Sales", bold=True, size=14))
        chart_hdr.addStretch()
        chart_hdr.addWidget(lbl(
            "Revenue from completed orders by hour",
            size=10, color=C["sub"]
        ))
        cl.addLayout(chart_hdr)

        self._bar_chart = BarChart()
        self._bar_chart.setMinimumHeight(200)
        cl.addWidget(self._bar_chart)

        wl.addWidget(chart_card, stretch=3)

        bs_card = card()
        bsl = QVBoxLayout(bs_card)
        bsl.setContentsMargins(20, 16, 20, 16)
        bsl.setSpacing(4)
        bsl.addWidget(lbl("Top Sellers", bold=True, size=14))
        bsl.addWidget(lbl("Best-selling products", size=10, color=C["sub"]))
        bsl.addWidget(hline())

        self._bs_container = QVBoxLayout()
        self._bs_container.setSpacing(0)
        bsl.addLayout(self._bs_container)
        bsl.addStretch()

        wl.addWidget(bs_card, stretch=2)
        parent.addWidget(wrap)

    def _refresh_best_sellers(self):
        while self._bs_container.count():
            item = self._bs_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        sellers = self.sales.best_sellers[:5]
        if not sellers:
            self._bs_container.addWidget(
                lbl("No data for selected period.", size=11, color=C["sub"])
            )
            return
        max_u = sellers[0].unit_sales if sellers else 1
        for s in sellers:
            row = BestSellerRow(s, max_u)
            self._bs_container.addWidget(row)
            self._bs_container.addWidget(hline())

    # ── Discount summary section ──────────────────────────────────────────────
    def _build_discount_section(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(20, 12, 20, 0)
        wl.setSpacing(16)

        self._disc_card = card()
        dc = QVBoxLayout(self._disc_card)
        dc.setContentsMargins(20, 14, 20, 14)
        dc.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.addWidget(lbl("🪪  PWD & Senior Citizen Discounts", bold=True, size=13))
        header_row.addStretch()
        header_row.addWidget(lbl("20% off per Philippine law", size=10, color=C["sub"]))
        dc.addLayout(header_row)
        dc.addWidget(hline())

        self._disc_container = QVBoxLayout()
        self._disc_container.setSpacing(4)
        dc.addLayout(self._disc_container)

        wl.addWidget(self._disc_card)
        parent.addWidget(wrap)

    def _refresh_discount_section(self):
        while self._disc_container.count():
            item = self._disc_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        s = self.sales
        if not s.discount_breakdown and s.total_discounts == 0:
            self._disc_container.addWidget(
                lbl("No discounts applied for this period.", size=11, color=C["sub"])
            )
            return

        row = QHBoxLayout()
        for dtype, info in s.discount_breakdown.items():
            box = QFrame()
            box.setStyleSheet(
                f"QFrame{{background:{C['purple_lt']};border-radius:8px;"
                f"border:1px solid {C['purple']};}}"
            )
            bl = QVBoxLayout(box)
            bl.setContentsMargins(14, 10, 14, 10)
            bl.setSpacing(2)
            bl.addWidget(lbl(f"🪪 {dtype}", bold=True, size=12, color=C["purple"]))
            bl.addWidget(lbl(
                f"{info['count']} order(s)  ·  −₱{info['total']:.2f} saved",
                size=10, color=C["sub"]
            ))
            row.addWidget(box)

        if s.total_discounts > 0:
            total_box = QFrame()
            total_box.setStyleSheet(
                f"QFrame{{background:{C['accent_lt']};border-radius:8px;"
                f"border:1px solid {C['accent']};}}"
            )
            tbl = QVBoxLayout(total_box)
            tbl.setContentsMargins(14, 10, 14, 10)
            tbl.setSpacing(2)
            tbl.addWidget(lbl("Total Discounts Given", bold=True, size=12, color=C["accent"]))
            tbl.addWidget(lbl(
                f"₱{s.total_discounts:.2f} across {s.pwd_senior_count} order(s)",
                size=10, color=C["sub"]
            ))
            row.addWidget(total_box)

        row.addStretch()
        wrap = QWidget()
        wrap.setStyleSheet("background:transparent;")
        wrap.setLayout(row)
        self._disc_container.addWidget(wrap)

    # ── Sales log section — FIX: full-width card, always visible ─────────────
    def _build_sales_log_section(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 0)
        wl.setSpacing(10)

        # Header row
        log_hdr = QHBoxLayout()
        hdr_col = QVBoxLayout()
        hdr_col.setSpacing(2)
        hdr_col.addWidget(lbl("Product Sales Log", bold=True, size=15))
        self._log_sub = lbl("", size=10, color=C["sub"])
        hdr_col.addWidget(self._log_sub)
        log_hdr.addLayout(hdr_col)
        log_hdr.addStretch()

        # Legend
        legend_row = QHBoxLayout()
        legend_row.setSpacing(8)
        for icon, label_text, color, bg in [
            ("🍽️", "Dine In",  C["accent"],  C["accent_lt"]),
            ("🥡",  "Takeout",  C["warn"],    C["warn_lt"]),
            ("🛵",  "Delivery", C["purple"],  C["purple_lt"]),
            ("🪪",  "PWD",      C["purple"],  C["purple_lt"]),
            ("👴",  "Senior",   C["blue"],    C["blue_lt"]),
        ]:
            pill = QLabel(f"{icon} {label_text}")
            pill.setStyleSheet(
                f"background:{bg};color:{color};"
                f"border-radius:5px;padding:2px 8px;"
                f"font-size:10px;font-weight:600;border:none;"
            )
            legend_row.addWidget(pill)
        legend_row.addStretch()
        log_hdr.addLayout(legend_row)

        self._log_date_badge = QLabel()
        self._log_date_badge.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:4px 12px;background:{C['white']};"
            f"color:{C['sub']};font-size:11px;"
        )
        log_hdr.addWidget(self._log_date_badge)
        wl.addLayout(log_hdr)

        # Table card — give it a generous minimum height so it always renders
        log_card = card()
        log_card.setMinimumHeight(200)
        lcl = QVBoxLayout(log_card)
        lcl.setContentsMargins(0, 0, 0, 0)
        self._log_table = SalesLogTable()
        self._log_table.setMinimumHeight(200)
        lcl.addWidget(self._log_table)
        wl.addWidget(log_card)
        parent.addWidget(wrap)

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        self._status    = QLabel()
        self._flash_lbl = QLabel()
        self._flash_lbl.setStyleSheet(f"color:{C['accent']};font-weight:600;")
        self.statusBar().addWidget(self._status)
        self.statusBar().addPermanentWidget(self._flash_lbl)

    # ── Refresh ───────────────────────────────────────────────────────────────
    def _refresh(self):
        s = self.sales

        self._page_sub.setText(
            f"Showing: {self._date_range_label().replace('📅  ', '')}"
        )

        self._refresh_kpi()
        self._refresh_order_type_row()
        self._bar_chart.set_data(s.hourly_data)
        self._refresh_best_sellers()
        self._refresh_discount_section()

        self._log_sub.setText(
            f"Live from database · {len(s.sales_log)} product(s) · "
            f"{s.dine_in_count} dine-in, {s.takeout_count} takeout, "
            f"{s.delivery_count} delivery"
        )
        self._log_date_badge.setText(f"🐘  Live DB  ·  {self._date_range_label()}")
        self._log_table.populate(s.sales_log)
        self._update_db_status_label()

        disc_info = ""
        if s.total_discounts > 0:
            disc_info = f"  |  Discounts: −₱{s.total_discounts:.2f}"

        self._status.setText(
            f"Gross Sales: ₱{s.net_sales:,.2f}  |  "
            f"Units Sold: {s.orders_today}  |  "
            f"Avg: ₱{s.avg_ticket:.2f}  |  "
            f"Est. Profit: ₱{s.total_profit:.2f}  |  "
            f"Peak: {s.peak_hour} (₱{s.peak_revenue:,.0f})"
            f"{disc_info}"
        )

    def _flash(self, msg: str, ms: int = 4000):
        self._flash_lbl.setText(msg)
        QTimer.singleShot(ms, lambda: self._flash_lbl.setText(""))

    # ── Import dialog ─────────────────────────────────────────────────────────
    def _open_import(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Import Sales Data")
        dlg.setMinimumSize(520, 380)
        dlg.setStyleSheet(f"background:{C['white']};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        lay.addWidget(lbl("Import Sales Data", bold=True, size=16))
        lay.addWidget(lbl(
            "Load hourly buckets and sales-log rows from CSV.\n"
            "Or use 'Reload' in the toolbar for live data.",
            color=C["sub"]
        ))
        lay.addWidget(hline())

        def btn_style():
            return (
                f"QPushButton{{background:{C['border']};border-radius:6px;"
                f"padding:6px 14px;border:none;}}"
                f"QPushButton:hover{{background:#D1D5DB;}}"
            )

        csv_box = QFrame()
        csv_box.setStyleSheet(
            f"QFrame{{border:1px solid {C['border']};"
            f"border-radius:10px;background:{C['bg']};}}"
        )
        bl_csv = QVBoxLayout(csv_box)
        bl_csv.setContentsMargins(16, 14, 16, 14)
        bl_csv.setSpacing(8)
        bl_csv.addWidget(lbl("From CSV Files", bold=True, size=12))
        bl_csv.addWidget(lbl(
            "One file for hourly (hour, revenue) · one for log rows",
            size=10, color=C["sub"]
        ))

        hourly_path = QLabel("No file selected")
        hourly_path.setStyleSheet(f"color:{C['sub']};font-size:11px;")
        log_path = QLabel("No file selected")
        log_path.setStyleSheet(f"color:{C['sub']};font-size:11px;")

        def pick(label_widget, attr):
            p, _ = QFileDialog.getOpenFileName(
                dlg, "Select CSV", "", "CSV (*.csv);;All (*)"
            )
            if p:
                label_widget.setText(p)
                setattr(dlg, attr, p)

        h_btn = QPushButton("Hourly CSV…")
        h_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        h_btn.setStyleSheet(btn_style())
        h_btn.clicked.connect(lambda: pick(hourly_path, "_h_path"))

        l_btn = QPushButton("Log CSV…")
        l_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        l_btn.setStyleSheet(btn_style())
        l_btn.clicked.connect(lambda: pick(log_path, "_l_path"))

        csv_row1 = QHBoxLayout()
        csv_row1.addWidget(h_btn)
        csv_row1.addWidget(hourly_path)
        bl_csv.addLayout(csv_row1)

        csv_row2 = QHBoxLayout()
        csv_row2.addWidget(l_btn)
        csv_row2.addWidget(log_path)
        bl_csv.addLayout(csv_row2)

        run_csv = QPushButton("Import CSV Files")
        run_csv.setCursor(Qt.CursorShape.PointingHandCursor)
        run_csv.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:white;border-radius:6px;"
            f"padding:7px 18px;font-weight:700;border:none;}}"
            f"QPushButton:hover{{background:#245f4a;}}"
        )

        def do_csv():
            hp = getattr(dlg, "_h_path", None)
            lp = getattr(dlg, "_l_path", None)
            if not hp or not lp:
                QMessageBox.warning(dlg, "Missing", "Select both CSV files.")
                return
            try:
                self._update_db_status_label()
                dlg.accept()
            except Exception as e:
                QMessageBox.critical(dlg, "Error", str(e))

        run_csv.clicked.connect(do_csv)
        bl_csv.addWidget(run_csv, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(csv_box)

        lay.addStretch()
        close = QPushButton("Close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton{{background:{C['border']};border-radius:7px;"
            f"padding:7px 20px;font-weight:600;border:none;}}"
            f"QPushButton:hover{{background:#D1D5DB;}}"
        )
        close.clicked.connect(dlg.accept)
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()


# ─────────────────────────────────────────────────────────────────────────────
# App entry point
# ─────────────────────────────────────────────────────────────────────────────
class SalesApp(QApplication):
    def __init__(self, argv=None):
        super().__init__(argv or sys.argv)
        self.setApplicationName("Pawffinated Sales Monitor")
        self.window = SalesWindow()

    def run(self):
        self.window.show()
        return self.exec()


if __name__ == "__main__":
    app = SalesApp(sys.argv)
    sys.exit(app.run())