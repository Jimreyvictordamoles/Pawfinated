"""
PAWFFINATED – Login Screen  (PyQt6 Edition)
============================================
Run:
    python Login.py

Features:
  • Staff login with email + password validation
  • "Forgot Password?" flow: name, email, role, birthdate (with calendar picker)
  • "Sign Up Now!" swaps the right panel to the registration form IN-PLACE
  • On successful login → auto-launches Dashboard.py and closes
"""

from __future__ import annotations
import sys, subprocess, os

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QLineEdit, QHBoxLayout, QVBoxLayout, QCheckBox, QDialog,
    QComboBox, QCalendarWidget, QMessageBox, QSizePolicy, QStackedWidget,
    QScrollArea,
)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QFont

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg        = "#F7F5F0",
    white     = "#FFFFFF",
    accent    = "#2D7A5F",
    accent_lt = "#E8F4F0",
    accent_dk = "#1E5A45",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    border    = "#E5E7EB",
    panel_bg  = "#E8E4A0",
    danger    = "#D94F4F",
    danger_lt = "#FEE2E2",
    ok        = "#059669",
    ok_lt     = "#D1FAE5",
    input_bg  = "#F9F9F7",
    brand_bg  = "#5C3D2E",
)

# ── Demo credentials ──────────────────────────────────────────────────────────
VALID_USERS = [
    {"email": "manager@pawffinated.com", "password": "manager123", "name": "Sarah Jenkins",  "role": "Store Manager"},
    {"email": "barista@pawffinated.com", "password": "barista123", "name": "Maya Patel",     "role": "Barista"},
    {"email": "cashier@pawffinated.com", "password": "cashier123", "name": "Daniel Kim",     "role": "Cashier"},
    {"email": "admin@pawffinated.com",   "password": "admin123",   "name": "Leah Johnson",   "role": "Administrator"},
    {"email": "demo@pawffinated.com",    "password": "demo",       "name": "Demo User",      "role": "Store Manager"},
]

ACCOUNTS: dict = {}   # holds newly registered users at runtime

ROLES = ["Store Manager", "Shift Supervisor", "Barista", "Cashier",
         "Cashier Trainee", "Kitchen Staff", "Administrator"]


# ── Shared helpers ────────────────────────────────────────────────────────────
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


def inp_style() -> str:
    return (
        f"QLineEdit{{background:{C['input_bg']};border:1.5px solid {C['border']};"
        f"border-radius:9px;padding:10px 14px;font-size:13px;color:{C['text']};}}"
        f"QLineEdit:focus{{border-color:{C['accent']};background:{C['white']};}}"
        f"QLineEdit::placeholder{{color:{C['sub']};}}"
    )


def field_input(placeholder="", password=False) -> QLineEdit:
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    f.setFixedHeight(42)
    if password:
        f.setEchoMode(QLineEdit.EchoMode.Password)
    f.setStyleSheet(inp_style())
    return f


def combo_input(options: list[str]) -> QComboBox:
    c = QComboBox()
    c.addItems(options)
    c.setFixedHeight(42)
    c.setStyleSheet(
        f"QComboBox{{background:{C['input_bg']};border:1.5px solid {C['border']};"
        f"border-radius:9px;padding:0 14px;font-size:13px;color:{C['text']};}}"
        f"QComboBox::drop-down{{border:none;width:24px;}}"
        f"QComboBox QAbstractItemView{{border:1px solid {C['border']};"
        f"selection-background-color:{C['accent_lt']};}}"
    )
    return c


def _find_script(filename: str) -> str | None:
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        os.path.join(os.getcwd(), filename),
        filename,
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


