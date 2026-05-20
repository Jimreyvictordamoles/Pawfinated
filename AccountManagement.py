"""
PAWFFINATED – Account Management  (PyQt6 + PostgreSQL)
=======================================================
Accessible by ALL logged-in staff.

Each user sees and manages their own profile, schedule, and clock in/out.
Clock events are recorded with a foreign key to the users table.

Admin-only panel is a separate file: StaffAdminPanel.py
"""

from __future__ import annotations
import sys, os
from datetime import datetime, timedelta
from Db_connection import get_staff_db, get_auth_db, close_db, db_info, StaffDB
from Sidebar import PawffinatedSidebar

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
    QToolBar, QDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

# ── Palette ───────────────────────────────────────────────────────────────────
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

# ── Session — read environment variables set by Login.py on successful login ──
_USER_EMAIL    = os.environ.get("PAWFF_USER_EMAIL", "")
_USER_NAME     = os.environ.get("PAWFF_USER_NAME", "Unknown")
_USER_ROLE     = os.environ.get("PAWFF_USER_ROLE", "")
_USER_IS_ADMIN = os.environ.get("PAWFF_USER_IS_ADMIN", "0") == "1"
_USER_ID       = int(os.environ.get("PAWFF_USER_DB_ID", "0"))
ACTIVE_STAFF_ID = int(os.environ.get("STAFF_ID", "1"))


# ── UI helpers ────────────────────────────────────────────────────────────────
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


# ── Time-range pill bar ───────────────────────────────────────────────────────
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


