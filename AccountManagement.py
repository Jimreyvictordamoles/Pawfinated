"""
PAWFFINATED – Account Management  (PyQt6 Edition)
==================================================
Drop this file in the same folder as all other Pawffinated files.

HOW OTHER SCREENS OPEN THIS FILE
─────────────────────────────────
Your Sidebar.py already routes between screens via subprocess (same way it
opens Dashboard.py, AccessControl.py, ActivityLog.py, Inventory.py, etc.)

Step 1 – Add "Account Management" to your Sidebar nav list, mapped to this file.
         That's all.  The sidebar's existing subprocess logic will launch it.

Step 2 – To open it on a staff-name click from ANY other screen, paste this
         one-liner wherever the name is clicked:
             import subprocess, sys
             subprocess.Popen([sys.executable, "AccountManagement.py"])

HOW LOG OUT WORKS
──────────────────
Clicking "Log Out" launches your existing login file (tries Login.py / login.py)
via subprocess and closes this window — same pattern the sidebar uses.

Run standalone:
    python AccountManagement.py
"""

from __future__ import annotations
import sys
from datetime import datetime, timedelta
from Sidebar import PawffinatedSidebar

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
    QToolBar, QDialog,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

# ── Palette — identical to every other Pawffinated screen ─────────────────────
C = dict(
    bg        = "#F7F5F0",
    sidebar   = "#FFFFFF",
    white     = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_lt = "#E8F4F0",
    accent_dk = "#1E5A45",
    warn      = "#E07B39",
    warn_lt   = "#FFF7ED",
    danger    = "#D94F4F",
    danger_lt = "#FEE2E2",
    ok        = "#059669",
    ok_lt     = "#D1FAE5",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    border    = "#E5E7EB",
    muted     = "#9CA3AF",
)

# ── Staff record ──────────────────────────────────────────────────────────────
STAFF = {
    "name":               "Sarah Jenkins",
    "role":               "Store Manager",
    "email":              "s.jenkins@pawffinated.co",
    "avatar":             "👩",
    "role_desc":          "Inventory lead and floor supervision",
    "role_detail":        "Handles opening checks, stock review, and team handoff.",
    "schedule":           "9:00 – 5:30 PM",
    "shift_hrs":          "8.5 hour shift",
    "clock_in_time":      "8:57 AM",
    "device":             "Front desk device",
    "this_week":          "38 scheduled hours",
    "week_sub":           "4 upcoming shifts and 1 active shift today.",
    "last_month":         "98% attendance rate",
    "month_sub":          "Reliable performance with strong punctuality.",
    "hours_worked":       "162h",
    "hours_sub":          "2h above scheduled target",
    "attendance":         "98%",
    "att_sub":            "1 late arrival across the month",
    "avg_shift":          "8.1h",
    "avg_sub":            "Consistent full-day coverage",
    "punctuality_on":     "21 / 22 shifts",
    "punctuality_late":   "1 late check-in",
    "punctuality_rating": "Very good",
    "completed":          "20 completed",
    "adjusted":           "2 adjusted",
    "completed_rating":   "Stable",
    "mgr_note1":          "Strong opener",
    "mgr_note2":          "Reliable handoffs",
    "mgr_note3":          "Recommended",
    "schedule_rows": [
        ("Today",     "9:00 AM – 5:30 PM",  "Opening shift · inventory review at 10:30 AM", "In progress"),
        ("Wednesday", "8:30 AM – 4:30 PM",  "Delivery intake and supplier call",             "Morning"),
        ("Thursday",  "10:00 AM – 6:00 PM", "Floor support and staff handoff",               "Mid shift"),
        ("Friday",    "9:00 AM – 5:00 PM",  "Peak-hour coverage and closing checklist",      "Full day"),
        ("Saturday",  "11:00 AM – 4:00 PM", "Weekend support and stock recount",             "Short shift"),
    ],
}

# ── Pre-seeded clock log (spans today → last year so every filter has data) ───
_N = datetime.now()

def _dt(days_ago, hour, minute=0):
    return (_N - timedelta(days=days_ago)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)