# ── Left branding panel ───────────────────────────────────────────────────────
class BrandPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(340)
        self.setStyleSheet(f"background:{C['panel_bg']};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(44, 44, 44, 40)
        lay.setSpacing(0)

        # Logo
        logo_row = QHBoxLayout(); logo_row.setSpacing(12)
        paw = QLabel("🐾")
        paw.setFixedSize(42, 42)
        paw.setAlignment(Qt.AlignmentFlag.AlignCenter)
        paw.setStyleSheet("background:#5C3D2E;border-radius:10px;font-size:20px;border:none;")
        logo_row.addWidget(paw)
        brand = QLabel("PAWFFINATED")
        bf = QFont("Segoe UI", 13); bf.setBold(True)
        bf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        brand.setFont(bf)
        brand.setStyleSheet(f"color:{C['text']};background:transparent;")
        logo_row.addWidget(brand)
        logo_row.addStretch()
        lay.addLayout(logo_row)
        lay.addSpacing(36)

        # Badge
        badge = QLabel("  Staff/admin access  ")
        badge.setFixedHeight(26)
        badge.setStyleSheet(
            f"background:rgba(255,255,255,0.55);color:{C['text']};"
            f"border-radius:13px;font-size:11px;font-weight:600;padding:0 10px;"
        )
        badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay.addWidget(badge)
        lay.addSpacing(20)

        # Headline
        headline = QLabel("Sign in to manage\nstock, sales, and\norders.")
        hf = QFont("Segoe UI", 26); hf.setBold(True)
        headline.setFont(hf)
        headline.setStyleSheet(f"color:{C['text']};background:transparent;")
        headline.setWordWrap(True)
        lay.addWidget(headline)
        lay.addSpacing(16)

        sub = QLabel(
            "Access the back office with your staff credentials to\n"
            "review inventory, update items, and keep the counter\n"
            "moving without delays."
        )
        sub.setFont(QFont("Segoe UI", 11))
        sub.setStyleSheet(f"color:{C['sub']};background:transparent;")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(32)

        for emoji, text in [
            ("📦", "Real-time inventory visibility"),
            ("🔒", "Secure staff-only dashboard access"),
            ("📋", "Orders, items, and sales in one place"),
        ]:
            row = QHBoxLayout(); row.setSpacing(12)
            em = QLabel(emoji)
            em.setFixedSize(36, 36)
            em.setAlignment(Qt.AlignmentFlag.AlignCenter)
            em.setStyleSheet("background:rgba(45,122,95,0.18);border-radius:8px;font-size:16px;border:none;")
            row.addWidget(em)
            row.addWidget(lbl(text, size=11))
            row.addStretch()
            lay.addLayout(row)
            lay.addSpacing(10)

        lay.addStretch()
        lay.addWidget(lbl("Need help signing in?", size=10, color=C["sub"]))
        lay.addSpacing(2)
        lay.addWidget(lbl("Contact your store manager or system administrator", bold=True, size=11))


# ── Forgot Password Dialog ────────────────────────────────────────────────────
class ForgotPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reset Password")
        self.setMinimumSize(480, 520)
        self.setStyleSheet(f"background:{C['white']};")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(0)

        lay.addWidget(lbl("🔑  Reset Your Password", bold=True, size=17))
        lay.addSpacing(6)
        lay.addWidget(lbl("Fill in your details so we can verify your identity.", size=11, color=C["sub"]))
        lay.addSpacing(20)
        lay.addWidget(hline())
        lay.addSpacing(20)

        def add_field(label_text, widget):
            col = QVBoxLayout(); col.setSpacing(5)
            col.addWidget(lbl(label_text, size=10, color=C["sub"], bold=True))
            col.addWidget(widget)
            lay.addLayout(col)
            lay.addSpacing(14)

        self.f_name = field_input("e.g. Sarah Jenkins")
        add_field("Full Name *", self.f_name)

        self.f_email = field_input("your.email@pawffinated.com")
        add_field("Work Email *", self.f_email)

        self.f_role = combo_input(ROLES)
        add_field("Role *", self.f_role)

        # Birthdate with calendar picker
        bday_col = QVBoxLayout(); bday_col.setSpacing(5)
        bday_col.addWidget(lbl("Date of Birth *", size=10, color=C["sub"], bold=True))
        bday_row = QHBoxLayout(); bday_row.setSpacing(8)
        self.f_bday = field_input("Select your birthdate…")
        self.f_bday.setReadOnly(True)
        bday_row.addWidget(self.f_bday, stretch=1)
        cal_btn = QPushButton("📅")
        cal_btn.setFixedSize(42, 42)
        cal_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cal_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent_lt']};border:1.5px solid {C['accent']};"
            f"border-radius:9px;font-size:18px;}}"
            f"QPushButton:hover{{background:{C['accent']};color:white;}}"
        )
        cal_btn.clicked.connect(self._pick_date)
        bday_row.addWidget(cal_btn)
        bday_col.addLayout(bday_row)
        lay.addLayout(bday_col)
        lay.addSpacing(24)

        lay.addWidget(hline())
        lay.addSpacing(20)

        btn_row = QHBoxLayout(); btn_row.setSpacing(10); btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setFixedHeight(42)
        cancel.setStyleSheet(
            f"QPushButton{{background:{C['border']};color:{C['text']};"
            f"border-radius:9px;font-size:13px;font-weight:600;border:none;padding:0 22px;}}"
            f"QPushButton:hover{{background:#D1D5DB;}}"
        )
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Submit Request")
        submit.setCursor(Qt.CursorShape.PointingHandCursor)
        submit.setFixedHeight(42)
        submit.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:white;"
            f"border-radius:9px;font-size:13px;font-weight:700;border:none;padding:0 22px;}}"
            f"QPushButton:hover{{background:{C['accent_dk']};}}"
        )
        submit.clicked.connect(self._submit)
        btn_row.addWidget(cancel)
        btn_row.addWidget(submit)
        lay.addLayout(btn_row)

    def _pick_date(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Select Date of Birth")
        dlg.setStyleSheet(f"background:{C['white']};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        cal = QCalendarWidget()
        cal.setGridVisible(False)
        cal.setStyleSheet(
            f"QCalendarWidget{{background:{C['white']};}}"
            f"QCalendarWidget QToolButton{{background:{C['accent']};color:white;"
            f"border-radius:4px;padding:4px 8px;font-weight:600;}}"
            f"QCalendarWidget QAbstractItemView{{background:{C['white']};"
            f"selection-background-color:{C['accent']};selection-color:white;}}"
            f"QCalendarWidget QWidget#qt_calendar_navigationbar{{background:{C['accent_lt']};"
            f"border-radius:8px;padding:4px;}}"
        )
        lay.addWidget(cal)
        ok_btn = QPushButton("Select")
        ok_btn.setFixedHeight(38)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:white;border:none;"
            f"border-radius:8px;font-weight:700;font-size:13px;}}"
            f"QPushButton:hover{{background:{C['accent_dk']};}}"
        )
        ok_btn.clicked.connect(dlg.accept)
        lay.addWidget(ok_btn)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.f_bday.setText(cal.selectedDate().toString("MMMM d, yyyy"))

    def _submit(self):
        if not self.f_name.text().strip() or not self.f_email.text().strip() or not self.f_bday.text().strip():
            QMessageBox.warning(self, "Missing Information", "Please complete all required fields.")
            return
        QMessageBox.information(
            self, "Request Submitted",
            f"✅  Password reset request submitted!\n\n"
            f"Name:  {self.f_name.text().strip()}\n"
            f"Email: {self.f_email.text().strip()}\n"
            f"Role:  {self.f_role.currentText()}\n"
            f"DOB:   {self.f_bday.text().strip()}\n\n"
            f"Your manager will contact you shortly."
        )
        self.accept()


# ── Login Form — page 0 ───────────────────────────────────────────────────────
class LoginForm(QWidget):
    def __init__(self, switch_to_register, parent=None):
        super().__init__(parent)
        self._switch = switch_to_register
        self.setStyleSheet(f"background:{C['bg']};")
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setFixedWidth(440)
        card.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:16px;border:1px solid {C['border']};}}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(40, 36, 40, 36)
        cl.setSpacing(0)

        cl.addWidget(lbl("Welcome back", bold=True, size=22))
        cl.addSpacing(6)
        cl.addWidget(lbl(
            "Use your staff email and password to continue to the\n"
            "Pawffinated admin workspace.", size=11, color=C["sub"]
        ))
        cl.addSpacing(28)

        # Email
        cl.addWidget(lbl("Work email", size=11, color=C["sub"], bold=True))
        cl.addSpacing(6)
        self.email_field = field_input("manager@pawffinated.com")
        self.email_field.setFixedHeight(46)
        self.email_field.returnPressed.connect(self._try_login)
        cl.addWidget(self.email_field)
        cl.addSpacing(16)

        # Password
        pw_hdr = QHBoxLayout()
        pw_hdr.addWidget(lbl("Password", size=11, color=C["sub"], bold=True))
        pw_hdr.addStretch()
        forgot_btn = QPushButton("Forgot password?")
        forgot_btn.setFlat(True)
        forgot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        forgot_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['accent']};"
            f"font-size:11px;font-weight:600;border:none;padding:0;}}"
            f"QPushButton:hover{{color:{C['accent_dk']};}}"
        )
        forgot_btn.clicked.connect(lambda: ForgotPasswordDialog(self).exec())
        pw_hdr.addWidget(forgot_btn)
        cl.addLayout(pw_hdr)
        cl.addSpacing(6)

        self.pw_field = field_input("••••••••", password=True)
        self.pw_field.setFixedHeight(46)
        self.pw_field.returnPressed.connect(self._try_login)
        cl.addWidget(self.pw_field)
        cl.addSpacing(18)

        # Remember me
        chk_row = QHBoxLayout()
        self.remember = QCheckBox()
        self.remember.setChecked(True)
        self.remember.setStyleSheet(
            f"QCheckBox::indicator{{width:18px;height:18px;border-radius:4px;"
            f"border:1.5px solid {C['border']};background:{C['input_bg']};}}"
            f"QCheckBox::indicator:checked{{background:{C['accent']};border-color:{C['accent']};}}"
        )
        chk_row.addWidget(self.remember)
        chk_row.addSpacing(8)
        chk_row.addWidget(lbl("Keep me signed in on this device", size=12))
        chk_row.addStretch()
        cl.addLayout(chk_row)
        cl.addSpacing(20)

        # Error label
        self.error_lbl = QLabel("")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_lbl.setStyleSheet(
            f"background:{C['danger_lt']};color:{C['danger']};"
            f"border-radius:8px;padding:8px 12px;font-size:12px;font-weight:600;border:none;"
        )
        self.error_lbl.setVisible(False)
        cl.addWidget(self.error_lbl)
        cl.addSpacing(6)

        # Login button
        self.login_btn = QPushButton("  →  Log-in")
        self.login_btn.setFixedHeight(50)
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:white;"
            f"border-radius:10px;font-size:14px;font-weight:700;border:none;}}"
            f"QPushButton:hover{{background:{C['accent_dk']};}}"
            f"QPushButton:pressed{{background:#163D2D;}}"
        )
        self.login_btn.clicked.connect(self._try_login)
        cl.addWidget(self.login_btn)
        cl.addSpacing(14)

        # Security note
        sec = QFrame()
        sec.setStyleSheet(
            f"QFrame{{background:{C['bg']};border-radius:9px;border:1px solid {C['border']};}}"
        )
        sec_lay = QHBoxLayout(sec)
        sec_lay.setContentsMargins(14, 10, 14, 10)
        sec_lay.setSpacing(10)
        lock = QLabel("🛡")
        lock.setFont(QFont("Segoe UI", 14))
        lock.setStyleSheet("background:transparent;")
        sec_lay.addWidget(lock)
        sec_note = lbl("Staff/admin login only. Access is monitored for security.", size=10, color=C["sub"])
        sec_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sec_lay.addWidget(sec_note, stretch=1)
        cl.addWidget(sec)
        cl.addSpacing(16)

        # Sign up row — stays in the same window
        su_row = QHBoxLayout()
        su_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        su_row.addWidget(lbl("Don't have an account?", size=11, color=C["sub"]))
        su_row.addSpacing(4)
        su_btn = QPushButton("Sign Up Now!")
        su_btn.setFlat(True)
        su_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        su_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['accent']};"
            f"font-size:11px;font-weight:700;border:none;padding:0;}}"
            f"QPushButton:hover{{color:{C['accent_dk']};}}"
        )
        su_btn.clicked.connect(self._switch)   # ← swaps to register page in-place
        su_row.addWidget(su_btn)
        cl.addLayout(su_row)

        outer.addWidget(card)

    def _try_login(self):
        email = self.email_field.text().strip().lower()
        pw    = self.pw_field.text()
        if not email or not pw:
            self._show_error("Please enter your email and password.")
            return
        all_users = list(VALID_USERS) + [
            {"email": k, "password": v["password"], "name": v["name"], "role": v["role"]}
            for k, v in ACCOUNTS.items()
        ]
        for user in all_users:
            if user["email"].lower() == email and user["password"] == pw:
                self._show_success()
                return
        self._show_error("Incorrect email or password. Please try again.")
        self.pw_field.clear()
        self.pw_field.setFocus()

    def _show_error(self, msg: str):
        self.error_lbl.setText(f"⚠  {msg}")
        self.error_lbl.setVisible(True)

    def _show_success(self):
        self.login_btn.setText("✓  Logging in…")
        self.login_btn.setStyleSheet(
            f"QPushButton{{background:{C['ok']};color:white;"
            f"border-radius:10px;font-size:14px;font-weight:700;border:none;}}"
        )
        self.login_btn.setEnabled(False)
        self.error_lbl.setVisible(False)
        QTimer.singleShot(900, self._launch_dashboard)

    def _launch_dashboard(self):
        script = _find_script("Dashboard.py")
        if script:
            subprocess.Popen([sys.executable, script])
        else:
            QMessageBox.warning(
                self, "Dashboard Not Found",
                "Logged in successfully, but Dashboard.py was not found.\n"
                "Make sure all Pawffinated files are in the same folder."
            )
        self.window().close()


