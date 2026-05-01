"""
PAWFFINATED – Activity Log  (PyQt6 Edition · v3)
=================================================
New in v3:
  • Time-range pill bar — Today / This Week / This Month / This Year / All Time
  • Unflagging an entry restores its original pre-flag status (no longer stuck on "Review")
  • "Resolved" status badge for entries cleared from review
  • original_status tracked per-entry so flag/unflag is always reversible
  • Demo data spans today, this week, this month, last month, and last year
    so every time-range pill has entries to show

Run standalone:
    python ActivityLog.py
"""

from __future__ import annotations
import sys, csv
from datetime import datetime, timedelta

try:
    from Sidebar import PawffinatedSidebar
    HAS_SIDEBAR = True
except ImportError:
    HAS_SIDEBAR = False

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
    QLineEdit, QDialog, QTextEdit, QMenu, QToolBar, QFileDialog,
    QMessageBox, QGraphicsOpacityEffect, QComboBox,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QPropertyAnimation, QPointF,
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPainterPath, QPen,
    QGuiApplication, QKeySequence, QShortcut, QCursor,
)

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    white     = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_dk = "#1E5A45",
    accent_lt = "#E8F4F0",
    warn      = "#E07B39",
    warn_lt   = "#FFF7ED",
    danger    = "#D94F4F",
    danger_lt = "#FEE2E2",
    ok        = "#059669",
    ok_lt     = "#D1FAE5",
    purple    = "#6D28D9",
    purple_lt = "#EDE9FE",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    muted     = "#9CA3AF",
    border    = "#E5E7EB",
    hover     = "#F0FDF8",
    row_alt   = "#FAFAFA",
    pending   = "#F59E0B",
    pending_lt= "#FFFBEB",
)

STATUS_CFG = {
    "Completed": ("#2D7A5F", "#E8F4F0"),
    "Success":   ("#059669", "#D1FAE5"),
    "Adjusted":  ("#E07B39", "#FFF7ED"),
    "Review":    ("#D94F4F", "#FEE2E2"),
    "Resolved":  ("#6D28D9", "#EDE9FE"),
    "Pending":   ("#F59E0B", "#FFFBEB"),
}

# ── Demo data — real datetime objects so time-range filtering works ────────────
_NOW = datetime.now()

def _dt(days_ago: int, hour: int, minute: int = 0) -> datetime:
    return (_NOW - timedelta(days=days_ago)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )

def _fmt(dt: datetime) -> str:
    return dt.strftime("%b %d, %I:%M %p").lstrip("0").replace(" 0", " ")

_RAW = [
    # Today
    (1,  "order",     "Accepted order #4821 for dine-in",
     "2 cappuccinos, 1 almond croissant — table 7",
     "Maya Patel", "Front Counter", _dt(0,9,15), "Completed", False,
     ["09:15 AM — Order received via POS","09:17 AM — Sent to espresso bar","09:22 AM — Marked served"]),
    (2,  "inventory", "Updated oat milk inventory",
     "Adjusted stock from 12 cartons to 8 cartons",
     "Daniel Kim", "Back Office", _dt(0,8,42), "Adjusted", False,
     ["08:42 AM — Manual adjustment logged","08:43 AM — Saved to stock ledger"]),
    (3,  "login",     "Logged into POS terminal",
     "Opened morning shift on register 2",
     "Sofia Martinez", "Register 2", _dt(0,7,58), "Success", False,
     ["07:58 AM — PIN authenticated","07:58 AM — Session opened"]),
    # This week
    (4,  "order",     "Marked mobile order #4816 as ready",
     "Pickup ticket sent to customer via app notification",
     "Aiden Brooks", "Espresso Bar", _dt(2,7,46), "Completed", False,
     ["07:40 AM — Order started","07:46 AM — Status set to Ready","07:48 AM — Customer notified"]),
    (5,  "logout",    "Logged out of inventory console",
     "Ended stock count session after close",
     "Leah Johnson", "Stock Room", _dt(2,21,32), "Success", False,
     ["09:32 PM — Session ended","09:32 PM — Changes auto-saved"]),
    (6,  "void",      "Voided item on order #4807",
     "Removed duplicate pastry before payment — manager override used",
     "Noah Rivera", "Front Counter", _dt(3,18,14), "Review", True,
     ["06:14 PM — Void initiated","06:14 PM — Manager override requested",
      "06:15 PM — Approved by Shift Lead","06:15 PM — Flagged for end-of-day review"]),
    (7,  "order",     "Accepted order #4803 for takeout",
     "1 matcha latte, 1 blueberry muffin",
     "Maya Patel", "Front Counter", _dt(4,17,50), "Completed", False,
     ["05:50 PM — Order created","05:53 PM — Prepared","05:55 PM — Handed off"]),
    # This month
    (8,  "inventory", "Restocked almond croissants",
     "Added 12 units to pastry display case",
     "Daniel Kim", "Back Office", _dt(8,16,30), "Adjusted", False,
     ["04:30 PM — Restock logged"]),
    (9,  "login",     "Granted access to POS Terminal 04",
     "Approved by shift supervisor after credential reset",
     "Jimrey Oppa", "Front Counter", _dt(10,10,45), "Success", False,
     ["10:43 AM — Access request submitted","10:45 AM — Supervisor approved"]),
    (10, "void",      "Refund issued on order #4791",
     "Customer reported wrong item — full refund of $8.50 processed",
     "Sofia Martinez", "Register 2", _dt(12,9,12), "Review", True,
     ["09:12 AM — Refund triggered","09:13 AM — Payment gateway processed",
      "09:14 AM — Receipt emailed to customer","09:14 AM — Flagged for audit"]),
    (11, "order",     "High-volume morning rush — 34 orders",
     "Busiest hour on record for this register",
     "Aiden Brooks", "Espresso Bar", _dt(14,8,0), "Completed", False,
     ["08:00 AM — Rush started","09:00 AM — 34 orders completed"]),
    (12, "inventory", "Logged weekly stock count",
     "All categories within expected range",
     "Daniel Kim", "Back Office", _dt(16,17,0), "Adjusted", False,
     ["05:00 PM — Count started","05:40 PM — Count completed"]),
    # This year (but not this month)
    (13, "login",     "New staff onboarding — register access",
     "Jamie Cruz added to POS system",
     "Leah Johnson", "Back Office", _dt(45,9,0), "Success", False,
     ["09:00 AM — Account created","09:05 AM — Training mode enabled"]),
    (14, "void",      "Discount override on order #4720",
     "10% loyalty discount applied manually — needs manager sign-off",
     "Noah Rivera", "Register 2", _dt(60,14,30), "Review", True,
     ["02:30 PM — Discount applied","02:31 PM — Flagged for sign-off"]),
    (15, "inventory", "Monthly stock audit completed",
     "Full category review — 3 discrepancies noted",
     "Daniel Kim", "Back Office", _dt(75,16,0), "Adjusted", False,
     ["04:00 PM — Audit started","05:30 PM — Report submitted"]),
    (16, "void",      "Cash drawer discrepancy on register 1",
     "$12.50 short — investigated and resolved",
     "Sofia Martinez", "Register 1", _dt(90,20,0), "Resolved", False,
     ["08:00 PM — Discrepancy noted","08:15 PM — Manager reviewed",
      "08:20 PM — Resolved — entry error found"]),
    # Last year
    (17, "login",     "Annual system access audit",
     "All staff credentials reviewed and rotated",
     "Leah Johnson", "Back Office", _dt(380,9,0), "Success", False,
     ["09:00 AM — Audit initiated","11:00 AM — All accounts verified"]),
    (18, "inventory", "Year-end inventory reconciliation",
     "Full asset count — results submitted to head office",
     "Daniel Kim", "Back Office", _dt(365,15,0), "Adjusted", False,
     ["03:00 PM — Count started","07:00 PM — Reconciliation complete"]),
    (19, "order",     "POS system migration — data verified",
     "Migrated 14 months of transaction history",
     "Jimrey Oppa", "Back Office", _dt(400,8,0), "Completed", False,
     ["08:00 AM — Migration started","12:00 PM — Data verified","12:05 PM — Signed off"]),
]

