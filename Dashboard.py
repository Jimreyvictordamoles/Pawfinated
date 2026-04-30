"""
PAWFFINATED – Dashboard  (PyQt6 Edition)
=========================================
Run:
    python Dashboard.py
"""

from __future__ import annotations
import sys
from Sidebar import PawffinatedSidebar

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
    QToolBar, QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, QSize, QRect, QPoint, QTimer
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

# ── Demo data (mirrors POS + Inventory defaults) ───────────────────────────────
GROSS_SALES       = 3425.50
GROSS_SALES_DELTA = 12.5
TOTAL_ORDERS      = 142
ORDERS_DELTA      = 8.2
LOW_STOCK_COUNT   = 8
INVENTORY_VALUE   = 12450.00

HOURLY_DATA = [
    ("8 AM",  420),
    ("10 AM", 820),
    ("12 PM", 1020),
    ("2 PM",  640),
    ("4 PM",  540),
    ("6 PM",  260),
]

TOP_SELLERS = [
    ("Classic Latte",    "Coffee & Espresso", 42, "☕"),
    ("Almond Croissant", "Pastries",          28, "🥐"),
    ("Matcha Latte",     "Cold Beverages",    24, "🍵"),
    ("Blueberry Muffin", "Pastries",          19, "🫐"),
]

INVENTORY_ALERTS = [
    ("Turkey Avocado Sandwich", "Sandwiches", "Out of stock", "danger"),
    ("Almond Croissant",        "Pastries",   "3 left",       "warn"),
    ("Blueberry Muffin",        "Bakery",     "5 left",       "warn"),
]

