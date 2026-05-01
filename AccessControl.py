"""
PAWFFINATED – Access Control  (PyQt6 Edition)
=============================================
Matches the Dashboard.py palette, toolbar, sidebar style, and navigation.

Run standalone:
    python AccessControl.py

Place in the same folder as Dashboard.py so the "Dashboard" nav link works.
"""

from __future__ import annotations
import sys

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QSizePolicy, QStackedWidget,
    QToolBar,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush

# ── Palette  (identical to Dashboard.py) ──────────────────────────────────────
C = dict(
    bg="#F7F5F0",
    sidebar="#FFFFFF",
    white="#FFFFFF",
    accent="#2D7A5F",
    accent_lt="#E8F4F0",
    warn="#E07B39",
    warn_lt="#FFF7ED",
    danger="#D94F4F",
    danger_lt="#FEE2E2",
    ok="#059669",
    ok_lt="#D1FAE5",
    text="#1A1A1A",
    sub="#6B7280",
    border="#E5E7EB",
    card_icon="#F0FDF4",
    pending="#F59E0B",
    pending_lt="#FFFBEB",
)

# ── Demo data ─────────────────────────────────────────────────────────────────
ACCESS_REQUESTS: list[dict] = [
    {
        "id": 1042,
        "name": "Jimrey Oppa",
        "role": "Cashier Trainee",
        "avatar": "👩",
        "device": "POS Terminal 04",
        "device_full": "POS Terminal 04 (Front Counter)",
        "time": "10:42 AM",
        "time_display": "10:42 AM (Just now)",
        "access_level": "Standard POS",
        "date": "Oct 24",
        "status": "pending",
        "permissions": {
            "Device Login":     True,
            "Process Payments": True,
            "Issue Refunds":    False,
            "Modify Inventory": False,
            "View Reports":     False,
        },
    },
    {
        "id": 1043,
        "name": "Niata Megatron",
        "role": "Barista",
        "avatar": "👩\u200d🦱",
        "device": "Drive-Thru Pad 2",
        "device_full": "Drive-Thru Pad 2 (Station B)",
        "time": "10:15 AM",
        "time_display": "10:15 AM",
        "access_level": "Standard POS",
        "date": "Oct 24",
        "status": "pending",
        "permissions": {
            "Device Login":     True,
            "Process Payments": True,
            "Issue Refunds":    False,
            "Modify Inventory": False,
            "View Reports":     False,
        },
    },
    {
        "id": 1044,
        "name": "Jayson Maomoa",
        "role": "Shift Supervisor",
        "avatar": "👨",
        "device": "Back Office Mac",
        "device_full": "Back Office Mac (Manager Station)",
        "time": "09:30 AM",
        "time_display": "09:30 AM",
        "access_level": "Management",
        "date": "Oct 24",
        "status": "pending",
        "permissions": {
            "Device Login":     True,
            "Process Payments": True,
            "Issue Refunds":    True,
            "Modify Inventory": True,
            "View Reports":     True,
        },
    },
    {
        "id": 1039,
        "name": "Marco Delgado",
        "role": "Senior Barista",
        "avatar": "👨\u200d🍳",
        "device": "POS Terminal 02",
        "device_full": "POS Terminal 02 (Bar Area)",
        "time": "08:55 AM",
        "time_display": "08:55 AM",
        "access_level": "Standard POS",
        "date": "Oct 24",
        "status": "approved",
        "permissions": {
            "Device Login":     True,
            "Process Payments": True,
            "Issue Refunds":    False,
            "Modify Inventory": False,
            "View Reports":     False,
        },
    },
    {
        "id": 1038,
        "name": "Lena Park",
        "role": "Cashier",
        "avatar": "👩\u200d💼",
        "device": "POS Terminal 01",
        "device_full": "POS Terminal 01 (Front Counter)",
        "time": "08:30 AM",
        "time_display": "08:30 AM",
        "access_level": "Standard POS",
        "date": "Oct 24",
        "status": "approved",
        "permissions": {
            "Device Login":     True,
            "Process Payments": True,
            "Issue Refunds":    False,
            "Modify Inventory": False,
            "View Reports":     False,
        },
    },
    {
        "id": 1037,
        "name": "Sam Khoury",
        "role": "Kitchen Staff",
        "avatar": "👨\u200d🍳",
        "device": "Kitchen Display",
        "device_full": "Kitchen Display (Back Area)",
        "time": "08:15 AM",
        "time_display": "08:15 AM",
        "access_level": "Kitchen Only",
        "date": "Oct 24",
        "status": "rejected",
        "permissions": {
            "Device Login":     False,
            "Process Payments": False,
            "Issue Refunds":    False,
            "Modify Inventory": False,
            "View Reports":     False,
        },
    },
]

