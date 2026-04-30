"""
PAWFFINATED – Shared Sidebar Navigation
========================================
A centralized, reusable sidebar widget used across all Pawffinated screens.

─── QUICK USAGE ────────────────────────────────────────────────────────────
    from pawffinated_sidebar import PawffinatedSidebar

    # In your QMainWindow.__init__ or _build_ui():
    root_layout = QHBoxLayout(central_widget)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    sidebar = PawffinatedSidebar(active_page="Sales Monitor")
    sidebar.page_requested.connect(self._navigate)   # optional
    root_layout.addWidget(sidebar)

    # ... add your main content widget next ...
    root_layout.addWidget(your_main_content, stretch=1)

─── ACTIVE PAGE VALUES ──────────────────────────────────────────────────────
    Pass one of these strings to `active_page`:
        "Dashboard"
        "Orders"
        "Sales Monitor"
        "Access Control"
        "Activity Log"
        "Inventory"

─── NAVIGATION SIGNAL ───────────────────────────────────────────────────────
    sidebar.page_requested  →  pyqtSignal(str)
    Emitted with the page name whenever a nav button is clicked.

    Example:
        def _navigate(self, page: str):
            if page == "Orders":
                self.orders_win.show()
                self.close()
            elif page == "Inventory":
                subprocess.Popen(["python", "pawffinated_inventory_qt.py"])

─── USER CUSTOMIZATION ──────────────────────────────────────────────────────
    sidebar.set_user("Jane Doe", "Barista")      # change name / role
    sidebar.set_width(200)                        # change sidebar width (default 180)
    sidebar.set_active_page("Inventory")         # change active highlight at runtime

─── STYLING ─────────────────────────────────────────────────────────────────
    All colors come from the shared C dict.  Override by passing a custom
    palette dict to PawffinatedSidebar(palette={...}).
    Keys used: sidebar, border, accent, accent_lt, text, sub.
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

# ── Default palette (shared with all Pawffinated modules) ─────────────────────
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

# ── Nav structure ─────────────────────────────────────────────────────────────
#   (section_label | None,  icon, page_name)
NAV_ITEMS: list[tuple[str | None, str, str]] = [
    ("MAIN",       "📊", "Dashboard"),
    (None,         "📋", "Orders"),
    ("MANAGEMENT", "📈", "Sales Monitor"),
    (None,         "🔒", "Access Control"),
    (None,         "📝", "Activity Log"),
    (None,         "📦", "Inventory"),
]


def _hline(color: str) -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setFixedHeight(1)
    ln.setStyleSheet(f"background:{color};border:none;")
    return ln


class PawffinatedSidebar(QWidget):
    """
    Drop-in sidebar navigation widget.

    Parameters
    ----------
    active_page : str
        One of the page names in NAV_ITEMS.  Highlights that button.
    user_name   : str
        Display name shown in the footer.
    user_role   : str
        Role/subtitle shown below the name.
    palette     : dict | None
        Override color tokens.  Missing keys fall back to DEFAULT_PALETTE.
    parent      : QWidget | None
    """

    page_requested = pyqtSignal(str)   # emitted when user clicks a nav button

    def __init__(
        self,
        active_page: str = "Dashboard",
        user_name:   str = "Sarah Jenkins",
        user_role:   str = "Store Manager",
        palette:     dict | None = None,
        parent:      QWidget | None = None,
    ):
        super().__init__(parent)
        self._active = active_page
        self._user_name = user_name
        self._user_role = user_role
        self._C = {**DEFAULT_PALETTE, **(palette or {})}
        self._nav_buttons: dict[str, QPushButton] = {}

        self.setFixedWidth(180)
        self._apply_base_style()
        self._build()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_active_page(self, page: str) -> None:
        """Highlight a different nav item at runtime."""
        self._active = page
        self._restyle_buttons()

    def set_user(self, name: str, role: str = "") -> None:
        """Update the footer user name and role."""
        self._user_name = name
        self._user_role = role
        self._name_lbl.setText(name)
        self._role_lbl.setText(role)
        initials = "".join(p[0].upper() for p in name.split()[:2])
        self._avatar.setText(initials)

    def set_width(self, w: int) -> None:
        """Change the sidebar width (default 180 px)."""
        self.setFixedWidth(w)

    # ── Internal build ────────────────────────────────────────────────────────

    def _apply_base_style(self) -> None:
        C = self._C
        self.setStyleSheet(
            f"PawffinatedSidebar, QWidget#{self.objectName()} {{"
            f"  background: {C['sidebar']};"
            f"  border-right: 1px solid {C['border']};"
            f"}}"
        )

    def _build(self) -> None:
        C   = self._C
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 20, 12, 16)
        lay.setSpacing(2)

        # ── Logo ──
        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)

        icon_lbl = QLabel("🐾")
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            f"background:#5C3D2E;border-radius:8px;font-size:16px;"
        )
        logo_txt = QLabel("PAWFFINATED")
        f = QFont("Segoe UI", 10)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        logo_txt.setFont(f)
        logo_txt.setStyleSheet(f"color:{C['text']};background:transparent;")

        logo_row.addWidget(icon_lbl)
        logo_row.addWidget(logo_txt)
        logo_row.addStretch()
        lay.addLayout(logo_row)
        lay.addSpacing(12)

        # ── Nav items ──
        prev_section: str | None = "__start__"
        for section, icon, page in NAV_ITEMS:
            # Section label
            if section is not None and section != prev_section:
                sec_lbl = QLabel(section)
                sec_lbl.setFont(QFont("Segoe UI", 8))
                sec_lbl.setStyleSheet(
                    f"color:{C['sub']};background:transparent;"
                )
                sec_lbl.setContentsMargins(4, 10, 0, 2)
                lay.addWidget(sec_lbl)
                prev_section = section

            btn = self._make_nav_btn(icon, page)
            lay.addWidget(btn)
            self._nav_buttons[page] = btn

        lay.addStretch()

        # ── Divider ──
        lay.addWidget(_hline(C["border"]))
        lay.addSpacing(8)

        # ── User footer ──
        user_row = QHBoxLayout()
        user_row.setSpacing(10)

        initials = "".join(p[0].upper() for p in self._user_name.split()[:2])
        self._avatar = QLabel(initials)
        self._avatar.setFixedSize(34, 34)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setStyleSheet(
            f"background:{C['accent']};color:white;"
            f"border-radius:17px;font-weight:700;font-size:12px;"
        )

        info_col = QVBoxLayout()
        info_col.setSpacing(1)
        self._name_lbl = QLabel(self._user_name)
        nf = QFont("Segoe UI", 11)
        nf.setBold(True)
        self._name_lbl.setFont(nf)
        self._name_lbl.setStyleSheet(
            f"color:{C['text']};background:transparent;"
        )
        self._role_lbl = QLabel(self._user_role)
        self._role_lbl.setFont(QFont("Segoe UI", 10))
        self._role_lbl.setStyleSheet(
            f"color:{C['sub']};background:transparent;"
        )
        info_col.addWidget(self._name_lbl)
        info_col.addWidget(self._role_lbl)

        user_row.addWidget(self._avatar)
        user_row.addLayout(info_col)
        user_row.addStretch()
        lay.addLayout(user_row)

        self._restyle_buttons()

    def _make_nav_btn(self, icon: str, page: str) -> QPushButton:
        btn = QPushButton(f"  {icon}  {page}")
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(36)
        btn.setCheckable(False)
        btn.clicked.connect(lambda _, p=page: self._on_nav_click(p))
        return btn

    def _restyle_buttons(self) -> None:
        C = self._C
        for page, btn in self._nav_buttons.items():
            active = (page == self._active)
            if active:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  text-align: left;"
                    f"  border-radius: 6px;"
                    f"  padding-left: 6px;"
                    f"  background: {C['accent_lt']};"
                    f"  color: {C['accent']};"
                    f"  font-weight: 600;"
                    f"  border: none;"
                    f"}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  text-align: left;"
                    f"  border-radius: 6px;"
                    f"  padding-left: 6px;"
                    f"  background: transparent;"
                    f"  color: {C['text']};"
                    f"  font-weight: 400;"
                    f"  border: none;"
                    f"}}"
                    f"QPushButton:hover {{"
                    f"  background: {C['accent_lt']};"
                    f"}}"
                )

    def _on_nav_click(self, page: str) -> None:
        self.set_active_page(page)
        self.page_requested.emit(page)