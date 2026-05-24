"""
PAWFFINATED - Shared Sidebar Navigation (First-Name Edition)
============================================================
FIXES IN THIS VERSION
---------------------
1. get_current_user() — DB failure no longer silently drops the session-file
   fallback.  Previously the code did:

       if user_id is not None:
           try: ...DB lookup...
           except: pass
           if session_data.get("first_name"):   # <-- only reached on DB success
               return session_data fallback

   The `if session_data` block was *inside* the `if user_id` block but AFTER
   the try/except, so a DB exception caused it to be skipped entirely and the
   function fell through to Source 3 (env vars), which is also empty in a
   subprocess launched without those vars set.

   Fix: move the session-file fallback into the except clause so it is used
   immediately when the DB call fails.

2. save_session() guard in _open_account_management() and _route() was
   checking `self._user_name not in ("", "—")` but the sidebar is constructed
   BEFORE get_current_user() resolves correctly (because the DB import
   happens at call-time, not import-time).  The guard now always re-saves
   whatever the sidebar currently knows, removing the dead-end condition.

3. get_current_user() now also logs which resolution path succeeded so you
   can diagnose future issues without guesswork.

Footer shows the logged-in user's FIRST NAME and ROLE pulled live from the
database (or from the session file when the DB is unreachable).

User is resolved from THREE sources (first match wins):
  1. --user-id <int>      CLI arg passed between windows via subprocess
  2. .pawffinated_session  file written by save_session() at login
  3. PAWFF_USER_* env vars set by Login.py's _launch_dashboard()

USAGE - same 3 lines in every window:

    from pawffinated_sidebar import PawffinatedSidebar, get_current_user

    current_user = get_current_user()

    self.sidebar = PawffinatedSidebar(
        active_page="Dashboard",
        current_user=current_user,
    )

WIRE UP LOGIN - in Login.py's _launch_dashboard(), also call save_session:

    from pawffinated_sidebar import save_session
    save_session(CURRENT_USER)        # <-- add this one line
    subprocess.Popen([sys.executable, script], env=env)
"""

from __future__ import annotations
import json
import logging
import os
import sys
import subprocess
import argparse

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

log = logging.getLogger("pawffinated.sidebar")

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
ROUTES: dict[str, str] = {
    "Order":             "POS.py",
    "Inventory":         "Inventory.py",
    "Sales Monitor":     "Sales.py",
    "Dashboard":         "Dashboard.py",
    "Access Control":    "AccessControl.py",
    "Activity Log":      "ActivityLog.py",
    "Staff Management":  "StaffAdminPanel.py",
    "AccountManagement": "AccountManagement.py",
    "Menu":              "Menu.py",
}

# ---------------------------------------------------------------------------
# Nav items
# ---------------------------------------------------------------------------
NAV_ITEMS: list[tuple[str | None, str, str]] = [
    ("MAIN",       "📊", "Dashboard"),
    (None,         "📋", "Order"),
    ("MANAGEMENT", "📈", "Sales Monitor"),
    (None,         "📦", "Inventory"),
    (None,         "🍽️",  "Menu"),
    ("ADMIN",      "👥", "Staff Management"),
    (None,         "🔒", "Access Control"),
    (None,         "📝", "Activity Log"),
]

# ---------------------------------------------------------------------------
# Session file  (.pawffinated_session lives beside this script)
# ---------------------------------------------------------------------------
_SESSION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".pawffinated_session"
)


