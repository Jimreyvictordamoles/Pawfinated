"""
PAWFFINATED – Dashboard  (PyQt6 Edition)
=========================================
CHANGES:
    • Calendar: past dates are now selectable (no more setMinimumDate lock).
    • Quick Select presets changed to past-oriented:
        Today / Yesterday / Last 7 Days / Last 30 Days / This Month / Last Month.
    • Warning note removed (was telling users data is only from today onwards).
    • Chart auto-switches:
        - Single day  → Hourly Sales  (by hour, original behaviour)
        - Multi-day   → Daily Sales   (one bar per calendar date)
    • Chart title updates to reflect current mode.
    • _load_data() uses get_daily_snapshot() when multi-day range is selected.
"""

from __future__ import annotations
import sys
from Sidebar import PawffinatedSidebar
from DbConnection import get_db, db_info, InventoryDB

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
    QToolBar, QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QLineEdit, QComboBox, QCalendarWidget,
    QMenu, QWidgetAction,
)
from PyQt6.QtCore import Qt, QSize, QRect, QPoint, QTimer, QDate
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QBrush, QPen, QLinearGradient,
    QPainterPath, QAction, QPixmap,
)

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    sidebar   = "#FFFFFF",
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
    card_icon = "#F0FDF4",
)

LOW_STOCK_THRESHOLD = 10

# ── Module-level data (populated from DB on every refresh) ────────────────────
GROSS_SALES       = 0.0
GROSS_SALES_DELTA = 0.0
TOTAL_ORDERS      = 0
ORDERS_DELTA      = 0.0
HOURLY_DATA:      list[tuple] = []   # (label, revenue) — hourly OR daily
TOP_SELLERS:      list[tuple] = []
INVENTORY_FULL:   list[tuple] = []
INVENTORY_ALERTS: list[tuple] = []
LOW_STOCK_COUNT:  int   = 0
INVENTORY_VALUE:  float = 0.0

SALES_BREAKDOWN:  list[tuple] = []
CATEGORY_TOTALS:  dict        = {}

# Current chart mode — shared between _load_data and the chart widget
CHART_MODE: str = "hourly"   # "hourly" | "daily"

CAT_EMOJI = {
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


# ── Helpers ───────────────────────────────────────────────────────────────────
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


def card_frame(radius=12) -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        f"QFrame{{background:{C['white']};border-radius:{radius}px;"
        f"border:1px solid {C['border']};}}"
    )
    return f


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

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{C['accent']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 16, 24, 16)
        hl.addWidget(lbl("📅  Select Date Range", bold=True, size=15, color="#FFFFFF"))
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

        # ── Body ──────────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(16)

        # ── Presets — PAST-ORIENTED so users can view historical data ─────────
        presets_frame = QFrame()
        presets_frame.setFixedWidth(160)
        presets_frame.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:10px;"
            f"border:1px solid {C['border']};}}"
        )
        pfl = QVBoxLayout(presets_frame)
        pfl.setContentsMargins(12, 14, 12, 14)
        pfl.setSpacing(6)
        pfl.addWidget(lbl("Quick Select", bold=True, size=11, color=C["sub"]))

        today = QDate.currentDate()
        presets = [
            ("Today",        today,                         today),
            ("Yesterday",    today.addDays(-1),             today.addDays(-1)),
            ("Last 7 Days",  today.addDays(-6),             today),
            ("Last 30 Days", today.addDays(-29),            today),
            ("This Month",   QDate(today.year(), today.month(), 1), today),
            ("Last Month",
             QDate(today.year(), today.month(), 1).addMonths(-1),
             QDate(today.year(), today.month(), 1).addDays(-1)),
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

        # ── Dual calendars — past dates ALLOWED, future locked ────────────────
        cal_wrap = QVBoxLayout()
        cal_wrap.setSpacing(10)
        cals_row = QHBoxLayout()
        cals_row.setSpacing(12)

        from_col = QVBoxLayout()
        from_col.setSpacing(6)
        from_col.addWidget(lbl("From", bold=True, size=12))
        self._cal_from = QCalendarWidget()
        self._cal_from.setSelectedDate(self._from)
        # Allow any past date; only block future
        self._cal_from.setMaximumDate(QDate.currentDate())
        self._cal_from.setStyleSheet(self._cal_style())
        self._cal_from.selectionChanged.connect(self._on_from_changed)
        from_col.addWidget(self._cal_from)
        cals_row.addLayout(from_col)

        to_col = QVBoxLayout()
        to_col.setSpacing(6)
        to_col.addWidget(lbl("To", bold=True, size=12))
        self._cal_to = QCalendarWidget()
        self._cal_to.setSelectedDate(self._to)
        self._cal_to.setMaximumDate(QDate.currentDate())
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

        # ── Footer ────────────────────────────────────────────────────────────
        footer = QWidget()
        footer.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 12, 20, 12)
        fl.setSpacing(10)
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
        # If "from" is after "to", push "to" to match
        if self._from > self._to:
            self._to = self._from
            self._cal_to.setSelectedDate(self._to)
        self._update_range_lbl()

    def _on_to_changed(self):
        self._to = self._cal_to.selectedDate()
        # If "to" is before "from", pull "from" to match
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