def _build_entries() -> list[dict]:
    out = []
    for row in _RAW:
        eid, icon, activity, detail, staff, station, dt, status, flagged, audit = row
        out.append(dict(
            id=eid, icon=icon, activity=activity, detail=detail,
            staff=staff, station=station,
            datetime=_fmt(dt), _dt=dt,
            status=status,
            original_status=status,   # preserved for unflag restoration
            flagged=flagged,
            audit=list(audit),
        ))
    return out

ACTIVITY_LOG = _build_entries()
ORDERS_ACCEPTED   = 126
INVENTORY_UPDATES = 9
TIME_RANGES = ["Today", "This Week", "This Month", "This Year", "All Time"]


# ── Time-range helper ─────────────────────────────────────────────────────────
def _range_bounds(label: str):
    now = datetime.now()
    if label == "Today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if label == "This Week":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if label == "This Month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    if label == "This Year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), now
    return None   # All Time


# ── Widget helpers ────────────────────────────────────────────────────────────
def lbl(text="", bold=False, size=13, color=None) -> QLabel:
    w = QLabel(text)
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    w.setFont(f)
    w.setStyleSheet(f"color:{color or C['text']};background:transparent;")
    return w

def hline(color=None) -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setStyleSheet(f"background:{color or C['border']};max-height:1px;border:none;")
    ln.setFixedHeight(1)
    return ln

def make_btn(text, bg, fg="#FFFFFF", hover=None, size=12, bold=True,
             height=36, radius=8) -> QPushButton:
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
    fg = fg or C["text"]; border = border or C["border"]
    hover_bg = hover_bg or C["bg"]
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedHeight(height)
    b.setStyleSheet(
        f"QPushButton{{background:{C['white']};color:{fg};"
        f"border:1px solid {border};border-radius:8px;"
        f"font-size:{size}px;font-weight:600;padding:0 16px;}}"
        f"QPushButton:hover{{background:{hover_bg};}}"
    )
    return b

ICON_MAP = {
    "order":     ("🧾", "#E8F4F0", "#2D7A5F"),
    "inventory": ("📦", "#FFF7ED", "#E07B39"),
    "login":     ("→",  "#D1FAE5", "#059669"),
    "logout":    ("←",  "#E8F4F0", "#2D7A5F"),
    "void":      ("🗑", "#FEE2E2", "#D94F4F"),
    "note":      ("📝", "#EDE9FE", "#6D28D9"),
}

class ActivityIcon(QLabel):
    def __init__(self, icon_type: str, size=38, parent=None):
        super().__init__(parent)
        emoji, bg, fg = ICON_MAP.get(icon_type, ("•", C["border"], C["sub"]))
        self.setFixedSize(size, size)
        self.setText(emoji)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background:{bg};border-radius:{size//2}px;"
            f"font-size:{max(14,int(size*.38))}px;color:{fg};border:none;"
        )

def status_badge(status: str) -> QLabel:
    fg, bg = STATUS_CFG.get(status, (C["sub"], C["border"]))
    w = QLabel(status)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setFixedHeight(24)
    w.setStyleSheet(
        f"color:{fg};background:{bg};border-radius:6px;"
        f"padding:0 10px;font-size:11px;font-weight:700;border:none;"
    )
    return w