CLOCK_LOG: list[dict] = [
    {"date": _dt(0, 8, 57),  "type": "Clock In",  "device": "Front desk device", "duration": None},
    {"date": _dt(1, 9, 2),   "type": "Clock In",  "device": "Front desk device", "duration": None},
    {"date": _dt(1, 17, 31), "type": "Clock Out", "device": "Front desk device", "duration": "8h 29m"},
    {"date": _dt(2, 8, 45),  "type": "Clock In",  "device": "POS Terminal 02",   "duration": None},
    {"date": _dt(2, 17, 10), "type": "Clock Out", "device": "POS Terminal 02",   "duration": "8h 25m"},
    {"date": _dt(3, 10, 3),  "type": "Clock In",  "device": "Drive-Thru Pad 2",  "duration": None},
    {"date": _dt(3, 18, 0),  "type": "Clock Out", "device": "Drive-Thru Pad 2",  "duration": "7h 57m"},
    {"date": _dt(10, 9, 15), "type": "Clock In",  "device": "Front desk device", "duration": None},
    {"date": _dt(10, 17,45), "type": "Clock Out", "device": "Front desk device", "duration": "8h 30m"},
    {"date": _dt(35, 8, 50), "type": "Clock In",  "device": "Back Office Mac",   "duration": None},
    {"date": _dt(35, 17,20), "type": "Clock Out", "device": "Back Office Mac",   "duration": "8h 30m"},
    {"date": _dt(380, 9, 0), "type": "Clock In",  "device": "Front desk device", "duration": None},
    {"date": _dt(380,17, 0), "type": "Clock Out", "device": "Front desk device", "duration": "8h 0m"},
]


# ═══════════════════════════════════════════════════════════════════════════════
# Shared UI helpers  (same pattern as every other Pawffinated file)
# ═══════════════════════════════════════════════════════════════════════════════
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

def card_frame(radius=10) -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        f"QFrame{{background:{C['white']};border-radius:{radius}px;"
        f"border:1px solid {C['border']};}}"
    )
    return f

def make_btn(text, bg, fg="#FFFFFF", hover=None, height=36,
             radius=8, size=12, bold=True) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedHeight(height)
    b.setStyleSheet(
        f"QPushButton{{background:{bg};color:{fg};border:none;"
        f"border-radius:{radius}px;font-size:{size}px;"
        f"font-weight:{'700' if bold else '400'};padding:0 16px;}}"
        f"QPushButton:hover{{background:{hover or bg};}}"
    )
    return b

def outline_btn(text, fg=None, border=None, hover_bg=None,
                height=36, size=12) -> QPushButton:
    fg       = fg       or C["text"]
    border   = border   or C["border"]
    hover_bg = hover_bg or C["bg"]
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedHeight(height)
    b.setStyleSheet(
        f"QPushButton{{background:{C['white']};color:{fg};"
        f"border:1px solid {border};border-radius:8px;"
        f"font-size:{size}px;font-weight:600;padding:0 14px;}}"
        f"QPushButton:hover{{background:{hover_bg};}}"
    )
    return b

def status_pill(text, fg, bg) -> QLabel:
    w = QLabel(text)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(
        f"color:{fg};background:{bg};border-radius:5px;"
        f"padding:2px 10px;font-size:10px;font-weight:700;border:none;"
    )
    return w


# ═══════════════════════════════════════════════════════════════════════════════
# Time-range pill bar  (same style as ActivityLog.py)
# ═══════════════════════════════════════════════════════════════════════════════
class TimeRangeBar(QWidget):
    range_changed = pyqtSignal(str)
    RANGES = ["Today", "This Week", "This Month", "This Year", "All Time"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = "Today"
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._btns: dict[str, QPushButton] = {}
        for r in self.RANGES:
            btn = QPushButton(r)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, v=r: self._pick(v))
            self._btns[r] = btn
            lay.addWidget(btn)
        lay.addStretch()
        self._restyle()

    def _pick(self, r: str):
        self._active = r
        self._restyle()
        self.range_changed.emit(r)

    def _restyle(self):
        for name, btn in self._btns.items():
            if name == self._active:
                btn.setStyleSheet(
                    f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                    f"border:none;border-radius:6px;font-size:11px;"
                    f"font-weight:700;padding:0 12px;}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:{C['white']};color:{C['sub']};"
                    f"border:1px solid {C['border']};border-radius:6px;"
                    f"font-size:11px;padding:0 10px;}}"
                    f"QPushButton:hover{{background:{C['bg']};color:{C['text']};}}"
                )

    @property
    def active(self) -> str:
        return self._active