PERM_DESC = {
    "Device Login":     "Allow access to this terminal",
    "Process Payments": "Ring up orders and accept cash/card",
    "Issue Refunds":    "Process returns and cancellations",
    "Modify Inventory": "Adjust stock levels manually",
    "View Reports":     "Access sales and performance data",
}


# ── Shared helpers (mirrors Dashboard.py) ─────────────────────────────────────
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


# ── Toggle Switch ─────────────────────────────────────────────────────────────
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def checked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool):
        self._checked = val
        self.update()

    def mousePressEvent(self, _):
        self._checked = not self._checked
        self.toggled.emit(self._checked)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(C["accent"]) if self._checked else QColor("#D1D5DB")
        p.setBrush(QBrush(track))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 4, 44, 16, 8, 8)
        p.setBrush(QBrush(QColor("#FFFFFF")))
        x = 22 if self._checked else 2
        p.drawEllipse(x, 2, 20, 20)


# ── Avatar widget ─────────────────────────────────────────────────────────────
class AvatarLabel(QLabel):
    def __init__(self, emoji: str, size=44, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setText(emoji)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background:#E5EDEA;border-radius:{size // 2}px;"
            f"font-size:{int(size * 0.46)}px;border:none;"
        )


# ── Status badge ──────────────────────────────────────────────────────────────
def status_badge(status: str) -> QLabel:
    cfg = {
        "pending":  (C["pending"],  C["pending_lt"], "PENDING"),
        "approved": (C["ok"],       C["ok_lt"],      "APPROVED"),
        "rejected": (C["danger"],   C["danger_lt"],  "REJECTED"),
    }
    fg, bg, text = cfg.get(status, (C["sub"], C["border"], status.upper()))
    w = QLabel(text)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(
        f"color:{fg};background:{bg};border-radius:5px;"
        f"padding:2px 10px;font-size:10px;font-weight:700;border:none;"
    )
    return w


# ── Sidebar — self-contained, style-identical to Sidebar.py ──────────────────
class PawffinatedSidebar(QWidget):
    navigate = pyqtSignal(str)

    def __init__(self, active_page="Access Control", parent=None):
        super().__init__(parent)
        self._active = active_page
        self.setFixedWidth(220)
        self.setStyleSheet(
            f"background:{C['sidebar']};border-right:1px solid {C['border']};"
        )
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Logo bar
        logo_w = QWidget()
        logo_w.setFixedHeight(60)
        logo_w.setStyleSheet(
            f"background:{C['sidebar']};border-bottom:1px solid {C['border']};"
        )
        ll = QHBoxLayout(logo_w)
        ll.setContentsMargins(16, 0, 16, 0)
        logo_icon = QLabel("🐾")
        logo_icon.setFixedSize(32, 32)
        logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_icon.setStyleSheet(
            "background:#3D2B1A;border-radius:8px;font-size:16px;border:none;"
        )
        ll.addWidget(logo_icon)
        ll.addSpacing(10)
        ll.addWidget(lbl("PAWFFINATED", bold=True, size=11))
        lay.addWidget(logo_w)

        lay.addSpacing(12)

        lay.addWidget(self._section("MAIN"))
        for icon, name in [("⊞", "Dashboard"), ("📋", "Orders")]:
            lay.addWidget(self._nav_btn(icon, name))

        lay.addSpacing(8)
        lay.addWidget(self._section("MANAGEMENT"))
        for icon, name in [
            ("📊", "Sales Monitor"),
            ("🛡", "Access Control"),
            ("⏱", "Activity Log"),
            ("📦", "Inventory"),
        ]:
            lay.addWidget(self._nav_btn(icon, name))

        lay.addStretch()

        # Current user strip
        user_w = QWidget()
        user_w.setStyleSheet(
            f"background:{C['sidebar']};border-top:1px solid {C['border']};"
        )
        ul = QHBoxLayout(user_w)
        ul.setContentsMargins(16, 12, 16, 12)
        ul.setSpacing(10)
        ul.addWidget(AvatarLabel("👩\u200d💼", 32))
        uc = QVBoxLayout()
        uc.setSpacing(1)
        uc.addWidget(lbl("Sarah Jenkins", bold=True, size=11))
        uc.addWidget(lbl("Store Manager", size=9, color=C["sub"]))
        ul.addLayout(uc)
        lay.addWidget(user_w)

    def _section(self, text: str) -> QLabel:
        w = QLabel(f"  {text}")
        w.setFixedHeight(26)
        f = QFont("Segoe UI", 9)
        f.setBold(True)
        w.setFont(f)
        w.setStyleSheet(
            f"color:{C['sub']};background:transparent;letter-spacing:1px;"
        )
        return w

    def _nav_btn(self, icon: str, name: str) -> QPushButton:
        btn = QPushButton(f"  {icon}  {name}")
        btn.setFixedHeight(38)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        active = name == self._active
        if active:
            btn.setStyleSheet(
                f"QPushButton{{background:{C['accent_lt']};color:{C['accent']};"
                f"border:none;text-align:left;font-size:13px;font-weight:700;"
                f"border-radius:8px;margin:1px 8px;}}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C['text']};"
                f"border:none;text-align:left;font-size:13px;"
                f"border-radius:8px;margin:1px 8px;}}"
                f"QPushButton:hover{{background:{C['bg']};}}"
            )
        btn.clicked.connect(lambda _, n=name: self.navigate.emit(n))
        return btn