# ── Toast ─────────────────────────────────────────────────────────────────────
class Toast(QWidget):
    def __init__(self, message: str, parent: QWidget, kind="ok"):
        super().__init__(parent)
        bg = {"ok": C["accent"], "warn": C["warn"], "danger": C["danger"]}.get(kind, C["accent"])
        self.setFixedHeight(44)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(f"background:{bg};border-radius:10px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        msg = QLabel(message)
        msg.setStyleSheet("color:#FFFFFF;font-size:13px;font-weight:600;background:transparent;")
        lay.addWidget(msg)
        self._eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._eff)
        self._eff.setOpacity(0)
        self._in  = QPropertyAnimation(self._eff, b"opacity", self)
        self._in.setDuration(220); self._in.setEndValue(1.0)
        self._out = QPropertyAnimation(self._eff, b"opacity", self)
        self._out.setDuration(350); self._out.setEndValue(0.0)
        self._out.finished.connect(self.deleteLater)
        self._repos(); self.show(); self._in.start()
        QTimer.singleShot(2800, self._out.start)

    def _repos(self):
        if self.parent():
            pw = self.parent().width()
            w = max(300, min(460, pw - 80))
            self.setFixedWidth(w)
            self.move((pw - w) // 2, self.parent().height() - 80)

def show_toast(parent, message, kind="ok"):
    Toast(message, parent, kind).raise_()


# ── Time-range pill bar ───────────────────────────────────────────────────────
class TimeRangeBar(QWidget):
    range_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = "Today"
        self.setStyleSheet(f"background:{C['white']};")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 10, 28, 10)
        lay.setSpacing(6)
        lay.addWidget(lbl("View:", size=11, color=C["sub"]))
        lay.addSpacing(4)
        self._btns: dict[str, QPushButton] = {}
        for label in TIME_RANGES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(label == self._active)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _, l=label: self._pick(l))
            self._btns[label] = btn
            lay.addWidget(btn)
        lay.addStretch()
        self._count_lbl = lbl("", size=10, color=C["sub"])
        lay.addWidget(self._count_lbl)
        self._style_all()

    def _pick(self, label: str):
        self._active = label
        self._style_all()
        self.range_changed.emit(label)

    def _style_all(self):
        for name, btn in self._btns.items():
            if name == self._active:
                btn.setStyleSheet(
                    f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                    f"border:none;border-radius:6px;font-size:11px;"
                    f"font-weight:700;padding:0 14px;}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:{C['white']};color:{C['sub']};"
                    f"border:1px solid {C['border']};border-radius:6px;"
                    f"font-size:11px;padding:0 12px;}}"
                    f"QPushButton:hover{{background:{C['bg']};color:{C['text']};}}"
                )

    def set_count(self, shown: int, total: int):
        self._count_lbl.setText(f"{shown} of {total} entries")

    @property
    def active(self) -> str:
        return self._active


# ── View Details Dialog ───────────────────────────────────────────────────────
class ViewDetailsDialog(QDialog):
    flag_toggled = pyqtSignal(int, bool)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self._entry = entry
        self.setWindowTitle(f"Activity Detail — #{entry['id']}")
        self.setMinimumSize(580, 580)
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
        hdr.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 18, 24, 18)
        hl.setSpacing(14)
        hl.addWidget(ActivityIcon(self._entry["icon"], 44))
        tc = QVBoxLayout(); tc.setSpacing(3)
        tc.addWidget(lbl(self._entry["activity"], bold=True, size=15))
        tc.addWidget(lbl(self._entry["detail"], size=11, color=C["sub"]))
        hl.addLayout(tc, stretch=1)
        hl.addWidget(status_badge(self._entry["status"]))
        root.addWidget(hdr)

        # Scrollable body
        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 20)
        bl.setSpacing(16)

        # Meta grid
        meta = self._card()
        mg = QGridLayout(meta)
        mg.setContentsMargins(20, 16, 20, 16)
        mg.setHorizontalSpacing(24)
        mg.setVerticalSpacing(12)
        fields = [
            ("Staff Member",    self._entry["staff"]),
            ("Station",         self._entry["station"]),
            ("Date & Time",     self._entry["datetime"]),
            ("Entry ID",        f"#{self._entry['id']}"),
            ("Current Status",  self._entry["status"]),
            ("Original Status", self._entry.get("original_status", "—")),
            ("Flagged",         "Yes ⚑" if self._entry.get("flagged") else "No"),
        ]
        for i, (k, v) in enumerate(fields):
            col = (i % 2) * 2
            row = i // 2
            mg.addWidget(lbl(k, size=10, color=C["sub"]), row, col)
            vl = lbl(v, bold=True, size=12)
            if k == "Current Status":
                fg, bg = STATUS_CFG.get(v, (C["sub"], C["border"]))
                vl.setStyleSheet(
                    f"color:{fg};background:{bg};border-radius:5px;"
                    f"padding:2px 8px;font-size:11px;font-weight:700;"
                )
            mg.addWidget(vl, row, col + 1)
        bl.addWidget(meta)

        # Audit trail
        bl.addWidget(lbl("Audit Trail", bold=True, size=13))
        ac = self._card()
        al = QVBoxLayout(ac)
        al.setContentsMargins(20, 14, 20, 14)
        al.setSpacing(0)
        audit_list = self._entry.get("audit", [
            self._entry["datetime"] + " — " + self._entry["activity"]
        ])
        for i, line in enumerate(audit_list):
            rw = QWidget(); rw.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 6, 0, 6)
            rl.setSpacing(14)
            dc = QVBoxLayout(); dc.setSpacing(0)
            is_last = (i == len(audit_list) - 1)
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(
                f"background:{C['accent'] if is_last else C['border']};"
                f"border-radius:5px;border:none;"
            )
            dc.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter)
            if not is_last:
                vln = QFrame(); vln.setFixedWidth(2); vln.setMinimumHeight(16)
                vln.setStyleSheet(f"background:{C['border']};border:none;")
                dc.addWidget(vln, alignment=Qt.AlignmentFlag.AlignHCenter)
                dc.addStretch()
            rl.addLayout(dc)
            parts = line.split(" — ", 1)
            if len(parts) == 2:
                tl = lbl(parts[0], size=10, color=C["sub"]); tl.setFixedWidth(100)
                rl.addWidget(tl)
                rl.addWidget(lbl(parts[1], size=11))
            else:
                rl.addWidget(lbl(line, size=11))
            rl.addStretch()
            al.addWidget(rw)
        bl.addWidget(ac)
        bl.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;")
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        # Footer
        foot = QWidget()
        foot.setStyleSheet(f"background:{C['white']};border-top:1px solid {C['border']};")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(24, 14, 24, 14)
        fl.setSpacing(10)
        cb = outline_btn("  📋  Copy Entry", height=36)
        cb.clicked.connect(self._copy)
        fl.addWidget(cb)
        flagged   = self._entry.get("flagged", False)
        flag_text = "  ⚑  Unflag Entry" if flagged else "  ⚑  Flag for Review"
        flag_fg   = C["accent"]    if flagged else C["danger"]
        flag_hov  = C["accent_lt"] if flagged else C["danger_lt"]
        self._fb  = outline_btn(flag_text, fg=flag_fg, border=flag_fg,
                                hover_bg=flag_hov, height=36)
        self._fb.clicked.connect(self._toggle_flag)
        fl.addWidget(self._fb)
        fl.addStretch()
        fl.addWidget(make_btn("Close", C["accent"], hover=C["accent_dk"]))
        foot.layout().itemAt(foot.layout().count()-1).widget().clicked.connect(self.accept)
        root.addWidget(foot)

    def _card(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:10px;"
            f"border:1px solid {C['border']};}}"
        )
        return f

    def _copy(self):
        e = self._entry
        QGuiApplication.clipboard().setText(
            f"Activity Log Entry #{e['id']}\n{'─'*40}\n"
            f"Activity        : {e['activity']}\n"
            f"Detail          : {e['detail']}\n"
            f"Staff           : {e['staff']}\n"
            f"Station         : {e['station']}\n"
            f"Date/Time       : {e['datetime']}\n"
            f"Status          : {e['status']}\n"
            f"Original Status : {e.get('original_status','—')}\n"
            f"Flagged         : {'Yes' if e.get('flagged') else 'No'}\n"
        )

    def _toggle_flag(self):
        self._entry["flagged"] = not self._entry.get("flagged", False)
        self.flag_toggled.emit(self._entry["id"], self._entry["flagged"])
        self.accept()


