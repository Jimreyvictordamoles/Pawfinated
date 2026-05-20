"""
PAWFFINATED – Staff Admin Panel  (PyQt6 + PostgreSQL)
=====================================================
Accessible ONLY by administrators (is_admin = TRUE in users table).

Admins can:
  • View all registered users in a sortable table
  • Edit each user's role and station inline
  • Add / remove / edit scheduled shifts per user
  • Reset a user's password
  • Grant or revoke admin privileges
  • Delete a user account

Run standalone (requires PAWFF_USER_EMAIL + PAWFF_USER_IS_ADMIN env vars
set by Login.py):
    python StaffAdminPanel.py
"""

from __future__ import annotations
import sys, os, subprocess
from datetime import datetime

from DbConnection import get_auth_db, get_staff_db, close_db, db_info, AuthDB

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
    QToolBar, QDialog, QMessageBox, QLineEdit, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialogButtonBox, QFormLayout, QTabWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
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
    admin_bg  = "#FEF3C7",
    admin_border = "#F59E0B",
)

ROLES = [
    "Administrator", "Store Manager", "Shift Supervisor",
    "Senior Barista", "Barista", "Cashier", "Cashier Trainee",
    "Kitchen Staff",
]
STATIONS = [
    "Back Office", "Front Counter", "Espresso Bar",
    "Drive-Thru", "Kitchen", "Register 1", "Register 2",
]
SHIFT_TAGS = ["Scheduled", "Confirmed", "Tentative", "On Leave", "Day Off"]

# ── Session ───────────────────────────────────────────────────────────────────
_USER_EMAIL    = os.environ.get("PAWFF_USER_EMAIL", "")
_USER_NAME     = os.environ.get("PAWFF_USER_NAME", "Unknown")
_USER_ROLE     = os.environ.get("PAWFF_USER_ROLE", "")
_USER_IS_ADMIN = os.environ.get("PAWFF_USER_IS_ADMIN", "0") == "1"


# ── Admin guard ───────────────────────────────────────────────────────────────
def _verify_admin() -> bool:
    """
    Confirm admin status via env var, then double-check against the DB.
    Shows an Access Denied dialog and returns False for non-admins.
    """
    is_admin = _USER_IS_ADMIN
    if not is_admin and _USER_EMAIL:
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
            "⛔  Staff Admin Panel is restricted to administrators only.\n\n"
            f"Logged in as: {_USER_NAME or 'Unknown'}\n"
            f"Role: {_USER_ROLE or 'Unknown'}\n\n"
            "Contact your system administrator if you need access."
        )
        msg.exec()
        return False
    return True


# ── Shared UI helpers ─────────────────────────────────────────────────────────
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


def _combo(options: list[str], current: str = "") -> QComboBox:
    c = QComboBox()
    c.addItems(options)
    if current in options:
        c.setCurrentText(current)
    c.setFixedHeight(36)
    c.setStyleSheet(
        f"QComboBox{{border:1px solid {C['border']};border-radius:8px;"
        f"padding:0 10px;background:{C['white']};font-size:12px;color:{C['text']};}}"
        f"QComboBox::drop-down{{border:none;width:20px;}}"
        f"QComboBox QAbstractItemView{{border:1px solid {C['border']};"
        f"selection-background-color:{C['accent_lt']};}}"
    )
    return c


def _field(placeholder="", value="", password=False) -> QLineEdit:
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    f.setFixedHeight(36)
    if value:
        f.setText(value)
    if password:
        f.setEchoMode(QLineEdit.EchoMode.Password)
    f.setStyleSheet(
        f"QLineEdit{{border:1px solid {C['border']};border-radius:8px;"
        f"padding:0 10px;background:{C['white']};font-size:12px;color:{C['text']};}}"
        f"QLineEdit:focus{{border-color:{C['accent']};background:{C['accent_lt']};}}"
    )
    return f