# ── Register Form — page 1 ────────────────────────────────────────────────────
class RegisterForm(QWidget):
    def __init__(self, switch_to_login, parent=None):
        super().__init__(parent)
        self._switch = switch_to_login
        self.setStyleSheet(f"background:{C['bg']};")

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;background:transparent;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setStyleSheet(f"background:{C['bg']};")
        root = QVBoxLayout(container)
        root.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        root.setContentsMargins(0, 40, 0, 40)
        root.setSpacing(0)

        card = QFrame()
        card.setFixedWidth(480)
        card.setStyleSheet(
            f"QFrame{{background:{C['white']};border:1px solid {C['border']};border-radius:16px;}}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(40, 36, 40, 36)
        cl.setSpacing(0)

        # Header
        brand_row = QHBoxLayout(); brand_row.setSpacing(10)
        icon = QLabel("🐾")
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"background:{C['brand_bg']};border-radius:7px;font-size:15px;border:none;")
        brand_row.addWidget(icon)
        brand_row.addWidget(lbl("PAWFFINATED", bold=True, size=12))
        brand_row.addStretch()
        cl.addLayout(brand_row)
        cl.addSpacing(18)

        cl.addWidget(lbl("Create your account", bold=True, size=20))
        cl.addSpacing(4)
        cl.addWidget(lbl(
            "Fill in your details to request access. Your manager will review and approve.",
            size=11, color=C["sub"]
        ))
        cl.addSpacing(22)
        cl.addWidget(hline())
        cl.addSpacing(20)

        # Name row
        name_row = QHBoxLayout(); name_row.setSpacing(14)
        fc = QVBoxLayout(); fc.setSpacing(5)
        fc.addWidget(lbl("First name *", size=10, color=C["sub"]))
        self.first = field_input("Sarah")
        fc.addWidget(self.first)
        name_row.addLayout(fc)
        lc_lay = QVBoxLayout(); lc_lay.setSpacing(5)
        lc_lay.addWidget(lbl("Last name *", size=10, color=C["sub"]))
        self.last = field_input("Jenkins")
        lc_lay.addWidget(self.last)
        name_row.addLayout(lc_lay)
        cl.addLayout(name_row)
        cl.addSpacing(14)

        # Email
        cl.addWidget(lbl("Work email *", size=10, color=C["sub"]))
        cl.addSpacing(5)
        self.email = field_input("yourname@pawffinated.com")
        cl.addWidget(self.email)
        cl.addSpacing(14)

        # Password row
        pw_row = QHBoxLayout(); pw_row.setSpacing(14)
        p1c = QVBoxLayout(); p1c.setSpacing(5)
        p1c.addWidget(lbl("Password *", size=10, color=C["sub"]))
        self.pw = field_input("Min 8 characters", password=True)
        p1c.addWidget(self.pw)
        pw_row.addLayout(p1c)
        p2c = QVBoxLayout(); p2c.setSpacing(5)
        p2c.addWidget(lbl("Confirm password *", size=10, color=C["sub"]))
        self.pw2 = field_input("Repeat password", password=True)
        p2c.addWidget(self.pw2)
        pw_row.addLayout(p2c)
        cl.addLayout(pw_row)
        cl.addSpacing(14)

        # Role / Station row
        rs_row = QHBoxLayout(); rs_row.setSpacing(14)
        rc = QVBoxLayout(); rc.setSpacing(5)
        rc.addWidget(lbl("Role", size=10, color=C["sub"]))
        self.role = combo_input([
            "Store Manager", "Shift Supervisor", "Barista",
            "Cashier", "Cashier Trainee", "Kitchen Staff", "Senior Barista",
        ])
        rc.addWidget(self.role)
        rs_row.addLayout(rc)
        sc = QVBoxLayout(); sc.setSpacing(5)
        sc.addWidget(lbl("Station", size=10, color=C["sub"]))
        self.station = combo_input([
            "Front Counter", "Espresso Bar", "Drive-Thru",
            "Back Office", "Kitchen", "Register 1", "Register 2",
        ])
        sc.addWidget(self.station)
        rs_row.addLayout(sc)
        cl.addLayout(rs_row)
        cl.addSpacing(16)

        # Error label
        self.error_lbl = QLabel()
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setStyleSheet(
            f"background:{C['danger_lt']};color:{C['danger']};"
            f"border-radius:8px;padding:8px 12px;font-size:12px;font-weight:600;border:none;"
        )
        self.error_lbl.setVisible(False)
        cl.addWidget(self.error_lbl)
        cl.addSpacing(4)

        cl.addWidget(hline())
        cl.addSpacing(18)

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        back = QPushButton("← Back to Login")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(44)
        back.setStyleSheet(
            f"QPushButton{{background:{C['white']};color:{C['text']};"
            f"border:1.5px solid {C['border']};border-radius:9px;"
            f"font-size:12px;font-weight:600;padding:0 20px;}}"
            f"QPushButton:hover{{background:{C['bg']};}}"
        )
        back.clicked.connect(self._switch)   # ← swaps back to login page in-place
        btn_row.addWidget(back)
        btn_row.addStretch()
        create = QPushButton("Create Account")
        create.setCursor(Qt.CursorShape.PointingHandCursor)
        create.setFixedHeight(44)
        create.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:white;border:none;"
            f"border-radius:9px;font-size:13px;font-weight:700;padding:0 28px;}}"
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

    def _do_register(self):
        first   = self.first.text().strip()
        last    = self.last.text().strip()
        email   = self.email.text().strip().lower()
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
        all_existing = [u["email"].lower() for u in VALID_USERS] + list(ACCOUNTS.keys())
        if email in all_existing:
            self._show_error("An account with this email already exists.")
            return

        ACCOUNTS[email] = {
            "password": pw, "name": f"{first} {last}",
            "role": role, "station": station,
        }

        QMessageBox.information(
            self, "Account Created",
            f"Welcome, {first}! 🎉\n\n"
            "Your account has been created successfully.\n"
            "Please log in with your new credentials."
        )
        self._switch()   # go straight back to login

    def _show_error(self, msg: str):
        self.error_lbl.setText(f"⚠  {msg}")
        self.error_lbl.setVisible(True)


# ── Main Window ───────────────────────────────────────────────────────────────
class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Log-in")
        self.resize(1100, 700)
        self.setMinimumSize(860, 600)
        self.setStyleSheet(
            f"QMainWindow{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(BrandPanel(), stretch=9)

        # QStackedWidget holds both pages — no new window ever opens
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{C['bg']};")

        self._login_page    = LoginForm(switch_to_register=self._show_register)
        self._register_page = RegisterForm(switch_to_login=self._show_login)

        self._stack.addWidget(self._login_page)    # index 0
        self._stack.addWidget(self._register_page) # index 1

        layout.addWidget(self._stack, stretch=11)

    def _show_register(self):
        self.setWindowTitle("Pawffinated – Create Account")
        self._stack.setCurrentIndex(1)

    def _show_login(self):
        self.setWindowTitle("Pawffinated – Log-in")
        self._stack.setCurrentIndex(0)


# ── App entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Pawffinated Login")
    win = LoginWindow()
    win.show()
    sys.exit(app.exec())