# ── Add Note Dialog ───────────────────────────────────────────────────────────
class AddNoteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Note to Activity Log")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"QDialog{{background:{C['white']};}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(lbl("Add a Note", bold=True, size=16))
        lay.addWidget(lbl("Notes are visible to managers and shift supervisors.",
                          size=10, color=C["sub"]))
        lay.addWidget(hline())
        for fl, attr, ph in [
            ("Staff Member", "staff_field",   "e.g. Maya Patel"),
            ("Station",      "station_field", "e.g. Front Counter"),
        ]:
            lay.addWidget(lbl(fl, size=11, color=C["sub"]))
            f = QLineEdit(); f.setPlaceholderText(ph); f.setFixedHeight(38)
            f.setStyleSheet(
                f"border:1px solid {C['border']};border-radius:7px;"
                f"padding:0 12px;background:{C['bg']};font-size:13px;"
            )
            setattr(self, attr, f); lay.addWidget(f)
        lay.addWidget(lbl("Note", size=11, color=C["sub"]))
        self.note_field = QTextEdit()
        self.note_field.setPlaceholderText("Describe the activity or observation…")
        self.note_field.setFixedHeight(100)
        self.note_field.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:7px;"
            f"padding:8px;background:{C['bg']};font-size:13px;"
        )
        lay.addWidget(self.note_field)
        lay.addWidget(lbl("Priority", size=11, color=C["sub"]))
        self.priority = QComboBox()
        self.priority.addItems(["Completed", "Adjusted", "Review"])
        self.priority.setFixedHeight(38)
        self.priority.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:7px;"
            f"padding:0 10px;background:{C['bg']};font-size:13px;"
        )
        lay.addWidget(self.priority)
        lay.addWidget(hline())
        br = QHBoxLayout(); br.addStretch()
        cancel = outline_btn("Cancel"); cancel.clicked.connect(self.reject)
        save = make_btn("  +  Add Note", C["accent"], hover=C["accent_dk"])
        save.clicked.connect(self._save)
        br.addWidget(cancel); br.addSpacing(8); br.addWidget(save)
        lay.addLayout(br)

    def _save(self):
        if not self.staff_field.text().strip() or not self.note_field.toPlainText().strip():
            QMessageBox.warning(self, "Required", "Staff member and note are required.")
            return
        self.accept()

    def get_status(self) -> str:
        return self.priority.currentText()


# ── Filter Dialog ─────────────────────────────────────────────────────────────
class FilterDialog(QDialog):
    filter_applied = pyqtSignal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter Activity")
        self.setMinimumWidth(400)
        self.setStyleSheet(f"QDialog{{background:{C['white']};}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(lbl("Filter Activity Log", bold=True, size=15))
        lay.addWidget(hline())
        lay.addWidget(lbl("Status", size=11, color=C["sub"]))
        self._status_btns: dict[str, QPushButton] = {}
        self._current_status = "All"
        all_statuses = ["All", "Completed", "Success", "Adjusted", "Review", "Resolved"]
        r1 = QHBoxLayout(); r1.setSpacing(6)
        r2 = QHBoxLayout(); r2.setSpacing(6)
        for i, s in enumerate(all_statuses):
            btn = QPushButton(s)
            btn.setCheckable(True); btn.setChecked(s == "All")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _, st=s: self._pick(st))
            self._status_btns[s] = btn
            (r1 if i < 3 else r2).addWidget(btn)
        lay.addLayout(r1); lay.addLayout(r2)
        self._restyle("All")
        lay.addWidget(lbl("Staff Member", size=11, color=C["sub"]))
        self.staff_box = QLineEdit()
        self.staff_box.setPlaceholderText("Search by name…"); self.staff_box.setFixedHeight(38)
        self.staff_box.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:7px;"
            f"padding:0 12px;background:{C['bg']};font-size:13px;"
        )
        lay.addWidget(self.staff_box)
        self._fo = QPushButton("  ⚑  Show Flagged Only")
        self._fo.setCheckable(True)
        self._fo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fo.setFixedHeight(34)
        self._fo.setStyleSheet(
            f"QPushButton{{background:{C['white']};color:{C['danger']};"
            f"border:1px solid {C['danger']};border-radius:7px;"
            f"font-size:12px;font-weight:600;padding:0 14px;}}"
            f"QPushButton:checked{{background:{C['danger']};color:#FFFFFF;}}"
        )
        lay.addWidget(self._fo)
        lay.addWidget(hline())
        br = QHBoxLayout(); br.addStretch()
        cancel = outline_btn("Cancel"); cancel.clicked.connect(self.reject)
        apply = make_btn("Apply Filter", C["accent"], hover=C["accent_dk"])
        apply.clicked.connect(self._apply)
        br.addWidget(cancel); br.addSpacing(8); br.addWidget(apply)
        lay.addLayout(br)

    def _pick(self, s: str):
        self._current_status = s; self._restyle(s)

    def _restyle(self, active: str):
        for name, btn in self._status_btns.items():
            if name == active:
                btn.setStyleSheet(
                    f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                    f"border:none;border-radius:6px;font-size:11px;"
                    f"font-weight:700;padding:0 10px;}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:{C['white']};color:{C['text']};"
                    f"border:1px solid {C['border']};border-radius:6px;"
                    f"font-size:11px;padding:0 8px;}}"
                    f"QPushButton:hover{{background:{C['bg']};}}"
                )

    def _apply(self):
        self.filter_applied.emit(
            self._current_status, self.staff_box.text().strip().lower(),
            self._fo.isChecked()
        )
        self.accept()