# ── Sales Report Dialog ───────────────────────────────────────────────────────
class SalesReportDialog(QDialog):
    def __init__(self, date_from: QDate, date_to: QDate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sales Report")
        self.setMinimumSize(780, 620)
        self.resize(860, 680)
        self.setStyleSheet(f"background:{C['white']};")
        self._date_from = date_from
        self._date_to   = date_to
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['accent']};border-bottom:1px solid {C['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 18)
        hl.setSpacing(0)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        t = lbl("📊  Sales Report", bold=True, size=17, color="#FFFFFF")
        title_col.addWidget(t)
        date_range_str = (
            f"{self._date_from.toString('MMM d, yyyy')}  →  "
            f"{self._date_to.toString('MMM d, yyyy')}"
        )
        title_col.addWidget(lbl(date_range_str, size=10, color="#A7D9C6"))
        hl.addLayout(title_col)
        hl.addStretch()

        close_btn = QPushButton("✕  Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton{{background:rgba(255,255,255,0.15);color:white;"
            f"border:1px solid rgba(255,255,255,0.3);border-radius:7px;"
            f"padding:6px 16px;font-weight:600;font-size:12px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.25);}}"
        )
        close_btn.clicked.connect(self.accept)
        hl.addWidget(close_btn)
        lay.addWidget(hdr)

        kpi_strip = QWidget()
        kpi_strip.setStyleSheet(
            f"background:{C['bg']};border-bottom:1px solid {C['border']};"
        )
        kl = QHBoxLayout(kpi_strip)
        kl.setContentsMargins(28, 14, 28, 14)
        kl.setSpacing(0)

        total_rev    = sum(u * up for _, _, u, up, *_ in SALES_BREAKDOWN) if SALES_BREAKDOWN else GROSS_SALES
        total_units  = sum(u for _, _, u, *_ in SALES_BREAKDOWN) if SALES_BREAKDOWN else TOTAL_ORDERS
        total_profit = sum(tp for *_, tp in SALES_BREAKDOWN) if SALES_BREAKDOWN else 0.0
        avg_ticket   = total_rev / total_units if total_units else 0

        kpis = [
            ("Gross Revenue",  f"₱{total_rev:,.2f}",    C["accent"]),
            ("Units Sold",     str(total_units),          C["text"]),
            ("Total Profit",   f"₱{total_profit:,.2f}",  C["ok"]),
            ("Avg Ticket",     f"₱{avg_ticket:.2f}",     C["text"]),
            ("Profit Margin",  f"{total_profit/total_rev*100:.1f}%" if total_rev else "0%", C["warn"]),
        ]
        for i, (title, val, color) in enumerate(kpis):
            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(lbl(title, size=10, color=C["sub"]))
            col.addWidget(lbl(val, bold=True, size=18, color=color))
            kl.addLayout(col)
            if i < len(kpis) - 1:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.VLine)
                div.setStyleSheet(
                    f"background:{C['border']};border:none;margin:0 28px;"
                )
                kl.addWidget(div)

        lay.addWidget(kpi_strip)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"border:none;background:{C['bg']};")

        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 16, 24, 24)
        bl.setSpacing(20)

        if CATEGORY_TOTALS:
            bl.addWidget(lbl("Revenue by Category", bold=True, size=13))
            cat_card = QFrame()
            cat_card.setStyleSheet(
                f"QFrame{{background:{C['white']};border-radius:10px;"
                f"border:1px solid {C['border']};}}"
            )
            ccl = QVBoxLayout(cat_card)
            ccl.setContentsMargins(16, 14, 16, 14)
            ccl.setSpacing(10)

            max_rev_cat = max(v["revenue"] for v in CATEGORY_TOTALS.values()) or 1
            for cat, data in CATEGORY_TOTALS.items():
                row = QHBoxLayout()
                row.setSpacing(12)
                row.addWidget(lbl(cat, size=11, bold=True), 0)

                bar_bg = QFrame()
                bar_bg.setFixedHeight(8)
                bar_bg.setStyleSheet(
                    f"background:{C['border']};border-radius:4px;border:none;"
                )
                bar_bg.setLayout(QHBoxLayout())
                bar_bg.layout().setContentsMargins(0, 0, 0, 0)
                frac = data["revenue"] / max_rev_cat
                fill = QFrame(bar_bg)
                fill.setFixedHeight(8)
                fill.setStyleSheet(
                    f"background:{C['accent']};border-radius:4px;border:none;"
                )
                fill.setFixedWidth(max(4, int(300 * frac)))
                row.addWidget(bar_bg, 1)
                row.addWidget(lbl(f"₱{data['revenue']:,.2f}", bold=True, size=11,
                                   color=C["accent"]), 0)
                row.addWidget(lbl(f"{data['units']} units", size=10,
                                   color=C["sub"]), 0)
                row.addWidget(lbl(f"Profit ₱{data['profit']:,.2f}", size=10,
                                   color=C["ok"]), 0)
                ccl.addLayout(row)

            bl.addWidget(cat_card)

        if SALES_BREAKDOWN:
            bl.addWidget(lbl("Item Breakdown", bold=True, size=13))

            table = QTableWidget()
            COLS = ["Item", "Category", "Units", "Unit Price",
                    "Gross Revenue", "Cost", "Profit/Item", "Total Profit"]
            table.setColumnCount(len(COLS))
            table.setHorizontalHeaderLabels(COLS)
            table.verticalHeader().setVisible(False)
            table.setShowGrid(False)
            table.setAlternatingRowColors(False)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            table.setSortingEnabled(True)

            hdr_t = table.horizontalHeader()
            hdr_t.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for i in range(1, len(COLS)):
                hdr_t.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

            table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['white']};border:none;outline:none;font-size:12px;
                border-radius:10px;
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
            """)

            for name, cat, units, up, cost, pp, tp in SALES_BREAKDOWN:
                r = table.rowCount()
                table.insertRow(r)
                table.setRowHeight(r, 44)

                name_w = QWidget()
                name_w.setStyleSheet("background:transparent;")
                nl = QHBoxLayout(name_w)
                nl.setContentsMargins(8, 0, 0, 0)
                nl.setSpacing(8)
                em = QLabel(CAT_EMOJI.get(cat, "📦"))
                em.setFixedSize(28, 28)
                em.setAlignment(Qt.AlignmentFlag.AlignCenter)
                em.setStyleSheet(
                    "font-size:14px;background:#F0EDE8;"
                    "border-radius:6px;border:none;"
                )
                nl.addWidget(em)
                nl.addWidget(lbl(name, bold=True, size=11))
                nl.addStretch()
                table.setCellWidget(r, 0, name_w)

                def cell(text, color=None, align_right=False):
                    item = QTableWidgetItem(text)
                    if align_right:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
                        )
                    if color:
                        item.setForeground(QBrush(QColor(color)))
                    return item

                table.setItem(r, 1, cell(cat, C["sub"]))
                table.setItem(r, 2, cell(str(units), align_right=True))
                table.setItem(r, 3, cell(f"₱{up:.2f}", align_right=True))
                table.setItem(r, 4, cell(f"₱{up*units:.2f}", C["accent"], True))
                table.setItem(r, 5, cell(f"₱{cost:.2f}", C["sub"], True))
                table.setItem(r, 6, cell(f"₱{pp:.2f}", align_right=True))
                table.setItem(r, 7, cell(f"₱{tp:.2f}", C["ok"], True))

            table.setFixedHeight(min(len(SALES_BREAKDOWN) + 2, 14) * 46 + 40)
            bl.addWidget(table)

        if HOURLY_DATA:
            bl.addWidget(lbl("Revenue Breakdown", bold=True, size=13))
            h_card = QFrame()
            h_card.setStyleSheet(
                f"QFrame{{background:{C['white']};border-radius:10px;"
                f"border:1px solid {C['border']};}}"
            )
            hcl = QHBoxLayout(h_card)
            hcl.setContentsMargins(16, 14, 16, 14)
            hcl.setSpacing(0)

            peak_val = max(v for _, v in HOURLY_DATA)
            for label_str, rev in HOURLY_DATA:
                col_w = QVBoxLayout()
                col_w.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
                col_w.setSpacing(4)
                color = C["accent"] if rev == peak_val else C["sub"]
                col_w.addWidget(lbl(f"₱{rev:,}", bold=(rev == peak_val),
                                    size=9, color=color))
                col_w.addWidget(lbl(label_str, size=9, color=C["sub"]))
                hcl.addLayout(col_w)
                if label_str != HOURLY_DATA[-1][0]:
                    div = QFrame()
                    div.setFrameShape(QFrame.Shape.VLine)
                    div.setStyleSheet(
                        f"background:{C['border']};border:none;margin:0 12px;"
                    )
                    hcl.addWidget(div)

            bl.addWidget(h_card)

        if not SALES_BREAKDOWN and not HOURLY_DATA:
            no_data = lbl(
                "No sales data found for the selected date range.",
                size=13, color=C["sub"]
            )
            no_data.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bl.addWidget(no_data)

        bl.addStretch()
        scroll.setWidget(body)
        lay.addWidget(scroll, stretch=1)


# ── Bar Chart — supports hourly AND daily labels ──────────────────────────────
class MiniBarChart(QWidget):
    def __init__(self, data, chart_mode="hourly", parent=None):
        super().__init__(parent)
        self._data       = data
        self._chart_mode = chart_mode
        self._hovered    = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data, chart_mode="hourly"):
        self._data       = data
        self._chart_mode = chart_mode
        self._hovered    = -1
        self.update()

    def _format_label(self, raw: str) -> str:
        """Hourly: return as-is. Daily: convert 'YYYY-MM-DD' → 'May 20'."""
        if self._chart_mode == "hourly":
            return raw
        try:
            from datetime import date as _date
            d = _date.fromisoformat(raw)
            return d.strftime("%b %-d")   # Linux/Mac
        except Exception:
            pass
        try:
            from datetime import date as _date
            d = _date.fromisoformat(raw)
            return d.strftime("%b %#d")   # Windows
        except Exception:
            return raw

    def mouseMoveEvent(self, e):
        n = len(self._data)
        if not n:
            return
        pad_l, pad_r = 52, 16
        slot_w = (self.width() - pad_l - pad_r) / n
        idx = int((e.position().x() - pad_l) / slot_w)
        new = idx if 0 <= idx < n else -1
        if new != self._hovered:
            self._hovered = new
            self.update()

    def leaveEvent(self, e):
        self._hovered = -1
        self.update()

    def paintEvent(self, _):
        if not self._data:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setFont(QFont("Segoe UI", 11))
            p.setPen(QPen(QColor(C["sub"])))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "No sales data for selected range")
            p.end()
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 60, 16, 20, 36
        chart_w = w - pad_l - pad_r
        chart_h = h - pad_t - pad_b
        max_v = max(v for _, v in self._data) or 1
        n = len(self._data)
        slot_w = chart_w / n
        bar_w  = max(slot_w * 0.55, 8)

        grid_c = QColor(C["border"])
        text_c = QColor(C["sub"])

        # Grid lines
        steps = 4
        p.setFont(QFont("Segoe UI", 8))
        for i in range(steps + 1):
            frac = i / steps
            y = pad_t + chart_h * (1 - frac)
            p.setPen(QPen(grid_c, 1, Qt.PenStyle.DashLine))
            p.drawLine(pad_l, int(y), w - pad_r, int(y))
            p.setPen(QPen(text_c))
            p.drawText(0, int(y) - 7, pad_l - 6, 16,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"₱{int(max_v * frac):,}")

        peak_v = max(v for _, v in self._data)
        skip   = max(1, n // 18)   # max ~18 x-axis labels

        for i, (raw_label, value) in enumerate(self._data):
            frac = value / max_v
            bh   = max(int(chart_h * frac), 2 if value > 0 else 0)
            x    = pad_l + slot_w * i + (slot_w - bar_w) / 2
            y    = pad_t + chart_h - bh

            is_peak = (value == peak_v and peak_v > 0)
            is_hov  = (i == self._hovered)

            grad = QLinearGradient(x, y, x, y + bh)
            if is_hov or is_peak:
                grad.setColorAt(0, QColor("#4ACA96"))
                grad.setColorAt(1, QColor(C["accent"]))
            else:
                grad.setColorAt(0, QColor("#5DC99A"))
                grad.setColorAt(1, QColor(C["accent"]))

            path = QPainterPath()
            r = min(5, bar_w / 2)
            path.moveTo(x + r, y)
            path.lineTo(x + bar_w - r, y)
            path.quadTo(x + bar_w, y, x + bar_w, y + r)
            path.lineTo(x + bar_w, y + bh)
            path.lineTo(x, y + bh)
            path.lineTo(x, y + r)
            path.quadTo(x, y, x + r, y)
            path.closeSubpath()
            p.fillPath(path, QBrush(grad))

            # Hover tooltip
            if is_hov:
                p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                p.setPen(QPen(QColor(C["accent"])))
                p.drawText(int(x) - 5, int(y) - 16, int(bar_w) + 10, 14,
                           Qt.AlignmentFlag.AlignCenter, f"₱{value:,.0f}")

            # X-axis label
            label_str = self._format_label(raw_label)
            if i % skip == 0 or i == n - 1:
                if self._chart_mode == "daily" and n > 14:
                    # Rotate for dense daily charts
                    p.save()
                    p.setFont(QFont("Segoe UI", 8))
                    p.setPen(QPen(text_c))
                    cx = int(x + bar_w / 2)
                    p.translate(cx, h - pad_b + 8)
                    p.rotate(-35)
                    p.drawText(0, 0, label_str)
                    p.restore()
                else:
                    p.setFont(QFont("Segoe UI", 8))
                    p.setPen(QPen(text_c))
                    p.drawText(int(x - 8), h - pad_b + 4,
                               int(bar_w + 16), 18,
                               Qt.AlignmentFlag.AlignCenter, label_str)
        p.end()


# ── KPI Card ──────────────────────────────────────────────────────────────────
class KpiCard(QFrame):
    def __init__(self, title, value, delta_text, icon, delta_positive=True, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:12px;"
            f"border:1px solid {C['border']};}}"
        )
        self._build(title, value, delta_text, icon, delta_positive)

    def _build(self, title, value, delta_text, icon, positive):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(lbl(title, size=11, color=C["sub"]))
        top.addStretch()

        icon_lbl = QLabel(icon)
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            f"background:{C['accent_lt']};border-radius:8px;"
            f"font-size:16px;border:none;"
        )
        top.addWidget(icon_lbl)
        lay.addLayout(top)

        lay.addWidget(lbl(value, bold=True, size=26))

        if delta_text:
            delta_color = C["ok"] if positive else C["danger"]
            arrow = "↑" if positive else "↓"
            d = lbl(f"{arrow} {delta_text}", size=10, color=delta_color)
            lay.addWidget(d)


# ── Manage Inventory Dialog ───────────────────────────────────────────────────
class ManageInventoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Inventory")
        self.setMinimumSize(820, 640)
        self.resize(900, 700)
        self.setStyleSheet(f"background:{C['white']};")

        db = get_db()
        rows = db.fetch_all()
        self._items = [
            (r["id"], r["name"], r["sku"], r["category"],
             r["stock"], r["unit"], r["price"])
            for r in rows
        ]

        self._filter = "All"
        self._search = ""
        self._build()

    @staticmethod
    def _status(stock):
        if stock == 0:
            return "Out of Stock"
        if stock <= LOW_STOCK_THRESHOLD:
            return "Low Stock"
        return "In Stock"

    @staticmethod
    def _status_colors(status):
        return {
            "In Stock":     (C["ok_lt"],     C["ok"]),
            "Low Stock":    (C["warn_lt"],   C["warn"]),
            "Out of Stock": (C["danger_lt"], C["danger"]),
        }.get(status, (C["border"], C["sub"]))

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(f"background:{C['accent']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 18)
        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        title_col.addWidget(lbl("📦  Manage Inventory", bold=True, size=17, color="#FFFFFF"))
        title_col.addWidget(lbl("View stock levels, edit quantities and details.",
                                size=10, color="#A7D9C6"))
        hl.addLayout(title_col)
        hl.addStretch()
        close_btn = QPushButton("✕  Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton{{background:rgba(255,255,255,0.15);color:white;"
            f"border:1px solid rgba(255,255,255,0.3);border-radius:7px;"
            f"padding:6px 16px;font-weight:600;font-size:12px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,0.25);}}"
        )
        close_btn.clicked.connect(self.accept)
        hl.addWidget(close_btn)
        lay.addWidget(hdr)

        stats = QWidget()
        stats.setStyleSheet(
            f"background:{C['bg']};border-bottom:1px solid {C['border']};"
        )
        sl = QHBoxLayout(stats)
        sl.setContentsMargins(28, 12, 28, 12)
        sl.setSpacing(0)

        total_val = sum(stock * price for _, _, _, _, stock, _, price in self._items)
        low_ct    = sum(1 for *_, stock, _, price in self._items
                        if 0 < stock <= LOW_STOCK_THRESHOLD)
        out_ct    = sum(1 for *_, stock, _, price in self._items if stock == 0)

        stat_data = [
            ("Total Products",  str(len(self._items)), C["text"]),
            ("Low Stock",       str(low_ct),           C["warn"]),
            ("Out of Stock",    str(out_ct),            C["danger"]),
            ("Inventory Value", f"₱{total_val:,.2f}",  C["accent"]),
        ]
        for i, (title, val, color) in enumerate(stat_data):
            sc = QVBoxLayout()
            sc.setSpacing(2)
            sc.addWidget(lbl(title, size=10, color=C["sub"]))
            sc.addWidget(lbl(val, bold=True, size=16, color=color))
            sl.addLayout(sc)
            if i < len(stat_data) - 1:
                d = QFrame()
                d.setFrameShape(QFrame.Shape.VLine)
                d.setStyleSheet(
                    f"background:{C['border']};border:none;margin:0 28px;"
                )
                sl.addWidget(d)

        lay.addWidget(stats)

        toolbar = QWidget()
        toolbar.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(20, 10, 20, 10)
        tl.setSpacing(10)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍  Search products…")
        self._search_box.setFixedHeight(32)
        self._search_box.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:7px;"
            f"padding:0 10px;background:{C['bg']};font-size:12px;"
        )
        self._search_box.textChanged.connect(self._on_search)
        tl.addWidget(self._search_box, stretch=1)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All", "In Stock", "Low Stock", "Out of Stock"])
        self._filter_combo.setFixedHeight(32)
        self._filter_combo.setStyleSheet(
            f"QComboBox{{border:1px solid {C['border']};border-radius:7px;"
            f"padding:0 10px;background:{C['bg']};font-size:12px;min-width:130px;}}"
            f"QComboBox::drop-down{{border:none;width:22px;}}"
            f"QComboBox QAbstractItemView{{border:1px solid {C['border']};"
            f"selection-background-color:{C['accent_lt']};}}"
        )
        self._filter_combo.currentTextChanged.connect(self._on_filter)
        tl.addWidget(self._filter_combo)

        self._count_lbl = lbl("", size=10, color=C["sub"])
        tl.addWidget(self._count_lbl)
        lay.addWidget(toolbar)

        self._table = QTableWidget()
        COLS = ["", "Product", "Category", "Stock", "Unit", "Unit Price", "Value", "Status"]
        self._table.setColumnCount(len(COLS))
        self._table.setHorizontalHeaderLabels(COLS)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setSortingEnabled(True)

        th = self._table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in range(2, len(COLS)):
            th.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(0, 52)

        self._table.setStyleSheet(f"""
        QTableWidget {{
            background:{C['white']};border:none;outline:none;font-size:12px;
        }}
        QTableWidget::item {{
            padding:0 8px;
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
        """)

        lay.addWidget(self._table, stretch=1)

        footer = QWidget()
        footer.setStyleSheet(
            f"background:{C['bg']};border-top:1px solid {C['border']};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 8, 20, 8)
        fl.addWidget(lbl("Click a row to select  ·  Low stock items are highlighted",
                         size=10, color=C["sub"]))
        fl.addStretch()
        self._footer_lbl = lbl("", size=10, color=C["accent"])
        fl.addWidget(self._footer_lbl)
        lay.addWidget(footer)

        self._populate()

    def _on_search(self, text):
        self._search = text.lower()
        self._populate()

    def _on_filter(self, status):
        self._filter = status
        self._populate()

    def _visible(self):
        result = []
        for row in self._items:
            _, name, sku, cat, stock, unit, price = row
            status = self._status(stock)
            if self._filter != "All" and status != self._filter:
                continue
            q = self._search
            if q and q not in name.lower() and q not in sku.lower() \
                  and q not in cat.lower():
                continue
            result.append(row)
        return result

    def _populate(self):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        visible = self._visible()
        self._count_lbl.setText(
            f"Showing {len(visible)} of {len(self._items)} items"
        )

        total_val = sum(stock * price for _, _, _, _, stock, _, price in visible)
        self._footer_lbl.setText(f"Filtered value: ₱{total_val:,.2f}")

        for item_id, name, sku, cat, stock, unit, price in visible:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setRowHeight(r, 60)

            status = self._status(stock)

            em_lbl = QLabel(CAT_EMOJI.get(cat, "📦"))
            em_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em_lbl.setStyleSheet(
                "font-size:22px;background:#F0EDE8;"
                "border-radius:8px;margin:8px;padding:2px;border:none;"
            )
            self._table.setCellWidget(r, 0, em_lbl)

            name_w = QWidget()
            name_w.setStyleSheet("background:transparent;")
            nl = QVBoxLayout(name_w)
            nl.setContentsMargins(8, 0, 0, 0)
            nl.setSpacing(2)
            nl.addWidget(lbl(name, bold=True, size=12))
            nl.addWidget(lbl(f"SKU: {sku}", size=9, color=C["sub"]))
            self._table.setCellWidget(r, 1, name_w)

            cat_item = QTableWidgetItem(cat)
            cat_item.setForeground(QBrush(QColor(C["sub"])))
            self._table.setItem(r, 2, cat_item)

            stock_color = (C["danger"] if stock == 0
                           else C["warn"] if stock <= LOW_STOCK_THRESHOLD
                           else C["text"])
            stock_item = QTableWidgetItem(str(stock))
            stock_item.setForeground(QBrush(QColor(stock_color)))
            if stock <= LOW_STOCK_THRESHOLD:
                f = QFont("Segoe UI", 12)
                f.setBold(True)
                stock_item.setFont(f)
            stock_item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            )
            self._table.setItem(r, 3, stock_item)

            self._table.setItem(r, 4, QTableWidgetItem(unit))

            price_item = QTableWidgetItem(f"₱{price:.2f}")
            price_item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            )
            self._table.setItem(r, 5, price_item)

            val_item = QTableWidgetItem(f"₱{price * stock:,.2f}")
            val_item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            )
            self._table.setItem(r, 6, val_item)

            badge_bg, badge_fg = self._status_colors(status)
            badge = QLabel(status)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedHeight(24)
            badge.setMinimumWidth(96)
            badge.setStyleSheet(
                f"background:{badge_bg};color:{badge_fg};border-radius:5px;"
                f"padding:0 10px;font-size:10px;font-weight:700;border:none;"
            )
            badge_wrap = QWidget()
            badge_wrap.setStyleSheet("background:transparent;")
            bwl = QHBoxLayout(badge_wrap)
            bwl.setContentsMargins(6, 0, 6, 0)
            bwl.addWidget(badge)
            bwl.addStretch()
            self._table.setCellWidget(r, 7, badge_wrap)

        self._table.setSortingEnabled(True)


# ── Dashboard Window ──────────────────────────────────────────────────────────
class DashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Dashboard")
        self.resize(1200, 820)
        self.setMinimumSize(900, 640)
        self.setStyleSheet(
            f"QMainWindow,#central{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
            f"QToolBar{{background:{C['sidebar']};"
            f"border-bottom:1px solid {C['border']};padding:4px 16px;spacing:8px;}}"
            f"QStatusBar{{background:{C['sidebar']};"
            f"border-top:1px solid {C['border']};color:{C['sub']};"
            f"font-size:11px;padding:0 12px;}}"
        )

        today = QDate.currentDate()
        self._date_from = today
        self._date_to   = today

        self._load_data()
        self._build_toolbar()
        self._build_ui()

    # ── Date helpers ──────────────────────────────────────────────────────────
    def _date_strings(self) -> tuple[str, str]:
        return (
            self._date_from.toString("yyyy-MM-dd"),
            self._date_to.toString("yyyy-MM-dd"),
        )

    def _is_single_day(self) -> bool:
        return self._date_from == self._date_to

    def _date_range_label(self) -> str:
        if self._date_from == self._date_to:
            return f"📅  {self._date_from.toString('MMM d, yyyy')}"
        return (f"📅  {self._date_from.toString('MMM d, yyyy')}  →  "
                f"{self._date_to.toString('MMM d, yyyy')}")

    def _chart_title(self) -> str:
        return "Sales Overview — Daily" if CHART_MODE == "daily" else "Sales Overview — Hourly"

    # ── Live DB load ──────────────────────────────────────────────────────────
    def _load_data(self):
        global INVENTORY_FULL, INVENTORY_ALERTS, LOW_STOCK_COUNT, INVENTORY_VALUE
        global GROSS_SALES, GROSS_SALES_DELTA, TOTAL_ORDERS, ORDERS_DELTA
        global HOURLY_DATA, TOP_SELLERS, SALES_BREAKDOWN, CATEGORY_TOTALS
        global CHART_MODE

        d_from, d_to = self._date_strings()

        try:
            db = get_db()

            rows            = db.fetch_all()
            LOW_STOCK_COUNT = db.get_low_stock_count()
            INVENTORY_VALUE = db.get_total_inventory_value()
            alerts          = db.get_alerts()

            INVENTORY_FULL = [
                (r["id"], r["name"], r["sku"], r["category"],
                 r["stock"], r["unit"], r["price"])
                for r in rows
            ]
            INVENTORY_ALERTS = [
                (a["name"], a["category"], a["label"], a["severity"])
                for a in alerts
            ]

            summary           = db.get_sales_summary(date_from=d_from, date_to=d_to)
            GROSS_SALES       = summary.get("gross_sales", 0.0)
            GROSS_SALES_DELTA = summary.get("sales_change", 0.0)
            TOTAL_ORDERS      = summary.get("total_orders", 0)
            ORDERS_DELTA      = 0.0

            # ── Auto-select hourly vs daily based on range ─────────────────
            if self._is_single_day():
                CHART_MODE  = "hourly"
                hourly_rows = db.get_hourly_sales(date_from=d_from, date_to=d_to)
                HOURLY_DATA = [(r["hour"], float(r["revenue"])) for r in hourly_rows]
            else:
                CHART_MODE = "daily"
                if hasattr(db, "get_daily_snapshot"):
                    daily_rows  = db.get_daily_snapshot(date_from=d_from, date_to=d_to)
                    HOURLY_DATA = [(r.get("day", r.get("hour", "")),
                                    float(r["revenue"])) for r in daily_rows]
                else:
                    # Fallback: aggregate all hourly into a single total
                    hourly_rows = db.get_hourly_sales(date_from=d_from, date_to=d_to)
                    total = sum(float(r["revenue"]) for r in hourly_rows)
                    HOURLY_DATA = [(d_from, total)]

            top_raw     = db.get_top_sellers(date_from=d_from, date_to=d_to, limit=4)
            TOP_SELLERS = [
                (
                    r["name"],
                    r.get("category", ""),
                    int(r.get("units_sold", 0)),
                    CAT_EMOJI.get(r.get("category", ""), "📦"),
                )
                for r in top_raw
            ]

            log_rows = db.get_sales_log(date_from=d_from, date_to=d_to)
            SALES_BREAKDOWN = [
                (
                    r["name"],
                    r.get("category", ""),
                    int(r.get("unit_sales", 0)),
                    float(r.get("unit_price", 0.0)),
                    float(r.get("ingredient_cost", 0.0)),
                    float(r.get("profit_per_item", 0.0)),
                    float(r.get("total_profit", 0.0)),
                )
                for r in log_rows
            ]

            CATEGORY_TOTALS = {}
            for _n, _cat, _u, _up, _c, _pp, _tp in SALES_BREAKDOWN:
                if _cat not in CATEGORY_TOTALS:
                    CATEGORY_TOTALS[_cat] = {"units": 0, "revenue": 0.0, "profit": 0.0}
                CATEGORY_TOTALS[_cat]["units"]   += _u
                CATEGORY_TOTALS[_cat]["revenue"] += _u * _up
                CATEGORY_TOTALS[_cat]["profit"]  += _tp

        except Exception as e:
            print(f"[Dashboard] Could not load data from DB: {e}")
            INVENTORY_FULL    = []
            INVENTORY_ALERTS  = []
            LOW_STOCK_COUNT   = 0
            INVENTORY_VALUE   = 0.0
            GROSS_SALES       = 0.0
            GROSS_SALES_DELTA = 0.0
            TOTAL_ORDERS      = 0
            HOURLY_DATA       = []
            TOP_SELLERS       = []
            SALES_BREAKDOWN   = []
            CATEGORY_TOTALS   = {}
            CHART_MODE        = "hourly"

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)

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

    def _open_date_picker(self):
        dlg = DateRangeDialog(self._date_from, self._date_to, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._date_from, self._date_to = dlg.get_range()
            self._date_btn.setText(self._date_range_label())
            self._refresh_dashboard()

    # ── Full dashboard refresh ────────────────────────────────────────────────
    def _refresh_dashboard(self):
        self._load_data()
        self._header_sub.setText(
            f"Showing data for: {self._date_range_label().replace('📅  ', '')}"
        )
        self._rebuild_kpi_row()
        # Update chart title and data with correct mode
        self._chart_title_lbl.setText(self._chart_title())
        self._chart_widget.set_data(HOURLY_DATA, chart_mode=CHART_MODE)
        self._rebuild_top_sellers()
        self._rebuild_alerts()

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(PawffinatedSidebar(active_page="Dashboard"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"border:none;background:{C['bg']};")

        content = QWidget()
        content.setStyleSheet(f"background:{C['bg']};")
        self._cl = QVBoxLayout(content)
        self._cl.setContentsMargins(0, 0, 0, 24)
        self._cl.setSpacing(0)

        self._build_header(self._cl)
        self._build_kpi_row(self._cl)
        self._build_middle(self._cl)
        self._build_alerts(self._cl)

        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

    def _build_header(self, parent):
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 14)
        hl.setSpacing(4)
        hl.addWidget(lbl("Dashboard", bold=True, size=20))
        self._header_sub = lbl(
            f"Showing data for: {self._date_range_label().replace('📅  ', '')}",
            size=11, color=C["sub"]
        )
        hl.addWidget(self._header_sub)
        parent.addWidget(hdr)

    def _build_kpi_row(self, parent):
        self._kpi_wrap = QWidget()
        self._kpi_wrap.setStyleSheet(f"background:{C['bg']};")
        self._kpi_layout = QHBoxLayout(self._kpi_wrap)
        self._kpi_layout.setContentsMargins(20, 20, 20, 0)
        self._kpi_layout.setSpacing(16)
        self._fill_kpi_cards()
        parent.addWidget(self._kpi_wrap)

    def _fill_kpi_cards(self):
        while self._kpi_layout.count():
            item = self._kpi_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        delta_sign = "+" if GROSS_SALES_DELTA >= 0 else ""
        cards = [
            ("Gross Sales",
             f"₱{GROSS_SALES:,.2f}",
             f"{delta_sign}{GROSS_SALES_DELTA:.1f}% from prev. period",
             "💵", GROSS_SALES_DELTA >= 0),
            ("Total Orders",
             str(TOTAL_ORDERS),
             "— Live from database",
             "🧾", True),
            ("Low Stock Items",
             str(LOW_STOCK_COUNT),
             None,
             "⚠️", False),
            ("Inventory Value",
             f"₱{INVENTORY_VALUE:,.2f}",
             "— Live from database",
             "🐾", True),
        ]
        for title, value, delta, icon, pos in cards:
            c = KpiCard(title, value, delta, icon, pos)
            self._kpi_layout.addWidget(c)

    def _rebuild_kpi_row(self):
        self._fill_kpi_cards()

    def _build_middle(self, parent):
        self._middle_wrap = QWidget()
        self._middle_wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QHBoxLayout(self._middle_wrap)
        wl.setContentsMargins(20, 16, 20, 0)
        wl.setSpacing(16)

        chart_card = card_frame()
        ccl = QVBoxLayout(chart_card)
        ccl.setContentsMargins(20, 16, 20, 16)
        ccl.setSpacing(10)

        ch_hdr = QHBoxLayout()
        self._chart_title_lbl = lbl(self._chart_title(), bold=True, size=14)
        ch_hdr.addWidget(self._chart_title_lbl)
        ch_hdr.addStretch()
        view_btn = QPushButton("View Report  ›")
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['accent']};"
            f"border:none;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{text-decoration:underline;}}"
        )
        view_btn.clicked.connect(
            lambda: SalesReportDialog(self._date_from, self._date_to, self).exec()
        )
        ch_hdr.addWidget(view_btn)
        ccl.addLayout(ch_hdr)

        self._chart_widget = MiniBarChart(HOURLY_DATA, chart_mode=CHART_MODE)
        self._chart_widget.setMinimumHeight(200)
        ccl.addWidget(self._chart_widget)

        wl.addWidget(chart_card, stretch=3)

        self._sellers_card = card_frame()
        self._sellers_layout = QVBoxLayout(self._sellers_card)
        self._sellers_layout.setContentsMargins(20, 16, 20, 16)
        self._sellers_layout.setSpacing(6)
        self._sellers_layout.addWidget(lbl("Top Selling Items", bold=True, size=14))
        self._sellers_layout.addWidget(hline())
        self._sellers_content_layout = QVBoxLayout()
        self._sellers_content_layout.setSpacing(0)
        self._sellers_layout.addLayout(self._sellers_content_layout)
        self._sellers_layout.addStretch()
        self._fill_top_sellers()

        wl.addWidget(self._sellers_card, stretch=2)
        parent.addWidget(self._middle_wrap)

    def _fill_top_sellers(self):
        while self._sellers_content_layout.count():
            item = self._sellers_content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not TOP_SELLERS:
            no_data = lbl("No sales data for this period.", size=11, color=C["sub"])
            self._sellers_content_layout.addWidget(no_data)
            return

        for name, cat, units, emoji in TOP_SELLERS:
            row = QHBoxLayout()
            row.setSpacing(12)

            em = QLabel(emoji)
            em.setFixedSize(44, 44)
            em.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em.setStyleSheet(
                "font-size:22px;background:#F0EDE8;"
                "border-radius:8px;border:none;"
            )
            row.addWidget(em)

            info = QVBoxLayout()
            info.setSpacing(2)
            info.addWidget(lbl(name, bold=True, size=12))
            info.addWidget(lbl(cat, size=10, color=C["sub"]))
            row.addLayout(info)
            row.addStretch()

            units_col = QVBoxLayout()
            units_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            units_col.addWidget(lbl(str(units), bold=True, size=13))
            units_col.addWidget(lbl("sold", size=9, color=C["sub"]))
            row.addLayout(units_col)

            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_w.setLayout(row)
            self._sellers_content_layout.addWidget(row_w)
            self._sellers_content_layout.addWidget(hline())

    def _rebuild_top_sellers(self):
        self._fill_top_sellers()

    def _build_alerts(self, parent):
        self._alerts_wrap = QWidget()
        self._alerts_wrap.setStyleSheet(f"background:{C['bg']};")
        self._alerts_outer = QVBoxLayout(self._alerts_wrap)
        self._alerts_outer.setContentsMargins(20, 16, 20, 0)
        self._alerts_outer.setSpacing(12)
        self._fill_alerts()
        parent.addWidget(self._alerts_wrap)

    def _fill_alerts(self):
        while self._alerts_outer.count():
            item = self._alerts_outer.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        alert_hdr = QHBoxLayout()
        alert_hdr.addWidget(lbl("Inventory Alerts", bold=True, size=15))

        alert_count = len(INVENTORY_ALERTS)
        if alert_count:
            badge = QLabel(str(alert_count))
            badge.setFixedHeight(22)
            badge.setMinimumWidth(22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                f"background:{C['danger']};color:white;border-radius:11px;"
                f"font-size:11px;font-weight:700;padding:0 6px;border:none;"
            )
            alert_hdr.addWidget(badge)

        alert_hdr.addStretch()
        mgr_btn = QPushButton("Manage Inventory  ›")
        mgr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mgr_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['accent']};"
            f"border:none;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{text-decoration:underline;}}"
        )
        mgr_btn.clicked.connect(lambda: ManageInventoryDialog(self).exec())
        alert_hdr.addWidget(mgr_btn)
        self._alerts_outer.addLayout(alert_hdr)

        alerts_card = card_frame()
        acl = QGridLayout(alerts_card)
        acl.setContentsMargins(20, 16, 20, 16)
        acl.setSpacing(16)
        acl.setHorizontalSpacing(24)

        if not INVENTORY_ALERTS:
            no_alerts = lbl("✅  All items are well stocked.", size=12, color=C["ok"])
            acl.addWidget(no_alerts, 0, 0)
        else:
            for i, (name, cat, status, stype) in enumerate(INVENTORY_ALERTS):
                row_w = QWidget()
                row_w.setStyleSheet("background:transparent;")
                rl = QHBoxLayout(row_w)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(12)

                emoji = CAT_EMOJI.get(cat, "📦")
                em = QLabel(emoji)
                em.setFixedSize(44, 44)
                em.setAlignment(Qt.AlignmentFlag.AlignCenter)
                em.setStyleSheet(
                    "font-size:22px;background:#F0EDE8;"
                    "border-radius:8px;border:none;"
                )
                rl.addWidget(em)

                info = QVBoxLayout()
                info.setSpacing(2)
                info.addWidget(lbl(name, bold=True, size=12))
                info.addWidget(lbl(cat, size=10, color=C["sub"]))
                rl.addLayout(info)
                rl.addStretch()

                badge = QLabel(status)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if stype == "danger":
                    bg, fg = C["danger"], "#FFFFFF"
                else:
                    bg, fg = C["warn"], "#FFFFFF"
                badge.setStyleSheet(
                    f"background:{bg};color:{fg};border-radius:6px;"
                    f"padding:3px 12px;font-size:11px;font-weight:700;border:none;"
                )
                rl.addWidget(badge)

                col = i % 2
                row = i // 2
                acl.addWidget(row_w, row, col)

        self._alerts_outer.addWidget(alerts_card)

    def _rebuild_alerts(self):
        self._fill_alerts()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())


# ── App entry ─────────────────────────────────────────────────────────────────
class DashboardApp(QApplication):
    def __init__(self, argv=None):
        super().__init__(argv or sys.argv)
        self.setApplicationName("Pawffinated Dashboard")
        self.window = DashboardWindow()

    def run(self):
        self.window.show()
        return self.exec()


if __name__ == "__main__":
    app = DashboardApp(sys.argv)
    sys.exit(app.run())