# ── Clock In / Out Log Dialog ─────────────────────────────────────────────────
class ClockLogDialog(QDialog):
    """
    Displays clock events loaded from the DB, joined with user data.
    Shows exact date/time, user name, role, device, and duration.
    """

    def __init__(self, sdb: StaffDB, staff_id: int,
                 user_id: int | None = None, parent=None):
        super().__init__(parent)
        self._sdb      = sdb
        self._staff_id = staff_id
        self._user_id  = user_id
        self.setWindowTitle("Clock In / Out Log")
        self.setMinimumSize(860, 580)
        self.resize(920, 640)
        self.setStyleSheet(
            f"QDialog{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        self._build()

    # ── Load from DB — prefer user_id join, fall back to staff_id ────────────
    def _load_entries(self) -> list[dict]:
        if self._user_id:
            rows = self._sdb.get_clock_log_by_user(self._user_id)
        else:
            rows = self._sdb.get_clock_log(self._staff_id)
        entries = []
        for r in rows:
            first = r.get("first_name") or ""
            last  = r.get("last_name")  or ""
            full  = f"{first} {last}".strip() or _USER_NAME
            entries.append({
                "date":       r["timestamp"],
                "type":       r["event_type"],
                "device":     r["device"],
                "duration":   r.get("duration") or "—",
                "user_name":  full,
                "user_role":  r.get("user_role") or _USER_ROLE,
                "user_email": r.get("user_email") or _USER_EMAIL,
            })
        return entries

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
        lc = QVBoxLayout()
        lc.setSpacing(3)
        lc.addWidget(lbl("Clock In / Out Log", bold=True, size=15))
        lc.addWidget(lbl(
            "Full history of clock-in and clock-out sessions — live from database.",
            size=10, color=C["sub"],
        ))
        hl.addLayout(lc)
        hl.addStretch()

        reload_b = make_btn("↻  Refresh", C["accent_lt"], fg=C["accent"],
                            hover=C["accent_lt"], height=32, size=11)
        reload_b.clicked.connect(self.reload)
        hl.addWidget(reload_b)

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
        return True  # "All Time"

    def reload(self):
        """Re-fetch from DB and repaint the current range."""
        self._refresh(self._range_bar.active)

    def _refresh(self, label: str | None = None):
        label = label or self._range_bar.active

        # Clear body
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        all_entries = self._load_entries()
        visible = [e for e in all_entries if self._in_range(e["date"], label)]
        self._count_lbl.setText(f"{len(visible)} of {len(all_entries)} entries")

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

        # Column headers — now includes User and Role columns
        col_hdr = QWidget()
        col_hdr.setStyleSheet(f"background:{C['bg']};")
        chl = QHBoxLayout(col_hdr)
        chl.setContentsMargins(16, 10, 16, 10)
        for col_text, stretch in [
            ("Date & Time", 3), ("User", 2), ("Role", 2),
            ("Type", 1), ("Device", 2), ("Duration", 1)
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

            # Exact date and time (seconds included)
            dt_str = entry["date"].strftime("%b %d, %Y  %I:%M:%S %p").lstrip("0")
            rl.addWidget(lbl(dt_str, size=11), 3)

            rl.addWidget(lbl(entry.get("user_name", _USER_NAME), size=11), 2)
            rl.addWidget(lbl(entry.get("user_role", _USER_ROLE), size=11,
                             color=C["sub"]), 2)

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


# ── Account Management Panel ──────────────────────────────────────────────────
class AccountManagementPanel(QWidget):
    """
    Main content panel — accessible by ANY logged-in staff member.
    Shows the current user's own profile, schedule, and clock in/out.
    Clock events record the exact timestamp and FK to users.id.
    """

    def __init__(self, staff_id: int = ACTIVE_STAFF_ID, parent=None):
        super().__init__(parent)
        self._staff_id    = staff_id
        self._sdb         = get_staff_db()
        self._clocked_in  = False
        self._elapsed_sec = 0

        # ── Resolve user_id from users table via email ────────────────────────
        self._user_id: int | None = _USER_ID if _USER_ID > 0 else None
        if self._user_id is None and _USER_EMAIL:
            try:
                adb = get_auth_db()
                all_users = adb.get_all_users()
                matched = [u for u in all_users
                           if u["email"].lower() == _USER_EMAIL.lower()]
                if matched:
                    self._user_id = matched[0]["id"]
            except Exception:
                pass

        # ── Load staff profile from DB ─────────────────────────────────────
        self._staff = self._sdb.get_staff(staff_id)
        if not self._staff:
            # If no staff row, create a lightweight profile from session vars
            self._staff = {
                "name":     _USER_NAME,
                "email":    _USER_EMAIL,
                "role":     _USER_ROLE,
                "device":   "Desktop",
                "schedule": "9:00 AM – 5:30 PM",
                "shift_hrs": "8.5h",
                "avatar":   "👤",
            }

        # ── Restore clocked-in state — prefer user_id lookup ─────────────────
        last_event = None
        if self._user_id:
            last_event = self._sdb.get_last_clock_event_by_user(self._user_id)
        if last_event is None:
            last_event = self._sdb.get_last_clock_event(staff_id)

        if last_event and last_event["event_type"] == "Clock In":
            self._clocked_in  = True
            delta = datetime.now() - last_event["timestamp"].replace(tzinfo=None)
            self._elapsed_sec = int(delta.total_seconds())

        self.setStyleSheet(f"background:{C['bg']};")

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_live_clock)
        self._clock_timer.start(1000)

        self._build()
        self._update_live_clock()

        if self._clocked_in:
            self._elapsed_timer.start(1000)
            self._sync_clock_ui()

    # ── Convenience getter ────────────────────────────────────────────────────
    def _s(self, key: str, fallback: str = "—") -> str:
        """Safe dict getter with fallback for missing/None DB values."""
        return str(self._staff.get(key) or fallback)

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

    # ── Top row (clock panel + profile card) ─────────────────────────────────
    def _build_top_row(self, parent: QVBoxLayout):
        row = QHBoxLayout()
        row.setSpacing(16)

        # ── Clock panel ───────────────────────────────────────────────────────
        clock_card = card_frame(12)
        ccl = QVBoxLayout(clock_card)
        ccl.setContentsMargins(24, 20, 24, 20)
        ccl.setSpacing(10)

        status_row = QHBoxLayout()
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._set_dot(self._clocked_in)
        status_row.addWidget(self._dot)
        self._status_lbl = lbl(
            "Clocked in" if self._clocked_in else "Not clocked in",
            size=11, color=C["sub"],
        )
        status_row.addWidget(self._status_lbl)
        status_row.addStretch()
        status_row.addWidget(
            lbl(f"⏱  Shift ends {self._s('schedule', '5:30 PM').split('–')[-1].strip()}",
                size=11, color=C["sub"])
        )
        ccl.addLayout(status_row)

        ccl.addWidget(lbl(
            datetime.now().strftime("%A, %d %B").lstrip("0"),
            size=11, color=C["sub"],
        ))

        self._live_clock_lbl = lbl("", bold=True, size=32)
        ccl.addWidget(self._live_clock_lbl)

        sub_line = lbl(
            f"Today {self._s('name')} is on the opening shift and covering "
            "inventory review.",
            size=11, color=C["sub"],
        )
        sub_line.setWordWrap(True)
        ccl.addWidget(sub_line)

        # Stats strip
        stats_row = QHBoxLayout()
        stats_row.setSpacing(0)
        for i, (label_text, value, sub_text) in enumerate([
            ("Clock in",   self._s("clock_in_time"), self._s("device")),
            ("Scheduled",  self._s("schedule"),      self._s("shift_hrs")),
            ("Hours today","2h 45m",                 "On track for full shift"),
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
            "🟢  Clock In" if not self._clocked_in else "🔴  Clock Out",
            C["accent"] if not self._clocked_in else C["danger"],
            hover=C["accent_dk"] if not self._clocked_in else "#B03A3A",
            height=38,
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

        # ── Profile card ──────────────────────────────────────────────────────
        profile_card = card_frame(12)
        profile_card.setMinimumWidth(220)
        pcl = QVBoxLayout(profile_card)
        pcl.setContentsMargins(20, 20, 20, 20)
        pcl.setSpacing(12)

        av_row = QHBoxLayout()
        av_row.setSpacing(12)
        av = QLabel(self._s("avatar", "👤"))
        av.setFixedSize(48, 48)
        av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setStyleSheet(
            "background:#E5EDEA;border-radius:24px;font-size:22px;border:none;"
        )
        av_row.addWidget(av)
        nc = QVBoxLayout()
        nc.setSpacing(2)
        nc.addWidget(lbl(self._s("name"), bold=True, size=13))
        nc.addWidget(lbl(self._s("role"), size=10, color=C["sub"]))
        av_row.addLayout(nc)
        pcl.addLayout(av_row)
        pcl.addWidget(hline())

        for icon, period, value, sub in [
            ("💼", "Role",       self._s("role_desc"),  self._s("role_detail")),
            ("📅", "This week",  self._s("this_week"),  self._s("week_sub")),
            ("📊", "Last month", self._s("last_month"), self._s("month_sub")),
        ]:
            item_w = QWidget()
            item_w.setStyleSheet(f"background:{C['accent_lt']};border-radius:8px;")
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
            tc = QVBoxLayout()
            tc.setSpacing(2)
            tc.addWidget(lbl(period, size=9, color=C["sub"]))
            tc.addWidget(lbl(value, bold=True, size=11))
            tc.addWidget(lbl(sub, size=9, color=C["sub"]))
            il.addLayout(tc)
            pcl.addWidget(item_w)

        row.addWidget(profile_card, stretch=2)
        parent.addLayout(row)

    # ── Schedule + Calendar ───────────────────────────────────────────────────
    def _build_schedule_calendar(self, parent: QVBoxLayout):
        row = QHBoxLayout()
        row.setSpacing(16)

        # Load schedule from DB
        schedule_rows = self._sdb.get_staff_schedule(self._staff_id)
        if not schedule_rows:
            schedule_rows = []

        # Schedule card
        sched_card = card_frame(12)
        scl = QVBoxLayout(sched_card)
        scl.setContentsMargins(20, 16, 20, 16)
        scl.setSpacing(8)

        sh = QHBoxLayout()
        sc = QVBoxLayout()
        sc.setSpacing(2)
        sc.addWidget(lbl("Schedule", bold=True, size=14))
        sc.addWidget(lbl(
            f"Upcoming shifts and what {self._s('name')} is expected to cover.",
            size=10, color=C["sub"],
        ))
        sh.addLayout(sc)
        sh.addStretch()
        sh.addWidget(lbl(f"🗓  {self._s('this_week')}", size=10, color=C["sub"]))
        scl.addLayout(sh)
        scl.addWidget(hline())

        if schedule_rows:
            for sched in schedule_rows:
                rw = QWidget()
                rw.setStyleSheet("background:transparent;")
                rl = QHBoxLayout(rw)
                rl.setContentsMargins(0, 8, 0, 8)
                rl.setSpacing(12)
                day_lbl = lbl(sched.get("day", "—"), bold=True, size=11)
                day_lbl.setFixedWidth(80)
                rl.addWidget(day_lbl)
                tc = QVBoxLayout()
                tc.setSpacing(2)
                tc.addWidget(lbl(sched.get("time", "—"), bold=True, size=11))
                tc.addWidget(lbl(sched.get("note", "—"), size=10, color=C["sub"]))
                rl.addLayout(tc, stretch=1)
                tag = sched.get("tag", "—")
                rl.addWidget(status_pill(tag, C["accent"], C["accent_lt"]))
                scl.addWidget(rw)
                scl.addWidget(hline())
        else:
            msg = lbl("No scheduled shifts.", size=11, color=C["sub"])
            scl.addWidget(msg)

        row.addWidget(sched_card, stretch=3)

        # Calendar card (simplified)
        cal_card = card_frame(12)
        cal_card.setMinimumWidth(220)
        cll = QVBoxLayout(cal_card)
        cll.setContentsMargins(16, 16, 16, 16)
        cll.setSpacing(10)

        ch = QHBoxLayout()
        ch.addWidget(lbl("Calendar", bold=True, size=14))
        ch.addStretch()
        ch.addWidget(lbl("🗓  Shifts", size=10, color=C["sub"]))
        cll.addLayout(ch)
        cll.addWidget(lbl("Current month overview", size=10, color=C["sub"]))

        cal_note = lbl("Calendar view coming soon", size=11, color=C["sub"])
        cal_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cll.addSpacing(40)
        cll.addWidget(cal_note)
        cll.addStretch()

        row.addWidget(cal_card, stretch=2)
        parent.addLayout(row)

    # ── Info section ──────────────────────────────────────────────────────────
    def _build_info(self, parent: QVBoxLayout):
        hdr = QVBoxLayout()
        hdr.setSpacing(2)
        hdr.addWidget(lbl("Info", bold=True, size=15))
        hdr.addWidget(lbl("Key staff details and current work context.",
                          size=10, color=C["sub"]))
        parent.addLayout(hdr)

        grid = QGridLayout()
        grid.setSpacing(12)
        cells = [
            ("Role",           self._s("role"),
             self._s("role_desc")),
            ("Contact",        self._s("email"),
             "Preferred contact for scheduling and shift approvals."),
            ("Employment",     f"Started {self._s('started_on')}",
             "Retail Operations team · Tue–Sat regular availability."),
            ("Current status", "Clocked in" if self._clocked_in else "Not clocked in",
             f"Device: {self._s('device')}"),
        ]
        for i, (field, val, sub_val) in enumerate(cells):
            c = card_frame(8)
            cl = QVBoxLayout(c)
            cl.setContentsMargins(16, 14, 16, 14)
            cl.setSpacing(4)
            cl.addWidget(lbl(field, size=10, color=C["sub"]))
            cl.addWidget(lbl(val, bold=True, size=13))
            cl.addWidget(lbl(sub_val, size=10, color=C["sub"]))
            grid.addWidget(c, i // 2, i % 2)
        parent.addLayout(grid)

    # ── Work summary ──────────────────────────────────────────────────────────
    def _build_work_summary(self, parent: QVBoxLayout):
        hdr_row = QHBoxLayout()
        hc = QVBoxLayout()
        hc.setSpacing(2)
        hc.addWidget(lbl("Work summary · Last month", bold=True, size=15))
        hc.addWidget(lbl(
            "A simple monthly monitor of time, attendance, and performance consistency.",
            size=10, color=C["sub"],
        ))
        hdr_row.addLayout(hc)
        hdr_row.addStretch()
        hdr_row.addWidget(outline_btn("📊  Monthly overview", height=32, size=11))
        parent.addLayout(hdr_row)

        # KPI strip
        kpi_card = card_frame(12)
        kpi_lay = QHBoxLayout(kpi_card)
        kpi_lay.setContentsMargins(0, 0, 0, 0)
        kpi_lay.setSpacing(0)
        for i, (label_text, val, sub) in enumerate([
            ("Hours worked",    self._s("hours_worked"), self._s("hours_sub")),
            ("Attendance rate", self._s("attendance"),   self._s("att_sub")),
            ("Avg shift length",self._s("avg_shift"),    self._s("avg_sub")),
        ]):
            col = QVBoxLayout()
            col.setContentsMargins(24, 20, 24, 20)
            col.setSpacing(4)
            col.addWidget(lbl(label_text, size=10, color=C["sub"]))
            col.addWidget(lbl(val, bold=True, size=28))
            col.addWidget(lbl(sub, size=10, color=C["muted"]))
            kpi_lay.addLayout(col)
            if i < 2:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.VLine)
                div.setStyleSheet(f"background:{C['border']};border:none;")
                kpi_lay.addWidget(div)
        parent.addWidget(kpi_card)

        # Performance rows
        perf_card = card_frame(12)
        pl = QVBoxLayout(perf_card)
        pl.setContentsMargins(20, 4, 20, 4)
        pl.setSpacing(0)

        def _perf_row(title, subtitle, *values):
            rw = QWidget()
            rw.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 14, 0, 14)
            rl.setSpacing(12)
            tc = QVBoxLayout()
            tc.setSpacing(2)
            tc.addWidget(lbl(title, bold=True, size=12))
            tc.addWidget(lbl(subtitle, size=10, color=C["sub"]))
            rl.addLayout(tc, stretch=1)
            for v in values:
                vl = lbl(v, size=11)
                vl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                rl.addWidget(vl)
            return rw

        def _tag_row(title, subtitle, *tags):
            rw = QWidget()
            rw.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 14, 0, 14)
            rl.setSpacing(12)
            tc = QVBoxLayout()
            tc.setSpacing(2)
            tc.addWidget(lbl(title, bold=True, size=12))
            tc.addWidget(lbl(subtitle, size=10, color=C["sub"]))
            rl.addLayout(tc, stretch=1)
            for tag in tags:
                rl.addWidget(status_pill(tag, C["accent"], C["accent_lt"]))
            return rw

        pl.addWidget(_perf_row(
            "Punctuality", "On-time arrivals for scheduled shifts",
            self._s("punctuality_on"),
            self._s("punctuality_late"),
            self._s("punctuality_rating"),
        ))
        pl.addWidget(hline())
        pl.addWidget(_perf_row(
            "Completed shifts", "Finished planned hours without early clock-out",
            self._s("completed"),
            self._s("adjusted"),
            self._s("completed_rating"),
        ))
        pl.addWidget(hline())
        pl.addWidget(_tag_row(
            "Manager note", "General month-end performance observation",
            self._s("mgr_note1"),
            self._s("mgr_note2"),
            self._s("mgr_note3"),
        ))
        parent.addWidget(perf_card)

    # ── Clock helpers ─────────────────────────────────────────────────────────
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

    def _sync_clock_ui(self):
        """Force the clock button and dot to match self._clocked_in."""
        if self._clocked_in:
            self._set_dot(True)
            h, rem = divmod(self._elapsed_sec, 3600)
            m, s   = divmod(rem, 60)
            self._status_lbl.setText(
                f"Clocked in · {h}h {m:02d}m {s:02d}s elapsed"
            )
            self._clock_btn.setText("🔴  Clock Out")
            self._clock_btn.setStyleSheet(
                f"QPushButton{{background:{C['danger']};color:#FFFFFF;"
                f"border:none;border-radius:8px;font-size:12px;"
                f"font-weight:700;padding:0 16px;}}"
                f"QPushButton:hover{{background:#B03A3A;}}"
            )
        else:
            self._set_dot(False)
            self._status_lbl.setText("Not clocked in")
            self._clock_btn.setText("🟢  Clock In")
            self._clock_btn.setStyleSheet(
                f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                f"border:none;border-radius:8px;font-size:12px;"
                f"font-weight:700;padding:0 16px;}}"
                f"QPushButton:hover{{background:{C['accent_dk']};}}"
            )

    # ── Toggle clock — writes to DB with user_id FK ───────────────────────────
    def _toggle_clock(self):
        device = self._s("device", "Desktop")

        if not self._clocked_in:
            # ── Clock IN ──────────────────────────────────────────────────────
            self._clocked_in  = True
            self._elapsed_sec = 0
            self._elapsed_timer.start(1000)
            clock_in_time = datetime.now()

            try:
                self._sdb.add_clock_event(
                    self._staff_id, "Clock In", device,
                    user_id=self._user_id,
                )
                QMessageBox.information(
                    self, "Clock In",
                    f"Successfully clocked in!\n"
                    f"Time: {clock_in_time.strftime('%I:%M:%S %p')}\n"
                    f"Date: {clock_in_time.strftime('%B %d, %Y')}\n"
                    f"User: {_USER_NAME}",
                )
            except Exception as e:
                QMessageBox.warning(self, "DB Warning",
                                    f"Clock In error:\n{str(e)}")
                self._clocked_in = False
                self._elapsed_timer.stop()
                return

            self._sync_clock_ui()

        else:
            # ── Clock OUT ─────────────────────────────────────────────────────
            self._clocked_in = False
            h, rem  = divmod(self._elapsed_sec, 3600)
            m, _    = divmod(rem, 60)
            dur_str = f"{h}h {m:02d}m"
            clock_out_time = datetime.now()
            self._elapsed_timer.stop()

            try:
                self._sdb.update_clock_out_duration(self._staff_id, dur_str)
                self._sdb.add_clock_event(
                    self._staff_id, "Clock Out", device, duration=dur_str,
                    user_id=self._user_id,
                )
                QMessageBox.information(
                    self, "Clock Out",
                    f"Successfully clocked out!\n"
                    f"Time: {clock_out_time.strftime('%I:%M:%S %p')}\n"
                    f"Date: {clock_out_time.strftime('%B %d, %Y')}\n"
                    f"Session duration: {dur_str}\n"
                    f"User: {_USER_NAME}",
                )
            except Exception as e:
                QMessageBox.warning(self, "DB Warning",
                                    f"Clock Out error:\n{str(e)}")
                self._clocked_in = True
                self._elapsed_timer.start(1000)
                return

            self._status_lbl.setText(
                f"Not clocked in · Last session: {dur_str}"
            )
            self._sync_clock_ui()

    # ── Open log dialog ───────────────────────────────────────────────────────
    def _open_log(self):
        dlg = ClockLogDialog(self._sdb, self._staff_id,
                             user_id=self._user_id, parent=self)
        dlg.exec()

    # ── Log out ───────────────────────────────────────────────────────────────
    def _log_out(self):
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


# ── Main Window ───────────────────────────────────────────────────────────────
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
        self.statusBar().showMessage(
            f"  🔌  {db_info()}    |    👤  {_USER_NAME}  ({_USER_ROLE})", 0
        )

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

        # Show logged-in user badge
        user_badge = QLabel(f"👤  {_USER_NAME}  ·  {_USER_ROLE}")
        user_badge.setStyleSheet(
            f"color:{C['accent']};font-size:11px;font-weight:700;"
            f"border:1px solid {C['accent_lt']};border-radius:6px;"
            f"padding:4px 12px;background:{C['accent_lt']};"
        )
        tb.addWidget(user_badge)

        date_lbl = QLabel(
            f"  📅  Today · {datetime.now().strftime('%b %d').lstrip('0')}"
            f"  ·  Account Management"
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

        root.addWidget(PawffinatedSidebar(active_page="Account Management"))
        root.addWidget(
            AccountManagementPanel(staff_id=ACTIVE_STAFF_ID),
            stretch=1,
        )

    def closeEvent(self, event):
        close_db()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Pawffinated Account Management")

    try:
        win = AccountManagementWindow()
    except ConnectionError as exc:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Database Connection Failed")
        msg.setText("Pawffinated could not connect to the database.")
        msg.setDetailedText(str(exc))
        msg.exec()
        sys.exit(1)

    win.show()
    sys.exit(app.exec())