# ── Activity Row ──────────────────────────────────────────────────────────────
class ActivityRow(QWidget):
    view_requested = pyqtSignal(dict)
    flag_requested = pyqtSignal(dict)
    copy_requested = pyqtSignal(dict)

    def __init__(self, entry: dict, alt_bg=False, parent=None):
        super().__init__(parent)
        self._entry = entry; self._alt_bg = alt_bg; self._hovered = False
        self.setMouseTracking(True)
        self._build(); self._refresh_style()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 16, 12); lay.setSpacing(12)
        lay.addWidget(ActivityIcon(self._entry["icon"], 36))

        ac = QVBoxLayout(); ac.setSpacing(2)
        self._act = lbl(self._entry["activity"], bold=True, size=12)
        self._det = lbl(self._entry["detail"], size=10, color=C["sub"])
        self._det.setWordWrap(True)
        ac.addWidget(self._act); ac.addWidget(self._det)
        lay.addLayout(ac, stretch=3)

        self._stf = lbl(self._entry["staff"],    size=12)
        self._stn = lbl(self._entry["station"],  size=12, color=C["sub"])
        self._dtl = lbl(self._entry["datetime"], size=11, color=C["muted"])
        lay.addWidget(self._stf, stretch=2)
        lay.addWidget(self._stn, stretch=2)
        lay.addWidget(self._dtl, stretch=2)

        self._badge = status_badge(self._entry["status"])
        bw = QWidget(); bw.setStyleSheet("background:transparent;")
        bwl = QHBoxLayout(bw); bwl.setContentsMargins(0,0,0,0)
        bwl.addWidget(self._badge); bwl.addStretch()
        lay.addWidget(bw, stretch=1)

        self._fdot = QLabel("⚑")
        self._fdot.setFixedSize(20, 20)
        self._fdot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fdot.setStyleSheet(f"color:{C['danger']};font-size:12px;background:transparent;")
        lay.addWidget(self._fdot)

        dots = QPushButton("⋯")
        dots.setFixedSize(32, 28)
        dots.setCursor(Qt.CursorShape.PointingHandCursor)
        dots.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['sub']};"
            f"border:none;font-size:18px;border-radius:5px;}}"
            f"QPushButton:hover{{background:{C['border']};color:{C['text']};}}"
        )
        dots.clicked.connect(self._menu)
        lay.addWidget(dots)
        self._refresh_flag()

    def _refresh_flag(self):
        self._fdot.setVisible(self._entry.get("flagged", False))

    def _refresh_style(self):
        bg = C["hover"] if self._hovered else (C["row_alt"] if self._alt_bg else C["white"])
        self.setStyleSheet(f"background:{bg};")

    def enterEvent(self, e): self._hovered=True;  self._refresh_style(); super().enterEvent(e)
    def leaveEvent(self, e): self._hovered=False; self._refresh_style(); super().leaveEvent(e)
    def mouseDoubleClickEvent(self, e): self.view_requested.emit(self._entry)

    def _menu(self):
        m = QMenu(self)
        m.setStyleSheet(
            f"QMenu{{background:{C['white']};border:1px solid {C['border']};"
            f"border-radius:10px;padding:6px;}}"
            f"QMenu::item{{padding:9px 20px;border-radius:5px;font-size:12px;color:{C['text']};}}"
            f"QMenu::item:selected{{background:{C['accent_lt']};color:{C['accent']};}}"
            f"QMenu::separator{{background:{C['border']};height:1px;margin:4px 10px;}}"
        )
        va = m.addAction("  👁   View Details")
        ca = m.addAction("  📋  Copy Entry")
        m.addSeparator()
        flagged = self._entry.get("flagged", False)
        fa = m.addAction("  ⚑   Unflag Entry" if flagged else "  ⚑   Flag for Review")
        chosen = m.exec(QCursor.pos())
        if chosen == va: self.view_requested.emit(self._entry)
        elif chosen == ca: self.copy_requested.emit(self._entry)
        elif chosen == fa: self.flag_requested.emit(self._entry)

    def refresh_from_entry(self):
        self._act.setText(self._entry["activity"])
        self._det.setText(self._entry["detail"])
        self._stf.setText(self._entry["staff"])
        self._stn.setText(self._entry["station"])
        self._dtl.setText(self._entry["datetime"])
        fg, bg = STATUS_CFG.get(self._entry["status"], (C["sub"], C["border"]))
        self._badge.setText(self._entry["status"])
        self._badge.setStyleSheet(
            f"color:{fg};background:{bg};border-radius:6px;"
            f"padding:0 10px;font-size:11px;font-weight:700;border:none;"
        )
        self._refresh_flag()