# ── Edit User Dialog ──────────────────────────────────────────────────────────
class EditUserDialog(QDialog):
    """Full editor for a single user: profile, role, station, admin flag, password reset."""

    saved = pyqtSignal()

    def __init__(self, user: dict, adb: AuthDB, parent=None):
        super().__init__(parent)
        self._user = user
        self._adb  = adb
        self.setWindowTitle(
            f"Edit User — {user['first_name']} {user['last_name']}"
        )
        self.setMinimumSize(520, 580)
        self.resize(560, 620)
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
        hc = QVBoxLayout()
        hc.setSpacing(3)
        hc.addWidget(lbl(
            f"✏️  {self._user['first_name']} {self._user['last_name']}",
            bold=True, size=15,
        ))
        hc.addWidget(lbl(self._user["email"], size=10, color=C["sub"]))
        hl.addLayout(hc)
        hl.addStretch()
        root.addWidget(hdr)

        # Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane{{border:none;background:{C['bg']};}}"
            f"QTabBar::tab{{background:{C['white']};color:{C['sub']};"
            f"border:1px solid {C['border']};border-bottom:none;"
            f"border-radius:6px 6px 0 0;padding:8px 18px;font-size:12px;}}"
            f"QTabBar::tab:selected{{background:{C['accent']};color:#fff;"
            f"font-weight:700;}}"
        )

        # ── Tab 1: Profile & Role ─────────────────────────────────────────────
        profile_tab = QWidget()
        profile_tab.setStyleSheet(f"background:{C['bg']};")
        fl = QFormLayout(profile_tab)
        fl.setContentsMargins(28, 24, 28, 24)
        fl.setSpacing(14)
        fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._first = _field(value=self._user.get("first_name", ""))
        self._last  = _field(value=self._user.get("last_name", ""))
        self._email = _field(value=self._user.get("email", ""))
        self._role  = _combo(ROLES, self._user.get("role", "Barista"))
        self._stn   = _combo(STATIONS, self._user.get("station", "Front Counter"))

        self._admin_chk = QCheckBox("Grant administrator privileges")
        self._admin_chk.setChecked(bool(self._user.get("is_admin")))
        self._admin_chk.setStyleSheet(
            f"QCheckBox{{font-size:12px;color:{C['text']};}}"
            f"QCheckBox::indicator{{width:16px;height:16px;border-radius:4px;"
            f"border:1.5px solid {C['border']};background:{C['white']};}}"
            f"QCheckBox::indicator:checked{{background:{C['warn']};"
            f"border-color:{C['warn']};}}"
        )

        fl.addRow(lbl("First name", size=11, color=C["sub"]), self._first)
        fl.addRow(lbl("Last name",  size=11, color=C["sub"]), self._last)
        fl.addRow(lbl("Email",      size=11, color=C["sub"]), self._email)
        fl.addRow(lbl("Role",       size=11, color=C["sub"]), self._role)
        fl.addRow(lbl("Station",    size=11, color=C["sub"]), self._stn)
        fl.addRow(QWidget(), hline())

        # Admin warning box
        warn_box = QFrame()
        warn_box.setStyleSheet(
            f"QFrame{{background:{C['admin_bg']};border:1px solid {C['admin_border']};"
            f"border-radius:8px;padding:4px;}}"
        )
        wl = QHBoxLayout(warn_box)
        wl.setContentsMargins(12, 10, 12, 10)
        warn_icon = lbl("⚠️", size=14)
        wl.addWidget(warn_icon)
        warn_text = lbl(
            "Admins can access the Staff Admin Panel and modify all user accounts.",
            size=10, color="#92400E",
        )
        warn_text.setWordWrap(True)
        wl.addWidget(warn_text, stretch=1)
        fl.addRow(QWidget(), warn_box)
        fl.addRow(QWidget(), self._admin_chk)

        tabs.addTab(profile_tab, "Profile & Role")

        # ── Tab 2: Password Reset ─────────────────────────────────────────────
        pw_tab = QWidget()
        pw_tab.setStyleSheet(f"background:{C['bg']};")
        pl = QFormLayout(pw_tab)
        pl.setContentsMargins(28, 24, 28, 24)
        pl.setSpacing(14)
        pl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._pw1 = _field("New password", password=True)
        self._pw2 = _field("Confirm new password", password=True)
        self._pw_err = lbl("", size=10, color=C["danger"])
        self._pw_err.setVisible(False)

        note = lbl(
            "Leave blank to keep the current password unchanged.",
            size=10, color=C["sub"],
        )
        note.setWordWrap(True)

        pl.addRow(note)
        pl.addRow(lbl("New password",     size=11, color=C["sub"]), self._pw1)
        pl.addRow(lbl("Confirm password", size=11, color=C["sub"]), self._pw2)
        pl.addRow(QWidget(), self._pw_err)

        tabs.addTab(pw_tab, "Reset Password")

        root.addWidget(tabs)

        # Footer buttons
        footer = QWidget()
        footer.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        ftl = QHBoxLayout(footer)
        ftl.setContentsMargins(24, 14, 24, 14)
        ftl.setSpacing(10)

        cancel = outline_btn("Cancel", height=40)
        cancel.clicked.connect(self.reject)
        ftl.addWidget(cancel)
        ftl.addStretch()

        save = make_btn("💾  Save Changes", C["accent"], hover=C["accent_dk"], height=40)
        save.clicked.connect(self._save)
        ftl.addWidget(save)
        root.addWidget(footer)

    def _save(self):
        first  = self._first.text().strip()
        last   = self._last.text().strip()
        email  = self._email.text().strip().lower()
        role   = self._role.currentText()
        stn    = self._stn.currentText()
        adm    = self._admin_chk.isChecked()
        pw1    = self._pw1.text()
        pw2    = self._pw2.text()

        if not first or not last or not email:
            QMessageBox.warning(self, "Missing Fields",
                                "First name, last name, and email are required.")
            return

        if pw1 or pw2:
            if pw1 != pw2:
                self._pw_err.setText("Passwords do not match.")
                self._pw_err.setVisible(True)
                return
            if len(pw1) < 8:
                self._pw_err.setText("Password must be at least 8 characters.")
                self._pw_err.setVisible(True)
                return

        try:
            uid = self._user["id"]
            self._adb.update_user(
                uid,
                first_name=first,
                last_name=last,
                email=email,
                role=role,
                station=stn,
                is_admin=adm,
            )
            if pw1:
                self._adb.update_password(uid, pw1)
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return

        self.saved.emit()
        QMessageBox.information(
            self, "Saved",
            f"User '{first} {last}' updated successfully."
        )
        self.accept()


