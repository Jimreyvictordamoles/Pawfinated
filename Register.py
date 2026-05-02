"""
PAWFFINATED – Registration Screen  (PyQt6 Edition)
===================================================
Run standalone:
    python Register.py

On successful registration → redirects back to Login.py
"""

from __future__ import annotations
import sys, subprocess, os

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QLineEdit, QVBoxLayout, QHBoxLayout, QFrame, QComboBox,
    QSizePolicy, QMessageBox, QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    white     = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_dk = "#1E5A45",
    accent_lt = "#E8F4F0",
    danger    = "#D94F4F",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    border    = "#E5E7EB",
    brand_bg  = "#5C3D2E",
)

# ── Shared account store (same dict as Login.py if run together) ──────────────
try:
    from Login import ACCOUNTS
except ImportError:
    ACCOUNTS: dict = {}


# ── Helpers ───────────────────────────────────────────────────────────────────
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


def _field(placeholder="", password=False, value="") -> QLineEdit:
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    f.setFixedHeight(40)
    if password:
        f.setEchoMode(QLineEdit.EchoMode.Password)
    if value:
        f.setText(value)
    f.setStyleSheet(
        f"QLineEdit{{border:1px solid {C['border']};border-radius:8px;"
        f"padding:0 12px;background:{C['white']};font-size:13px;color:{C['text']};}}"
        f"QLineEdit:focus{{border:1px solid {C['accent']};background:{C['accent_lt']};}}"
    )
    return f


def _combo(options: list[str]) -> QComboBox:
    c = QComboBox()
    c.addItems(options)
    c.setFixedHeight(40)
    c.setStyleSheet(
        f"QComboBox{{border:1px solid {C['border']};border-radius:8px;"
        f"padding:0 12px;background:{C['white']};font-size:13px;color:{C['text']};}}"
        f"QComboBox::drop-down{{border:none;width:24px;}}"
        f"QComboBox QAbstractItemView{{border:1px solid {C['border']};"
        f"selection-background-color:{C['accent_lt']};}}"
    )
    return c


def _find(filename: str) -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    for p in [os.path.join(here, filename), os.path.join(os.getcwd(), filename)]:
        if os.path.isfile(p):
            return p
    return None


def _launch(script: str):
    path = _find(script)
    if path:
        subprocess.Popen([sys.executable, path])
    else:
        QMessageBox.warning(None, "Not Found", f"Could not locate {script}.")