ITEM_EMOJI = {
    "Classic Latte":          "☕",
    "Almond Croissant":       "🥐",
    "Matcha Latte":           "🍵",
    "Blueberry Muffin":       "🫐",
    "Turkey Avocado Sandwich":"🥪",
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


# ── Full sales breakdown data ─────────────────────────────────────────────────
SALES_BREAKDOWN = [
    # (name, category, units, unit_price, cost, profit_per, total_profit)
    ("Classic Latte",       "Coffee & Espresso", 42, 4.50, 1.20, 3.30,  138.60),
    ("Matcha Latte",        "Coffee & Espresso", 24, 5.00, 1.80, 3.20,   76.80),
    ("Iced Macchiato",      "Coffee & Espresso", 18, 5.25, 1.50, 3.75,   67.50),
    ("Cold Brew",           "Cold Beverages",    15, 4.75, 0.90, 3.85,   57.75),
    ("Vanilla Frappé",      "Cold Beverages",    11, 5.50, 1.40, 4.10,   45.10),
    ("Almond Croissant",    "Pastries",          28, 3.75, 1.10, 2.65,   74.20),
    ("Blueberry Muffin",    "Pastries",          19, 3.50, 0.95, 2.55,   48.45),
    ("Choc Chip Cookie",    "Pastries",          14, 2.50, 0.60, 1.90,   26.60),
    ("Cinnamon Roll",       "Pastries",           9, 4.00, 1.20, 2.80,   25.20),
    ("Bagel & Cream Cheese","Sandwiches",         7, 6.00, 2.10, 3.90,   27.30),
    ("House Blend Beans",   "Merchandise",        5,16.00, 8.00, 8.00,   40.00),
]

CATEGORY_TOTALS = {}
for _n, _cat, _u, _up, _c, _pp, _tp in SALES_BREAKDOWN:
    if _cat not in CATEGORY_TOTALS:
        CATEGORY_TOTALS[_cat] = {"units": 0, "revenue": 0.0, "profit": 0.0}
    CATEGORY_TOTALS[_cat]["units"]   += _u
    CATEGORY_TOTALS[_cat]["revenue"] += _u * _up
    CATEGORY_TOTALS[_cat]["profit"]  += _tp


# ── Sales Report Dialog ───────────────────────────────────────────────────────
class SalesReportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sales Report – Today")
        self.setMinimumSize(780, 620)
        self.resize(860, 680)
        self.setStyleSheet(f"background:{C['white']};")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
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
        title_col.addWidget(lbl("Today · 7:00 AM – 8:00 PM  ·  Oct 18, 2020",
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

        # ── Summary KPI strip ─────────────────────────────────────────────────
        kpi_strip = QWidget()
        kpi_strip.setStyleSheet(
            f"background:{C['bg']};border-bottom:1px solid {C['border']};"
        )
        kl = QHBoxLayout(kpi_strip)
        kl.setContentsMargins(28, 14, 28, 14)
        kl.setSpacing(0)

        total_rev    = sum(u * up for _, _, u, up, *_ in SALES_BREAKDOWN)
        total_units  = sum(u for _, _, u, *_ in SALES_BREAKDOWN)
        total_profit = sum(tp for *_, tp in SALES_BREAKDOWN)
        avg_ticket   = total_rev / total_units if total_units else 0

        kpis = [
            ("Gross Revenue",  f"${total_rev:,.2f}",    C["accent"]),
            ("Units Sold",     str(total_units),         C["text"]),
            ("Total Profit",   f"${total_profit:,.2f}",  C["ok"]),
            ("Avg Ticket",     f"${avg_ticket:.2f}",     C["text"]),
            ("Profit Margin",  f"{total_profit/total_rev*100:.1f}%", C["warn"]),
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

        # ── Scrollable body ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"border:none;background:{C['bg']};")

        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 16, 24, 24)
        bl.setSpacing(20)

        # ── Category breakdown ────────────────────────────────────────────────
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

            # Progress bar
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
            # We'll size it via a fixed width percentage trick using a spacer
            fill.setFixedWidth(max(4, int(300 * frac)))
            row.addWidget(bar_bg, 1)

            row.addWidget(lbl(f"${data['revenue']:,.2f}", bold=True, size=11,
                               color=C["accent"]), 0)
            row.addWidget(lbl(f"{data['units']} units", size=10,
                               color=C["sub"]), 0)
            row.addWidget(lbl(f"Profit ${data['profit']:,.2f}", size=10,
                               color=C["ok"]), 0)
            ccl.addLayout(row)

        bl.addWidget(cat_card)

        # ── Item-by-item table ────────────────────────────────────────────────
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

        EMOJI = {
            "Coffee & Espresso": "☕", "Cold Beverages": "🧊",
            "Pastries": "🥐", "Sandwiches": "🥪", "Merchandise": "🛍️",
        }

        for name, cat, units, up, cost, pp, tp in SALES_BREAKDOWN:
            r = table.rowCount()
            table.insertRow(r)
            table.setRowHeight(r, 44)

            # Name cell with emoji
            name_w = QWidget()
            name_w.setStyleSheet("background:transparent;")
            nl = QHBoxLayout(name_w)
            nl.setContentsMargins(8, 0, 0, 0)
            nl.setSpacing(8)
            em = QLabel(EMOJI.get(cat, "📦"))
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
            table.setItem(r, 3, cell(f"${up:.2f}", align_right=True))
            table.setItem(r, 4, cell(f"${up*units:.2f}", C["accent"], True))
            table.setItem(r, 5, cell(f"${cost:.2f}", C["sub"], True))
            table.setItem(r, 6, cell(f"${pp:.2f}", align_right=True))
            table.setItem(r, 7, cell(f"${tp:.2f}", C["ok"], True))

        # Totals row
        r = table.rowCount()
        table.insertRow(r)
        table.setRowHeight(r, 44)
        totals_w = QWidget()
        totals_w.setStyleSheet("background:transparent;")
        tl = QHBoxLayout(totals_w)
        tl.setContentsMargins(8, 0, 0, 0)
        tl.addWidget(lbl("TOTAL", bold=True, size=11))
        tl.addStretch()
        table.setCellWidget(r, 0, totals_w)
        table.setItem(r, 2, QTableWidgetItem(str(total_units)))
        table.setItem(r, 4, QTableWidgetItem(f"${total_rev:.2f}"))
        profit_item = QTableWidgetItem(f"${total_profit:.2f}")
        profit_item.setForeground(QBrush(QColor(C["ok"])))
        table.setItem(r, 7, profit_item)
        for col in [2, 4, 7]:
            if table.item(r, col):
                table.item(r, col).setFont(
                    QFont("Segoe UI", 11, QFont.Weight.Bold)
                )

        table.setFixedHeight(min(len(SALES_BREAKDOWN) + 2, 14) * 46 + 40)
        bl.addWidget(table)

        # ── Hourly breakdown table ─────────────────────────────────────────────
        bl.addWidget(lbl("Hourly Revenue Breakdown", bold=True, size=13))
        h_card = QFrame()
        h_card.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:10px;"
            f"border:1px solid {C['border']};}}"
        )
        hcl = QHBoxLayout(h_card)
        hcl.setContentsMargins(16, 14, 16, 14)
        hcl.setSpacing(0)

        peak_val = max(v for _, v in HOURLY_DATA)
        for hour, rev in HOURLY_DATA:
            col_w = QVBoxLayout()
            col_w.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            col_w.setSpacing(4)
            color = C["accent"] if rev == peak_val else C["sub"]
            col_w.addWidget(lbl(f"${rev:,}", bold=(rev == peak_val),
                                size=9, color=color))
            col_w.addWidget(lbl(hour, size=9, color=C["sub"]))
            hcl.addLayout(col_w)
            if hour != HOURLY_DATA[-1][0]:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.VLine)
                div.setStyleSheet(
                    f"background:{C['border']};border:none;margin:0 12px;"
                )
                hcl.addWidget(div)

        bl.addWidget(h_card)
        bl.addStretch()

        scroll.setWidget(body)
        lay.addWidget(scroll, stretch=1)


# ── Bar Chart ─────────────────────────────────────────────────────────────────
class MiniBarChart(QWidget):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self._data = data   # list of (label, value)
        self._hovered = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

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
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 52, 16, 20, 36
        chart_w = w - pad_l - pad_r
        chart_h = h - pad_t - pad_b
        max_v = max(v for _, v in self._data) or 1
        n = len(self._data)
        slot_w = chart_w / n
        bar_w = max(slot_w * 0.50, 14)

        grid_c = QColor(C["border"])
        text_c = QColor(C["sub"])

        # Grid + y-labels
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
                       f"${int(max_v * frac):,}")

        peak_v = max(v for _, v in self._data)
        for i, (label_text, value) in enumerate(self._data):
            frac = value / max_v
            bh = int(chart_h * frac)
            x = pad_l + slot_w * i + (slot_w - bar_w) / 2
            y = pad_t + chart_h - bh

            is_peak = (value == peak_v)
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

            if is_hov:
                p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                p.setPen(QPen(QColor(C["accent"])))
                p.drawText(int(x) - 5, int(y) - 16, int(bar_w) + 10, 14,
                           Qt.AlignmentFlag.AlignCenter, f"${value:,}")

            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QPen(text_c))
            p.drawText(int(x - 8), h - pad_b + 4,
                       int(bar_w + 16), 18,
                       Qt.AlignmentFlag.AlignCenter, label_text)
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
        self._build_toolbar()
        self._build_ui()

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)
        date_lbl = QLabel("📅  Today · 7:00 AM – 8:00 PM")
        date_lbl.setStyleSheet(
            f"color:{C['sub']};font-size:12px;"
            f"border:1px solid {C['border']};border-radius:6px;padding:4px 12px;"
            f"background:{C['white']};"
        )
        tb.addWidget(date_lbl)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(PawffinatedSidebar(active_page="Dashboard"))

        # Scrollable main content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"border:none;background:{C['bg']};")

        content = QWidget()
        content.setStyleSheet(f"background:{C['bg']};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 24)
        cl.setSpacing(0)

        self._build_header(cl)
        self._build_kpi_row(cl)
        self._build_middle(cl)
        self._build_alerts(cl)

        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

    # ── Page header ───────────────────────────────────────────────────────────
    def _build_header(self, parent):
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 14)
        hl.setSpacing(4)
        hl.addWidget(lbl("Dashboard", bold=True, size=20))
        hl.addWidget(lbl("Overview of your store's sales and inventory performance today.",
                         size=11, color=C["sub"]))
        parent.addWidget(hdr)

    # ── KPI cards row ─────────────────────────────────────────────────────────
    def _build_kpi_row(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(20, 20, 20, 0)
        wl.setSpacing(16)

        cards = [
            ("Gross Sales",      f"${GROSS_SALES:,.2f}",   f"+{GROSS_SALES_DELTA}% from yesterday", "💵", True),
            ("Total Orders",     str(TOTAL_ORDERS),         f"+{ORDERS_DELTA}% from yesterday",      "🧾", True),
            ("Low Stock Items",  str(LOW_STOCK_COUNT),      None,                                     "⚠️", False),
            ("Inventory Value",  f"${INVENTORY_VALUE:,.2f}","— Stable",                              "🐾", True),
        ]
        for title, value, delta, icon, pos in cards:
            card = KpiCard(title, value, delta, icon, pos)
            wl.addWidget(card)

        parent.addWidget(wrap)

    # ── Middle: chart + top sellers ───────────────────────────────────────────
    def _build_middle(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 0)
        wl.setSpacing(16)

        # Chart card
        chart_card = card_frame()
        ccl = QVBoxLayout(chart_card)
        ccl.setContentsMargins(20, 16, 20, 16)
        ccl.setSpacing(10)

        ch_hdr = QHBoxLayout()
        ch_hdr.addWidget(lbl("Sales Overview", bold=True, size=14))
        ch_hdr.addStretch()
        view_btn = QPushButton("View Report  ›")
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['accent']};"
            f"border:none;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{text-decoration:underline;}}"
        )
        view_btn.clicked.connect(lambda: SalesReportDialog(self).exec())
        ch_hdr.addWidget(view_btn)
        ccl.addLayout(ch_hdr)

        chart = MiniBarChart(HOURLY_DATA)
        chart.setMinimumHeight(200)
        ccl.addWidget(chart)

        wl.addWidget(chart_card, stretch=3)

        # Top Sellers card
        sellers_card = card_frame()
        scl = QVBoxLayout(sellers_card)
        scl.setContentsMargins(20, 16, 20, 16)
        scl.setSpacing(6)
        scl.addWidget(lbl("Top Selling Items", bold=True, size=14))
        scl.addWidget(hline())

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

            scl.addLayout(row)
            scl.addWidget(hline())

        scl.addStretch()
        wl.addWidget(sellers_card, stretch=2)
        parent.addWidget(wrap)

    # ── Inventory Alerts ──────────────────────────────────────────────────────
    def _build_alerts(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 0)
        wl.setSpacing(12)

        alert_hdr = QHBoxLayout()
        alert_hdr.addWidget(lbl("Inventory Alerts", bold=True, size=15))
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
        wl.addLayout(alert_hdr)

        alerts_card = card_frame()
        acl = QGridLayout(alerts_card)
        acl.setContentsMargins(20, 16, 20, 16)
        acl.setSpacing(16)
        acl.setHorizontalSpacing(24)

        for i, (name, cat, status, stype) in enumerate(INVENTORY_ALERTS):
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(12)

            emoji = ITEM_EMOJI.get(name, "📦")
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

        wl.addWidget(alerts_card)
        parent.addWidget(wrap)


