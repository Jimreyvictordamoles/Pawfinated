"""
PAWFFINATED – Access Control  (PyQt6 + PostgreSQL · DB-Connected)
=================================================================
OWNER / ADMIN ONLY.

REDESIGN APPLIED (header / stats / filter bar):
  • Page header: taller, left green accent bar, generous padding, cleaner subtitle
  • Stats strip: taller cards (96px), large bold numbers, colored left-border pills,
    proper proportional spacing, no divider clutter
  • Filter tab bar: softer pill shape, count badges embedded, 38px height
  • Search bar: 38px height, rounded, icon padding, focus ring
  • Overall: more whitespace, consistent 28px horizontal gutters

ORIGINAL FIXES RETAINED:
  • DetailPanel cache removed — always rebuilds so every user click shows correct data
  • _on_action: removed duplicate _rebuild_action_bar() call
  • _clear_layout: recursively deletes nested QHBoxLayout rows used in card grid
  • RequestCard.update_req: properly deletes old layout before rebuilding
  • AuditDrawer close button: now correctly calls AccessControlWindow._toggle_audit
  • DB: get_clock_log_by_user returns [] gracefully when no matching records
  • Sort: datetime.min edge-case handled so users with no clock events sort last safely
"""

from __future__ import annotations

import copy
import csv
import io
import os
import sys
from datetime import datetime, date
from typing import Optional

try:
    from Sidebar import PawffinatedSidebar, get_current_user
    _HAVE_SIDEBAR = True
except ImportError:
    _HAVE_SIDEBAR = False
    def get_current_user():
        return None

try:
    from DbConnection import get_auth_db, get_staff_db, AuthDB, StaffDB
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    AuthDB = None
    StaffDB = None

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QSizePolicy, QStackedWidget,
    QToolBar, QSplitter, QLineEdit, QDialog, QDialogButtonBox,
    QTextEdit, QFileDialog, QMessageBox, QCalendarWidget, QCheckBox,
    QGroupBox,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve,
    QRect, QPoint, QSize, QDate,
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QBrush, QKeySequence, QShortcut,
    QPen, QPainterPath,
)

_SESSION_USER  = get_current_user() or {}
_USER_EMAIL    = _SESSION_USER.get("email",      os.environ.get("PAWFF_USER_EMAIL", ""))
_USER_FNAME    = _SESSION_USER.get("first_name", os.environ.get("PAWFF_USER_FIRST_NAME", ""))
_USER_LNAME    = _SESSION_USER.get("last_name",  os.environ.get("PAWFF_USER_LAST_NAME", ""))
_USER_NAME     = (
    f"{_USER_FNAME} {_USER_LNAME}".strip()
    or os.environ.get("PAWFF_USER_NAME", "Unknown")
)
_USER_IS_ADMIN = _SESSION_USER.get("is_admin", os.environ.get("PAWFF_USER_IS_ADMIN", "0") == "1")

C: dict[str, str] = dict(
    bg="#F7F5F0",
    sidebar="#FFFFFF",
    white="#FFFFFF",
    accent="#2D7A5F",
    accent_lt="#E8F4F0",
    accent_md="#C1E0D4",
    warn="#E07B39",
    warn_lt="#FFF7ED",
    danger="#D94F4F",
    danger_lt="#FEE2E2",
    ok="#059669",
    ok_lt="#D1FAE5",
    text="#1A1A1A",
    sub="#6B7280",
    sub_lt="#9CA3AF",
    border="#E5E7EB",
    border_md="#D1D5DB",
    pending="#F59E0B",
    pending_lt="#FFFBEB",
    toast_bg="#1A1A1A",
    splitter="#E5E7EB",
    hdr_bg="#FAFAFA",
)

PERM_DESC: dict[str, str] = {
    "Device Login":     "Allow access to this terminal",
    "Process Payments": "Ring up orders and accept cash/card",
    "Issue Refunds":    "Process returns and cancellations",
    "Modify Inventory": "Adjust stock levels manually",
    "View Reports":     "Access sales and performance data",
}

_ROLE_PERMS: dict[str, dict[str, bool]] = {
    "Administrator":    {"Device Login": True,  "Process Payments": True,  "Issue Refunds": True,  "Modify Inventory": True,  "View Reports": True},
    "Store Manager":    {"Device Login": True,  "Process Payments": True,  "Issue Refunds": True,  "Modify Inventory": True,  "View Reports": True},
    "Shift Supervisor": {"Device Login": True,  "Process Payments": True,  "Issue Refunds": True,  "Modify Inventory": True,  "View Reports": True},
    "Senior Barista":   {"Device Login": True,  "Process Payments": True,  "Issue Refunds": False, "Modify Inventory": False, "View Reports": False},
    "Barista":          {"Device Login": True,  "Process Payments": True,  "Issue Refunds": False, "Modify Inventory": False, "View Reports": False},
    "Cashier":          {"Device Login": True,  "Process Payments": True,  "Issue Refunds": False, "Modify Inventory": False, "View Reports": False},
    "Cashier Trainee":  {"Device Login": True,  "Process Payments": True,  "Issue Refunds": False, "Modify Inventory": False, "View Reports": False},
    "Kitchen Staff":    {"Device Login": False, "Process Payments": False, "Issue Refunds": False, "Modify Inventory": False, "View Reports": False},
}

_AVATAR_MAP = {
    "Administrator": "👑", "Store Manager": "🧑‍💼", "Shift Supervisor": "👨‍💼",
    "Senior Barista": "☕", "Barista": "☕", "Cashier": "💰",
    "Cashier Trainee": "👩", "Kitchen Staff": "👨‍🍳",
}

_STATION_DEVICE = {
    "Front Counter": "POS Terminal (Front Counter)",
    "Espresso Bar":  "POS Terminal (Espresso Bar)",
    "Drive-Thru":    "Drive-Thru Pad",
    "Back Office":   "Back Office Mac",
    "Kitchen":       "Kitchen Display",
    "Register 1":    "POS Terminal 01",
    "Register 2":    "POS Terminal 02",
}

_SESSION_STATUS: dict[int, str] = {}
_PAGE_ACCESS_GRANTS: dict[int, set] = {}

# All navigable tabs with their display metadata.
# Format: (section_label, emoji, tab_name, default_allowed_for_non_admin)
ALL_TABS: list[tuple[str, str, str, bool]] = [
    ("MAIN",       "📊", "Dashboard",       True),
    ("MAIN",       "📋", "Order",            True),
    ("MANAGEMENT", "📈", "Sales Monitor",    True),
    ("MANAGEMENT", "📦", "Inventory",        True),
    ("MANAGEMENT", "🍽️",  "Menu",            True),
    ("ADMIN",      "👥", "Staff Management", False),
    ("ADMIN",      "🔒", "Access Control",   False),
    ("ADMIN",      "📝", "Activity Log",     False),
]

# Default tabs non-admin users get (used when no explicit grant is set yet)
_DEFAULT_ALLOWED_TABS: set[str] = {t[2] for t in ALL_TABS if t[3]}


class AuditLog:
    def __init__(self) -> None:
        self._entries: list[dict] = []

    def record(self, req_id: int, name: str, action: str,
               operator: str = "Manager") -> None:
        self._entries.append({
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "req_id":    req_id,
            "name":      name,
            "action":    action,
            "operator":  operator,
        })

    def entries(self) -> list[dict]:
        return list(reversed(self._entries))

    def to_csv_string(self, all_requests: list[dict]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "ID", "Name", "Role", "Device", "Access Level", "Date", "Time",
            "Status", "Device Login", "Process Payments", "Issue Refunds",
            "Modify Inventory", "View Reports",
        ])
        for r in all_requests:
            perms = r.get("permissions", {})
            writer.writerow([
                r["id"], r["name"], r["role"], r["device"],
                r.get("access_level", r["role"]),
                r.get("date", ""), r.get("time", ""), r["status"].upper(),
                *["Yes" if perms.get(k) else "No" for k in [
                    "Device Login", "Process Payments", "Issue Refunds",
                    "Modify Inventory", "View Reports",
                ]],
            ])
        return buf.getvalue()


AUDIT = AuditLog()


