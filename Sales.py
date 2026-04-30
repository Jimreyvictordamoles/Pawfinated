"""
PAWFFINATED – Sales Monitor  (PyQt6 Edition)
============================================
Install:
    pip install PyQt6

Run:
    python pawffinated_sales_qt.py

─── EXPOSED VARIABLES ──────────────────────────────────────────────────────
    app = SalesApp(sys.argv)
    win = app.window                        # SalesWindow

    win.sales.net_sales           → float
    win.sales.net_sales_change    → float   (% vs yesterday)
    win.sales.orders_today        → int
    win.sales.avg_ticket          → float
    win.sales.best_seller         → SalesItem
    win.sales.peak_hour           → str     e.g. "11 AM"
    win.sales.peak_revenue        → float
    win.sales.hourly_data         → list[HourlyBucket]
    win.sales.sales_log           → list[SalesItem]
    win.sales.best_sellers        → list[SalesItem]  (sorted by units)
    win.sales.date_label          → str
    win.sales.shift_label         → str

    Signals:
    win.sales.data_changed        → pyqtSignal()

─── DATA IMPORT ─────────────────────────────────────────────────────────────
    Programmatic:
        win.sales.load_from_query(conn, hourly_q, log_q)
        win.sales.load_from_csv(hourly_path, log_path)
        win.sales.load_from_list(hourly_list, log_list)

    Expected hourly columns:  hour | revenue
    Expected log columns:     name | sku | unit_sales | unit_price
                              | ingredient_cost | profit_per_item | total_profit
"""

from __future__ import annotations
import sys, csv, io, sqlite3, math
from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
    QFileDialog, QDialog, QTextEdit, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QToolBar, QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize, QTimer, QRect, QPoint
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QBrush, QPen, QLinearGradient,
    QPainterPath, QAction, QPolygon,
)

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    sidebar   = "#FFFFFF",
    white     = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_lt = "#E8F4F0",
    accent_bar= "#3DAA80",
    warn      = "#E07B39",
    warn_lt   = "#FEF3C7",
    danger    = "#D94F4F",
    ok        = "#059669",
    ok_lt     = "#D1FAE5",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    border    = "#E5E7EB",
    green_tag = "#22C55E",
)

# ── Domain models ─────────────────────────────────────────────────────────────
@dataclass
class HourlyBucket:
    hour: str        # "8 AM"
    revenue: float


@dataclass
class SalesItem:
    name: str
    sku: str
    unit_sales: int
    unit_price: float
    ingredient_cost: float
    profit_per_item: float
    total_profit: float

    @property
    def gross_revenue(self) -> float:
        return self.unit_price * self.unit_sales


# ── Default demo data ─────────────────────────────────────────────────────────
_HOURLY_DEMO = [
    HourlyBucket("8 AM",  420),
    HourlyBucket("9 AM",  580),
    HourlyBucket("10 AM", 740),
    HourlyBucket("11 AM", 1180),
    HourlyBucket("12 PM", 970),
    HourlyBucket("1 PM",  660),
    HourlyBucket("2 PM",  590),
    HourlyBucket("3 PM",  510),
]

_LOG_DEMO = [
    SalesItem("Classic Latte",   "SKU: ESP-MW-01", 10, 4.50, 6.50, 2.50, 12.50),
    SalesItem("Matcha Latte",    "SKU: ESP-BM-01", 13, 4.50, 9.50, 5.50, 16.50),
    SalesItem("Blueberry Muffin","SKU: DRY-MW-01", 21, 2.50, 4.50, 3.50, 19.50),
    SalesItem("Almond Croissant","SKU: DRY-MW-01", 19, 3.50, 4.50, 5.50, 15.50),
]

ITEM_EMOJI = {
    "Classic Latte":    "☕",
    "Matcha Latte":     "🍵",
    "Blueberry Muffin": "🫐",
    "Almond Croissant": "🥐",
    "Cold Brew":        "🧊",
    "Iced Macchiato":   "☕",
}