# ── Registration Form ─────────────────────────────────────────────────────────
class RegisterCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C['bg']};")

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;background:transparent;")

        container = QWidget()
        container.setStyleSheet(f"background:{C['bg']};")
        root = QVBoxLayout(container)
        root.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        root.setContentsMargins(0, 40, 0, 40)
        root.setSpacing(0)

        card = QFrame()
        card.setFixedWidth(520)
        card.setStyleSheet(
            f"QFrame{{background:{C['white']};border:1px solid {C['border']};"
            f"border-radius:14px;}}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(36, 36, 36, 36)
        cl.setSpacing(0)

        # Header
        brand_row = QHBoxLayout(); brand_row.setSpacing(10)
        icon = QLabel("🐾")
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"background:{C['brand_bg']};border-radius:7px;font-size:15px;"
        )
        brand_row.addWidget(icon)
        brand_row.addWidget(lbl("PAWFFINATED", bold=True, size=12, color=C["text"]))
        brand_row.addStretch()
        cl.addLayout(brand_row)
        cl.addSpacing(18)

        cl.addWidget(lbl("Create your account", bold=True, size=18))
        cl.addSpacing(4)
        cl.addWidget(lbl(
            "Fill in your details to request access. Your manager will review and approve.",
            size=11, color=C["sub"]
        ))
        cl.addSpacing(24)
        cl.addWidget(hline())
        cl.addSpacing(20)

        # ── Name row ──────────────────────────────────────────────────────────
        name_row = QHBoxLayout(); name_row.setSpacing(14)
        first_col = QVBoxLayout(); first_col.setSpacing(5)
        first_col.addWidget(lbl("First name *", size=11, color=C["sub"]))
        self.first = _field("Sarah")
        first_col.addWidget(self.first)
        name_row.addLayout(first_col)

        last_col = QVBoxLayout(); last_col.setSpacing(5)
        last_col.addWidget(lbl("Last name *", size=11, color=C["sub"]))
        self.last = _field("Jenkins")
        last_col.addWidget(self.last)
        name_row.addLayout(last_col)
        cl.addLayout(name_row)
        cl.addSpacing(14)

        # ── Email ─────────────────────────────────────────────────────────────
        cl.addWidget(lbl("Work email *", size=11, color=C["sub"]))
        cl.addSpacing(5)
        self.email = _field("yourname@pawffinated.co")
        cl.addWidget(self.email)
        cl.addSpacing(14)

        # ── Password row ──────────────────────────────────────────────────────
        pw_row = QHBoxLayout(); pw_row.setSpacing(14)
        pw1_col = QVBoxLayout(); pw1_col.setSpacing(5)
        pw1_col.addWidget(lbl("Password *", size=11, color=C["sub"]))
        self.pw = _field("Min 8 characters", password=True)
        pw1_col.addWidget(self.pw)
        pw_row.addLayout(pw1_col)

        pw2_col = QVBoxLayout(); pw2_col.setSpacing(5)
        pw2_col.addWidget(lbl("Confirm password *", size=11, color=C["sub"]))
        self.pw2 = _field("Repeat password", password=True)
        pw2_col.addWidget(self.pw2)
        pw_row.addLayout(pw2_col)
        cl.addLayout(pw_row)
        cl.addSpacing(14)

        # ── Role / Station row ────────────────────────────────────────────────
        rs_row = QHBoxLayout(); rs_row.setSpacing(14)
        role_col = QVBoxLayout(); role_col.setSpacing(5)
        role_col.addWidget(lbl("Role", size=11, color=C["sub"]))
        self.role = _combo([
            "Store Manager", "Shift Supervisor", "Barista",
            "Cashier", "Cashier Trainee", "Kitchen Staff", "Senior Barista",
        ])
        role_col.addWidget(self.role)
        rs_row.addLayout(role_col)

        stn_col = QVBoxLayout(); stn_col.setSpacing(5)
        stn_col.addWidget(lbl("Station", size=11, color=C["sub"]))
        self.station = _combo([
            "Front Counter", "Espresso Bar", "Drive-Thru",
            "Back Office", "Kitchen", "Register 1", "Register 2",
        ])
        stn_col.addWidget(self.station)
        rs_row.addLayout(stn_col)
        cl.addLayout(rs_row)
        cl.addSpacing(20)

        # ── Error label ───────────────────────────────────────────────────────
        self.error_lbl = QLabel()
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setStyleSheet(
            f"color:{C['danger']};font-size:11px;background:transparent;"
        )
        self.error_lbl.setVisible(False)
        cl.addWidget(self.error_lbl)
        cl.addSpacing(4)

        cl.addWidget(hline())
        cl.addSpacing(18)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        back = QPushButton("← Back to login")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(42)
        back.setStyleSheet(
            f"QPushButton{{background:{C['white']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:8px;"
            f"font-size:12px;font-weight:600;padding:0 20px;}}"
            f"QPushButton:hover{{background:{C['bg']};}}"
        )
        back.clicked.connect(self._go_login)
        btn_row.addWidget(back)
        btn_row.addStretch()

        create = QPushButton("Create account")
        create.setCursor(Qt.CursorShape.PointingHandCursor)
        create.setFixedHeight(42)
        create.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:#FFFFFF;border:none;"
            f"border-radius:8px;font-size:13px;font-weight:700;padding:0 28px;}}"
            f"QPushButton:hover{{background:{C['accent_dk']};}}"
        )
        create.clicked.connect(self._do_register)
        btn_row.addWidget(create)
        cl.addLayout(btn_row)

        root.addWidget(card)
        scroll.setWidget(container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    # ── Validation & submit ───────────────────────────────────────────────────
    def _do_register(self):
        first   = self.first.text().strip()
        last    = self.last.text().strip()
        email   = self.email.text().strip()
        pw      = self.pw.text()
        pw2     = self.pw2.text()
        role    = self.role.currentText()
        station = self.station.currentText()

        if not first or not last or not email or not pw or not pw2:
            self._show_error("Please fill in all required fields (*).")
            return
        if "@" not in email or "." not in email:
            self._show_error("Please enter a valid email address.")
            return
        if len(pw) < 8:
            self._show_error("Password must be at least 8 characters.")
            return
        if pw != pw2:
            self._show_error("Passwords do not match. Please try again.")
            return
        if email in ACCOUNTS:
            self._show_error("An account with this email already exists.")
            return

        # Register the new account
        ACCOUNTS[email] = {
            "password": pw,
            "name":     f"{first} {last}",
            "role":     role,
            "station":  station,
        }

        QMessageBox.information(
            self, "Account Created",
            f"Welcome, {first}!\n\n"
            "Your account has been created successfully.\n"
            "Please log in with your new credentials."
        )
        self._go_login()

    def _show_error(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_lbl.setVisible(True)

    def _go_login(self):
        _launch("Login.py")
        self.window().close()


# ── Main Window ───────────────────────────────────────────────────────────────
class RegisterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Create Account")
        self.resize(680, 700)
        self.setMinimumSize(580, 560)
        self.setStyleSheet(
            f"QMainWindow{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        self.setCentralWidget(RegisterCard())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Pawffinated Register")
    win = RegisterWindow()
    win.show()
    sys.exit(app.exec())