def _build_requests_from_db(
    date_from: Optional[QDate] = None,
    date_to:   Optional[QDate] = None,
) -> list[dict]:
    if not _DB_AVAILABLE:
        return _demo_requests()

    try:
        adb = get_auth_db()
        sdb = get_staff_db()
        users = adb.get_all_users()
        all_tab_perms = adb.get_all_tab_permissions()  # {user_id: {tab: bool}}
    except Exception as exc:
        print(f"[AccessControl] DB error loading users: {exc}")
        return _demo_requests()

    df_str = date_from.toString("yyyy-MM-dd") if date_from else None
    dt_str = date_to.toString("yyyy-MM-dd")   if date_to   else None

    requests: list[dict] = []
    for u in users:
        uid   = u["id"]
        name  = f"{u['first_name']} {u['last_name']}"
        role  = u.get("role", "Staff")
        email = u.get("email", "")

        try:
            events = sdb.get_clock_log_by_user(uid)
        except Exception as exc:
            print(f"[AccessControl] clock log error for user {uid}: {exc}")
            events = []

        def _in_range(evt: dict) -> bool:
            ts = evt.get("timestamp")
            if ts is None:
                return True
            ts_date = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
            if df_str and ts_date < df_str:
                return False
            if dt_str and ts_date > dt_str:
                return False
            return True

        filtered_events = [e for e in events if _in_range(e)]
        clock_ins = [e for e in filtered_events if e.get("event_type") == "Clock In"]

        if clock_ins:
            latest = clock_ins[0]
            ts: datetime = latest["timestamp"]
            time_display = ts.strftime("%I:%M %p")
            date_display = ts.strftime("%b %d")
            time_sort = ts
        else:
            time_display = "Never"
            date_display = "—"
            time_sort = None

        station = u.get("station", "Front Counter")
        device  = _STATION_DEVICE.get(station, f"Device ({station})")
        perms   = _ROLE_PERMS.get(role, {k: False for k in PERM_DESC})
        status  = _SESSION_STATUS.get(uid, "pending")
        is_admin_user = bool(u.get("is_admin"))

        # Build page_grants: admins always get all tabs.
        # For others: start with role-default, apply DB overrides, then
        # apply any in-session changes from _PAGE_ACCESS_GRANTS.
        if is_admin_user:
            page_grants = {t[2] for t in ALL_TABS}
        else:
            # Start from default allowed tabs for the role
            base_grants = set(_DEFAULT_ALLOWED_TABS)
            # Apply DB-persisted overrides
            db_perms = all_tab_perms.get(uid, {})
            for tab_name, allowed in db_perms.items():
                if allowed:
                    base_grants.add(tab_name)
                else:
                    base_grants.discard(tab_name)
            # Apply in-session overrides (from this session's changes)
            if uid in _PAGE_ACCESS_GRANTS:
                page_grants = _PAGE_ACCESS_GRANTS[uid]
            else:
                page_grants = base_grants

        requests.append({
            "id":           uid,
            "name":         name,
            "role":         role,
            "email":        email,
            "avatar":       _AVATAR_MAP.get(role, "👤"),
            "device":       device,
            "device_full":  device,
            "time":         time_display,
            "time_display": time_display,
            "time_sort":    time_sort,
            "access_level": role,
            "date":         date_display,
            "status":       status,
            "permissions":  dict(perms),
            "is_admin":     is_admin_user,
            "station":      station,
            "page_grants":  page_grants,
            # Legacy fields kept for backward compat
            "page_access_control":   "Access Control" in page_grants,
            "page_staff_management": "Staff Management" in page_grants,
        })

    status_order = {"pending": 0, "approved": 1, "rejected": 2}
    requests.sort(key=lambda r: (
        status_order.get(r["status"], 9),
        -(r["time_sort"].timestamp() if r["time_sort"] is not None else 0),
    ))
    return requests


def _demo_requests() -> list[dict]:
    return [
        {
            "id": 1042, "name": "Jimrey Oppa", "role": "Cashier Trainee",
            "email": "jimrey@example.com",
            "avatar": "👩", "device": "POS Terminal 04",
            "device_full": "POS Terminal 04 (Front Counter)",
            "time": "10:42 AM", "time_display": "10:42 AM",
            "time_sort": datetime.now(),
            "access_level": "Standard POS", "date": "Oct 24", "status": "pending",
            "is_admin": False, "station": "Front Counter",
            "permissions": {
                "Device Login": True, "Process Payments": True,
                "Issue Refunds": False, "Modify Inventory": False, "View Reports": False,
            },
            "page_grants": set(_DEFAULT_ALLOWED_TABS),
            "page_access_control": False,
            "page_staff_management": False,
        },
    ]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def lbl(text: str = "", bold: bool = False, size: int = 13,
        color: Optional[str] = None) -> QLabel:
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


def card_frame(radius: int = 12) -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        f"QFrame{{background:{C['white']};border-radius:{radius}px;"
        f"border:1px solid {C['border']};}}"
    )
    return f