# ── Filter Tab Bar ─────────────────────────────────────────────────────────────
class FilterTabBar(QWidget):
    filter_changed = pyqtSignal(str)
    TABS = ["All Users", "All Requests",
            "Pending", "Recently Approved", "Rejected"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self._current = "Pending"
        self._btns: dict[str, QPushButton] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for tab in self.TABS:
            btn = QPushButton(tab)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btns[tab] = btn
            self._style(btn, tab == self._current)
            btn.clicked.connect(lambda _, t=tab: self._select(t))
            lay.addWidget(btn)
        lay.addStretch()

    def _style(self, btn: QPushButton, active: bool):
        if active:
            btn.setStyleSheet(
                f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                f"border:none;border-radius:17px;font-size:12px;"
                f"font-weight:700;padding:0 16px;}}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton{{background:{C['white']};color:{C['text']};"
                f"border:1px solid {C['border']};border-radius:17px;"
                f"font-size:12px;padding:0 14px;}}"
                f"QPushButton:hover{{background:{C['bg']};}}"
            )

    def _select(self, tab: str):
        for name, btn in self._btns.items():
            self._style(btn, name == tab)
        self._current = tab
        self.filter_changed.emit(tab)

    def set_pending_count(self, n: int):
        btn = self._btns.get("Pending")
        if btn:
            btn.setText(f"Pending ({n})" if n else "Pending")


# ── Request Card ──────────────────────────────────────────────────────────────
class RequestCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, req: dict, parent=None):
        super().__init__(parent)
        self._req = req
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()
        self._build()

    def _apply_style(self):
        if self._selected:
            self.setStyleSheet(
                f"QFrame{{background:{C['white']};border-radius:12px;"
                f"border:2px solid {C['accent']};}}"
            )
        else:
            self.setStyleSheet(
                f"QFrame{{background:{C['white']};border-radius:12px;"
                f"border:1px solid {C['border']};}}"
                f"QFrame:hover{{border-color:#A8C8BD;}}"
            )

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(AvatarLabel(self._req["avatar"], 40))
        nc = QVBoxLayout()
        nc.setSpacing(2)
        nc.addWidget(lbl(self._req["name"], bold=True, size=12))
        nc.addWidget(lbl(self._req["role"], size=10, color=C["sub"]))
        top.addLayout(nc)
        top.addStretch()
        top.addWidget(status_badge(self._req["status"]))
        lay.addLayout(top)

        lay.addWidget(hline())

        for field, val in [
            ("Device",       self._req["device"]),
            ("Time",         self._req["time_display"]),
            ("Access Level", self._req["access_level"]),
        ]:
            row = QHBoxLayout()
            row.addWidget(lbl(field, size=10, color=C["sub"]))
            row.addStretch()
            row.addWidget(lbl(val, bold=True, size=10))
            lay.addLayout(row)

    def set_selected(self, val: bool):
        self._selected = val
        self._apply_style()

    def mousePressEvent(self, e):
        self.clicked.emit(self._req)
        super().mousePressEvent(e)