def save_session(user: dict) -> None:
    """
    Persist the logged-in user's data to disk so every window can show
    the correct name/role without needing --user-id passed explicitly.

    Called automatically by Login.py's _launch_dashboard() before
    launching any subprocess window.
    """
    try:
        payload = {
            "user_id":    user.get("id"),
            "first_name": user.get("first_name", ""),
            "last_name":  user.get("last_name", ""),
            "role":       user.get("role", ""),
            "station":    user.get("station", ""),
            "is_admin":   user.get("is_admin", False),
        }
        with open(_SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        log.debug("save_session: wrote %s", payload)
    except Exception as exc:
        log.warning("save_session failed: %s", exc)


def clear_session() -> None:
    """Remove the saved session (call on logout)."""
    try:
        os.remove(_SESSION_FILE)
        log.debug("clear_session: removed %s", _SESSION_FILE)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# get_current_user()  — FIXED
# ---------------------------------------------------------------------------

def get_current_user() -> dict | None:
    """
    Resolve the logged-in user from THREE sources (first match wins):
    1. --user-id CLI arg  →  DB lookup, then session-file fallback
    2. .pawffinated_session file  →  DB lookup, then raw session data
    3. PAWFF_USER_* environment variables

    KEY FIX: previously a DB exception caused the session-file fallback to
    be skipped entirely because the fallback `if` block was positioned after
    a bare `except: pass`.  Now the DB exception *directly* falls through to
    the session-file data so the footer always shows something meaningful.
    """

    # ── Source 1 & 2 setup: collect user_id + session file data ─────────────
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--user-id", type=int, default=None)
    args, _ = parser.parse_known_args()
    user_id: int | None = args.user_id

    session_data: dict = {}
    try:
        with open(_SESSION_FILE, "r", encoding="utf-8") as f:
            session_data = json.load(f)
        log.debug("get_current_user: loaded session %s", session_data)
        if user_id is None:
            uid = session_data.get("user_id")
            if uid is not None:
                user_id = int(uid)
    except FileNotFoundError:
        log.debug("get_current_user: no session file at %s", _SESSION_FILE)
    except Exception as exc:
        log.warning("get_current_user: could not read session file: %s", exc)

    # ── Try DB lookup if we have a user_id ───────────────────────────────────
    if user_id is not None:
        try:
            from DbConnection import get_auth_db
            all_users = get_auth_db().get_all_users()
            user = next((u for u in all_users if u["id"] == user_id), None)
            if user:
                log.debug("get_current_user: resolved from DB — %s", user.get("first_name"))
                return user
        except Exception as exc:
            # ── FIX: DB failed — fall back to session file immediately ───────
            log.warning(
                "get_current_user: DB lookup failed (user_id=%s): %s — "
                "falling back to session file.",
                user_id, exc,
            )

        # Reached here means: DB failed OR user_id not found in DB.
        # Use whatever the session file has.
        first_name = session_data.get("first_name", "").strip()
        role       = session_data.get("role",       "").strip()
        if first_name or role:
            log.debug(
                "get_current_user: using session-file fallback — %s / %s",
                first_name, role,
            )
            return {
                "id":         user_id,
                "first_name": first_name,
                "last_name":  session_data.get("last_name",  ""),
                "role":       role,
                "station":    session_data.get("station",    ""),
                "is_admin":   session_data.get("is_admin",   False),
            }

    # ── Source 3: PAWFF_USER_* environment variables ─────────────────────────
    first_name = os.environ.get("PAWFF_USER_FIRST_NAME", "").strip()
    role       = os.environ.get("PAWFF_USER_ROLE",       "").strip()

    if not first_name:
        full = os.environ.get("PAWFF_USER_NAME", "").strip()
        if full:
            first_name = full.split()[0]

    staff_id_str = os.environ.get("STAFF_ID", "").strip()
    staff_id     = int(staff_id_str) if staff_id_str.isdigit() else None

    if first_name or role:
        log.debug("get_current_user: resolved from env vars — %s / %s", first_name, role)
        return {
            "id":         staff_id,
            "first_name": first_name,
            "role":       role,
        }

    log.warning("get_current_user: could not resolve user from any source.")
    return None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _hline(color: str) -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setFixedHeight(1)
    ln.setStyleSheet(f"background:{color};border:none;")
    return ln


def _find_script(filename: str) -> str | None:
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        os.path.join(os.getcwd(), filename),
        filename,
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _build_launch_cmd(path: str, user_id: int | None) -> list[str]:
    """Build the subprocess command, appending --user-id when available."""
    cmd = [sys.executable, path]
    if user_id is not None:
        cmd += ["--user-id", str(user_id)]
    return cmd


# ---------------------------------------------------------------------------
# PawffinatedSidebar
# ---------------------------------------------------------------------------

class PawffinatedSidebar(QWidget):
    """
    Self-routing sidebar.

    Footer:
      Top line    -> current_user["first_name"]   e.g. "Admin"
      Bottom line -> current_user["role"]         e.g. "Administrator"
      Avatar      -> first initial                e.g. "A"

    Parameters
    ----------
    active_page   : str        - nav item to highlight
    current_user  : dict|None  - dict from get_current_user()
    auto_navigate : bool       - True = sidebar opens windows itself
    palette       : dict       - optional colour overrides
    """

    page_requested = pyqtSignal(str)

    def __init__(
        self,
        active_page:   str = "Dashboard",
        current_user:  dict | None = None,
        auto_navigate: bool = True,
        palette:       dict | None = None,
        parent:        QWidget | None = None,
    ):
        super().__init__(parent)
        self._active       = active_page
        self.auto_navigate = auto_navigate
        self._C            = {**DEFAULT_PALETTE, **(palette or {})}
        self._nav_buttons: dict[str, QPushButton] = {}

        # Pull first_name, role, and id from the resolved user dict.
        if current_user:
            self._user_name = current_user.get("first_name", "").strip() or "User"
            self._user_role = current_user.get("role",       "").strip() or "Staff"
            self._user_id   = current_user.get("id")
        else:
            self._user_name = "—"
            self._user_role = "Not logged in"
            self._user_id   = None

        self.setFixedWidth(180)
        self.setStyleSheet(
            f"background:{self._C['sidebar']};"
            f"border-right:1px solid {self._C['border']};"
        )
        self._build()

    # -- Public API -----------------------------------------------------------

    def set_active_page(self, page: str) -> None:
        self._active = page
        self._restyle_buttons()

    def set_user(self, first_name: str, role: str = "Staff") -> None:
        """Update footer and avatar initial at runtime."""
        self._user_name = first_name.strip() or "—"
        self._user_role = role.strip()        or "Staff"
        self._name_lbl.setText(self._user_name)
        self._role_lbl.setText(self._user_role)
        initial = self._user_name[0].upper() if self._user_name != "—" else "?"
        self._avatar.setText(initial)

    def set_width(self, w: int) -> None:
        self.setFixedWidth(w)

    # -- Build ----------------------------------------------------------------

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

        # User footer (clickable -> AccountManagement)
        self._user_btn = QPushButton()
        self._user_btn.setFlat(True)
        self._user_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._user_btn.setFixedHeight(50)
        self._user_btn.setToolTip("Account Management")
        self._user_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;"
            f"border-radius:8px;text-align:left;}}"
            f"QPushButton:hover{{background:{C['accent_lt']};}}"
        )
        self._user_btn.clicked.connect(self._open_account_management)

        user_row = QHBoxLayout()
        user_row.setSpacing(10)
        user_row.setContentsMargins(4, 6, 4, 6)

        # Avatar: first initial of first_name
        initial = self._user_name[0].upper() if self._user_name not in ("", "—") else "?"
        self._avatar = QLabel(initial)
        self._avatar.setFixedSize(34, 34)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setStyleSheet(
            f"background:{C['accent']};color:white;"
            f"border-radius:17px;font-weight:700;font-size:12px;"
        )
        self._avatar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        info = QVBoxLayout()
        info.setSpacing(1)

        # Top line: first_name
        self._name_lbl = QLabel(self._user_name)
        nf = QFont("Segoe UI", 11)
        nf.setBold(True)
        self._name_lbl.setFont(nf)
        self._name_lbl.setStyleSheet(f"color:{C['text']};background:transparent;")
        self._name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Bottom line: role
        self._role_lbl = QLabel(self._user_role)
        self._role_lbl.setFont(QFont("Segoe UI", 10))
        self._role_lbl.setStyleSheet(f"color:{C['sub']};background:transparent;")
        self._role_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        info.addWidget(self._name_lbl)
        info.addWidget(self._role_lbl)

        user_row.addWidget(self._avatar)
        user_row.addLayout(info)
        user_row.addStretch()

        container = QWidget()
        container.setLayout(user_row)
        container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        btn_inner = QHBoxLayout(self._user_btn)
        btn_inner.setContentsMargins(0, 0, 0, 0)
        btn_inner.addWidget(container)

        lay.addWidget(self._user_btn)
        self._restyle_buttons()

    # -- Nav button factory ---------------------------------------------------

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

    # -- Navigation -----------------------------------------------------------

    def _on_nav_click(self, page: str) -> None:
        if page == self._active:
            return
        self.set_active_page(page)
        self.page_requested.emit(page)
        if self.auto_navigate:
            self._route(page)

    def _route(self, page: str) -> None:
        script = ROUTES.get(page)
        if script is None:
            QMessageBox.information(
                self, "Coming Soon",
                f"{page} is not yet implemented.\nStay tuned! 🐾",
            )
            self.set_active_page(self._active)
            return

        path = _find_script(script)
        if path is None:
            QMessageBox.warning(
                self, "Script Not Found",
                f"Could not locate {script}.\n\n"
                f"Make sure all Pawffinated files are in the same folder.",
            )
            self.set_active_page(self._active)
            return

        # FIX: always re-save session before launching — no guard condition
        # that could silently skip the save when user_name is "—".
        self._persist_session()

        subprocess.Popen(
            _build_launch_cmd(path, self._user_id),
            env=os.environ.copy(),
        )

        top = self.window()
        if top:
            top.close()

    def _open_account_management(self) -> None:
        script = ROUTES.get("AccountManagement")
        path   = _find_script(script)
        if path is None:
            QMessageBox.warning(
                self, "Script Not Found",
                f"Could not locate AccountManagement.py.\n\n"
                f"Make sure all Pawffinated files are in the same folder.",
            )
            return

        # FIX: always re-save session before launching.
        self._persist_session()

        subprocess.Popen(
            _build_launch_cmd(path, self._user_id),
            env=os.environ.copy(),
        )

        top = self.window()
        if top:
            top.close()

    # -- Internal helpers -----------------------------------------------------

    def _persist_session(self) -> None:
        """
        Re-write the session file with whatever this sidebar knows about the
        current user.  Called before every subprocess launch so the child
        window can always load the user from Source 2 even if the DB is slow
        or the --user-id arg is somehow missing.

        FIX: the old code had a guard:
            if self._user_id is not None or self._user_name not in ("", "—"):
        which was False when the sidebar itself had failed to resolve the user
        (showing "—" / "Not logged in"), creating a vicious cycle where no
        window could ever recover the session.  The guard is now removed.
        """
        save_session({
            "id":         self._user_id,
            "first_name": self._user_name if self._user_name != "—" else "",
            "role":       self._user_role if self._user_role != "Not logged in" else "",
        })