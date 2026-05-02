"""
PAWFFINATED – Shared Sidebar Navigation
========================================
Self-contained sidebar that handles ALL navigation internally.
No _navigate() method needed in any window — just drop it in.

─── USAGE (same 3 lines in every window) ────────────────────────────────────

    from pawffinated_sidebar import PawffinatedSidebar

    # Inside _build_ui(), after creating your root QHBoxLayout:
    self.sidebar = PawffinatedSidebar(active_page="Orders")
    root_layout.addWidget(self.sidebar)
    root_layout.addWidget(your_main_content, stretch=1)

    That's it. Clicking any nav button opens the correct window and
    closes the current one automatically.

─── ACTIVE PAGE VALUES ──────────────────────────────────────────────────────
    "Dashboard" | "Orders" | "Sales Monitor" |
    "Access Control" | "Activity Log" | "Inventory"

─── FILE → SCRIPT MAPPING (edit ROUTES below if your filenames differ) ──────
    "Orders"        → pawffinated_pos_qt.py
    "Inventory"     → pawffinated_inventory_qt.py
    "Sales Monitor" → pawffinated_sales_qt.py
    Others          → show a "coming soon" notice (easy to extend)

─── OPTIONAL PUBLIC API ─────────────────────────────────────────────────────
    sidebar.set_user("Jane Doe", "Barista")   # update logged-in user
    sidebar.set_active_page("Inventory")      # change highlight at runtime
    sidebar.set_width(210)                    # widen if needed

    # If you want to intercept navigation yourself instead of auto-routing:
    sidebar.page_requested.connect(my_handler)   # connect BEFORE adding to layout
    # Then set sidebar.auto_navigate = False to suppress the built-in routing.
"""

from __future__ import annotations
import os
import sys
import subprocess

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

# ── Shared palette ────────────────────────────────────────────────────────────
DEFAULT_PALETTE = dict(
    sidebar   = "#FFFFFF",
    border    = "#E5E7EB",
    accent    = "#2D7A5F",
    accent_lt = "#E8F4F0",
    text      = "#1A1A1A",
    sub       = "#6B7280",
    white     = "#FFFFFF",
    bg        = "#F7F5F0",
)

# ── Page → script filename mapping ───────────────────────────────────────────
# Edit these paths if your files live in a different location.
ROUTES: dict[str, str] = {
    "Order":        "POS.py",
    "Inventory":     "Inventory.py",
    "Sales Monitor": "Sales.py",
    "Dashboard" : "Dashboard.py",
    "Access Control": "AccessControl.py",
    "Activity Log": "ActivityLog.py"
}

# ── Nav structure  (section_label | None, emoji, page_name) ──────────────────
NAV_ITEMS: list[tuple[str | None, str, str]] = [
    ("MAIN",       "📊", "Dashboard"),
    (None,         "📋", "Order"),
    ("MANAGEMENT", "📈", "Sales Monitor"),
    (None,         "🔒", "Access Control"),
    (None,         "📝", "Activity Log"),
    (None,         "📦", "Inventory"),
]


# ── Small helpers ─────────────────────────────────────────────────────────────
def _hline(color: str) -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setFixedHeight(1)
    ln.setStyleSheet(f"background:{color};border:none;")
    return ln