# ═══════════════════════════════════════════════════════════════════════════════
# Clock In / Out Log Dialog
# ═══════════════════════════════════════════════════════════════════════════════
class ClockLogDialog(QDialog):
    def __init__(self, log_entries: list[dict], parent=None):
        super().__init__(parent)
        self._log = log_entries
        self.setWindowTitle("Clock In / Out Log")
        self.setMinimumSize(700, 560)
        self.resize(760, 600)
        self.setStyleSheet(
            f"QDialog{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 18, 24, 18)
        lc = QVBoxLayout(); lc.setSpacing(3)
        lc.addWidget(lbl("Clock In / Out Log", bold=True, size=15))
        lc.addWidget(lbl(
            "Full history of clock-in and clock-out sessions.",
            size=10, color=C["sub"],
        ))
        hl.addLayout(lc)
        hl.addStretch()
        close_b = make_btn("Close", C["accent"], hover=C["accent_dk"])
        close_b.clicked.connect(self.accept)
        hl.addWidget(close_b)
        root.addWidget(hdr)

        # Time-range bar
        range_wrap = QWidget()
        range_wrap.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        rl = QHBoxLayout(range_wrap)
        rl.setContentsMargins(24, 10, 24, 10)
        rl.addWidget(lbl("View:", size=11, color=C["sub"]))
        rl.addSpacing(6)
        self._range_bar = TimeRangeBar()
        self._range_bar.range_changed.connect(self._refresh)
        rl.addWidget(self._range_bar)
        self._count_lbl = lbl("", size=10, color=C["sub"])
        rl.addWidget(self._count_lbl)
        root.addWidget(range_wrap)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C['bg']};}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:5px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )
        self._body = QWidget()
        self._body.setStyleSheet(f"background:{C['bg']};")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(20, 16, 20, 20)
        self._body_lay.setSpacing(12)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, stretch=1)

        self._refresh("Today")

    @staticmethod
    def _in_range(dt: datetime, label: str) -> bool:
        now = datetime.now()
        if label == "Today":
            return dt.date() == now.date()
        if label == "This Week":
            start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0)
            return dt >= start
        if label == "This Month":
            return dt.year == now.year and dt.month == now.month
        if label == "This Year":
            return dt.year == now.year
        return True

    def _refresh(self, label: str | None = None):
        label = label or self._range_bar.active

        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        visible = [e for e in self._log if self._in_range(e["date"], label)]
        self._count_lbl.setText(f"{len(visible)} of {len(self._log)} entries")

        if not visible:
            msg = lbl("No clock entries for this period.", size=12, color=C["sub"])
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._body_lay.addSpacing(40)
            self._body_lay.addWidget(msg)
            self._body_lay.addStretch()
            return

        table_card = card_frame(12)
        cl = QVBoxLayout(table_card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Column header
        col_hdr = QWidget()
        col_hdr.setStyleSheet(f"background:{C['bg']};")
        chl = QHBoxLayout(col_hdr)
        chl.setContentsMargins(16, 10, 16, 10)
        for col_text, stretch in [
            ("Date & Time", 3), ("Type", 1), ("Device", 2), ("Duration", 1)
        ]:
            chl.addWidget(lbl(col_text, size=10, bold=True, color=C["sub"]), stretch)
        cl.addWidget(col_hdr)
        cl.addWidget(hline())

        for i, entry in enumerate(visible):
            row_w = QWidget()
            row_w.setStyleSheet(
                f"background:{'#FAFAFA' if i % 2 == 1 else C['white']};"
            )
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(16, 12, 16, 12)
            rl.setSpacing(0)

            dt_str = entry["date"].strftime("%b %d, %Y  %I:%M %p").lstrip("0")
            rl.addWidget(lbl(dt_str, size=11), 3)

            is_in   = entry["type"] == "Clock In"
            pill_fg = C["ok"]    if is_in else C["danger"]
            pill_bg = C["ok_lt"] if is_in else C["danger_lt"]
            icon    = "→" if is_in else "←"
            pill_wrap = QWidget()
            pill_wrap.setStyleSheet("background:transparent;")
            pw = QHBoxLayout(pill_wrap)
            pw.setContentsMargins(0, 0, 0, 0)
            pw.addWidget(status_pill(f"{icon}  {entry['type']}", pill_fg, pill_bg))
            pw.addStretch()
            rl.addWidget(pill_wrap, 1)

            rl.addWidget(lbl(entry["device"], size=11), 2)

            dur       = entry.get("duration") or ("Active" if is_in else "—")
            dur_color = C["accent"] if dur == "Active" else C["text"]
            rl.addWidget(lbl(dur, size=11, bold=(dur == "Active"), color=dur_color), 1)

            cl.addWidget(row_w)
            if i < len(visible) - 1:
                cl.addWidget(hline())

        self._body_lay.addWidget(table_card)
        self._body_lay.addStretch()

    def add_entry(self, entry: dict):
        """Called by the panel when a new clock event occurs — refreshes view."""
        self._refresh()


# ═══════════════════════════════════════════════════════════════════════════════
# Account Management Panel
# ═══════════════════════════════════════════════════════════════════════════════
class AccountManagementPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._clocked_in  = False
        self._elapsed_sec = 0
        self._log         = list(CLOCK_LOG)

        self.setStyleSheet(f"background:{C['bg']};")

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_live_clock)
        self._clock_timer.start(1000)

        self._build()
        self._update_live_clock()

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Page header
        page_hdr = QWidget()
        page_hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        page_hdr.setFixedHeight(72)
        phl = QVBoxLayout(page_hdr)
        phl.setContentsMargins(28, 14, 28, 14)
        phl.setSpacing(3)
        phl.addWidget(lbl("Account Management", bold=True, size=20))
        phl.addWidget(lbl(
            "Manage staff details, working hours, daily attendance, "
            "and monthly performance from one place.",
            size=11, color=C["sub"],
        ))
        root.addWidget(page_hdr)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C['bg']};}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:5px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )
        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 24)
        bl.setSpacing(20)

        self._build_top_row(bl)
        self._build_schedule_calendar(bl)
        self._build_info(bl)
        self._build_work_summary(bl)

        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

    # ── Top row ───────────────────────────────────────────────────────────────
    def _build_top_row(self, parent: QVBoxLayout):
        row = QHBoxLayout()
        row.setSpacing(16)

        # Clock panel
        clock_card = card_frame(12)
        ccl = QVBoxLayout(clock_card)
        ccl.setContentsMargins(24, 20, 24, 20)
        ccl.setSpacing(10)

        status_row = QHBoxLayout()
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._set_dot(False)
        status_row.addWidget(self._dot)
        self._status_lbl = lbl("Not clocked in", size=11, color=C["sub"])
        status_row.addWidget(self._status_lbl)
        status_row.addStretch()
        status_row.addWidget(lbl("⏱  Shift ends 5:30 PM", size=11, color=C["sub"]))
        ccl.addLayout(status_row)

        ccl.addWidget(lbl(
            datetime.now().strftime("%A, %d %B").lstrip("0"),
            size=11,
            color=C["sub"]
        ))

        self._live_clock_lbl = lbl("", bold=True, size=32)
        ccl.addWidget(self._live_clock_lbl)

        sub_line = lbl(
            "Today she is on the opening shift and covering inventory review.",
            size=11, color=C["sub"],
        )
        sub_line.setWordWrap(True)
        ccl.addWidget(sub_line)

        # Stats: Clock in | Scheduled | Hours today
        stats_row = QHBoxLayout()
        stats_row.setSpacing(0)
        for i, (label_text, value, sub_text) in enumerate([
            ("Clock in",   STAFF["clock_in_time"], STAFF["device"]),
            ("Scheduled",  STAFF["schedule"],      STAFF["shift_hrs"]),
            ("Hours today","2h 45m",               "On track for full shift"),
        ]):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(lbl(label_text, size=10, color=C["sub"]))
            col.addWidget(lbl(value, bold=True, size=13))
            col.addWidget(lbl(sub_text, size=10, color=C["sub"]))
            stats_row.addLayout(col)
            if i < 2:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.VLine)
                div.setStyleSheet(
                    f"background:{C['border']};border:none;margin:0 20px;"
                )
                stats_row.addWidget(div)
        ccl.addLayout(stats_row)

        ccl.addWidget(hline())

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._clock_btn = make_btn(
            "🟢  Clock In", C["accent"], hover=C["accent_dk"], height=38
        )
        self._clock_btn.clicked.connect(self._toggle_clock)
        btn_row.addWidget(self._clock_btn)

        log_btn = outline_btn("🗒  Clock In / Out Log", height=38)
        log_btn.clicked.connect(self._open_log)
        btn_row.addWidget(log_btn)

        logout_btn = outline_btn(
            "→  Log Out",
            fg=C["danger"], border=C["danger"], hover_bg=C["danger_lt"],
            height=38,
        )
        logout_btn.clicked.connect(self._log_out)
        btn_row.addWidget(logout_btn)

        ccl.addLayout(btn_row)
        row.addWidget(clock_card, stretch=3)

        # Profile card
        profile_card = card_frame(12)
        profile_card.setMinimumWidth(220)
        pcl = QVBoxLayout(profile_card)
        pcl.setContentsMargins(20, 20, 20, 20)
        pcl.setSpacing(12)

        av_row = QHBoxLayout()
        av_row.setSpacing(12)
        av = QLabel(STAFF["avatar"])
        av.setFixedSize(48, 48)
        av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setStyleSheet(
            "background:#E5EDEA;border-radius:24px;font-size:22px;border:none;"
        )
        av_row.addWidget(av)
        nc = QVBoxLayout(); nc.setSpacing(2)
        nc.addWidget(lbl(STAFF["name"], bold=True, size=13))
        nc.addWidget(lbl(STAFF["role"], size=10, color=C["sub"]))
        av_row.addLayout(nc)
        pcl.addLayout(av_row)
        pcl.addWidget(hline())

        for icon, period, value, sub in [
            ("💼", "Role",       STAFF["role_desc"],  STAFF["role_detail"]),
            ("📅", "This week",  STAFF["this_week"],  STAFF["week_sub"]),
            ("📊", "Last month", STAFF["last_month"], STAFF["month_sub"]),
        ]:
            item_w = QWidget()
            item_w.setStyleSheet(
                f"background:{C['accent_lt']};border-radius:8px;"
            )
            il = QHBoxLayout(item_w)
            il.setContentsMargins(10, 10, 10, 10)
            il.setSpacing(10)
            ic = QLabel(icon)
            ic.setFixedSize(28, 28)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic.setStyleSheet(
                f"background:{C['white']};border-radius:6px;font-size:14px;border:none;"
            )
            il.addWidget(ic)
            tc = QVBoxLayout(); tc.setSpacing(2)
            tc.addWidget(lbl(period, size=9, color=C["sub"]))
            tc.addWidget(lbl(value, bold=True, size=11))
            tc.addWidget(lbl(sub, size=9, color=C["sub"]))
            il.addLayout(tc)
            pcl.addWidget(item_w)

        row.addWidget(profile_card, stretch=2)
        parent.addLayout(row)

    # ── Schedule + Calendar ───────────────────────────────────────────────────
    def _build_schedule_calendar(self, parent: QVBoxLayout):
        row = QHBoxLayout(); row.setSpacing(16)

        # Schedule card
        sched_card = card_frame(12)
        scl = QVBoxLayout(sched_card)
        scl.setContentsMargins(20, 16, 20, 16)
        scl.setSpacing(8)

        sh = QHBoxLayout()
        sc = QVBoxLayout(); sc.setSpacing(2)
        sc.addWidget(lbl("Schedule", bold=True, size=14))
        sc.addWidget(lbl(
            "Upcoming shifts and what Sarah is expected to cover.",
            size=10, color=C["sub"],
        ))
        sh.addLayout(sc); sh.addStretch()
        sh.addWidget(lbl("🗓  38 hrs this week", size=10, color=C["sub"]))
        scl.addLayout(sh)
        scl.addWidget(hline())

        for day, time, note, tag in STAFF["schedule_rows"]:
            rw = QWidget(); rw.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 8, 0, 8); rl.setSpacing(12)
            day_lbl = lbl(day, bold=(day == "Today"), size=11)
            day_lbl.setFixedWidth(80)
            rl.addWidget(day_lbl)
            tc = QVBoxLayout(); tc.setSpacing(2)
            tc.addWidget(lbl(time, bold=True, size=11))
            tc.addWidget(lbl(note, size=10, color=C["sub"]))
            rl.addLayout(tc, stretch=1)
            tag_fg = C["accent"] if day == "Today" else C["sub"]
            tag_bg = C["accent_lt"] if day == "Today" else C["border"]
            rl.addWidget(status_pill(tag, tag_fg, tag_bg))
            scl.addWidget(rw); scl.addWidget(hline())

        row.addWidget(sched_card, stretch=3)

        # Calendar card
        cal_card = card_frame(12)
        cal_card.setMinimumWidth(220)
        cll = QVBoxLayout(cal_card)
        cll.setContentsMargins(16, 16, 16, 16)
        cll.setSpacing(10)

        ch = QHBoxLayout()
        ch.addWidget(lbl("Calendar", bold=True, size=14)); ch.addStretch()
        ch.addWidget(lbl("🗓  5 shift days", size=10, color=C["sub"]))
        cll.addLayout(ch)
        cll.addWidget(lbl("October schedule overview", size=10, color=C["sub"]))

        dow_row = QHBoxLayout(); dow_row.setSpacing(0)
        for d in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]:
            dl = lbl(d, size=9, color=C["sub"])
            dl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dow_row.addWidget(dl, 1)
        cll.addLayout(dow_row)

        grid = QGridLayout(); grid.setSpacing(2)
        today_day      = 8
        scheduled_days = {8, 10, 11, 14, 15, 17, 21, 22}
        start_col      = 3   # Oct 1 is Thursday
        col, row_idx, day_num = start_col, 0, 1

        while day_num <= 31:
            if day_num == 1:
                for c in range(start_col):
                    grid.addWidget(QLabel(""), row_idx, c)
            cell = QWidget(); cell.setFixedSize(28, 28)
            cl2 = QVBoxLayout(cell)
            cl2.setContentsMargins(0, 0, 0, 0); cl2.setSpacing(0)
            day_label = QLabel(str(day_num))
            day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            day_label.setFixedSize(24, 24)
            if day_num == today_day:
                day_label.setStyleSheet(
                    f"background:{C['accent']};color:#FFFFFF;"
                    f"border-radius:12px;font-size:11px;font-weight:700;"
                )
            else:
                color = C["text"] if day_num in scheduled_days else C["muted"]
                day_label.setStyleSheet(f"color:{color};font-size:11px;")
            cl2.addWidget(day_label, alignment=Qt.AlignmentFlag.AlignCenter)
            if day_num in scheduled_days and day_num != today_day:
                dot = QLabel("•"); dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
                dot.setStyleSheet(
                    f"color:{C['accent']};font-size:8px;background:transparent;"
                )
                dot.setFixedHeight(8); cl2.addWidget(dot)
            grid.addWidget(cell, row_idx, col)
            col += 1
            if col == 7: col = 0; row_idx += 1
            day_num += 1

        cll.addLayout(grid)

        leg = QHBoxLayout(); leg.setSpacing(12)
        for dot_c, leg_text in [(C["accent"], "Scheduled shift"), (C["ok"], "Today")]:
            lw = QHBoxLayout(); lw.setSpacing(4)
            d = QLabel("●")
            d.setStyleSheet(f"color:{dot_c};font-size:10px;background:transparent;")
            lw.addWidget(d); lw.addWidget(lbl(leg_text, size=10, color=C["sub"]))
            leg.addLayout(lw)
        leg.addStretch(); cll.addLayout(leg)

        row.addWidget(cal_card, stretch=2)
        parent.addLayout(row)

    # ── Info section ──────────────────────────────────────────────────────────
    def _build_info(self, parent: QVBoxLayout):
        hdr = QVBoxLayout(); hdr.setSpacing(2)
        hdr.addWidget(lbl("Info", bold=True, size=15))
        hdr.addWidget(lbl("Key staff details and current work context.",
                          size=10, color=C["sub"]))
        parent.addLayout(hdr)

        grid = QGridLayout(); grid.setSpacing(12)
        cells = [
            ("Role",           STAFF["role"],
             "Front counter, floor supervision, and opening checks."),
            ("Contact",        STAFF["email"],
             "Preferred contact for scheduling and shift approvals."),
            ("Employment",     "Started Feb 2022",
             "Retail Operations team · Tue–Sat regular availability."),
            ("Current status", "Clocked in",
             f"Checked in at {STAFF['clock_in_time']} from the front desk device."),
        ]
        for i, (field, val, sub_val) in enumerate(cells):
            c = card_frame(8)
            cl = QVBoxLayout(c)
            cl.setContentsMargins(16, 14, 16, 14); cl.setSpacing(4)
            cl.addWidget(lbl(field, size=10, color=C["sub"]))
            cl.addWidget(lbl(val, bold=True, size=13))
            cl.addWidget(lbl(sub_val, size=10, color=C["sub"]))
            grid.addWidget(c, i // 2, i % 2)
        parent.addLayout(grid)

    # ── Work summary ──────────────────────────────────────────────────────────
    def _build_work_summary(self, parent: QVBoxLayout):
        hdr_row = QHBoxLayout()
        hc = QVBoxLayout(); hc.setSpacing(2)
        hc.addWidget(lbl("Work summary · Last month", bold=True, size=15))
        hc.addWidget(lbl(
            "A simple monthly monitor of time, attendance, and performance consistency.",
            size=10, color=C["sub"],
        ))
        hdr_row.addLayout(hc); hdr_row.addStretch()
        hdr_row.addWidget(outline_btn("📊  September overview", height=32, size=11))
        parent.addLayout(hdr_row)

        # KPI strip
        kpi_card = card_frame(12)
        kpi_lay = QHBoxLayout(kpi_card)
        kpi_lay.setContentsMargins(0, 0, 0, 0); kpi_lay.setSpacing(0)
        for i, (label_text, val, sub) in enumerate([
            ("Hours worked",    STAFF["hours_worked"], STAFF["hours_sub"]),
            ("Attendance rate", STAFF["attendance"],   STAFF["att_sub"]),
            ("Avg shift length",STAFF["avg_shift"],    STAFF["avg_sub"]),
        ]):
            col = QVBoxLayout()
            col.setContentsMargins(24, 20, 24, 20); col.setSpacing(4)
            col.addWidget(lbl(label_text, size=10, color=C["sub"]))
            col.addWidget(lbl(val, bold=True, size=28))
            col.addWidget(lbl(sub, size=10, color=C["muted"]))
            kpi_lay.addLayout(col)
            if i < 2:
                div = QFrame(); div.setFrameShape(QFrame.Shape.VLine)
                div.setStyleSheet(f"background:{C['border']};border:none;")
                kpi_lay.addWidget(div)
        parent.addWidget(kpi_card)

        # Performance rows
        perf_card = card_frame(12)
        pl = QVBoxLayout(perf_card)
        pl.setContentsMargins(20, 4, 20, 4); pl.setSpacing(0)

        def _perf_row(title, subtitle, *values):
            rw = QWidget(); rw.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 14, 0, 14); rl.setSpacing(12)
            tc = QVBoxLayout(); tc.setSpacing(2)
            tc.addWidget(lbl(title, bold=True, size=12))
            tc.addWidget(lbl(subtitle, size=10, color=C["sub"]))
            rl.addLayout(tc, stretch=1)
            for v in values:
                vl = lbl(v, size=11)
                vl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                rl.addWidget(vl)
            return rw

        def _tag_row(title, subtitle, *tags):
            rw = QWidget(); rw.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 14, 0, 14); rl.setSpacing(12)
            tc = QVBoxLayout(); tc.setSpacing(2)
            tc.addWidget(lbl(title, bold=True, size=12))
            tc.addWidget(lbl(subtitle, size=10, color=C["sub"]))
            rl.addLayout(tc, stretch=1)
            for tag in tags:
                rl.addWidget(status_pill(tag, C["accent"], C["accent_lt"]))
            return rw

        pl.addWidget(_perf_row(
            "Punctuality", "On-time arrivals for scheduled shifts",
            STAFF["punctuality_on"], STAFF["punctuality_late"], STAFF["punctuality_rating"],
        ))
        pl.addWidget(hline())
        pl.addWidget(_perf_row(
            "Completed shifts", "Finished planned hours without early clock-out",
            STAFF["completed"], STAFF["adjusted"], STAFF["completed_rating"],
        ))
        pl.addWidget(hline())
        pl.addWidget(_tag_row(
            "Manager note", "General month-end performance observation",
            STAFF["mgr_note1"], STAFF["mgr_note2"], STAFF["mgr_note3"],
        ))
        parent.addWidget(perf_card)

    # ═══════════════════════════════════════════════════════════════════════════
    # Clock logic
    # ═══════════════════════════════════════════════════════════════════════════
    def _set_dot(self, clocked_in: bool):
        color = C["ok"] if clocked_in else C["muted"]
        self._dot.setStyleSheet(
            f"background:{color};border-radius:4px;border:none;"
        )

    def _update_live_clock(self):
        self._live_clock_lbl.setText(
        datetime.now().strftime("%I:%M:%S %p").lstrip("0")
    )

    def _tick_elapsed(self):
        self._elapsed_sec += 1
        h, rem = divmod(self._elapsed_sec, 3600)
        m, s   = divmod(rem, 60)
        self._status_lbl.setText(
            f"Clocked in · {h}h {m:02d}m {s:02d}s elapsed"
        )

    def _toggle_clock(self):
        if not self._clocked_in:
            # Clock IN
            self._clocked_in  = True
            self._elapsed_sec = 0
            self._elapsed_timer.start(1000)
            self._set_dot(True)
            self._status_lbl.setText("Clocked in · 0h 00m 00s elapsed")
            self._clock_btn.setText("🔴  Clock Out")
            self._clock_btn.setStyleSheet(
                f"QPushButton{{background:{C['danger']};color:#FFFFFF;"
                f"border:none;border-radius:8px;font-size:12px;"
                f"font-weight:700;padding:0 16px;}}"
                f"QPushButton:hover{{background:#B03A3A;}}"
            )
            self._log.insert(0, {
                "date":     datetime.now(),
                "type":     "Clock In",
                "device":   "Front desk device",
                "duration": None,
            })
        else:
            # Clock OUT
            self._clocked_in = False
            h, rem  = divmod(self._elapsed_sec, 3600)
            m, _    = divmod(rem, 60)
            dur_str = f"{h}h {m:02d}m"
            self._elapsed_timer.stop()
            self._set_dot(False)
            self._status_lbl.setText(
                f"Not clocked in · Last session: {dur_str}"
            )
            self._clock_btn.setText("🟢  Clock In")
            self._clock_btn.setStyleSheet(
                f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                f"border:none;border-radius:8px;font-size:12px;"
                f"font-weight:700;padding:0 16px;}}"
                f"QPushButton:hover{{background:{C['accent_dk']};}}"
            )
            for e in self._log:
                if e["type"] == "Clock In" and e.get("duration") is None:
                    e["duration"] = dur_str
                    break
            self._log.insert(0, {
                "date":     datetime.now(),
                "type":     "Clock Out",
                "device":   "Front desk device",
                "duration": dur_str,
            })

    def _open_log(self):
        ClockLogDialog(self._log, self).exec()

    def _log_out(self):
        """Close this window and re-launch your login file."""
        import subprocess
        for candidate in ["Login.py", "login.py", "LogIn.py"]:
            try:
                subprocess.Popen([sys.executable, candidate])
                break
            except FileNotFoundError:
                continue
        top = self.window()
        if top:
            top.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Main Window  — identical structure to Dashboard, AccessControl, etc.
# ═══════════════════════════════════════════════════════════════════════════════
class AccountManagementWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Account Management")
        self.resize(1200, 820)
        self.setMinimumSize(960, 660)
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
        logo.setStyleSheet(
            f"font-weight:800;font-size:14px;color:{C['accent']};"
        )
        tb.addWidget(logo)
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)
        date_lbl = QLabel(
            f"📅  Today · {datetime.now().strftime('%b %d').lstrip('0')}  ·  Account Management"
        )
        date_lbl.setStyleSheet(
            f"color:{C['sub']};font-size:12px;"
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:4px 12px;background:{C['white']};"
        )
        tb.addWidget(date_lbl)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar — same as every other Pawffinated screen
        sidebar = PawffinatedSidebar(active_page="Account Management")
        root.addWidget(sidebar)

        # Account management content
        root.addWidget(AccountManagementPanel(), stretch=1)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Pawffinated Account Management")
    win = AccountManagementWindow()
    win.show()
    sys.exit(app.exec())