# ── Column Header ─────────────────────────────────────────────────────────────
class ColumnHeader(QWidget):
    sort_requested = pyqtSignal(str, bool)
    COLS = [("Activity","activity",3),("Staff Member","staff",2),
            ("Station","station",2),("Date & Time","datetime",2),("Status","status",1)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setStyleSheet(f"background:{C['bg']};border-bottom:1px solid {C['border']};")
        self._sf = None; self._asc = True; self._btns = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 16, 0); lay.setSpacing(12)
        sp = QWidget(); sp.setFixedWidth(48); lay.addWidget(sp)
        for label, field, stretch in self.COLS:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C['sub']};"
                f"border:none;font-size:10px;font-weight:700;text-align:left;padding:0;}}"
                f"QPushButton:hover{{color:{C['accent']};}}"
            )
            btn.clicked.connect(lambda _, f=field: self._sort(f))
            self._btns[field] = btn; lay.addWidget(btn, stretch=stretch)
        for w in [20, 32]:
            sp = QWidget(); sp.setFixedWidth(w); lay.addWidget(sp)

    def _sort(self, field: str):
        self._asc = not self._asc if self._sf == field else True
        self._sf = field
        arrow = " ↑" if self._asc else " ↓"
        for f, b in self._btns.items():
            base = self.COLS[[c[1] for c in self.COLS].index(f)][0]
            b.setText(base + (arrow if f == field else ""))
        self.sort_requested.emit(field, self._asc)


# ── Sparkline ─────────────────────────────────────────────────────────────────
class SparkLine(QWidget):
    def __init__(self, vals, w=80, h=32, parent=None):
        super().__init__(parent); self._vals=vals; self.setFixedSize(w,h)
    def paintEvent(self, _):
        if len(self._vals) < 2: return
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        mn, mx = min(self._vals), max(self._vals); rng = mx-mn or 1
        step = w/(len(self._vals)-1)
        pts = [QPointF(i*step, h-(v-mn)/rng*h) for i,v in enumerate(self._vals)]
        pen = QPen(QColor(C["accent"]), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(); path.moveTo(pts[0])
        for pt in pts[1:]: path.lineTo(pt)
        p.drawPath(path); p.end()


# ── Stat Card ─────────────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, label, value, badge_text, badge_fg, badge_bg,
                 subtitle, trend_vals=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame{background:#FFFFFF;border-radius:0px;border:none;}")
        lay = QVBoxLayout(self); lay.setContentsMargins(28,22,28,22); lay.setSpacing(6)
        top = QHBoxLayout(); top.setSpacing(10)
        top.addWidget(lbl(label, size=11, color=C["sub"]))
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"background:{badge_bg};color:{badge_fg};"
            f"border-radius:5px;padding:2px 10px;font-size:10px;font-weight:700;border:none;"
        )
        top.addWidget(badge); top.addStretch(); lay.addLayout(top)
        bot = QHBoxLayout(); bot.setSpacing(12)
        bot.addWidget(lbl(str(value), bold=True, size=34))
        if trend_vals:
            bot.addWidget(SparkLine(trend_vals), alignment=Qt.AlignmentFlag.AlignBottom)
        bot.addStretch(); lay.addLayout(bot)
        lay.addWidget(lbl(subtitle, size=10, color=C["muted"]))


# ── Activity Table ────────────────────────────────────────────────────────────
class ActivityTable(QWidget):
    entry_view_requested = pyqtSignal(dict)
    entry_flag_requested = pyqtSignal(dict)
    entry_copy_requested = pyqtSignal(dict)
    match_count_changed  = pyqtSignal(int)

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self._entries    = entries
        self._search     = ""
        self._status_f   = "All"
        self._staff_f    = ""
        self._flag_only  = False
        self._sort_field = None
        self._sort_asc   = True
        self._time_range = "Today"
        self.setStyleSheet(f"background:{C['white']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        hdr = ColumnHeader(); hdr.sort_requested.connect(self._on_sort)
        root.addWidget(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C['white']};}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )
        self._body = QWidget(); self._body.setStyleSheet(f"background:{C['white']};")
        self._bl   = QVBoxLayout(self._body)
        self._bl.setContentsMargins(0,0,0,0); self._bl.setSpacing(0)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, stretch=1)
        self._refresh()

    def _in_range(self, e: dict) -> bool:
        bounds = _range_bounds(self._time_range)
        if bounds is None: return True
        dt = e.get("_dt")
        if dt is None: return True
        return bounds[0] <= dt <= bounds[1]

    def _filtered(self) -> list[dict]:
        result = []
        for e in self._entries:
            if not self._in_range(e): continue
            if self._search and not any(
                self._search in str(e.get(k,"")).lower()
                for k in ("activity","staff","station","detail")
            ): continue
            if self._status_f != "All" and e["status"] != self._status_f: continue
            if self._staff_f and self._staff_f not in e["staff"].lower(): continue
            if self._flag_only and not e.get("flagged", False): continue
            result.append(e)
        if self._sort_field:
            result.sort(
                key=lambda x: str(x.get(self._sort_field,"")).lower(),
                reverse=not self._sort_asc
            )
        return result

    def _refresh(self):
        while self._bl.count():
            item = self._bl.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        visible = self._filtered()
        self.match_count_changed.emit(len(visible))
        if not visible:
            msg = ("No activity in this time range."
                   if not self._search and self._status_f == "All"
                   else "No activity matches your filter.")
            el = lbl(msg, size=12, color=C["sub"])
            el.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._bl.addSpacing(48); self._bl.addWidget(el); self._bl.addStretch()
            return
        for i, entry in enumerate(visible):
            row = ActivityRow(entry, alt_bg=(i%2==1))
            row.view_requested.connect(self.entry_view_requested)
            row.flag_requested.connect(self.entry_flag_requested)
            row.copy_requested.connect(self.entry_copy_requested)
            self._bl.addWidget(row)
            if i < len(visible)-1: self._bl.addWidget(hline())
        self._bl.addStretch()

    def set_search(self, text: str):    self._search = text.lower(); self._refresh()
    def set_time_range(self, label: str): self._time_range = label; self._refresh()
    def add_entry(self, entry: dict):   self._entries.insert(0, entry); self._refresh()
    def refresh_entry(self, _id: int):  self._refresh()
    def apply_filter(self, status, staff, flag_only):
        self._status_f = status; self._staff_f = staff
        self._flag_only = flag_only; self._refresh()
    def _on_sort(self, field, asc):
        self._sort_field = field; self._sort_asc = asc; self._refresh()