def _find_script(filename: str) -> str | None:
    """
    Locate the script file relative to this sidebar module OR the CWD.
    Returns the absolute path if found, else None.
    """
    candidates = [
        # same directory as pawffinated_sidebar.py
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        # current working directory
        os.path.join(os.getcwd(), filename),
        # absolute path passed directly
        filename,
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


# ─────────────────────────────────────────────────────────────────────────────
class PawffinatedSidebar(QWidget):
    """
    Self-routing sidebar navigation.

    Parameters
    ----------
    active_page   : str   — which nav item to highlight on launch
    user_name     : str   — footer display name
    user_role     : str   — footer subtitle
    auto_navigate : bool  — True (default) = sidebar handles routing itself
                            False = only emit page_requested, caller handles it
    palette       : dict  — optional color overrides
    """

    # Emitted on every nav click regardless of auto_navigate
    page_requested = pyqtSignal(str)

    def __init__(
        self,
        active_page:   str  = "Dashboard",
        user_name:     str  = "Sarah Jenkins",
        user_role:     str  = "Store Manager",
        auto_navigate: bool = True,
        palette:       dict | None = None,
        parent:        QWidget | None = None,
    ):
        super().__init__(parent)
        self._active        = active_page
        self._user_name     = user_name
        self._user_role     = user_role
        self.auto_navigate  = auto_navigate
        self._C             = {**DEFAULT_PALETTE, **(palette or {})}
        self._nav_buttons:  dict[str, QPushButton] = {}

        self.setFixedWidth(180)
        self.setStyleSheet(
            f"background:{self._C['sidebar']};"
            f"border-right:1px solid {self._C['border']};"
        )
        self._build()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_active_page(self, page: str) -> None:
        """Change the highlighted nav item at runtime."""
        self._active = page
        self._restyle_buttons()

    def set_user(self, name: str, role: str = "") -> None:
        """Update the footer user info."""
        self._user_name = name
        self._user_role = role
        self._name_lbl.setText(name)
        self._role_lbl.setText(role)
        self._avatar.setText("".join(p[0].upper() for p in name.split()[:2]))

    def set_width(self, w: int) -> None:
        """Resize the sidebar (default 180 px)."""
        self.setFixedWidth(w)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        C   = self._C
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 20, 12, 16)
        lay.setSpacing(2)

        # Logo row
        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)

        paw = QLabel("🐾")
        paw.setFixedSize(32, 32)
        paw.setAlignment(Qt.AlignmentFlag.AlignCenter)
        paw.setStyleSheet("background:#5C3D2E;border-radius:8px;font-size:16px;")

        brand = QLabel("PAWFFINATED")
        bf = QFont("Segoe UI", 10)
        bf.setBold(True)
        bf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        brand.setFont(bf)
        brand.setStyleSheet(f"color:{C['text']};background:transparent;")

        logo_row.addWidget(paw)
        logo_row.addWidget(brand)
        logo_row.addStretch()
        lay.addLayout(logo_row)
        lay.addSpacing(14)

        # Nav items
        prev_section = "__start__"
        for section, icon, page in NAV_ITEMS:
            if section is not None and section != prev_section:
                sec_lbl = QLabel(section)
                sec_lbl.setFont(QFont("Segoe UI", 8))
                sec_lbl.setStyleSheet(f"color:{C['sub']};background:transparent;")
                sec_lbl.setContentsMargins(4, 10, 0, 2)
                lay.addWidget(sec_lbl)
                prev_section = section

            btn = self._make_nav_btn(icon, page)
            lay.addWidget(btn)
            self._nav_buttons[page] = btn

        lay.addStretch()
        lay.addWidget(_hline(C["border"]))
        lay.addSpacing(8)

        # User footer
        user_row = QHBoxLayout()
        user_row.setSpacing(10)

        self._avatar = QLabel("".join(p[0].upper() for p in self._user_name.split()[:2]))
        self._avatar.setFixedSize(34, 34)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setStyleSheet(
            f"background:{C['accent']};color:white;"
            f"border-radius:17px;font-weight:700;font-size:12px;"
        )

        info = QVBoxLayout()
        info.setSpacing(1)
        self._name_lbl = QLabel(self._user_name)
        nf = QFont("Segoe UI", 11)
        nf.setBold(True)
        self._name_lbl.setFont(nf)
        self._name_lbl.setStyleSheet(f"color:{C['text']};background:transparent;")

        self._role_lbl = QLabel(self._user_role)
        self._role_lbl.setFont(QFont("Segoe UI", 10))
        self._role_lbl.setStyleSheet(f"color:{C['sub']};background:transparent;")

        info.addWidget(self._name_lbl)
        info.addWidget(self._role_lbl)
        user_row.addWidget(self._avatar)
        user_row.addLayout(info)
        user_row.addStretch()
        lay.addLayout(user_row)

        self._restyle_buttons()

    def _make_nav_btn(self, icon: str, page: str) -> QPushButton:
        btn = QPushButton(f"  {icon}  {page}")
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(36)
        btn.clicked.connect(lambda _, p=page: self._on_nav_click(p))
        return btn

    def _restyle_buttons(self) -> None:
        C = self._C
        for page, btn in self._nav_buttons.items():
            if page == self._active:
                btn.setStyleSheet(
                    f"QPushButton{{text-align:left;border-radius:6px;"
                    f"padding-left:6px;background:{C['accent_lt']};"
                    f"color:{C['accent']};font-weight:600;border:none;}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{text-align:left;border-radius:6px;"
                    f"padding-left:6px;background:transparent;"
                    f"color:{C['text']};font-weight:400;border:none;}}"
                    f"QPushButton:hover{{background:{C['accent_lt']};}}"
                )

    # ── Navigation logic (lives here, not in the windows) ────────────────────

    def _on_nav_click(self, page: str) -> None:
        # Already on this page — do nothing
        if page == self._active:
            return

        self.set_active_page(page)
        self.page_requested.emit(page)

        if self.auto_navigate:
            self._route(page)

    def _route(self, page: str) -> None:
        """
        Open the target screen and close the current window.
        Pages without a script show a "coming soon" message.
        """
        script = ROUTES.get(page)

        if script is None:
            # Pages not yet implemented (Dashboard, Access Control, Activity Log)
            QMessageBox.information(
                self,
                "Coming Soon",
                f"{page} is not yet implemented.\nStay tuned! 🐾",
            )
            # Revert the highlight to the actual open page
            self.set_active_page(self._active)
            return

        path = _find_script(script)
        if path is None:
            QMessageBox.warning(
                self,
                "Script Not Found",
                f"Could not locate {script}.\n\n"
                f"Make sure all Pawffinated files are in the same folder.",
            )
            self.set_active_page(self._active)
            return

        # Launch the new window as a separate process
        subprocess.Popen([sys.executable, path])

        # Close the current top-level window
        top = self.window()
        if top:
            top.close()