# ── Full inventory data ───────────────────────────────────────────────────────
INVENTORY_FULL = [
    # (id, name, sku, category, stock, unit, price)
    (1,  "House Blend Beans",   "BNS-HB-01",  "Whole Beans",       45, "kg",    24.00),
    (2,  "Oat Milk (1L)",       "DRY-OAT-02", "Dairy Alt",          8, "units",  5.50),
    (3,  "Blueberry Muffin",    "PST-BM-01",  "Pastries",           0, "units",  3.50),
    (4,  "Vanilla Syrup (1L)",  "SYR-VAN-01", "Syrups",            24, "units", 12.50),
    (5,  "Whole Milk (Gallon)", "DRY-WM-01",  "Dairy",             12, "units",  4.50),
    (6,  "Classic Latte",       "ESP-CL-01",  "Coffee & Espresso", 42, "cups",   4.50),
    (7,  "Almond Croissant",    "PST-AC-01",  "Pastries",           3, "units",  3.75),
    (8,  "Cold Brew Bags",      "BNS-CB-01",  "Whole Beans",        6, "bags",   9.00),
    (9,  "Choc Chip Cookie",    "PST-CC-01",  "Pastries",          18, "units",  2.50),
    (10, "Matcha Powder",       "SYR-MT-01",  "Syrups",             5, "tins",  14.00),
    (11, "Caramel Sauce",       "SYR-CS-01",  "Syrups",            30, "units",  8.00),
    (12, "Iced Macchiato",      "ESP-IM-01",  "Coffee & Espresso", 28, "cups",   5.25),
]