# ── Shift Editor Dialog ───────────────────────────────────────────────────────
class ShiftEditorDialog(QDialog):
    """Add, edit, and delete shifts for a specific user."""

    def __init__(self, user: dict, adb: AuthDB, parent=None):
        super().__init__(parent)
        self._user = user
        self._adb  = adb
        self.setWindowTitle(
            f"Shifts — {user['first_name']} {user['last_name']}"
        )
        self.setMinimumSize(700, 500)
        self.resize(760, 560)
        self.setStyleSheet(
            f"QDialog{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        self._build()
        self._load()

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
        hl.setContentsMargins(24, 16, 24, 16)
        hc = QVBoxLayout(); hc.setSpacing(2)
        hc.addWidget(lbl(
            f"🗓  {self._user['first_name']} {self._user['last_name']} — Shifts",
            bold=True, size=14,
        ))
        hc.addWidget(lbl(
            f"{self._user.get('role', '')} · {self._user.get('station', '')}",
            size=10, color=C["sub"],
        ))
        hl.addLayout(hc)
        hl.addStretch()

        add_btn = make_btn("+ Add Shift", C["accent"], hover=C["accent_dk"],
                           height=34, size=11)
        add_btn.clicked.connect(self._add_shift)
        hl.addWidget(add_btn)
        root.addWidget(hdr)

        # Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Day", "Time", "Note", "Tag", "Actions"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Fixed
        )
        self._table.setColumnWidth(4, 160)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            f"QTableWidget{{border:none;background:{C['white']};"
            f"gridline-color:{C['border']};font-size:12px;}}"
            f"QTableWidget::item{{padding:8px 12px;}}"
            f"QTableWidget::item:alternate{{background:#FAFAFA;}}"
            f"QHeaderView::section{{background:{C['bg']};color:{C['sub']};"
            f"font-size:11px;font-weight:700;padding:8px 12px;"
            f"border:none;border-bottom:1px solid {C['border']};}}"
        )
        root.addWidget(self._table, stretch=1)

        # Footer
        footer = QWidget()
        footer.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 12, 24, 12)
        close_b = make_btn("Done", C["accent"], hover=C["accent_dk"], height=38)
        close_b.clicked.connect(self.accept)
        fl.addStretch()
        fl.addWidget(close_b)
        root.addWidget(footer)

    def _load(self):
        self._table.setRowCount(0)
        try:
            shifts = self._adb.get_user_shifts(self._user["id"])
        except Exception as exc:
            QMessageBox.warning(self, "Load Error", str(exc))
            return

        for row_idx, s in enumerate(shifts):
            self._table.insertRow(row_idx)
            for col, key in enumerate(["day", "time", "note", "tag"]):
                item = QTableWidgetItem(str(s.get(key) or "—"))
                item.setData(Qt.ItemDataRole.UserRole, s)
                self._table.setItem(row_idx, col, item)

            # Action buttons cell
            act_w = QWidget()
            act_w.setStyleSheet("background:transparent;")
            al = QHBoxLayout(act_w)
            al.setContentsMargins(6, 4, 6, 4)
            al.setSpacing(6)

            edit_b = outline_btn("Edit", fg=C["accent"],
                                 border=C["accent"], height=28, size=10)
            del_b  = outline_btn("Delete", fg=C["danger"],
                                 border=C["danger"], hover_bg=C["danger_lt"],
                                 height=28, size=10)

            shift_data = dict(s)
            edit_b.clicked.connect(
                lambda _, sd=shift_data: self._edit_shift(sd)
            )
            del_b.clicked.connect(
                lambda _, sd=shift_data: self._delete_shift(sd)
            )

            al.addWidget(edit_b)
            al.addWidget(del_b)
            self._table.setCellWidget(row_idx, 4, act_w)

    def _shift_form_dialog(self, title: str,
                           prefill: dict | None = None) -> dict | None:
        """Show a dialog to enter/edit shift details. Returns dict or None."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setFixedSize(400, 280)
        dlg.setStyleSheet(
            f"QDialog{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        fl = QFormLayout()
        fl.setSpacing(10)
        fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        day_f  = _field("e.g. Monday", value=prefill.get("day",  "") if prefill else "")
        time_f = _field("e.g. 9:00 AM – 5:30 PM",
                        value=prefill.get("time", "") if prefill else "")
        note_f = _field("Optional note", value=prefill.get("note", "") if prefill else "")
        tag_c  = _combo(SHIFT_TAGS, prefill.get("tag", "Scheduled") if prefill else "Scheduled")

        fl.addRow(lbl("Day *",  size=11, color=C["sub"]), day_f)
        fl.addRow(lbl("Time *", size=11, color=C["sub"]), time_f)
        fl.addRow(lbl("Note",   size=11, color=C["sub"]), note_f)
        fl.addRow(lbl("Tag",    size=11, color=C["sub"]), tag_c)
        lay.addLayout(fl)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        day  = day_f.text().strip()
        time = time_f.text().strip()
        if not day or not time:
            QMessageBox.warning(self, "Missing Fields", "Day and Time are required.")
            return None

        return {
            "day":  day,
            "time": time,
            "note": note_f.text().strip() or None,
            "tag":  tag_c.currentText(),
        }

    def _add_shift(self):
        data = self._shift_form_dialog("Add Shift")
        if not data:
            return
        try:
            result = self._adb.add_user_shift(
                self._user["id"],
                day=data["day"], time=data["time"],
                note=data["note"], tag=data["tag"],
            )
            if result is None:
                QMessageBox.warning(
                    self, "No Staff Record",
                    "No staff record linked to this user's email.\n"
                    "Shifts are stored against staff records — ensure the user's\n"
                    "email matches a record in the staff table.",
                )
                return
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        self._load()

    def _edit_shift(self, shift_data: dict):
        data = self._shift_form_dialog("Edit Shift", prefill=shift_data)
        if not data:
            return
        try:
            self._adb.update_shift(
                shift_data["id"],
                day=data["day"], time=data["time"],
                note=data["note"], tag=data["tag"],
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        self._load()

    def _delete_shift(self, shift_data: dict):
        confirm = QMessageBox.question(
            self, "Delete Shift",
            f"Delete the {shift_data.get('day', '')} shift at "
            f"{shift_data.get('time', '')}?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._adb.delete_shift(shift_data["id"])
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        self._load()


# ── Main Users Table ──────────────────────────────────────────────────────────
class UsersTablePanel(QWidget):
    """The main admin panel — shows all users with management actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._adb = get_auth_db()
        self.setStyleSheet(f"background:{C['bg']};")
        self._build()
        self._load()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Page header
        page_hdr = QWidget()
        page_hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        page_hdr.setFixedHeight(80)
        phl = QHBoxLayout(page_hdr)
        phl.setContentsMargins(28, 14, 28, 14)

        hc = QVBoxLayout(); hc.setSpacing(3)
        hc.addWidget(lbl("👥  Staff Admin Panel", bold=True, size=20))
        hc.addWidget(lbl(
            "Manage user accounts, roles, stations, schedules, and admin privileges.",
            size=11, color=C["sub"],
        ))
        phl.addLayout(hc, stretch=1)

        refresh_btn = make_btn("↻  Refresh", C["accent_lt"],
                               fg=C["accent"], hover=C["accent_lt"],
                               height=36, size=11)
        refresh_btn.clicked.connect(self._load)
        phl.addWidget(refresh_btn)

        root.addWidget(page_hdr)

        # Admin notice banner
        banner = QFrame()
        banner.setStyleSheet(
            f"QFrame{{background:{C['admin_bg']};"
            f"border-bottom:1px solid {C['admin_border']};}}"
        )
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(28, 10, 28, 10)
        bl.addWidget(lbl("⚠️", size=14))
        bl.addSpacing(8)
        bl.addWidget(lbl(
            f"You are viewing this as an administrator: {_USER_NAME} ({_USER_EMAIL}). "
            "Changes here are permanent and affect live user accounts.",
            size=11, color="#92400E",
        ))
        bl.addStretch()
        root.addWidget(banner)

        # Table
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Email", "Role", "Station", "Admin", "Joined", "Actions"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, 60)
        self._table.setColumnWidth(5, 110)
        self._table.setColumnWidth(6, 240)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(
            f"QTableWidget{{border:none;background:{C['white']};"
            f"font-size:12px;}}"
            f"QTableWidget::item{{padding:10px 14px;border-bottom:1px solid {C['border']};}}"
            f"QTableWidget::item:alternate{{background:#FAFAFA;}}"
            f"QTableWidget::item:selected{{background:{C['accent_lt']};"
            f"color:{C['text']};}}"
            f"QHeaderView::section{{background:{C['bg']};color:{C['sub']};"
            f"font-size:11px;font-weight:700;padding:10px 14px;"
            f"border:none;border-bottom:2px solid {C['border']};}}"
        )
        root.addWidget(self._table, stretch=1)

        # Status bar
        self._status_lbl = lbl("", size=10, color=C["sub"])
        sb = QWidget()
        sb.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        sl = QHBoxLayout(sb)
        sl.setContentsMargins(24, 8, 24, 8)
        sl.addWidget(self._status_lbl)
        sl.addStretch()
        root.addWidget(sb)

    def _load(self):
        self._table.setRowCount(0)
        try:
            users = self._adb.get_all_users()
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))
            return

        for row_idx, u in enumerate(users):
            self._table.insertRow(row_idx)

            # Name
            full = f"{u['first_name']} {u['last_name']}"
            name_item = QTableWidgetItem(full)
            name_item.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            self._table.setItem(row_idx, 0, name_item)

            # Email
            self._table.setItem(row_idx, 1, QTableWidgetItem(u["email"]))

            # Role
            role_item = QTableWidgetItem(u["role"])
            role_item.setForeground(QColor(C["accent"]))
            self._table.setItem(row_idx, 2, role_item)

            # Station
            self._table.setItem(row_idx, 3, QTableWidgetItem(u.get("station", "—")))

            # Admin badge
            adm_text = "✓" if u["is_admin"] else "—"
            adm_item = QTableWidgetItem(adm_text)
            adm_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if u["is_admin"]:
                adm_item.setForeground(QColor(C["warn"]))
                adm_item.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            self._table.setItem(row_idx, 4, adm_item)

            # Joined date
            joined = u.get("created_at")
            joined_str = (
                joined.strftime("%b %d, %Y")
                if hasattr(joined, "strftime") else str(joined or "—")
            )
            self._table.setItem(row_idx, 5, QTableWidgetItem(joined_str))

            # Actions
            act_w = QWidget()
            act_w.setStyleSheet("background:transparent;")
            al = QHBoxLayout(act_w)
            al.setContentsMargins(8, 4, 8, 4)
            al.setSpacing(6)

            edit_b    = outline_btn("✏️ Edit",    fg=C["accent"],
                                    border=C["accent"],   height=30, size=10)
            shifts_b  = outline_btn("🗓 Shifts",  fg=C["text"],
                                    border=C["border"],   height=30, size=10)
            delete_b  = outline_btn("🗑 Delete",  fg=C["danger"],
                                    border=C["danger"],
                                    hover_bg=C["danger_lt"], height=30, size=10)

            user_snap = dict(u)
            edit_b.clicked.connect(
                lambda _, us=user_snap: self._open_edit(us)
            )
            shifts_b.clicked.connect(
                lambda _, us=user_snap: self._open_shifts(us)
            )
            delete_b.clicked.connect(
                lambda _, us=user_snap: self._delete_user(us)
            )

            al.addWidget(edit_b)
            al.addWidget(shifts_b)
            al.addWidget(delete_b)
            self._table.setCellWidget(row_idx, 6, act_w)
            self._table.setRowHeight(row_idx, 52)

        self._status_lbl.setText(
            f"{len(users)} user{'s' if len(users) != 1 else ''}  ·  "
            f"Last refreshed {datetime.now().strftime('%I:%M:%S %p')}"
        )

    def _open_edit(self, user: dict):
        dlg = EditUserDialog(user, self._adb, self)
        dlg.saved.connect(self._load)
        dlg.exec()

    def _open_shifts(self, user: dict):
        dlg = ShiftEditorDialog(user, self._adb, self)
        dlg.exec()

    def _delete_user(self, user: dict):
        full = f"{user['first_name']} {user['last_name']}"
        if user["email"].lower() == _USER_EMAIL.lower():
            QMessageBox.warning(
                self, "Cannot Delete",
                "You cannot delete your own account while logged in.",
            )
            return

        confirm = QMessageBox.question(
            self, "Delete User",
            f"Permanently delete user '{full}' ({user['email']})?\n\n"
            "Their clock-in/out history will be preserved with a NULL user reference.\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            self._adb.delete_user(user["id"])
        except Exception as exc:
            QMessageBox.critical(self, "Delete Failed", str(exc))
            return

        QMessageBox.information(
            self, "Deleted", f"User '{full}' has been removed."
        )
        self._load()


# ── Main Window ───────────────────────────────────────────────────────────────
class StaffAdminWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Staff Admin Panel")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 640)
        self.setStyleSheet(
            f"QMainWindow,#central{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
            f"QToolBar{{background:{C['white']};"
            f"border-bottom:1px solid {C['border']};padding:4px 16px;spacing:8px;}}"
            f"QStatusBar{{background:{C['white']};"
            f"border-top:1px solid {C['border']};color:{C['sub']};"
            f"font-size:11px;padding:0 12px;}}"
        )
        self._build_toolbar()
        self._build_ui()
        self.statusBar().showMessage(
            f"  🔌  {db_info()}    |    🔑  Admin: {_USER_NAME}", 0
        )

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(
            f"font-weight:800;font-size:14px;color:{C['accent']};"
        )
        tb.addWidget(logo)

        admin_badge = QLabel("  🔑 Admin Panel  ")
        admin_badge.setStyleSheet(
            f"color:{C['warn']};font-size:11px;font-weight:700;"
            f"border:1px solid {C['admin_border']};border-radius:6px;"
            f"padding:4px 10px;background:{C['admin_bg']};"
        )
        tb.addWidget(admin_badge)

        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)

        user_badge = QLabel(f"👤  {_USER_NAME}  ·  {_USER_ROLE}")
        user_badge.setStyleSheet(
            f"color:{C['sub']};font-size:11px;"
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:4px 12px;background:{C['white']};"
        )
        tb.addWidget(user_badge)

        date_lbl = QLabel(
            f"  📅  {datetime.now().strftime('%B %d, %Y')}"
        )
        date_lbl.setStyleSheet(
            f"color:{C['sub']};font-size:11px;"
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:4px 12px;background:{C['white']};"
        )
        tb.addWidget(date_lbl)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        try:
            from Sidebar import PawffinatedSidebar
            layout.addWidget(PawffinatedSidebar(active_page="Staff Admin"))
        except ImportError:
            pass

        layout.addWidget(UsersTablePanel(), stretch=1)

    def closeEvent(self, event):
        close_db()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Pawffinated Staff Admin")

    if not _verify_admin():
        sys.exit(1)

    try:
        win = StaffAdminWindow()
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