# ── Permission row ────────────────────────────────────────────────────────────
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

    def set_enabled(self, val: bool):
        self._toggle.setChecked(val)


# ── Detail panel (right pane) ─────────────────────────────────────────────────
class DetailPanel(QWidget):
    action_taken = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._req: dict | None = None
        self._perm_rows: list[PermissionRow] = []
        self.setStyleSheet(
            f"background:{C['white']};border-left:1px solid {C['border']};"
        )
        self.setMinimumWidth(300)
        self.setMaximumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Placeholder
        ph = QWidget()
        ph.setStyleSheet(f"background:{C['white']};")
        phl = QVBoxLayout(ph)
        phl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lbl = lbl("Select a request\nto view details",
                     size=12, color=C["sub"])
        ph_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        phl.addWidget(ph_lbl)

        self._detail_w = QWidget()
        self._detail_w.setStyleSheet("background:transparent;")
        self._detail_lay = QVBoxLayout(self._detail_w)
        self._detail_lay.setContentsMargins(0, 0, 0, 0)
        self._detail_lay.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(ph)
        self._stack.addWidget(self._detail_w)
        root.addWidget(self._stack)

    def load(self, req: dict):
        self._req = req
        self._perm_rows.clear()

        while self._detail_lay.count():
            item = self._detail_lay.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        # ── Strip header ──────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(48)
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.addWidget(lbl(f"Request #{req['id']}", bold=True, size=13))
        hl.addStretch()
        self._detail_lay.addWidget(hdr)

        # ── Scrollable body ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        bl.setSpacing(16)

        # Avatar + name
        av_row = QHBoxLayout()
        av_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        av_row.addWidget(AvatarLabel(req["avatar"], 72))
        bl.addLayout(av_row)
        name_lbl = lbl(req["name"], bold=True, size=16)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(name_lbl)
        role_lbl = lbl(req["role"], size=11, color=C["sub"])
        role_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(role_lbl)

        # Login context card
        ctx = card_frame(10)
        ctx_l = QVBoxLayout(ctx)
        ctx_l.setContentsMargins(14, 14, 14, 14)
        ctx_l.setSpacing(0)
        ctx_l.addWidget(lbl("LOGIN CONTEXT", size=9,
                        bold=True, color=C["sub"]))
        ctx_l.addSpacing(10)

        for icon, subtitle, value in [
            ("🖥", "Requested Device", req["device_full"]),
            ("🕐", "Attempt Time",     f"{req['date']}, {req['time']}"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(10)
            ic = QLabel(icon)
            ic.setFixedSize(28, 28)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic.setStyleSheet(
                f"background:{C['accent_lt']};border-radius:6px;"
                f"font-size:13px;border:none;"
            )
            row.addWidget(ic)
            vc = QVBoxLayout()
            vc.setSpacing(1)
            vc.addWidget(lbl(subtitle, size=9, color=C["sub"]))
            vc.addWidget(lbl(value, bold=True, size=11))
            row.addLayout(vc)
            ctx_l.addLayout(row)
            ctx_l.addSpacing(8)

        bl.addWidget(ctx)

        # Permissions
        bl.addWidget(lbl("CONFIGURE PERMISSIONS",
                     size=9, bold=True, color=C["sub"]))
        perm_card = card_frame(10)
        perm_l = QVBoxLayout(perm_card)
        perm_l.setContentsMargins(14, 4, 14, 4)
        perm_l.setSpacing(0)
        items = list(req["permissions"].items())
        for i, (pname, enabled) in enumerate(items):
            pr = PermissionRow(pname, enabled)
            self._perm_rows.append(pr)
            perm_l.addWidget(pr)
            if i < len(items) - 1:
                perm_l.addWidget(hline())
        bl.addWidget(perm_card)
        bl.addStretch()

        scroll.setWidget(body)
        self._detail_lay.addWidget(scroll, stretch=1)

        # ── Action buttons ─────────────────────────────────────────────────────
        if req["status"] == "pending":
            btn_bar = QWidget()
            btn_bar.setStyleSheet(
                f"background:{C['white']};border-top:1px solid {C['border']};"
            )
            bb = QHBoxLayout(btn_bar)
            bb.setContentsMargins(20, 14, 20, 14)
            bb.setSpacing(12)

            rej = QPushButton("Reject")
            rej.setCursor(Qt.CursorShape.PointingHandCursor)
            rej.setFixedHeight(42)
            rej.setStyleSheet(
                f"QPushButton{{background:{C['white']};color:{C['danger']};"
                f"border:2px solid {C['danger']};border-radius:8px;"
                f"font-size:13px;font-weight:700;}}"
                f"QPushButton:hover{{background:{C['danger_lt']};}}"
            )
            rej.clicked.connect(lambda: self._act("rejected"))

            apr = QPushButton("Approve Access")
            apr.setCursor(Qt.CursorShape.PointingHandCursor)
            apr.setFixedHeight(42)
            apr.setStyleSheet(
                f"QPushButton{{background:{C['accent']};color:#FFFFFF;"
                f"border:none;border-radius:8px;"
                f"font-size:13px;font-weight:700;}}"
                f"QPushButton:hover{{background:#236850;}}"
            )
            apr.clicked.connect(lambda: self._act("approved"))

            bb.addWidget(rej)
            bb.addWidget(apr, stretch=1)
            self._detail_lay.addWidget(btn_bar)

        elif req["status"] == "approved":
            bar = QWidget()
            bar.setStyleSheet(
                f"background:{C['ok_lt']};border-top:1px solid {C['border']};"
            )
            bl2 = QHBoxLayout(bar)
            bl2.setContentsMargins(20, 12, 20, 12)
            bl2.addWidget(lbl("✓  Access has been approved", bold=True,
                              size=12, color=C["ok"]))
            self._detail_lay.addWidget(bar)

        elif req["status"] == "rejected":
            bar = QWidget()
            bar.setStyleSheet(
                f"background:{C['danger_lt']};border-top:1px solid {C['border']};"
            )
            bl2 = QHBoxLayout(bar)
            bl2.setContentsMargins(20, 12, 20, 12)
            bl2.addWidget(lbl("✕  Access was rejected", bold=True,
                              size=12, color=C["danger"]))
            self._detail_lay.addWidget(bar)

        self._stack.setCurrentIndex(1)

    def _act(self, action: str):
        if not self._req:
            return
        keys = list(self._req["permissions"].keys())
        for i, row in enumerate(self._perm_rows):
            self._req["permissions"][keys[i]] = row.is_enabled()
        self._req["status"] = action
        self.action_taken.emit(self._req["id"], action)


# ── Cards panel (center) ──────────────────────────────────────────────────────
class CardsPanel(QWidget):
    request_selected = pyqtSignal(dict)

    def __init__(self, reqs: list[dict], parent=None):
        super().__init__(parent)
        self._reqs = reqs
        self._cards: dict[int, RequestCard] = {}
        self._selected_id: int | None = None
        self._filter = "Pending"
        self.setStyleSheet(f"background:{C['bg']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

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

        self._container = QWidget()
        self._container.setStyleSheet(f"background:{C['bg']};")
        self._grid = QVBoxLayout(self._container)
        self._grid.setContentsMargins(20, 16, 20, 20)
        self._grid.setSpacing(12)

        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)
        self._refresh()

    def _filtered(self) -> list[dict]:
        f = self._filter
        if f in ("All Users", "All Requests"):
            return self._reqs
        if f == "Pending":
            return [r for r in self._reqs if r["status"] == "pending"]
        if f == "Recently Approved":
            return [r for r in self._reqs if r["status"] == "approved"]
        if f == "Rejected":
            return [r for r in self._reqs if r["status"] == "rejected"]
        return self._reqs

    def _clear_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w:
                w.deleteLater()
            lay = item.layout()
            if lay:
                while lay.count():
                    si = lay.takeAt(0)
                    if si and si.widget():
                        si.widget().deleteLater()

    def _refresh(self):
        self._clear_grid()
        self._cards.clear()

        visible = self._filtered()
        if not visible:
            empty = lbl("No requests in this category.",
                        size=12, color=C["sub"])
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addSpacing(40)
            self._grid.addWidget(empty)
            self._grid.addStretch()
            return

        row_lay: QHBoxLayout | None = None
        for i, req in enumerate(visible):
            if i % 2 == 0:
                row_lay = QHBoxLayout()
                row_lay.setSpacing(12)
                self._grid.addLayout(row_lay)
            card = RequestCard(req)
            card.clicked.connect(self._card_clicked)
            self._cards[req["id"]] = card
            if row_lay is not None:
                row_lay.addWidget(card)

        if len(visible) % 2 == 1 and row_lay is not None:
            row_lay.addStretch()

        self._grid.addStretch()

        if self._selected_id and self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(True)

    def _card_clicked(self, req: dict):
        if self._selected_id and self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(False)
        self._selected_id = req["id"]
        if self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(True)
        self.request_selected.emit(req)

    def set_filter(self, f: str):
        self._filter = f
        self._selected_id = None
        self._refresh()

    def on_action(self, _req_id: int, _action: str):
        self._refresh()

    def pending_count(self) -> int:
        return sum(1 for r in self._reqs if r["status"] == "pending")

    def click_first(self):
        visible = self._filtered()
        if visible:
            self._card_clicked(visible[0])


# ── Access Control Window ─────────────────────────────────────────────────────
class AccessControlWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Access Control")
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
        self._reqs = ACCESS_REQUESTS
        self._open_windows: list[QMainWindow] = []
        self._build_toolbar()
        self._build_ui()

    # ── Toolbar — identical layout to Dashboard.py ─────────────────────────────
    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(
            f"font-weight:800;font-size:14px;color:{C['accent']};")
        tb.addWidget(logo)
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding,
                         QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)
        date_lbl = QLabel("📅  Today · Oct 24  ·  Access Control")
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

        # Sidebar
        sidebar = PawffinatedSidebar(active_page="Access Control")
        sidebar.navigate.connect(self._navigate)
        root.addWidget(sidebar)

        # Main content column
        main = QWidget()
        main.setStyleSheet(f"background:{C['bg']};")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        # Page header (same pattern as Dashboard._build_header)
        page_hdr = QWidget()
        page_hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        page_hdr.setFixedHeight(72)
        phl = QVBoxLayout(page_hdr)
        phl.setContentsMargins(28, 14, 28, 14)
        phl.setSpacing(3)
        phl.addWidget(lbl("Access Requests", bold=True, size=20))
        phl.addWidget(lbl(
            "Review login attempts, assign permissions, and manage device access.",
            size=11, color=C["sub"],
        ))
        ml.addWidget(page_hdr)

        # Filter tab bar strip
        tab_strip = QWidget()
        tab_strip.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        tsl = QHBoxLayout(tab_strip)
        tsl.setContentsMargins(24, 10, 24, 10)
        self._tab_bar = FilterTabBar()
        self._tab_bar.filter_changed.connect(self._on_filter)
        tsl.addWidget(self._tab_bar)
        ml.addWidget(tab_strip)

        # Cards + detail split
        split = QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)

        self._cards = CardsPanel(self._reqs)
        self._cards.request_selected.connect(self._on_select)
        split.addWidget(self._cards, stretch=1)

        self._detail = DetailPanel()
        self._detail.action_taken.connect(self._on_action)
        split.addWidget(self._detail)

        ml.addLayout(split, stretch=1)
        root.addWidget(main, stretch=1)

        # Auto-select first pending request
        QTimer.singleShot(80, self._cards.click_first)
        self._refresh_count()

    # ── Slots ──────────────────────────────────────────────────────────────────
    def _on_filter(self, f: str):
        self._cards.set_filter(f)

    def _on_select(self, req: dict):
        self._detail.load(req)

    def _on_action(self, req_id: int, action: str):
        self._cards.on_action(req_id, action)
        self._refresh_count()
        # Reload detail pane to show the updated status footer
        for r in self._reqs:
            if r["id"] == req_id:
                self._detail.load(r)
                break

    def _refresh_count(self):
        self._tab_bar.set_pending_count(self._cards.pending_count())

    # ── Navigation — same pattern as Dashboard.py ──────────────────────────────
    def _navigate(self, page: str):
        if page == "Access Control":
            return

        if page == "Dashboard":
            try:
                from Dashboard import DashboardWindow
                win = DashboardWindow()
                win.show()
                self._open_windows.append(win)
                self.close()
                return
            except ImportError:
                self.statusBar().showMessage(
                    "Dashboard.py not found – place it in the same folder.", 4000
                )
                return

        if page == "Orders":
            try:
                from Orders import OrdersWindow
                win = OrdersWindow()
                win.show()
                self._open_windows.append(win)
                self.close()
                return
            except ImportError:
                self.statusBar().showMessage(
                    "Orders.py not found – place it in the same folder.", 4000
                )
                return

        self.statusBar().showMessage(f"'{page}' is not yet implemented.", 3000)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Pawffinated Access Control")
    win = AccessControlWindow()
    win.show()
    sys.exit(app.exec())