# ─────────────────────────────────────────────────────────────────────────────
# Sales State
# ─────────────────────────────────────────────────────────────────────────────
class SalesState(QObject):
    data_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.hourly_data: list[HourlyBucket] = list(_HOURLY_DEMO)
        self.sales_log:   list[SalesItem]    = list(_LOG_DEMO)
        self.date_label:  str = "Oct 18, 2020"
        self.shift_label: str = "7:00 AM–8:00 PM"
        self.net_sales_change: float = 12.8

    # ── Computed ──────────────────────────────────────────────────────────────
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
        return max(self.hourly_data, key=lambda b: b.revenue) if self.hourly_data else None

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

    # ── Loaders ───────────────────────────────────────────────────────────────
    _H_ALIASES = {"hour": ["hour","time","period","slot"],
                  "revenue": ["revenue","sales","amount","total","gross"]}
    _L_ALIASES = {
        "name":            ["name","product","item","product_name"],
        "sku":             ["sku","code","barcode"],
        "unit_sales":      ["unit_sales","units","qty","quantity","sold"],
        "unit_price":      ["unit_price","price","retail"],
        "ingredient_cost": ["ingredient_cost","cost","cogs"],
        "profit_per_item": ["profit_per_item","profit","margin"],
        "total_profit":    ["total_profit","total","net"],
    }

    def _norm(self, aliases, headers, row):
        if isinstance(row, (list, tuple)):
            row = dict(zip(headers, row))
        rl = {k.lower().strip(): v for k, v in row.items()}
        out = {f: None for f in aliases}
        for f, alts in aliases.items():
            for a in alts:
                if a in rl:
                    out[f] = rl[a]
                    break
        return out

    def load_from_list(self, hourly: list[dict], log: list[dict]) -> None:
        hh = [list(d.keys()) for d in hourly[:1]]
        lh = [list(d.keys()) for d in log[:1]]
        self.hourly_data = []
        for row in hourly:
            r = self._norm(self._H_ALIASES, hh[0] if hh else [], row)
            try:
                self.hourly_data.append(
                    HourlyBucket(str(r["hour"]), float(r["revenue"]))
                )
            except (TypeError, ValueError):
                pass
        self.sales_log = []
        for row in log:
            r = self._norm(self._L_ALIASES, lh[0] if lh else [], row)
            try:
                self.sales_log.append(SalesItem(
                    name=str(r["name"] or ""),
                    sku=str(r["sku"] or ""),
                    unit_sales=int(r["unit_sales"] or 0),
                    unit_price=float(str(r["unit_price"] or 0).replace("$","")),
                    ingredient_cost=float(str(r["ingredient_cost"] or 0).replace("$","")),
                    profit_per_item=float(str(r["profit_per_item"] or 0).replace("$","")),
                    total_profit=float(str(r["total_profit"] or 0).replace("$","")),
                ))
            except (TypeError, ValueError):
                pass
        self.data_changed.emit()

    def load_from_csv(self, hourly_path: str, log_path: str) -> None:
        def read(p):
            with open(p, newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                return list(r)
        self.load_from_list(read(hourly_path), read(log_path))

    def load_from_query(self, conn: Any, hourly_q: str, log_q: str) -> None:
        def fetch(q):
            cur = conn.cursor()
            cur.execute(q)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        self.load_from_list(fetch(hourly_q), fetch(log_q))


# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
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
        w   = self.width()
        pad = 40
        n   = len(self._data)
        slot_w = (w - pad * 2) / n
        x = e.position().x()
        idx = int((x - pad) / slot_w)
        new = idx if 0 <= idx < n else -1
        if new != self._hovered:
            self._hovered = new
            self.update()

    def leaveEvent(self, e):
        self._hovered = -1
        self.update()

    def paintEvent(self, e):
        if not self._data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w     = self.width()
        h     = self.height()
        pad_l = 48
        pad_r = 20
        pad_t = 24
        pad_b = 36

        chart_w = w - pad_l - pad_r
        chart_h = h - pad_t - pad_b

        max_rev = max((b.revenue for b in self._data), default=1)
        n       = len(self._data)
        slot_w  = chart_w / n
        bar_w   = max(slot_w * 0.52, 12)

        # Grid lines + y labels
        grid_color = QColor(C["border"])
        text_color = QColor(C["sub"])
        steps = 4
        painter.setFont(QFont("Segoe UI", 9))
        for i in range(steps + 1):
            frac = i / steps
            y = pad_t + chart_h * (1 - frac)
            painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DashLine))
            painter.drawLine(pad_l, int(y), w - pad_r, int(y))
            val = int(max_rev * frac)
            painter.setPen(QPen(text_color))
            painter.drawText(0, int(y) - 6, pad_l - 6, 20,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"${val:,}")

        # Bars
        peak_rev = max(b.revenue for b in self._data)
        for i, bucket in enumerate(self._data):
            frac   = bucket.revenue / max_rev if max_rev else 0
            bar_h  = int(chart_h * frac)
            x      = pad_l + slot_w * i + (slot_w - bar_w) / 2
            y      = pad_t + chart_h - bar_h

            is_peak    = (bucket.revenue == peak_rev)
            is_hovered = (i == self._hovered)

            # Bar gradient
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

            # Hover tooltip value
            if is_hovered:
                tip = f"${bucket.revenue:,}"
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                painter.setPen(QPen(QColor(C["accent"])))
                painter.drawText(int(x), int(y) - 18, int(bar_w), 16,
                                 Qt.AlignmentFlag.AlignCenter, tip)

            # X-axis label
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QPen(text_color))
            painter.drawText(int(x - 10), h - pad_b + 6,
                             int(bar_w + 20), 20,
                             Qt.AlignmentFlag.AlignCenter,
                             bucket.hour)

        painter.end()