LOW_STOCK_THRESHOLD = 10

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


class ManageInventoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Inventory")
        self.setMinimumSize(820, 640)
        self.resize(900, 700)
        self.setStyleSheet(f"background:{C['white']};")
        self._items = list(INVENTORY_FULL)   # local copy; edits stay in dialog
        self._filter = "All"
        self._search = ""
        self._build()

    # ── Status helpers ────────────────────────────────────────────────────────
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

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
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

        # Stats strip
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
            ("Total Products",   str(len(self._items)),  C["text"]),
            ("Low Stock",        str(low_ct),             C["warn"]),
            ("Out of Stock",     str(out_ct),             C["danger"]),
            ("Inventory Value",  f"${total_val:,.2f}",   C["accent"]),
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

        # Search + filter bar
        toolbar = QWidget()
        toolbar.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(20, 10, 20, 10)
        tl.setSpacing(10)

        from PyQt6.QtWidgets import QLineEdit, QComboBox
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

        # Table
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
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
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

        # Footer hint
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

    # ── Filtering ─────────────────────────────────────────────────────────────
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

    # ── Populate table ────────────────────────────────────────────────────────
    def _populate(self):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        visible = self._visible()
        self._count_lbl.setText(
            f"Showing {len(visible)} of {len(self._items)} items"
        )

        total_val = sum(stock * price for _, _, _, _, stock, _, price in visible)
        self._footer_lbl.setText(f"Filtered value: ${total_val:,.2f}")

        for item_id, name, sku, cat, stock, unit, price in visible:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setRowHeight(r, 60)

            status = self._status(stock)

            # Col 0 – emoji
            em_lbl = QLabel(CAT_EMOJI.get(cat, "📦"))
            em_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em_lbl.setStyleSheet(
                "font-size:22px;background:#F0EDE8;"
                "border-radius:8px;margin:8px;padding:2px;border:none;"
            )
            self._table.setCellWidget(r, 0, em_lbl)

            # Col 1 – name + SKU
            name_w = QWidget()
            name_w.setStyleSheet("background:transparent;")
            nl = QVBoxLayout(name_w)
            nl.setContentsMargins(8, 0, 0, 0)
            nl.setSpacing(2)
            nl.addWidget(lbl(name, bold=True, size=12))
            nl.addWidget(lbl(f"SKU: {sku}", size=9, color=C["sub"]))
            self._table.setCellWidget(r, 1, name_w)

            # Col 2 – category
            cat_item = QTableWidgetItem(cat)
            cat_item.setForeground(QBrush(QColor(C["sub"])))
            self._table.setItem(r, 2, cat_item)

            # Col 3 – stock (coloured)
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

            # Col 4 – unit
            self._table.setItem(r, 4, QTableWidgetItem(unit))

            # Col 5 – price
            price_item = QTableWidgetItem(f"${price:.2f}")
            price_item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            )
            self._table.setItem(r, 5, price_item)

            # Col 6 – total value
            val_item = QTableWidgetItem(f"${price * stock:,.2f}")
            val_item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            )
            self._table.setItem(r, 6, val_item)

            # Col 7 – status badge widget
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