# ── Main Window ───────────────────────────────────────────────────────────────
class ActivityLogWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Activity Log")
        self.resize(1340, 900); self.setMinimumSize(960, 660)
        self.setStyleSheet(
            f"QMainWindow,#central{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
            f"QToolBar{{background:{C['white']};"
            f"border-bottom:1px solid {C['border']};padding:4px 16px;spacing:8px;}}"
            f"QStatusBar{{background:{C['white']};"
            f"border-top:1px solid {C['border']};color:{C['sub']};"
            f"font-size:11px;padding:0 12px;}}"
        )
        self._entries = list(ACTIVITY_LOG)
        self._build_toolbar(); self._build_ui()
        self._update_status(len([e for e in self._entries if self._table._in_range(e)]))
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            lambda: self._search_box.setFocus())
        QShortcut(QKeySequence("Escape"), self).activated.connect(
            lambda: (self._search_box.clear(), self._search_box.clearFocus()))

    def _build_toolbar(self):
        tb = self.addToolBar("Main"); tb.setMovable(False)
        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)
        sp = QWidget(); sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)
        dl = QLabel("📅  Activity Log  ·  All Shifts")
        dl.setStyleSheet(
            f"color:{C['sub']};font-size:12px;border:1px solid {C['border']};"
            f"border-radius:6px;padding:4px 12px;background:{C['white']};"
        )
        tb.addWidget(dl)

    def _build_ui(self):
        central = QWidget(); central.setObjectName("central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        if HAS_SIDEBAR:
            root.addWidget(PawffinatedSidebar(active_page="Activity Log"))
        main = QWidget(); main.setStyleSheet(f"background:{C['bg']};")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        self._build_page_header(ml)
        self._build_stat_strip(ml)
        self._build_time_range_bar(ml)
        self._build_recent_section(ml)
        root.addWidget(main, stretch=1)

    def _build_page_header(self, parent):
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(28,18,28,18); hl.setSpacing(14)
        left = QVBoxLayout(); left.setSpacing(3)
        left.addWidget(lbl("Activity Log", bold=True, size=20))
        left.addWidget(lbl(
            "Track staff actions across orders, inventory, and shifts.  "
            "Double-click any row for details.",
            size=10, color=C["sub"],
        ))
        hl.addLayout(left); hl.addStretch()
        eb = outline_btn("  ↓  Export CSV"); eb.clicked.connect(self._export_csv)
        hl.addWidget(eb)
        xb = outline_btn("  ⚠  View Exceptions", fg=C["danger"],
                         border=C["danger"], hover_bg=C["danger_lt"])
        xb.clicked.connect(self._view_exceptions); hl.addWidget(xb)
        nb = make_btn("  +  Add Note", C["accent"], hover=C["accent_dk"])
        nb.clicked.connect(self._add_note); hl.addWidget(nb)
        parent.addWidget(hdr)

    def _build_stat_strip(self, parent):
        strip = QWidget()
        strip.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        sl = QHBoxLayout(strip); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)
        flagged_n = sum(1 for e in self._entries if e.get("flagged"))
        cards = [
            ("Orders Accepted",   ORDERS_ACCEPTED, "On pace",        C["ok"],     C["ok_lt"],
             "Accepted by front counter and barista staff today", [98,104,110,115,120,124,126]),
            ("Inventory Updates", INVENTORY_UPDATES,"Needs review",  C["warn"],   C["warn_lt"],
             "Manual stock adjustments logged this shift",        [3,5,4,7,6,8,9]),
            ("Flagged Entries",   flagged_n,        "Action required",C["danger"],C["danger_lt"],
             "Entries currently flagged for manager review",      [0,1,1,1,2,2,flagged_n]),
        ]
        for i, (label, val, bt, bfg, bbg, sub, trend) in enumerate(cards):
            if i: sl.addWidget(QFrame(frameShape=QFrame.Shape.VLine,
                               styleSheet=f"background:{C['border']};border:none;"))
            sl.addWidget(StatCard(label, val, bt, bfg, bbg, sub, trend), stretch=1)
        parent.addWidget(strip)

    def _build_time_range_bar(self, parent):
        self._time_bar = TimeRangeBar()
        self._time_bar.range_changed.connect(self._on_time_range)
        wrapper = QWidget()
        wrapper.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        wl = QVBoxLayout(wrapper); wl.setContentsMargins(0,0,0,0); wl.setSpacing(0)
        wl.addWidget(self._time_bar)
        parent.addWidget(wrapper)

    def _build_recent_section(self, parent):
        wrap = QWidget(); wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QVBoxLayout(wrap); wl.setContentsMargins(28,20,28,20); wl.setSpacing(14)

        top = QHBoxLayout()
        lc = QVBoxLayout(); lc.setSpacing(2)
        lc.addWidget(lbl("Recent Activity", bold=True, size=16))
        lc.addWidget(lbl(
            "Click column headers to sort  ·  Double-click a row to open details",
            size=10, color=C["sub"]))
        top.addLayout(lc); top.addStretch()

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍  Search activity, staff, or station…")
        self._search_box.setFixedWidth(300); self._search_box.setFixedHeight(36)
        self._search_box.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:8px;"
            f"padding:0 14px;background:{C['white']};font-size:12px;"
        )
        self._search_box.textChanged.connect(self._on_search)
        top.addWidget(self._search_box)

        fb = outline_btn("  ▾  Filter"); fb.setFixedHeight(36)
        fb.clicked.connect(self._open_filter); top.addWidget(fb)
        wl.addLayout(top)

        tc = QFrame()
        tc.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:12px;border:1px solid {C['border']};}}"
        )
        tcl = QVBoxLayout(tc); tcl.setContentsMargins(0,0,0,0); tcl.setSpacing(0)
        self._table = ActivityTable(self._entries)
        self._table.entry_view_requested.connect(self._on_view_entry)
        self._table.entry_flag_requested.connect(self._on_flag_entry)
        self._table.entry_copy_requested.connect(self._on_copy_entry)
        self._table.match_count_changed.connect(self._on_match_count)
        tcl.addWidget(self._table)
        wl.addWidget(tc, stretch=1)
        parent.addWidget(wrap, stretch=1)

    # ── Slots ─────────────────────────────────────────────────────────────────
    def _on_time_range(self, label: str):
        self._table.set_time_range(label)

    def _on_search(self, text: str):
        self._table.set_search(text)

    def _open_filter(self):
        dlg = FilterDialog(self)
        dlg.filter_applied.connect(self._table.apply_filter)
        dlg.exec()

    def _on_view_entry(self, entry: dict):
        dlg = ViewDetailsDialog(entry, self)
        dlg.flag_toggled.connect(self._on_flag_toggled_from_dialog)
        dlg.exec()

    def _on_flag_entry(self, entry: dict):
        """
        Flagging  → saves current status to original_status, then sets status = "Review".
        Unflagging→ restores original_status (defaulting to "Resolved" if nothing was saved).
                    Status is NEVER left as "Review" after unflagging.
        """
        was_flagged = entry.get("flagged", False)
        entry["flagged"] = not was_flagged

        if entry["flagged"]:
            # Only overwrite original_status if we weren't already in Review
            if entry.get("status") != "Review":
                entry["original_status"] = entry["status"]
            entry["status"] = "Review"
            entry.setdefault("audit", []).append(
                f"{entry['datetime']} — Flagged for review"
            )
            show_toast(self.centralWidget(),
                       f"Entry #{entry['id']} flagged for review", "warn")
        else:
            # Restore — never leave on "Review"
            restored = entry.get("original_status") or "Resolved"
            if restored == "Review":
                restored = "Resolved"
            entry["status"] = restored
            entry.setdefault("audit", []).append(
                f"{entry['datetime']} — Flag removed · status restored to {restored}"
            )
            show_toast(self.centralWidget(),
                       f"Entry #{entry['id']} unflagged · status: {restored}", "ok")

        self._table.refresh_entry(entry["id"])
        self._update_status()

    def _on_copy_entry(self, entry: dict):
        QGuiApplication.clipboard().setText(
            f"Activity Log Entry #{entry['id']}\n{'─'*40}\n"
            f"Activity        : {entry['activity']}\n"
            f"Detail          : {entry['detail']}\n"
            f"Staff           : {entry['staff']}\n"
            f"Station         : {entry['station']}\n"
            f"Date/Time       : {entry['datetime']}\n"
            f"Status          : {entry['status']}\n"
            f"Original Status : {entry.get('original_status','—')}\n"
            f"Flagged         : {'Yes' if entry.get('flagged') else 'No'}\n"
        )
        show_toast(self.centralWidget(), "Entry copied to clipboard", "ok")

    def _on_flag_toggled_from_dialog(self, entry_id: int, _flagged: bool):
        for e in self._entries:
            if e["id"] == entry_id:
                self._on_flag_entry(e)
                break

    def _on_match_count(self, count: int):
        self._time_bar.set_count(count, len(self._entries))
        self._update_status(count)

    def _update_status(self, match_count: int | None = None):
        review_count  = sum(1 for e in self._entries if e["status"] == "Review")
        flagged_count = sum(1 for e in self._entries if e.get("flagged"))
        shown = match_count if match_count is not None else len(self._entries)
        self.statusBar().showMessage(
            f"Showing {shown} of {len(self._entries)} entries  ·  "
            f"Flagged: {flagged_count}  ·  In review: {review_count}  ·  "
            f"Ctrl+F: search  ·  Esc: clear"
        )

    def _add_note(self):
        dlg = AddNoteDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            note_text = dlg.note_field.toPlainText().strip()
            staff     = dlg.staff_field.text().strip()
            station   = dlg.station_field.text().strip() or "Back Office"
            now       = datetime.now()
            status    = dlg.get_status()
            new_entry = {
                "id":              max((e["id"] for e in self._entries), default=0) + 1,
                "icon":            "note",
                "activity":        f"Note: {note_text[:60]}{'…' if len(note_text)>60 else ''}",
                "detail":          note_text,
                "staff":           staff,
                "station":         station,
                "datetime":        now.strftime("%b %d, %I:%M %p"),
                "_dt":             now,
                "status":          status,
                "original_status": status,
                "flagged":         False,
                "audit":           [f"Now — Note added manually by {staff}"],
            }
            self._entries.insert(0, new_entry)
            self._table.add_entry(new_entry)
            self._update_status()
            show_toast(self.centralWidget(), "Note added to activity log", "ok")

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Activity Log", "activity_log.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path: return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["id","activity","detail","staff",
                                   "station","datetime","status","original_status","flagged"]
                )
                writer.writeheader()
                for e in self._entries:
                    writer.writerow({k: e.get(k,"") for k in writer.fieldnames})
            show_toast(self.centralWidget(), f"Exported {len(self._entries)} entries", "ok")
        except Exception as ex:
            QMessageBox.critical(self, "Export Failed", str(ex))

    def _view_exceptions(self):
        flagged = [e for e in self._entries if e.get("flagged") or e["status"]=="Review"]
        if not flagged:
            QMessageBox.information(self, "No Exceptions",
                                    "No entries are currently flagged for review. ✅")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Flagged Exceptions ({len(flagged)})")
        dlg.setMinimumSize(700, 480)
        dlg.setStyleSheet(
            f"QDialog{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        lay = QVBoxLayout(dlg); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(24,18,24,18)
        hl.addWidget(lbl(f"Flagged for Review — {len(flagged)} entries", bold=True, size=15))
        hl.addStretch()
        cb = make_btn("Close", C["accent"], hover=C["accent_dk"])
        cb.clicked.connect(dlg.accept); hl.addWidget(cb)
        lay.addWidget(hdr)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;")
        body = QWidget(); body.setStyleSheet(f"background:{C['white']};")
        bl = QVBoxLayout(body); bl.setContentsMargins(0,0,0,0); bl.setSpacing(0)
        for i, e in enumerate(flagged):
            row = ActivityRow(e, alt_bg=(i%2==1))
            row.view_requested.connect(lambda entry, d=dlg: (d.accept(), self._on_view_entry(entry)))
            row.copy_requested.connect(self._on_copy_entry)
            row.flag_requested.connect(lambda entry, d=dlg: (self._on_flag_entry(entry), d.accept()))
            bl.addWidget(row)
            if i < len(flagged)-1: bl.addWidget(hline())
        bl.addStretch()
        scroll.setWidget(body)
        lay.addWidget(scroll, stretch=1)
        dlg.exec()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Pawffinated Activity Log")
    win = ActivityLogWindow()
    win.show()
    sys.exit(app.exec())