# ─────────────────────────────────────────────────────────────────────────────
# Best Sellers Progress Bars
# ─────────────────────────────────────────────────────────────────────────────
class BestSellerRow(QWidget):
    def __init__(self, item: SalesItem, max_units: int, parent=None):
        super().__init__(parent)
        self.item = item
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
        top.addWidget(lbl(f"${self.item.gross_revenue:.0f}", bold=True,
                          size=12, color=C["text"]))
        lay.addLayout(top)

        units_lbl = lbl(f"{self.item.unit_sales} sold", size=10, color=C["sub"])
        lay.addWidget(units_lbl)

        # Progress bar
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
        # We'll set width in resizeEvent via a stretch trick
        self._bar_fill = bar_fill
        self._frac     = frac
        lay.addWidget(bar_bg)
        self._bar_bg = bar_bg

    def resizeEvent(self, e):
        super().resizeEvent(e)
        total = self._bar_bg.width()
        self._bar_fill.setFixedWidth(int(total * self._frac))


# ─────────────────────────────────────────────────────────────────────────────
# Sales Log Table
# ─────────────────────────────────────────────────────────────────────────────
LOG_COLS = ["Item", "Unit Sales", "Gross Revenue",
            "Ingredient Cost", "Profit/Item", "Total Profit"]

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
        for i in range(1, len(LOG_COLS)):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        self.setStyleSheet(f"""
        QTableWidget {{
            background:{C['white']};border:none;outline:none;font-size:13px;
        }}
        QTableWidget::item {{
            padding:4px 12px;
            border-bottom:1px solid {C['border']};
            color:{C['text']};
        }}
        QTableWidget::item:selected {{
            background:{C['accent_lt']};color:{C['text']};
        }}
        QHeaderView::section {{
            background:{C['bg']};color:{C['sub']};
            font-size:11px;font-weight:600;
            padding:8px 12px;border:none;
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

    def populate(self, items: list[SalesItem]):
        self.setRowCount(0)
        for item in items:
            r = self.rowCount()
            self.insertRow(r)
            self.setRowHeight(r, 62)

            # Col 0: emoji + name + sku
            name_w = QWidget()
            name_w.setStyleSheet("background:transparent;")
            nl = QHBoxLayout(name_w)
            nl.setContentsMargins(8, 0, 0, 0)
            nl.setSpacing(12)

            em = QLabel(ITEM_EMOJI.get(item.name, "📦"))
            em.setFixedSize(40, 40)
            em.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em.setStyleSheet(
                "font-size:22px;background:#F0EDE8;"
                "border-radius:8px;border:none;"
            )
            nl.addWidget(em)

            txt = QVBoxLayout()
            txt.setSpacing(2)
            txt.addWidget(lbl(item.name, bold=True, size=12))
            txt.addWidget(lbl(item.sku, size=10, color=C["sub"]))
            nl.addLayout(txt)
            nl.addStretch()
            self.setCellWidget(r, 0, name_w)

            def money_cell(val, color=None):
                w = QTableWidgetItem(f"${val:.2f}")
                w.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
                )
                if color:
                    w.setForeground(QBrush(QColor(color)))
                return w

            self.setItem(r, 1, QTableWidgetItem(f"{item.unit_sales} units"))
            self.setItem(r, 2, money_cell(item.gross_revenue))
            self.setItem(r, 3, money_cell(item.ingredient_cost, C["sub"]))
            self.setItem(r, 4, money_cell(item.profit_per_item))
            self.setItem(r, 5, money_cell(item.total_profit, C["ok"]))


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class SalesWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sales = SalesState()
        self.setWindowTitle("Pawffinated – Sales Monitor")
        self.resize(1200, 820)
        self.setMinimumSize(900, 650)
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

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(
            f"font-weight:800;font-size:14px;color:{C['accent']};"
        )
        tb.addWidget(logo)
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)

        date_lbl = QLabel(f"📅  Today · {self.sales.shift_label}")
        date_lbl.setStyleSheet(
            f"color:{C['sub']};font-size:12px;"
            f"border:1px solid {C['border']};border-radius:6px;padding:4px 12px;"
            f"background:{C['white']};"
        )
        tb.addWidget(date_lbl)

        imp = QAction("📥  Import Data", self)
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

        self._build_sidebar(root)

        # Scrollable main content
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
        self._build_middle_section(self._content_lay)
        self._build_sales_log_section(self._content_lay)

        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self, parent):
        sb = QWidget()
        sb.setFixedWidth(180)
        sb.setStyleSheet(
            f"background:{C['sidebar']};"
            f"border-right:1px solid {C['border']};"
        )
        sl = QVBoxLayout(sb)
        sl.setContentsMargins(12, 20, 12, 16)
        sl.setSpacing(2)

        def sec(t):
            w = lbl(t, size=9, color=C["sub"])
            w.setContentsMargins(4, 12, 0, 4)
            sl.addWidget(w)

        def nav(icon, text, active=False):
            b = QPushButton(f"  {icon}  {text}")
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(36)
            b.setStyleSheet(
                f"QPushButton{{text-align:left;border-radius:6px;padding-left:6px;"
                f"background:{''+C['accent_lt']+';color:'+C['accent'] if active else 'transparent;color:'+C['text']};"
                f"font-weight:{'600' if active else '400'};}}"
                f"QPushButton:hover{{background:{C['accent_lt']};}}"
            )
            sl.addWidget(b)

        sec("MAIN")
        nav("📊", "Dashboard")
        nav("📋", "Orders")
        sec("MANAGEMENT")
        nav("📈", "Sales Monitor", active=True)
        nav("🔒", "Access Control")
        nav("📝", "Activity Log")
        nav("📦", "Inventory")

        sl.addStretch()
        sl.addWidget(hline())

        ur = QHBoxLayout()
        ava = QLabel("SJ")
        ava.setFixedSize(34, 34)
        ava.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ava.setStyleSheet(
            f"background:{C['accent']};color:white;"
            f"border-radius:17px;font-weight:700;font-size:12px;"
        )
        info = QVBoxLayout()
        info.setSpacing(0)
        info.addWidget(lbl("Sarah Jenkins", bold=True, size=11))
        info.addWidget(lbl("Store Manager", size=10, color=C["sub"]))
        ur.addWidget(ava)
        ur.addLayout(info)
        ur.addStretch()
        sl.addLayout(ur)
        parent.addWidget(sb)

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
        left.addWidget(lbl(
            "Track hourly sales momentum and spot best sellers in real time.",
            size=11, color=C["sub"]
        ))
        hl.addLayout(left)
        hl.addStretch()
        parent.addWidget(hdr)

    # ── KPI bar ───────────────────────────────────────────────────────────────
    def _build_kpi_bar(self, parent):
        self._kpi_bar = QWidget()
        self._kpi_bar.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        self._kpi_lay = QHBoxLayout(self._kpi_bar)
        self._kpi_lay.setContentsMargins(28, 18, 28, 18)
        self._kpi_lay.setSpacing(0)
        parent.addWidget(self._kpi_bar)

    def _refresh_kpi(self):
        # Clear
        while self._kpi_lay.count():
            item = self._kpi_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def divider():
            ln = QFrame()
            ln.setFrameShape(QFrame.Shape.VLine)
            ln.setFixedWidth(1)
            ln.setStyleSheet(f"background:{C['border']};border:none;margin:0 32px;")
            self._kpi_lay.addWidget(ln)

        s = self.sales

        # Net sales
        self._kpi_lay.addLayout(
            self._kpi_card(
                "Net sales",
                f"${s.net_sales:,.0f}",
                badge_text=f"+{s.net_sales_change:.1f}%",
                badge_color=C["ok"], badge_bg=C["ok_lt"],
                sub="Compared with yesterday",
            )
        )
        divider()

        # Orders
        self._kpi_lay.addLayout(
            self._kpi_card(
                "Orders",
                str(s.orders_today),
                badge_text=f"{s.orders_today} today",
                badge_color=C["accent"], badge_bg=C["accent_lt"],
                sub=f"Average ticket ${s.avg_ticket:.2f}",
            )
        )
        divider()

        # Best seller
        bs = s.best_seller
        self._kpi_lay.addLayout(
            self._kpi_card(
                "Best seller",
                bs.name if bs else "—",
                badge_text="Top Item",
                badge_color=C["warn"], badge_bg=C["warn_lt"],
                sub=f"{bs.unit_sales} units sold · ${bs.gross_revenue:.0f} revenue" if bs else "",
                val_size=16,
            )
        )
        divider()

        # Peak hour
        self._kpi_lay.addLayout(
            self._kpi_card(
                "Peak hour",
                f"${s.peak_revenue:,.0f}",
                badge_text=s.peak_hour,
                badge_color=C["text"], badge_bg=C["border"],
                sub="Highest revenue block today",
            )
        )
        self._kpi_lay.addStretch()

    def _kpi_card(self, title, value, badge_text="", badge_color="",
                  badge_bg="", sub="", val_size=22):
        col = QVBoxLayout()
        col.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(lbl(title, size=11, color=C["sub"]))
        if badge_text:
            bdg = QLabel(badge_text)
            bdg.setStyleSheet(
                f"background:{badge_bg};color:{badge_color};"
                f"border-radius:5px;padding:1px 8px;"
                f"font-size:10px;font-weight:700;"
            )
            top.addWidget(bdg)
        top.addStretch()
        col.addLayout(top)

        val = lbl(value, bold=True, size=val_size)
        col.addWidget(val)
        col.addWidget(lbl(sub, size=10, color=C["sub"]))
        return col

    # ── Middle section: chart + best sellers ─────────────────────────────────
    def _build_middle_section(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 0)
        wl.setSpacing(16)

        # ── Chart card ──
        chart_card = card()
        chart_card.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:12px;"
            f"border:1px solid {C['border']};}}"
        )
        cl = QVBoxLayout(chart_card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(8)

        chart_hdr = QHBoxLayout()
        chart_hdr.addWidget(lbl("Hourly sales", bold=True, size=14))
        chart_hdr.addStretch()
        chart_hdr.addWidget(
            lbl("Revenue by hour across the active shift",
                size=10, color=C["sub"])
        )
        cl.addLayout(chart_hdr)

        self._bar_chart = BarChart()
        self._bar_chart.setMinimumHeight(200)
        cl.addWidget(self._bar_chart)

        wl.addWidget(chart_card, stretch=3)

        # ── Best sellers card ──
        bs_card = card()
        bs_card.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:12px;"
            f"border:1px solid {C['border']};}}"
        )
        bsl = QVBoxLayout(bs_card)
        bsl.setContentsMargins(20, 16, 20, 16)
        bsl.setSpacing(4)
        bsl.addWidget(lbl("Best sellers", bold=True, size=14))
        bsl.addWidget(lbl("Top products by units sold today",
                          size=10, color=C["sub"]))
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
        max_u   = sellers[0].unit_sales if sellers else 1
        for s in sellers:
            row = BestSellerRow(s, max_u)
            self._bs_container.addWidget(row)
            self._bs_container.addWidget(hline())

    # ── Sales log section ─────────────────────────────────────────────────────
    def _build_sales_log_section(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 20, 0)
        wl.setSpacing(10)

        log_hdr = QHBoxLayout()
        hdr_col = QVBoxLayout()
        hdr_col.setSpacing(2)
        hdr_col.addWidget(lbl("Sales Log", bold=True, size=15))
        self._log_sub = lbl("", size=10, color=C["sub"])
        hdr_col.addWidget(self._log_sub)
        log_hdr.addLayout(hdr_col)
        log_hdr.addStretch()

        self._log_date_badge = QLabel()
        self._log_date_badge.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:4px 12px;background:{C['white']};"
            f"color:{C['sub']};font-size:11px;"
        )
        log_hdr.addWidget(self._log_date_badge)
        wl.addLayout(log_hdr)

        log_card = card()
        log_card.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:12px;"
            f"border:1px solid {C['border']};}}"
        )
        lcl = QVBoxLayout(log_card)
        lcl.setContentsMargins(0, 0, 0, 0)

        self._log_table = SalesLogTable()
        lcl.addWidget(self._log_table)
        wl.addWidget(log_card)
        parent.addWidget(wrap)

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        self._status = QLabel()
        self._flash_lbl = QLabel()
        self._flash_lbl.setStyleSheet(f"color:{C['accent']};font-weight:600;")
        self.statusBar().addWidget(self._status)
        self.statusBar().addPermanentWidget(self._flash_lbl)

    # ── Refresh ───────────────────────────────────────────────────────────────
    def _refresh(self):
        s = self.sales
        self._refresh_kpi()
        self._bar_chart.set_data(s.hourly_data)
        self._refresh_best_sellers()
        self._log_sub.setText(
            f"{s.date_label} · {s.orders_today} items overview"
        )
        self._log_date_badge.setText(f"📅  {s.date_label}")
        self._log_table.populate(s.sales_log)
        self._status.setText(
            f"Net sales: ${s.net_sales:,.2f}  |  "
            f"Orders: {s.orders_today}  |  "
            f"Avg ticket: ${s.avg_ticket:.2f}  |  "
            f"Total profit: ${s.total_profit:.2f}  |  "
            f"Peak hour: {s.peak_hour} (${s.peak_revenue:,.0f})"
        )

    # ── Import dialog ─────────────────────────────────────────────────────────
    def _open_import(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Import Sales Data")
        dlg.setMinimumSize(520, 440)
        dlg.setStyleSheet(f"background:{C['white']};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        lay.addWidget(lbl("Import Sales Data", bold=True, size=16))
        lay.addWidget(lbl("Load hourly buckets and sales-log rows from CSV or SQL.",
                          color=C["sub"]))
        lay.addWidget(hline())

        def section(title, sub):
            box = QFrame()
            box.setStyleSheet(
                f"QFrame{{border:1px solid {C['border']};"
                f"border-radius:10px;background:{C['bg']};}}"
            )
            bl = QVBoxLayout(box)
            bl.setContentsMargins(16, 14, 16, 14)
            bl.setSpacing(8)
            bl.addWidget(lbl(title, bold=True, size=12))
            bl.addWidget(lbl(sub, size=10, color=C["sub"]))
            lay.addWidget(box)
            return bl

        def inp_style():
            return (
                f"border:1px solid {C['border']};border-radius:6px;"
                f"padding:5px 10px;background:{C['white']};font-size:12px;"
            )

        # CSV
        bl_csv = section("From CSV Files",
                         "One file for hourly (hour,revenue) · one for log rows")
        csv_row = QHBoxLayout()
        hourly_path = QLabel("No file selected")
        hourly_path.setStyleSheet(f"color:{C['sub']};font-size:11px;")
        log_path    = QLabel("No file selected")
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
        h_btn.setStyleSheet(
            f"background:{C['border']};border-radius:6px;"
            f"padding:6px 14px;border:none;"
        )
        h_btn.clicked.connect(lambda: pick(hourly_path, "_h_path"))

        l_btn = QPushButton("Log CSV…")
        l_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        l_btn.setStyleSheet(h_btn.styleSheet())
        l_btn.clicked.connect(lambda: pick(log_path, "_l_path"))

        csv_row.addWidget(h_btn)
        csv_row.addWidget(hourly_path)
        bl_csv.addLayout(csv_row)
        csv_row2 = QHBoxLayout()
        csv_row2.addWidget(l_btn)
        csv_row2.addWidget(log_path)
        bl_csv.addLayout(csv_row2)

        run_csv = QPushButton("Import CSV Files")
        run_csv.setCursor(Qt.CursorShape.PointingHandCursor)
        run_csv.setStyleSheet(
            f"background:{C['accent']};color:white;border-radius:6px;"
            f"padding:7px 18px;font-weight:700;border:none;"
        )

        def do_csv():
            hp = getattr(dlg, "_h_path", None)
            lp = getattr(dlg, "_l_path", None)
            if not hp or not lp:
                QMessageBox.warning(dlg, "Missing", "Select both CSV files.")
                return
            try:
                self.sales.load_from_csv(hp, lp)
                dlg.accept()
            except Exception as e:
                QMessageBox.critical(dlg, "Error", str(e))

        run_csv.clicked.connect(do_csv)
        bl_csv.addWidget(run_csv, alignment=Qt.AlignmentFlag.AlignLeft)

        # SQL
        bl_sql = section("From SQLite + Query",
                         "Two queries: one for hourly, one for log rows")
        dlg._db_path_edit = QLineEdit()
        dlg._db_path_edit.setPlaceholderText("Path to .db file…")
        dlg._db_path_edit.setStyleSheet(inp_style())

        br = QPushButton("Browse…")
        br.setCursor(Qt.CursorShape.PointingHandCursor)
        br.setStyleSheet(
            f"background:{C['border']};border-radius:6px;"
            f"padding:6px 14px;border:none;"
        )
        def pick_db():
            p, _ = QFileDialog.getOpenFileName(
                dlg, "Select DB", "",
                "SQLite (*.db *.sqlite *.sqlite3);;All (*)"
            )
            if p:
                dlg._db_path_edit.setText(p)
        br.clicked.connect(pick_db)

        db_row = QHBoxLayout()
        db_row.addWidget(dlg._db_path_edit)
        db_row.addWidget(br)
        bl_sql.addLayout(db_row)

        bl_sql.addWidget(lbl("Hourly query:", size=11))
        dlg._hq = QTextEdit()
        dlg._hq.setText("SELECT hour, revenue FROM hourly_sales")
        dlg._hq.setFixedHeight(52)
        dlg._hq.setStyleSheet(inp_style())
        bl_sql.addWidget(dlg._hq)

        bl_sql.addWidget(lbl("Log query:", size=11))
        dlg._lq = QTextEdit()
        dlg._lq.setText("SELECT * FROM sales_log")
        dlg._lq.setFixedHeight(52)
        dlg._lq.setStyleSheet(inp_style())
        bl_sql.addWidget(dlg._lq)

        run_sql = QPushButton("Run Queries & Import")
        run_sql.setCursor(Qt.CursorShape.PointingHandCursor)
        run_sql.setStyleSheet(
            f"background:{C['accent']};color:white;border-radius:6px;"
            f"padding:7px 18px;font-weight:700;border:none;"
        )

        def do_sql():
            db = dlg._db_path_edit.text().strip()
            hq = dlg._hq.toPlainText().strip()
            lq = dlg._lq.toPlainText().strip()
            if not db or not hq or not lq:
                QMessageBox.warning(dlg, "Missing", "Fill all fields.")
                return
            try:
                conn = sqlite3.connect(db)
                self.sales.load_from_query(conn, hq, lq)
                conn.close()
                dlg.accept()
            except Exception as e:
                QMessageBox.critical(dlg, "Error", str(e))

        run_sql.clicked.connect(do_sql)
        bl_sql.addWidget(run_sql, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addStretch()
        close = QPushButton("Close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"background:{C['border']};border-radius:7px;"
            f"padding:7px 20px;font-weight:600;border:none;"
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