def _clear_layout(layout) -> None:
    """Recursively clears a layout, handling nested layouts."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        else:
            child_layout = item.layout()
            if child_layout is not None:
                _clear_layout(child_layout)


# ─── Widgets ──────────────────────────────────────────────────────────────────

class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)
    _TRACK_W = 44; _TRACK_H = 16; _THUMB_D = 20
    _THUMB_Y = 2; _THUMB_OFF = 2; _THUMB_ON = 22

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(self._TRACK_W, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def checked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool) -> None:
        if val != self._checked:
            self._checked = val
            self.update()

    def mousePressEvent(self, _) -> None:
        self._checked = not self._checked
        self.toggled.emit(self._checked)
        self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track_color = QColor(C["accent"]) if self._checked else QColor("#D1D5DB")
        p.setBrush(QBrush(track_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, self._THUMB_Y + 2, self._TRACK_W, self._TRACK_H, 8, 8)
        shadow_color = QColor(0, 0, 0, 30)
        p.setBrush(QBrush(shadow_color))
        thumb_x = self._THUMB_ON if self._checked else self._THUMB_OFF
        p.drawEllipse(thumb_x + 1, self._THUMB_Y + 2, self._THUMB_D, self._THUMB_D)
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.drawEllipse(thumb_x, self._THUMB_Y, self._THUMB_D, self._THUMB_D)


class AvatarLabel(QLabel):
    def __init__(self, emoji: str, size: int = 44, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setText(emoji)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_pt = max(10, int(size * 0.34))
        self.setStyleSheet(
            f"background:#E5EDEA;border-radius:{size // 2}px;"
            f"font-size:{font_pt}pt;border:none;"
        )


_STATUS_CFG: dict[str, tuple[str, str, str, str]] = {
    "pending":  (C["pending"],  C["pending_lt"], "⏳", "PENDING"),
    "approved": (C["ok"],       C["ok_lt"],      "✓",  "APPROVED"),
    "rejected": (C["danger"],   C["danger_lt"],  "✕",  "REJECTED"),
}


def status_badge(status: str) -> QLabel:
    fg, bg, icon, text = _STATUS_CFG.get(
        status, (C["sub"], C["border"], "?", status.upper())
    )
    w = QLabel(f"{icon}  {text}")
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(
        f"color:{fg};background:{bg};border-radius:5px;"
        f"padding:2px 10px;font-size:10px;font-weight:700;border:none;"
    )
    return w


class Toast(QWidget):
    def __init__(self, parent: QWidget, message: str,
                 color: str = C["accent"], duration_ms: int = 3000):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            f"background:{C['toast_bg']};border-radius:10px;"
            f"color:#FFFFFF;padding:10px 20px;"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color};font-size:10px;background:transparent;")
        lay.addWidget(dot)
        msg = QLabel(message)
        msg.setStyleSheet("color:#FFFFFF;font-size:12px;font-weight:600;background:transparent;")
        lay.addWidget(msg)
        self.adjustSize()
        self._position_bottom(parent)
        self.setWindowOpacity(0.0)
        self.show()
        self._anim_in = QPropertyAnimation(self, b"windowOpacity")
        self._anim_in.setDuration(200)
        self._anim_in.setEndValue(1.0)
        self._anim_in.start()
        QTimer.singleShot(duration_ms, self._fade_out)

    def _position_bottom(self, parent: QWidget) -> None:
        pw = parent.width(); ph = parent.height()
        w = max(self.width(), 280); h = self.height()
        self.setGeometry((pw - w) // 2, ph - h - 24, w, h)

    def _fade_out(self) -> None:
        self._anim_out = QPropertyAnimation(self, b"windowOpacity")
        self._anim_out.setDuration(300)
        self._anim_out.setEndValue(0.0)
        self._anim_out.finished.connect(self.deleteLater)
        self._anim_out.start()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.parent():
            self._position_bottom(self.parent())


class ConfirmDialog(QDialog):
    def __init__(self, action: str, req: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Action")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(
            f"QDialog{{background:{C['white']};border-radius:12px;}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 20)
        lay.setSpacing(16)

        is_approve = action == "approved"
        icon_text  = "✅" if is_approve else "🚫"
        verb       = "Approve" if is_approve else "Reject"
        color      = C["ok"] if is_approve else C["danger"]

        ic = QLabel(icon_text)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet("font-size:36px;background:transparent;")
        lay.addWidget(ic)

        title = lbl(f"{verb} Access Request #{req['id']}?", bold=True, size=14)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        body_text = (
            f"You are about to <b>{verb.lower()}</b> the access request from "
            f"<b>{req['name']}</b> ({req['role']}) for <b>{req['device']}</b>."
        )
        if not is_approve:
            body_text += "<br><br>This action will be logged in the audit trail."
        body = QLabel(body_text)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setStyleSheet(f"color:{C['sub']};font-size:12px;background:transparent;")
        lay.addWidget(body)

        if is_approve and _DB_AVAILABLE:
            db_note = QLabel("ℹ️  User permissions will be recorded in the audit log.")
            db_note.setWordWrap(True)
            db_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            db_note.setStyleSheet(
                f"color:{C['accent']};font-size:11px;background:{C['accent_lt']};"
                f"border-radius:6px;padding:6px 10px;border:none;"
            )
            lay.addWidget(db_note)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            f"QPushButton{{background:{C['white']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:8px;"
            f"font-size:13px;padding:8px 20px;}}"
            f"QPushButton:hover{{background:{C['bg']};}}"
        )
        confirm_btn = QPushButton(verb)
        confirm_btn.setStyleSheet(
            f"QPushButton{{background:{color};color:#FFFFFF;"
            f"border:none;border-radius:8px;"
            f"font-size:13px;font-weight:700;padding:8px 20px;}}"
        )
        cancel_btn.clicked.connect(self.reject)
        confirm_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(confirm_btn, stretch=1)
        lay.addLayout(btn_row)


class GrantPageAccessDialog(QDialog):
    def __init__(self, req: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Permissions & Tab Access")
        self.setModal(True)
        self.setFixedWidth(540)
        self.setStyleSheet(
            f"QDialog{{background:{C['white']};border-radius:12px;}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        self._req = req
        # Tab grants
        current = req.get("page_grants", set(_DEFAULT_ALLOWED_TABS))
        self._result_grants: set = set(current)
        self._toggles: dict[str, ToggleSwitch] = {}
        # Action permissions (copy so we don't mutate)
        self._result_perms: dict[str, bool] = dict(req.get("permissions", {}))
        self._perm_toggles: dict[str, ToggleSwitch] = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{C['accent']};border-radius:0px;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 18, 24, 18)
        icon_lbl = QLabel("🔑")
        icon_lbl.setStyleSheet("font-size:22px;background:transparent;")
        hl.addWidget(icon_lbl)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(lbl("Manage Permissions & Tab Access", bold=True, size=14, color="#FFFFFF"))
        title_col.addWidget(lbl(
            f"{self._req['name']}  ·  {self._req['role']}",
            size=11, color="rgba(255,255,255,0.8)"
        ))
        hl.addLayout(title_col)
        hl.addStretch()
        lay.addWidget(hdr)

        # ── Scrollable body ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C['white']};}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:5px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )

        body = QWidget()
        body.setStyleSheet(f"background:{C['white']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 16)
        bl.setSpacing(14)

        # ── Section 1: Action Permissions ─────────────────────────────────────
        bl.addWidget(lbl("ACTION PERMISSIONS", bold=True, size=9, color=C["sub"]))

        perm_frame = card_frame(10)
        pfl = QVBoxLayout(perm_frame)
        pfl.setContentsMargins(14, 4, 14, 4)
        pfl.setSpacing(0)

        is_admin_user = self._req.get("is_admin", False)
        perm_items = list(self._result_perms.items())
        for i, (pname, enabled) in enumerate(perm_items):
            # Build inline toggle row
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(0, 10, 0, 10)
            row_lay.setSpacing(12)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(lbl(pname, bold=True, size=12))
            col.addWidget(lbl(PERM_DESC.get(pname, ""), size=10, color=C["sub"]))
            row_lay.addLayout(col)
            row_lay.addStretch()
            toggle = ToggleSwitch(checked=enabled)
            toggle.toggled.connect(lambda checked, n=pname: self._toggle_perm(n, checked))
            if is_admin_user:
                toggle.setEnabled(False)
            self._perm_toggles[pname] = toggle
            row_lay.addWidget(toggle)
            pfl.addWidget(row_w)
            if i < len(perm_items) - 1:
                pfl.addWidget(hline())

        bl.addWidget(perm_frame)

        # ── Section 2: Tab Access ─────────────────────────────────────────────
        bl.addWidget(lbl("SIDEBAR TAB ACCESS", bold=True, size=9, color=C["sub"]))

        # Info banner
        info = QLabel(
            "Toggle which sidebar tabs this staff member can access. "
            "Changes are saved to the database and enforced immediately."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color:{C['sub']};font-size:11px;background:{C['bg']};"
            f"border-radius:8px;padding:10px 14px;border:none;"
        )
        bl.addWidget(info)

        if not is_admin_user:
            # ── Quick-select buttons ───────────────────────────────────────────
            quick_row = QHBoxLayout()
            quick_row.setSpacing(8)
            grant_all_btn = QPushButton("✓ Grant All")
            grant_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            grant_all_btn.setStyleSheet(
                f"QPushButton{{background:{C['ok_lt']};color:{C['ok']};"
                f"border:1px solid {C['ok']};border-radius:6px;"
                f"font-size:11px;font-weight:700;padding:5px 14px;}}"
                f"QPushButton:hover{{background:{C['ok']};color:white;}}"
            )
            grant_all_btn.clicked.connect(self._grant_all)
            quick_row.addWidget(grant_all_btn)

            revoke_all_btn = QPushButton("✕ Revoke All")
            revoke_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            revoke_all_btn.setStyleSheet(
                f"QPushButton{{background:{C['danger_lt']};color:{C['danger']};"
                f"border:1px solid {C['danger']};border-radius:6px;"
                f"font-size:11px;font-weight:700;padding:5px 14px;}}"
                f"QPushButton:hover{{background:{C['danger']};color:white;}}"
            )
            revoke_all_btn.clicked.connect(self._revoke_all)
            quick_row.addWidget(revoke_all_btn)

            reset_btn = QPushButton("↺ Reset to Default")
            reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            reset_btn.setStyleSheet(
                f"QPushButton{{background:{C['bg']};color:{C['sub']};"
                f"border:1px solid {C['border']};border-radius:6px;"
                f"font-size:11px;font-weight:600;padding:5px 14px;}}"
                f"QPushButton:hover{{background:{C['border']};}}"
            )
            reset_btn.clicked.connect(self._reset_defaults)
            quick_row.addWidget(reset_btn)
            quick_row.addStretch()
            bl.addLayout(quick_row)

        # ── Tab cards grouped by section ───────────────────────────────────────
        _SECTION_ICONS = {"MAIN": "🏠", "MANAGEMENT": "📊", "ADMIN": "🔐"}
        _SECTION_LABELS = {"MAIN": "Main", "MANAGEMENT": "Management", "ADMIN": "Admin"}

        prev_section = None
        for section, tab_icon, tab_name, _default in ALL_TABS:
            if section != prev_section:
                sec_frame = QFrame()
                sec_frame.setStyleSheet(
                    f"QFrame{{background:{C['bg']};border-radius:6px;border:none;}}"
                )
                sf_lay = QHBoxLayout(sec_frame)
                sf_lay.setContentsMargins(10, 5, 10, 5)
                sec_lbl = lbl(
                    f"{_SECTION_ICONS.get(section, '📌')}  {_SECTION_LABELS.get(section, section)}",
                    bold=True, size=10, color=C["sub"]
                )
                sf_lay.addWidget(sec_lbl)
                sf_lay.addStretch()
                bl.addWidget(sec_frame)
                prev_section = section

            is_admin_only = not _default
            card = self._make_tab_card(tab_icon, tab_name, is_admin_only, is_admin_user)
            bl.addWidget(card)

        bl.addStretch()
        scroll.setWidget(body)
        lay.addWidget(scroll)

        # ── Footer ─────────────────────────────────────────────────────────────
        footer = QWidget()
        footer.setStyleSheet(f"background:{C['white']};border-top:1px solid {C['border']};")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 14, 24, 14)
        fl.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            f"QPushButton{{background:{C['bg']};border:1px solid {C['border']};"
            f"border-radius:8px;padding:8px 20px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:#E5E7EB;}}"
        )
        cancel_btn.clicked.connect(self.reject)
        fl.addWidget(cancel_btn)

        save_btn = QPushButton("💾  Save Permissions & Access")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:white;"
            f"border-radius:8px;padding:8px 22px;font-size:12px;font-weight:700;border:none;}}"
            f"QPushButton:hover{{background:#245f4a;}}"
        )
        save_btn.clicked.connect(self.accept)
        fl.addWidget(save_btn)
        lay.addWidget(footer)

    def _make_tab_card(self, tab_icon: str, tab_name: str,
                       is_admin_only: bool, is_admin_user: bool) -> QFrame:
        granted = tab_name in self._result_grants
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:{C['bg']};border-radius:10px;"
            f"border:1px solid {C['border']};}}"
        )
        cl = QHBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(12)

        ic = QLabel(tab_icon)
        ic.setFixedSize(36, 36)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(f"background:{C['white']};border-radius:8px;font-size:16px;border:none;")
        cl.addWidget(ic)

        txt_col = QVBoxLayout()
        txt_col.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_row.addWidget(lbl(tab_name, bold=True, size=12))
        if is_admin_only:
            badge = QLabel("Admin-only")
            badge.setStyleSheet(
                f"color:{C['warn']};background:{C['warn_lt']};border-radius:4px;"
                f"padding:1px 6px;font-size:9px;font-weight:700;border:none;"
            )
            name_row.addWidget(badge)
        name_row.addStretch()
        txt_col.addLayout(name_row)

        desc_map = {
            "Dashboard":       "Overview of sales, activity, and key metrics",
            "Order":           "Process customer orders at the POS terminal",
            "Sales Monitor":   "View sales history, trends, and reports",
            "Inventory":       "Manage stock levels and product inventory",
            "Menu":            "Browse and manage the menu catalog",
            "Staff Management":"View staff profiles, roles, and schedules",
            "Access Control":  "Approve/reject logins and manage permissions",
            "Activity Log":    "Review system events and staff activity",
        }
        desc = lbl(desc_map.get(tab_name, ""), size=10, color=C["sub"])
        desc.setWordWrap(True)
        txt_col.addWidget(desc)
        cl.addLayout(txt_col, stretch=1)

        # Admin users always have all tabs — show lock instead of toggle
        if is_admin_user:
            lock_lbl = QLabel("🔓 Always")
            lock_lbl.setStyleSheet(
                f"color:{C['ok']};font-size:10px;font-weight:700;background:transparent;"
            )
            cl.addWidget(lock_lbl)
        else:
            toggle = ToggleSwitch(checked=granted)
            toggle.toggled.connect(lambda checked, n=tab_name: self._toggle_grant(n, checked))
            self._toggles[tab_name] = toggle
            cl.addWidget(toggle)

        return card

    def _toggle_grant(self, tab_name: str, checked: bool) -> None:
        if checked:
            self._result_grants.add(tab_name)
        else:
            self._result_grants.discard(tab_name)

    def _toggle_perm(self, perm_name: str, checked: bool) -> None:
        self._result_perms[perm_name] = checked

    def _grant_all(self) -> None:
        for tab_name, toggle in self._toggles.items():
            toggle.setChecked(True)
            self._result_grants.add(tab_name)

    def _revoke_all(self) -> None:
        for tab_name, toggle in self._toggles.items():
            toggle.setChecked(False)
            self._result_grants.discard(tab_name)

    def _reset_defaults(self) -> None:
        for tab_name, toggle in self._toggles.items():
            default_on = tab_name in _DEFAULT_ALLOWED_TABS
            toggle.setChecked(default_on)
            if default_on:
                self._result_grants.add(tab_name)
            else:
                self._result_grants.discard(tab_name)

    def get_grants(self) -> set:
        return self._result_grants

    def get_permissions(self) -> dict[str, bool]:
        return self._result_perms


class DateRangeDialog(QDialog):
    def __init__(self, current_from: QDate, current_to: QDate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter by Date Range")
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
        hl.addWidget(lbl("📅  Filter Access Requests by Date", bold=True, size=15, color="#FFFFFF"))
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
            f"QFrame{{background:{C['white']};border-radius:10px;border:1px solid {C['border']};}}"
        )
        pfl = QVBoxLayout(presets_frame)
        pfl.setContentsMargins(12, 14, 12, 14)
        pfl.setSpacing(6)
        pfl.addWidget(lbl("Quick Select", bold=True, size=11, color=C["sub"]))

        today = QDate.currentDate()
        presets = [
            ("Today",        today, today),
            ("Yesterday",    today.addDays(-1), today.addDays(-1)),
            ("Last 7 Days",  today.addDays(-6), today),
            ("Last 30 Days", today.addDays(-29), today),
            ("This Month",   QDate(today.year(), today.month(), 1), today),
            ("All Time",     QDate(2020, 1, 1), today),
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
        from_col.addWidget(lbl("From", bold=True, size=12))
        self._cal_from = QCalendarWidget()
        self._cal_from.setSelectedDate(self._from)
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

        footer = QWidget()
        footer.setStyleSheet(f"background:{C['white']};border-top:1px solid {C['border']};")
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
            f"border-radius:7px;padding:7px 22px;font-size:12px;font-weight:700;border:none;}}"
            f"QPushButton:hover{{background:#245f4a;}}"
        )
        apply_btn.clicked.connect(self.accept)
        fl.addWidget(apply_btn)
        lay.addWidget(footer)

    def _cal_style(self) -> str:
        return f"""
        QCalendarWidget QAbstractItemView {{
            selection-background-color: {C['accent']};
            selection-color: white; font-size: 11px;
        }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background: {C['accent']}; border-radius: 8px;
        }}
        QCalendarWidget QToolButton {{
            color: white; background: transparent;
            border: none; font-weight: 700;
        }}
        QCalendarWidget QToolButton:hover {{
            background: rgba(255,255,255,0.2); border-radius: 4px;
        }}
        QCalendarWidget QSpinBox {{
            color: white; background: transparent;
            border: none; font-weight: 700;
        }}
        """

    def _apply_preset(self, d_from: QDate, d_to: QDate):
        self._from = d_from; self._to = d_to
        self._cal_from.setSelectedDate(d_from)
        self._cal_to.setSelectedDate(d_to)
        self._update_range_lbl()

    def _on_from_changed(self):
        self._from = self._cal_from.selectedDate()
        if self._from > self._to:
            self._to = self._from
            self._cal_to.setSelectedDate(self._to)
        self._update_range_lbl()

    def _on_to_changed(self):
        self._to = self._cal_to.selectedDate()
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


class AuditDrawer(QWidget):
    def __init__(self, parent: QWidget, toggle_callback=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#AuditDrawer{{background:{C['white']};"
            f"border-left:2px solid {C['border']};}}"
        )
        self.setObjectName("AuditDrawer")
        self.setFixedWidth(320)
        self._toggle_callback = toggle_callback
        self.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{C['accent']};border-bottom:1px solid {C['border']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        ic = QLabel("🔒")
        ic.setStyleSheet("font-size:16px;background:transparent;")
        hl.addWidget(ic)
        hl.addWidget(lbl("  Audit Log", bold=True, size=13, color="#FFFFFF"))
        hl.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.2);color:white;"
            "border:none;font-size:13px;border-radius:14px;font-weight:700;}"
            "QPushButton:hover{background:rgba(255,255,255,0.35);}"
        )
        close_btn.clicked.connect(self._on_close)
        hl.addWidget(close_btn)
        lay.addWidget(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C['bg']};}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:5px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )
        self._body = QWidget()
        self._body.setStyleSheet(f"background:{C['bg']};")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(12, 12, 12, 12)
        self._body_lay.setSpacing(8)
        self._scroll.setWidget(self._body)
        lay.addWidget(self._scroll, stretch=1)

        self._empty_lbl = lbl("No actions recorded yet.", size=11, color=C["sub"])
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body_lay.addStretch()
        self._body_lay.addWidget(self._empty_lbl)
        self._body_lay.addStretch()

    def _on_close(self) -> None:
        if self._toggle_callback is not None:
            self._toggle_callback()

    def refresh(self) -> None:
        _clear_layout(self._body_lay)
        entries = AUDIT.entries()
        if not entries:
            self._body_lay.addStretch()
            empty = lbl("No actions recorded yet.", size=11, color=C["sub"])
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._body_lay.addWidget(empty)
            self._body_lay.addStretch()
            return

        for e in entries:
            card = QFrame()
            action_color = C["ok"] if e["action"] == "approved" else (
                C["accent"] if "access" in e["action"].lower() else C["danger"]
            )
            card.setStyleSheet(
                f"QFrame{{background:{C['white']};border-radius:8px;"
                f"border-left:3px solid {action_color};"
                f"border-top:1px solid {C['border']};"
                f"border-right:1px solid {C['border']};"
                f"border-bottom:1px solid {C['border']};}}"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(4)

            action_icon = "✓" if e["action"] == "approved" else (
                "🔑" if "access" in e["action"].lower() else "✕"
            )
            top = QHBoxLayout()
            top.addWidget(lbl(f"{action_icon}  #{e['req_id']}", bold=True, size=11, color=action_color))
            top.addStretch()
            top.addWidget(lbl(e["timestamp"], size=9, color=C["sub"]))
            cl.addLayout(top)
            cl.addWidget(lbl(e["name"], bold=True, size=11))
            action_text = e["action"].capitalize().replace("_", " ")
            cl.addWidget(lbl(f"{action_text} by {e['operator']}", size=10, color=C["sub"]))
            self._body_lay.addWidget(card)

        self._body_lay.addStretch()


# ─── REDESIGNED: Search Bar ───────────────────────────────────────────────────

class SearchBar(QWidget):
    search_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self.setFixedHeight(38)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Wrapper frame gives the full pill its background + border
        wrapper = QFrame()
        wrapper.setFixedHeight(38)
        wrapper.setStyleSheet(
            f"QFrame{{background:{C['white']};border:1.5px solid {C['border_md']};"
            f"border-radius:19px;}}"
            f"QFrame:focus-within{{border-color:{C['accent']};}}"
        )
        wl = QHBoxLayout(wrapper)
        wl.setContentsMargins(14, 0, 10, 0)
        wl.setSpacing(8)

        search_icon = QLabel("🔍")
        search_icon.setStyleSheet("font-size:13px;background:transparent;border:none;")
        wl.addWidget(search_icon)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Search by name, role, or device…")
        self._edit.setFixedHeight(34)
        self._edit.setStyleSheet(
            f"QLineEdit{{background:transparent;border:none;"
            f"font-size:12px;color:{C['text']};padding:0;}}"
        )
        self._edit.textChanged.connect(self.search_changed)
        wl.addWidget(self._edit, stretch=1)

        clear = QPushButton("✕")
        clear.setFixedSize(22, 22)
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['sub_lt']};border:none;font-size:11px;}}"
            f"QPushButton:hover{{color:{C['text']};}}"
        )
        clear.clicked.connect(self._edit.clear)
        wl.addWidget(clear)
        lay.addWidget(wrapper)

    def text(self) -> str:
        return self._edit.text()


# ─── REDESIGNED: Filter Tab Bar ───────────────────────────────────────────────

class FilterTabBar(QWidget):
    filter_changed = pyqtSignal(str)
    TABS = ["All Users", "Pending", "Approved", "Rejected"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self._current = "All Users"
        self._btns: dict[str, QPushButton] = {}
        self._counts: dict[str, int] = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        for tab in self.TABS:
            btn = QPushButton(tab)
            btn.setFixedHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btns[tab] = btn
            self._style(btn, tab == self._current)
            btn.clicked.connect(lambda _, t=tab: self._select(t))
            lay.addWidget(btn)
        lay.addStretch()

    def _label_text(self, tab: str) -> str:
        count = self._counts.get(tab, 0)
        if tab == "Pending" and count:
            return f"Pending  {count}"
        return tab

    def _style(self, btn: QPushButton, active: bool) -> None:
        tab = btn.text().split("  ")[0].strip()  # strip count suffix if any
        is_pending_with_count = (tab == "Pending" and self._counts.get("Pending", 0) > 0)

        if active:
            btn.setStyleSheet(
                f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                f"border:none;border-radius:18px;font-size:12px;"
                f"font-weight:700;padding:0 18px;}}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton{{background:{C['white']};color:{C['text']};"
                f"border:1.5px solid {C['border_md']};border-radius:18px;"
                f"font-size:12px;font-weight:500;padding:0 16px;}}"
                f"QPushButton:hover{{background:{C['accent_lt']};"
                f"border-color:{C['accent_md']};color:{C['accent']};}}"
            )

    def _select(self, tab: str) -> None:
        for name, btn in self._btns.items():
            self._style(btn, name == tab)
        self._current = tab
        self.filter_changed.emit(tab)

    def set_pending_count(self, n: int) -> None:
        self._counts["Pending"] = n
        btn = self._btns.get("Pending")
        if btn:
            label = f"Pending  {n}" if n else "Pending"
            btn.setText(label)
            btn.adjustSize()
            btn.setMinimumWidth(0)
            self._style(btn, self._current == "Pending")

    @property
    def current(self) -> str:
        return self._current


class RequestCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, req: dict, parent=None):
        super().__init__(parent)
        self._req = req
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(168)
        self._apply_style()
        self._build()

    def _apply_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"QFrame{{background:{C['white']};border-radius:12px;border:2px solid {C['accent']};}}"
            )
        else:
            self.setStyleSheet(
                f"QFrame{{background:{C['white']};border-radius:12px;border:1px solid {C['border']};}}"
                f"QFrame:hover{{border-color:#A8C8BD;background:#FAFAF8;}}"
            )

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(AvatarLabel(self._req["avatar"], 38))
        nc = QVBoxLayout()
        nc.setSpacing(1)
        name_lbl = lbl(self._req["name"], bold=True, size=12)
        name_lbl.setMaximumWidth(160)
        nc.addWidget(name_lbl)
        nc.addWidget(lbl(self._req["role"], size=10, color=C["sub"]))
        top.addLayout(nc)
        top.addStretch()
        top.addWidget(status_badge(self._req["status"]))
        lay.addLayout(top)

        lay.addWidget(hline())

        info_grid = QWidget()
        info_grid.setStyleSheet("background:transparent;")
        ig_lay = QVBoxLayout(info_grid)
        ig_lay.setContentsMargins(0, 0, 0, 0)
        ig_lay.setSpacing(4)

        for icon_ch, label_text, value in [
            ("🖥", "Device", self._req["device"]),
            ("🕐", "Time",   self._req["time_display"]),
            ("📅", "Date",   self._req["date"]),
        ]:
            row = QHBoxLayout()
            row.setSpacing(6)
            ic = QLabel(icon_ch)
            ic.setFixedSize(16, 16)
            ic.setStyleSheet("font-size:10px;background:transparent;")
            row.addWidget(ic)
            row.addWidget(lbl(label_text, size=10, color=C["sub"]))
            row.addStretch()
            val_lbl = lbl(value, bold=True, size=10)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(val_lbl)
            ig_lay.addLayout(row)

        lay.addWidget(info_grid)

        if self._req.get("is_admin"):
            admin_row = QHBoxLayout()
            admin_badge = QLabel("👑 Admin")
            admin_badge.setStyleSheet(
                f"color:{C['warn']};background:{C['warn_lt']};border-radius:4px;"
                f"padding:1px 8px;font-size:9px;font-weight:700;border:none;"
            )
            admin_row.addWidget(admin_badge)
            admin_row.addStretch()
            lay.addLayout(admin_row)
        else:
            # Show tab access summary for non-admin users
            grants = self._req.get("page_grants", set(_DEFAULT_ALLOWED_TABS))
            total  = len(ALL_TABS)
            count  = len(grants)
            if count > 0:
                access_row = QHBoxLayout()
                restricted_tabs = [t[2] for t in ALL_TABS if t[2] not in grants]
                if not restricted_tabs:
                    badge_text  = f"🔓 All {total} tabs"
                    badge_color = C["ok"]
                    badge_bg    = C["ok_lt"]
                elif count >= total // 2:
                    badge_text  = f"🔒 {count}/{total} tabs"
                    badge_color = C["accent"]
                    badge_bg    = C["accent_lt"]
                else:
                    badge_text  = f"⚠ {count}/{total} tabs"
                    badge_color = C["warn"]
                    badge_bg    = C["warn_lt"]
                tab_badge = QLabel(badge_text)
                tab_badge.setStyleSheet(
                    f"color:{badge_color};background:{badge_bg};border-radius:4px;"
                    f"padding:1px 7px;font-size:9px;font-weight:700;border:none;"
                )
                access_row.addWidget(tab_badge)
                access_row.addStretch()
                lay.addLayout(access_row)

    def set_selected(self, val: bool) -> None:
        self._selected = val
        self._apply_style()

    def update_req(self, req: dict) -> None:
        self._req = req
        old_layout = self.layout()
        if old_layout is not None:
            _clear_layout(old_layout)
            QWidget().setLayout(old_layout)
        self._build()
        self._apply_style()

    def matches_search(self, query: str) -> bool:
        if not query:
            return True
        q = query.lower()
        return any(q in str(self._req.get(k, "")).lower()
                   for k in ("name", "role", "device", "access_level", "status", "email"))

    def mousePressEvent(self, e) -> None:
        self.clicked.emit(self._req)
        super().mousePressEvent(e)


class PermissionRow(QWidget):
    def __init__(self, name: str, enabled: bool, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(lbl(name, bold=True, size=12))
        col.addWidget(lbl(PERM_DESC.get(name, ""), size=10, color=C["sub"]))
        lay.addLayout(col)
        lay.addStretch()
        self._toggle = ToggleSwitch(checked=enabled)
        lay.addWidget(self._toggle)

    def is_enabled(self) -> bool:
        return self._toggle.checked

    def set_enabled(self, val: bool) -> None:
        self._toggle.setChecked(val)


class DetailPanel(QWidget):
    action_taken = pyqtSignal(int, str)
    page_access_changed = pyqtSignal(int, set)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._req: Optional[dict] = None
        self._perm_rows: list[PermissionRow] = []

        self.setStyleSheet(f"background:{C['white']};border-left:1px solid {C['border']};")
        self.setMinimumWidth(280)
        self.setMaximumWidth(440)

        self._root_lay = QVBoxLayout(self)
        self._root_lay.setContentsMargins(0, 0, 0, 0)
        self._root_lay.setSpacing(0)

        ph = QWidget()
        ph.setStyleSheet(f"background:{C['white']};")
        phl = QVBoxLayout(ph)
        phl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl = QLabel("🔐")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size:40px;background:transparent;")
        phl.addWidget(icon_lbl)
        ph_txt = lbl("Select a request\nto view details", size=12, color=C["sub"])
        ph_txt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        phl.addWidget(ph_txt)

        self._detail_w = QWidget()
        self._detail_w.setStyleSheet("background:transparent;")
        self._detail_lay = QVBoxLayout(self._detail_w)
        self._detail_lay.setContentsMargins(0, 0, 0, 0)
        self._detail_lay.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(ph)
        self._stack.addWidget(self._detail_w)
        self._root_lay.addWidget(self._stack)

    def load(self, req: dict, force_rebuild: bool = False) -> None:
        self._req = req
        self._rebuild(req)
        self._stack.setCurrentIndex(1)

    def _rebuild(self, req: dict) -> None:
        _clear_layout(self._detail_lay)
        self._perm_rows = []

        hdr = QWidget()
        hdr.setFixedHeight(48)
        hdr.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.addWidget(lbl(f"#{req['id']}  {req['name']}", bold=True, size=13))
        hl.addStretch()
        hl.addWidget(status_badge(req["status"]))
        self._detail_lay.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C['white']};}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:5px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )

        body = QWidget()
        body.setStyleSheet(f"background:{C['white']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 20, 20, 20)
        bl.setSpacing(14)

        av_row = QHBoxLayout()
        av_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        av_row.addWidget(AvatarLabel(req["avatar"], 64))
        bl.addLayout(av_row)
        name_lbl = lbl(req["name"], bold=True, size=15)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(name_lbl)
        role_lbl = lbl(req["role"], size=11, color=C["sub"])
        role_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(role_lbl)

        if req.get("email"):
            email_lbl = lbl(req["email"], size=10, color=C["accent"])
            email_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bl.addWidget(email_lbl)

        if req.get("is_admin"):
            adm = QLabel("👑  Administrator Account")
            adm.setAlignment(Qt.AlignmentFlag.AlignCenter)
            adm.setStyleSheet(
                f"color:{C['warn']};background:{C['warn_lt']};border-radius:6px;"
                f"padding:4px 12px;font-size:11px;font-weight:700;border:none;"
            )
            bl.addWidget(adm)

        grants = req.get("page_grants", set(_DEFAULT_ALLOWED_TABS))
        if grants and not req.get("is_admin"):
            restricted = [t[2] for t in ALL_TABS if t[2] not in grants]
            total = len(ALL_TABS)
            count = len(grants)
            if not restricted:
                summary_text  = f"🔓 Full tab access ({total}/{total})"
                summary_color = C["ok"]
                summary_bg    = C["ok_lt"]
            else:
                summary_text  = f"🔒 {count}/{total} tabs accessible"
                summary_color = C["accent"]
                summary_bg    = C["accent_lt"]
            summary_lbl = QLabel(summary_text)
            summary_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            summary_lbl.setStyleSheet(
                f"color:{summary_color};background:{summary_bg};border-radius:5px;"
                f"padding:3px 10px;font-size:10px;font-weight:700;border:none;"
            )
            bl.addWidget(summary_lbl)

        ctx = card_frame(10)
        ctx_l = QVBoxLayout(ctx)
        ctx_l.setContentsMargins(14, 14, 14, 14)
        ctx_l.setSpacing(0)
        ctx_l.addWidget(lbl("LOGIN CONTEXT", size=9, bold=True, color=C["sub"]))
        ctx_l.addSpacing(10)

        for icon_ch, subtitle, value in [
            ("🖥", "Requested Device",   req["device_full"]),
            ("🕐", "Last Login Attempt", f"{req['date']}, {req['time']}"),
            ("🔑", "Access Level",       req["access_level"]),
            ("📍", "Station",            req.get("station", "—")),
        ]:
            row = QHBoxLayout()
            row.setSpacing(10)
            ic = QLabel(icon_ch)
            ic.setFixedSize(28, 28)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic.setStyleSheet(f"background:{C['accent_lt']};border-radius:6px;font-size:13px;border:none;")
            row.addWidget(ic)
            vc = QVBoxLayout()
            vc.setSpacing(1)
            vc.addWidget(lbl(subtitle, size=9, color=C["sub"]))
            vc.addWidget(lbl(value, bold=True, size=11))
            row.addLayout(vc)
            ctx_l.addLayout(row)
            ctx_l.addSpacing(8)
        bl.addWidget(ctx)

        db_pill = QLabel("🔗  Live data" if _DB_AVAILABLE else "⚠️  Demo mode")
        db_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        db_pill.setStyleSheet(
            f"color:{C['accent'] if _DB_AVAILABLE else C['warn']};"
            f"background:{C['accent_lt'] if _DB_AVAILABLE else C['warn_lt']};"
            f"border-radius:5px;padding:3px 12px;font-size:10px;"
            f"font-weight:600;border:none;"
        )
        bl.addWidget(db_pill)

        bl.addWidget(lbl("CONFIGURE PERMISSIONS & TAB ACCESS", size=9, bold=True, color=C["sub"]))

        perm_tab_card = card_frame(10)
        ptl = QVBoxLayout(perm_tab_card)
        ptl.setContentsMargins(14, 12, 14, 12)
        ptl.setSpacing(0)

        # ── Sub-header: Action Permissions ────────────────────────────────────
        ptl.addWidget(lbl("Action Permissions", bold=True, size=11, color=C["text"]))
        ptl.addSpacing(4)
        action_desc = lbl(
            "Controls what operations this user can perform.",
            size=10, color=C["sub"]
        )
        action_desc.setWordWrap(True)
        ptl.addWidget(action_desc)
        ptl.addSpacing(8)

        items = list(req["permissions"].items())
        for i, (pname, enabled) in enumerate(items):
            pr = PermissionRow(pname, enabled)
            self._perm_rows.append(pr)
            ptl.addWidget(pr)
            if i < len(items) - 1:
                ptl.addWidget(hline())

        ptl.addSpacing(14)
        ptl.addWidget(hline())
        ptl.addSpacing(14)

        # ── Sub-header: Tab Access ────────────────────────────────────────────
        ptl.addWidget(lbl("Sidebar Tab Access", bold=True, size=11, color=C["text"]))
        ptl.addSpacing(4)

        grants_now = req.get("page_grants", set(_DEFAULT_ALLOWED_TABS))
        is_admin_user = req.get("is_admin", False)

        if is_admin_user:
            adm_note = lbl("👑  Admin — full access to all tabs (cannot be restricted)", size=10, color=C["warn"])
            adm_note.setWordWrap(True)
            ptl.addWidget(adm_note)
        else:
            tab_desc = lbl(
                "Controls which sidebar tabs this user can navigate to. "
                "Changes are saved to the database immediately.",
                size=10, color=C["sub"]
            )
            tab_desc.setWordWrap(True)
            ptl.addWidget(tab_desc)
            ptl.addSpacing(8)

            # Summary rows: show all tabs with granted/restricted status inline
            for _section, tab_icon, tab_name, _default in ALL_TABS:
                is_granted = tab_name in grants_now
                row = QHBoxLayout()
                row.setSpacing(6)
                ic2 = QLabel(tab_icon)
                ic2.setFixedSize(20, 20)
                ic2.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ic2.setStyleSheet("font-size:11px;background:transparent;border:none;")
                row.addWidget(ic2)
                row.addWidget(lbl(tab_name, size=10))
                row.addStretch()
                status_lbl = QLabel("✓" if is_granted else "✕")
                status_lbl.setStyleSheet(
                    f"color:{C['ok']};font-size:11px;font-weight:700;background:transparent;"
                    if is_granted else
                    f"color:{C['danger']};font-size:11px;font-weight:700;background:transparent;"
                )
                row.addWidget(status_lbl)
                ptl.addLayout(row)
                ptl.addSpacing(4)

        ptl.addSpacing(8)
        manage_btn = QPushButton("🔑  Manage Permissions & Tab Access")
        manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent_lt']};color:{C['accent']};"
            f"border:1px solid {C['accent']};border-radius:8px;"
            f"font-size:11px;font-weight:700;padding:7px 14px;}}"
            f"QPushButton:hover{{background:{C['accent']};color:#FFFFFF;}}"
        )
        manage_btn.clicked.connect(lambda: self._open_grant_dialog())
        ptl.addWidget(manage_btn)

        bl.addWidget(perm_tab_card)

        bl.addStretch()
        scroll.setWidget(body)
        self._detail_lay.addWidget(scroll, stretch=1)

        self._rebuild_action_bar(req)

    def _open_grant_dialog(self) -> None:
        if not self._req:
            return
        dlg = GrantPageAccessDialog(self._req, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_grants = dlg.get_grants()
            new_perms  = dlg.get_permissions()
            uid        = self._req["id"]
            old_grants = self._req.get("page_grants", set(_DEFAULT_ALLOWED_TABS))

            # ── Persist tab grants to DB ──────────────────────────────────────
            if _DB_AVAILABLE:
                try:
                    grants_map = {t[2]: (t[2] in new_grants) for t in ALL_TABS}
                    get_auth_db().set_tab_permissions(
                        uid, grants_map,
                        granted_by=_USER_NAME or "Manager",
                    )
                except Exception as exc:
                    print(f"[AccessControl] DB error saving tab permissions: {exc}")

            # ── In-session cache ──────────────────────────────────────────────
            _PAGE_ACCESS_GRANTS[uid] = new_grants

            # ── Audit log: tab changes ────────────────────────────────────────
            for pg in new_grants - old_grants:
                AUDIT.record(uid, self._req["name"],
                             f"granted_{pg.lower().replace(' ', '_')}",
                             operator=_USER_NAME or "Manager")
            for pg in old_grants - new_grants:
                AUDIT.record(uid, self._req["name"],
                             f"revoked_{pg.lower().replace(' ', '_')}",
                             operator=_USER_NAME or "Manager")

            # ── Audit log: permission changes ─────────────────────────────────
            old_perms = self._req.get("permissions", {})
            for pname, new_val in new_perms.items():
                if old_perms.get(pname) != new_val:
                    verb = "enabled" if new_val else "disabled"
                    AUDIT.record(uid, self._req["name"],
                                 f"{verb}_{pname.lower().replace(' ', '_')}",
                                 operator=_USER_NAME or "Manager")

            # ── Update local req dict ─────────────────────────────────────────
            self._req["page_grants"]          = new_grants
            self._req["permissions"]          = new_perms
            self._req["page_access_control"]   = "Access Control" in new_grants
            self._req["page_staff_management"] = "Staff Management" in new_grants
            self.page_access_changed.emit(uid, new_grants)
            self.load(self._req)

    def _rebuild_action_bar(self, req: dict) -> None:
        for i in range(self._detail_lay.count()):
            item = self._detail_lay.itemAt(i)
            if item and item.widget() and item.widget().property("is_action_bar"):
                w = self._detail_lay.takeAt(i).widget()
                w.setParent(None)
                w.deleteLater()
                break

        if req["status"] == "pending":
            bar = QWidget()
            bar.setProperty("is_action_bar", True)
            bar.setStyleSheet(f"background:{C['white']};border-top:1px solid {C['border']};")
            bb = QHBoxLayout(bar)
            bb.setContentsMargins(20, 14, 20, 14)
            bb.setSpacing(12)
            hint = lbl("A = Approve  ·  R = Reject", size=9, color=C["sub"])
            bb.addWidget(hint)
            bb.addStretch()
            rej = QPushButton("✕  Reject")
            rej.setCursor(Qt.CursorShape.PointingHandCursor)
            rej.setFixedHeight(40)
            rej.setStyleSheet(
                f"QPushButton{{background:{C['white']};color:{C['danger']};"
                f"border:2px solid {C['danger']};border-radius:8px;"
                f"font-size:12px;font-weight:700;padding:0 14px;}}"
                f"QPushButton:hover{{background:{C['danger_lt']};}}"
            )
            rej.clicked.connect(lambda: self._confirm_act("rejected"))
            apr = QPushButton("✓  Approve")
            apr.setCursor(Qt.CursorShape.PointingHandCursor)
            apr.setFixedHeight(40)
            apr.setStyleSheet(
                f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                f"border:none;border-radius:8px;"
                f"font-size:12px;font-weight:700;padding:0 14px;}}"
                f"QPushButton:hover{{background:#236850;}}"
            )
            apr.clicked.connect(lambda: self._confirm_act("approved"))
            bb.addWidget(rej)
            bb.addWidget(apr)
            self._detail_lay.addWidget(bar)

        elif req["status"] == "approved":
            bar = QWidget()
            bar.setProperty("is_action_bar", True)
            bar.setStyleSheet(f"background:{C['ok_lt']};border-top:1px solid {C['border']};")
            bl2 = QHBoxLayout(bar)
            bl2.setContentsMargins(20, 12, 20, 12)
            bl2.addWidget(lbl("✓  Access has been approved", bold=True, size=12, color=C["ok"]))
            self._detail_lay.addWidget(bar)

        elif req["status"] == "rejected":
            bar = QWidget()
            bar.setProperty("is_action_bar", True)
            bar.setStyleSheet(f"background:{C['danger_lt']};border-top:1px solid {C['border']};")
            bl2 = QHBoxLayout(bar)
            bl2.setContentsMargins(20, 12, 20, 12)
            bl2.addWidget(lbl("✕  Access was rejected", bold=True, size=12, color=C["danger"]))
            self._detail_lay.addWidget(bar)

    def _confirm_act(self, action: str) -> None:
        if not self._req:
            return
        dlg = ConfirmDialog(action, self._req, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._commit_act(action)

    def _commit_act(self, action: str) -> None:
        if not self._req:
            return
        req_copy = copy.deepcopy(self._req)
        keys = list(req_copy["permissions"].keys())
        for i, row in enumerate(self._perm_rows):
            req_copy["permissions"][keys[i]] = row.is_enabled()
        req_copy["status"] = action
        _SESSION_STATUS[req_copy["id"]] = action
        self._req = req_copy
        AUDIT.record(req_copy["id"], req_copy["name"], action,
                     operator=_USER_NAME or "Manager")
        self.action_taken.emit(req_copy["id"], action)

    def trigger_approve(self) -> None:
        if self._req and self._req["status"] == "pending":
            self._confirm_act("approved")

    def trigger_reject(self) -> None:
        if self._req and self._req["status"] == "pending":
            self._confirm_act("rejected")


class CardsPanel(QWidget):
    request_selected = pyqtSignal(dict)

    def __init__(self, reqs: list[dict], parent=None):
        super().__init__(parent)
        self._reqs = reqs
        self._cards: dict[int, RequestCard] = {}
        self._selected_id: Optional[int] = None
        self._filter = "All Users"
        self._search  = ""
        self.setStyleSheet(f"background:{C['bg']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C['bg']};}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:5px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )

        self._container = QWidget()
        self._container.setStyleSheet(f"background:{C['bg']};")
        self._grid = QVBoxLayout(self._container)
        self._grid.setContentsMargins(20, 16, 20, 20)
        self._grid.setSpacing(12)

        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)

        self._build_all_cards()
        self._refresh_visibility()

    def update_data(self, reqs: list[dict]) -> None:
        self._reqs = reqs
        self._selected_id = None
        self._build_all_cards()
        self._refresh_visibility()

    def _build_all_cards(self) -> None:
        _clear_layout(self._grid)
        self._cards.clear()

        row_lay: Optional[QHBoxLayout] = None
        for i, req in enumerate(self._reqs):
            if i % 2 == 0:
                row_lay = QHBoxLayout()
                row_lay.setSpacing(12)
                self._grid.addLayout(row_lay)
            card = RequestCard(req)
            card.clicked.connect(self._card_clicked)
            self._cards[req["id"]] = card
            if row_lay is not None:
                row_lay.addWidget(card)

        if len(self._reqs) % 2 == 1 and row_lay is not None:
            row_lay.addStretch()

        self._grid.addStretch()

    def _refresh_visibility(self) -> None:
        visible_ids = {r["id"] for r in self._filtered()}
        for req_id, card in self._cards.items():
            card.setVisible(
                req_id in visible_ids and card.matches_search(self._search)
            )
        any_visible = any(c.isVisible() for c in self._cards.values())
        if not any_visible:
            self._show_empty()
        else:
            self._hide_empty()

    def _show_empty(self) -> None:
        if not hasattr(self, "_empty_lbl"):
            self._empty_lbl = lbl("No requests match your filter.", size=12, color=C["sub"])
            self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.insertWidget(0, self._empty_lbl)
        self._empty_lbl.setVisible(True)

    def _hide_empty(self) -> None:
        if hasattr(self, "_empty_lbl"):
            self._empty_lbl.setVisible(False)

    def _filtered(self) -> list[dict]:
        f = self._filter
        if f == "All Users":
            return self._reqs
        if f == "Pending":
            return [r for r in self._reqs if r["status"] == "pending"]
        if f == "Approved":
            return [r for r in self._reqs if r["status"] == "approved"]
        if f == "Rejected":
            return [r for r in self._reqs if r["status"] == "rejected"]
        return self._reqs

    def _card_clicked(self, req: dict) -> None:
        if self._selected_id is not None and self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(False)
        self._selected_id = req["id"]
        self._cards[self._selected_id].set_selected(True)
        self.request_selected.emit(req)

    def set_filter(self, f: str) -> None:
        self._filter = f
        self._selected_id = None
        for card in self._cards.values():
            card.set_selected(False)
        self._refresh_visibility()

    def set_search(self, query: str) -> None:
        self._search = query
        self._refresh_visibility()

    def on_action(self, req_id: int, action: str, all_reqs: list[dict]) -> None:
        req = next((r for r in all_reqs if r["id"] == req_id), None)
        if req and req_id in self._cards:
            self._cards[req_id].update_req(req)
        self._refresh_visibility()

    def on_page_access_changed(self, req_id: int, grants: set, all_reqs: list[dict]) -> None:
        req = next((r for r in all_reqs if r["id"] == req_id), None)
        if req and req_id in self._cards:
            self._cards[req_id].update_req(req)

    def pending_count(self) -> int:
        return sum(1 for r in self._reqs if r["status"] == "pending")

    def click_first(self) -> None:
        visible = [r for r in self._filtered()
                   if self._cards.get(r["id"]) and self._cards[r["id"]].isVisible()]
        if visible:
            self._card_clicked(visible[0])

    def navigate(self, direction: int) -> None:
        visible = [r["id"] for r in self._filtered()
                   if self._cards.get(r["id"]) and self._cards[r["id"]].isVisible()]
        if not visible:
            return
        if self._selected_id not in visible:
            req = next(r for r in self._reqs if r["id"] == visible[0])
            self._card_clicked(req)
            return
        idx = visible.index(self._selected_id)
        new_idx = max(0, min(len(visible) - 1, idx + direction))
        req = next(r for r in self._reqs if r["id"] == visible[new_idx])
        self._card_clicked(req)


# ─── REDESIGNED: Main Window ──────────────────────────────────────────────────

class AccessControlWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Access Control")
        self.resize(1280, 840)
        self.setMinimumSize(960, 680)
        self.setStyleSheet(
            f"QMainWindow,#central{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
            f"QToolBar{{background:{C['white']};"
            f"border-bottom:1px solid {C['border']};padding:4px 16px;spacing:8px;}}"
            f"QSplitter::handle{{background:{C['splitter']};}}"
        )

        today = QDate.currentDate()
        self._date_from = today.addDays(-30)
        self._date_to   = today
        self._reqs: list[dict] = []

        self._build_toolbar()
        self._load_data()
        self._build_ui()
        self._register_shortcuts()

    def _date_range_label(self) -> str:
        if self._date_from == self._date_to:
            return f"📅  {self._date_from.toString('MMM d, yyyy')}"
        return (f"📅  {self._date_from.toString('MMM d, yyyy')}  →  "
                f"{self._date_to.toString('MMM d, yyyy')}")

    def _load_data(self) -> None:
        self._reqs = _build_requests_from_db(self._date_from, self._date_to)

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)

        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)

        self._db_lbl = QLabel()
        self._update_db_label()
        tb.addWidget(self._db_lbl)
        tb.addSeparator()

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

        refresh_btn = QPushButton("🔄  Refresh")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(
            f"QPushButton{{background:{C['white']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:6px;"
            f"font-size:12px;padding:4px 12px;}}"
            f"QPushButton:hover{{background:{C['bg']};}}"
        )
        refresh_btn.clicked.connect(self._refresh_all)
        tb.addWidget(refresh_btn)

        export_btn = QPushButton("⬇  Export CSV")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.setStyleSheet(
            f"QPushButton{{background:{C['white']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:6px;"
            f"font-size:12px;padding:4px 12px;}}"
            f"QPushButton:hover{{background:{C['bg']};}}"
        )
        export_btn.clicked.connect(self._export_csv)
        tb.addWidget(export_btn)

        self._audit_btn = QPushButton("🔒  Audit Log")
        self._audit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._audit_btn.setCheckable(True)
        self._audit_btn.setStyleSheet(
            f"QPushButton{{background:{C['white']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:6px;"
            f"font-size:12px;padding:4px 12px;}}"
            f"QPushButton:hover{{background:{C['bg']};}}"
            f"QPushButton:checked{{background:{C['accent_lt']};color:{C['accent']};"
            f"border-color:{C['accent']};}}"
        )
        self._audit_btn.clicked.connect(self._toggle_audit)
        tb.addWidget(self._audit_btn)

    def _update_db_label(self) -> None:
        if _DB_AVAILABLE:
            self._db_lbl.setText("🔗  Live data")
            self._db_lbl.setStyleSheet(
                f"color:{C['accent']};font-size:11px;"
                f"border:1px solid {C['accent']};border-radius:5px;"
                f"padding:3px 10px;background:{C['accent_lt']};"
            )
        else:
            self._db_lbl.setText("⚠️  Demo Mode")
            self._db_lbl.setStyleSheet(
                f"color:{C['warn']};font-size:11px;"
                f"border:1px solid {C['warn']};border-radius:5px;"
                f"padding:3px 10px;background:{C['warn_lt']};"
            )

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if _HAVE_SIDEBAR:
            current_user = get_current_user()
            sidebar = PawffinatedSidebar(
                active_page="Access Control",
                current_user=current_user,
            )
            outer.addWidget(sidebar)

        main = QWidget()
        main.setObjectName("main_area")
        main.setStyleSheet(f"background:{C['bg']};")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        # ── REDESIGNED: Page Header ────────────────────────────────────────────
        page_hdr = QWidget()
        page_hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        page_hdr.setFixedHeight(88)
        phl = QHBoxLayout(page_hdr)
        phl.setContentsMargins(0, 0, 32, 0)
        phl.setSpacing(0)

        # Left green accent bar
        accent_bar = QWidget()
        accent_bar.setFixedWidth(5)
        accent_bar.setStyleSheet(f"background:{C['accent']};border:none;")
        phl.addWidget(accent_bar)

        # Title + subtitle block
        title_block = QVBoxLayout()
        title_block.setContentsMargins(28, 0, 0, 0)
        title_block.setSpacing(4)
        title_block.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        page_title = lbl("Access Requests", bold=True, size=22)
        title_block.addWidget(page_title)

        self._page_sub = lbl(
            f"Showing {self._date_from.toString('MMM d, yyyy')} → "
            f"{self._date_to.toString('MMM d, yyyy')}  ·  "
            f"{len(self._reqs)} users",
            size=12, color=C["sub"],
        )
        title_block.addWidget(self._page_sub)
        phl.addLayout(title_block)
        phl.addStretch()

        # DB badge inline in header
        db_badge = QLabel("🔗  Live DB" if _DB_AVAILABLE else "⚠️  Demo")
        db_badge.setStyleSheet(
            f"color:{C['accent'] if _DB_AVAILABLE else C['warn']};"
            f"background:{C['accent_lt'] if _DB_AVAILABLE else C['warn_lt']};"
            f"border-radius:6px;padding:4px 12px;font-size:11px;"
            f"font-weight:600;border:none;"
        )
        phl.addWidget(db_badge)

        ml.addWidget(page_hdr)

        # ── REDESIGNED: Stats Strip ────────────────────────────────────────────
        self._stats_bar = self._build_stats_strip()
        ml.addWidget(self._stats_bar)

        # ── REDESIGNED: Filter + Search Bar ───────────────────────────────────
        strip = QWidget()
        strip.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        strip.setFixedHeight(64)
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(28, 0, 28, 0)
        sl.setSpacing(12)

        self._tab_bar = FilterTabBar()
        self._tab_bar.filter_changed.connect(self._on_filter)
        sl.addWidget(self._tab_bar)

        sl.addStretch()

        self._search_bar = SearchBar()
        self._search_bar.setFixedWidth(260)
        self._search_bar.search_changed.connect(self._on_search)
        sl.addWidget(self._search_bar)

        ml.addWidget(strip)

        # ── Splitter: Cards | Detail | Audit ──────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        self._splitter.setStyleSheet(f"QSplitter::handle{{background:{C['border']};}}")

        self._cards_panel = CardsPanel(self._reqs)
        self._cards_panel.request_selected.connect(self._on_select)
        self._splitter.addWidget(self._cards_panel)

        self._detail = DetailPanel()
        self._detail.action_taken.connect(self._on_action)
        self._detail.page_access_changed.connect(self._on_page_access_changed)
        self._splitter.addWidget(self._detail)

        self._audit_drawer = AuditDrawer(None, toggle_callback=self._toggle_audit)
        self._audit_drawer.hide()
        self._splitter.addWidget(self._audit_drawer)

        self._splitter.setSizes([700, 360, 0])
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setCollapsible(2, True)

        ml.addWidget(self._splitter, stretch=1)
        outer.addWidget(main, stretch=1)

        self._refresh_count()

    # ── REDESIGNED: Stats Strip ────────────────────────────────────────────────
    def _build_stats_strip(self) -> QWidget:
        """
        Redesigned stats strip:
        - White background, 96px height
        - Each stat card has a generous left colored border,
          a muted uppercase label, and a large bold number
        - Cards sit in equal-width columns separated by clean dividers
        - No cramped inline badges, no horizontal overflow
        """
        bar = QWidget()
        bar.setStyleSheet(f"background:{C['white']};border-bottom:1px solid {C['border']};")
        bar.setFixedHeight(96)

        total    = len(self._reqs)
        pending  = sum(1 for r in self._reqs if r["status"] == "pending")
        approved = sum(1 for r in self._reqs if r["status"] == "approved")
        rejected = sum(1 for r in self._reqs if r["status"] == "rejected")
        admins   = sum(1 for r in self._reqs if r.get("is_admin"))

        # (label, value, accent_color, bg_color)
        stats = [
            ("Total Users",    str(total),    C["text"],    C["bg"]),
            ("Pending",        str(pending),  C["pending"], C["pending_lt"]),
            ("Approved",       str(approved), C["ok"],      C["ok_lt"]),
            ("Rejected",       str(rejected), C["danger"],  C["danger_lt"]),
            ("Administrators", str(admins),   C["warn"],    C["warn_lt"]),
        ]

        outer_lay = QHBoxLayout(bar)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        for i, (label_text, val, color, bg) in enumerate(stats):
            # Stat card widget
            stat_card = QWidget()
            stat_card.setStyleSheet(
                f"background:{C['white']};border:none;"
            )
            card_lay = QVBoxLayout(stat_card)
            card_lay.setContentsMargins(0, 0, 0, 0)
            card_lay.setSpacing(0)
            card_lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

            # Inner wrapper with left accent border
            inner = QWidget()
            inner.setStyleSheet(
                f"background:{bg};border-radius:10px;border:none;"
            )
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(18, 14, 18, 14)
            inner_lay.setSpacing(4)

            # Label
            label_w = QLabel(label_text.upper())
            label_w.setStyleSheet(
                f"color:{C['sub']};font-size:10px;font-weight:600;"
                f"letter-spacing:0.5px;background:transparent;border:none;"
            )
            inner_lay.addWidget(label_w)

            # Value — large bold number in accent color
            val_w = QLabel(val)
            val_f = QFont("Segoe UI", 28)
            val_f.setBold(True)
            val_w.setFont(val_f)
            val_w.setStyleSheet(f"color:{color};background:transparent;border:none;")
            inner_lay.addWidget(val_w)

            # Left accent stripe — rendered as a thin colored frame on the left
            container = QWidget()
            container.setStyleSheet("background:transparent;border:none;")
            c_lay = QHBoxLayout(container)
            c_lay.setContentsMargins(20, 10, 20, 10)
            c_lay.setSpacing(0)

            stripe = QFrame()
            stripe.setFixedWidth(4)
            stripe.setStyleSheet(
                f"background:{color};border-radius:2px;border:none;"
            )
            c_lay.addWidget(stripe)
            c_lay.addSpacing(14)
            c_lay.addWidget(inner, stretch=1)

            card_lay.addWidget(container)
            outer_lay.addWidget(stat_card, stretch=1)

            # Divider between cards (not after the last one)
            if i < len(stats) - 1:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.VLine)
                div.setStyleSheet(f"background:{C['border']};border:none;max-width:1px;")
                div.setFixedWidth(1)
                outer_lay.addWidget(div)

        return bar

    def _register_shortcuts(self) -> None:
        QShortcut(QKeySequence("A"), self).activated.connect(self._detail.trigger_approve)
        QShortcut(QKeySequence("R"), self).activated.connect(self._detail.trigger_reject)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._deselect)
        QShortcut(QKeySequence("Up"),   self).activated.connect(lambda: self._cards_panel.navigate(-1))
        QShortcut(QKeySequence("Down"), self).activated.connect(lambda: self._cards_panel.navigate(1))

    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(0, self._cards_panel.click_first)

    def _on_filter(self, f: str) -> None:
        self._cards_panel.set_filter(f)

    def _on_search(self, query: str) -> None:
        self._cards_panel.set_search(query)

    def _on_select(self, req: dict) -> None:
        fresh = next((r for r in self._reqs if r["id"] == req["id"]), req)
        self._detail.load(fresh)

    def _on_action(self, req_id: int, action: str) -> None:
        req = None
        for i, r in enumerate(self._reqs):
            if r["id"] == req_id:
                self._reqs[i] = {**r, "status": action}
                req = self._reqs[i]
                break

        if req is None:
            return

        self._cards_panel.on_action(req_id, action, self._reqs)
        self._refresh_count()
        self._detail.load(req)

        verb  = "approved" if action == "approved" else "rejected"
        color = C["ok"] if action == "approved" else C["danger"]
        Toast(self.centralWidget(), f"#{req_id} ({req['name']}) {verb}.", color)

        if self._audit_drawer.isVisible():
            self._audit_drawer.refresh()

        self._replace_stats_strip()

    def _on_page_access_changed(self, req_id: int, grants: set) -> None:
        for i, r in enumerate(self._reqs):
            if r["id"] == req_id:
                self._reqs[i] = {
                    **r,
                    "page_grants":           grants,
                    "page_access_control":   "Access Control" in grants,
                    "page_staff_management": "Staff Management" in grants,
                }
                break
        self._cards_panel.on_page_access_changed(req_id, grants, self._reqs)
        req_name  = next((r["name"] for r in self._reqs if r["id"] == req_id), "")
        granted_count = len(grants)
        total_count   = len(ALL_TABS)
        Toast(self.centralWidget(),
              f"Tab access updated for {req_name}: {granted_count}/{total_count} tabs.", C["accent"])
        if self._audit_drawer.isVisible():
            self._audit_drawer.refresh()

    def _deselect(self) -> None:
        if self._cards_panel._selected_id is not None:
            card = self._cards_panel._cards.get(self._cards_panel._selected_id)
            if card:
                card.set_selected(False)
            self._cards_panel._selected_id = None
            self._detail._stack.setCurrentIndex(0)

    def _toggle_audit(self) -> None:
        currently_visible = self._audit_drawer.isVisible()
        if currently_visible:
            sizes = self._splitter.sizes()
            self._last_audit_width = sizes[2] if sizes[2] > 0 else 320
            self._splitter.setSizes([sizes[0] + sizes[2], sizes[1], 0])
            self._audit_drawer.hide()
            self._audit_btn.setChecked(False)
        else:
            sizes = self._splitter.sizes()
            restore_w = getattr(self, "_last_audit_width", 320)
            total = sizes[0] + sizes[2]
            new_cards = max(300, total - restore_w)
            self._splitter.setSizes([new_cards, sizes[1], restore_w])
            self._audit_drawer.show()
            self._audit_drawer.refresh()
            self._audit_btn.setChecked(True)

    def _open_date_picker(self) -> None:
        dlg = DateRangeDialog(self._date_from, self._date_to, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._date_from, self._date_to = dlg.get_range()
            self._date_btn.setText(self._date_range_label())
            self._refresh_all()

    def _replace_stats_strip(self) -> None:
        old_bar = self._stats_bar
        self._stats_bar = self._build_stats_strip()
        ml = old_bar.parent().layout()
        idx = ml.indexOf(old_bar)
        if idx >= 0:
            ml.takeAt(idx)
            old_bar.deleteLater()
            ml.insertWidget(idx, self._stats_bar)

    def _refresh_all(self) -> None:
        self._load_data()
        self._cards_panel.update_data(self._reqs)
        self._refresh_count()
        self._detail._stack.setCurrentIndex(0)

        self._page_sub.setText(
            f"Showing {self._date_from.toString('MMM d, yyyy')} → "
            f"{self._date_to.toString('MMM d, yyyy')}  ·  "
            f"{len(self._reqs)} users"
        )
        self._replace_stats_strip()
        Toast(self.centralWidget(),
              f"Refreshed — {len(self._reqs)} users loaded.", C["accent"])

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Access Log", "access_control_log.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            csv_data = AUDIT.to_csv_string(self._reqs)
            with open(path, "w", newline="", encoding="utf-8") as f:
                f.write(csv_data)
            Toast(self.centralWidget(), f"Exported to {path.split('/')[-1]}", C["ok"])
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _refresh_count(self) -> None:
        self._tab_bar.set_pending_count(
            sum(1 for r in self._reqs if r["status"] == "pending")
        )


def _verify_owner() -> bool:
    is_admin = _USER_IS_ADMIN
    if not is_admin and _USER_EMAIL and _DB_AVAILABLE:
        try:
            is_admin = get_auth_db().is_admin(_USER_EMAIL)
        except Exception:
            pass

    if not is_admin:
        app = QApplication.instance() or QApplication(sys.argv)
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Access Denied")
        msg.setText(
            "⛔  Access Control is restricted to administrators only.\n\n"
            f"Logged in as: {_USER_NAME or 'Unknown'}\n\n"
            "Contact your system administrator if you need access."
        )
        msg.exec()
        return False
    return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Pawffinated Access Control")

    if not _verify_owner():
        sys.exit(1)

    win = AccessControlWindow()
    win.show()
    sys.exit(app.exec())