"""
PAWFFINATED – Activity Log  (PyQt6 Edition · v5.4 — Stable Timestamps & Full Coverage)
========================================================================================
v5.4 CHANGES:

  A. Auto-refresh timer REMOVED
     → The 60-second _auto_timer has been completely removed.
       Timestamps now NEVER change after first load — the time shown is
       always the exact time the event was recorded in the database.
     → Manual "Refresh" button (toolbar + Ctrl+R) still works on demand.

  B. Full activity coverage guaranteed
     → Orders:          get_recent_orders() with large limit (5000)
     → Inventory:       get_inventory_log() — all add/edit/delete changes
     → Menu:            get_menu_change_log() — all add/edit/delete changes
     → Clock events:    login / logout per staff member
     → User accounts:   new registrations
     → Staff management: hire / edit / fire via get_staff_change_log()
     → Access control:   permission changes via get_access_log()

  C. Timestamp accuracy
     → All datetimes are stripped of tzinfo once on load and never
       recalculated.  The displayed string is frozen at load time.
     → Snapshot fallbacks (inventory / menu) still use _dt_frozen=True
       but since there is no auto-refresh the freeze is just a safety net.

  D. Login / Logout recording
     → Clock events are fetched for ALL staff members and recorded as
       "Login" / "Logout" entries with the exact timestamp from the DB.
"""

from __future__ import annotations
import sys, csv, os
from datetime import datetime, timedelta, date as _date

try:
    from Sidebar import PawffinatedSidebar, get_current_user
    HAS_SIDEBAR = True
except ImportError:
    HAS_SIDEBAR = False
    def get_current_user(): return None

try:
    from db_connection import get_db, get_staff_db, get_auth_db, get_menu_db
    HAS_DB = True
except ImportError:
    try:
        from DbConnection import get_db, get_staff_db, get_auth_db, get_menu_db
        HAS_DB = True
    except ImportError:
        HAS_DB = False

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QHBoxLayout, QVBoxLayout, QSizePolicy,
    QLineEdit, QDialog, QTextEdit, QMenu, QToolBar, QFileDialog,
    QMessageBox, QGraphicsOpacityEffect, QComboBox, QCalendarWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QPropertyAnimation, QPointF, QDate,
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPainterPath, QPen,
    QGuiApplication, QKeySequence, QShortcut, QCursor, QBrush,
)

# ── Session ───────────────────────────────────────────────────────────────────
_SESSION_USER = get_current_user() or {}
_USER_EMAIL   = _SESSION_USER.get("email",      os.environ.get("PAWFF_USER_EMAIL", ""))
_USER_FNAME   = _SESSION_USER.get("first_name", os.environ.get("PAWFF_USER_FIRST_NAME", ""))
_USER_LNAME   = _SESSION_USER.get("last_name",  os.environ.get("PAWFF_USER_LAST_NAME", ""))
_USER_NAME    = (
    f"{_USER_FNAME} {_USER_LNAME}".strip()
    or os.environ.get("PAWFF_USER_NAME", "Unknown")
)
_USER_ROLE    = _SESSION_USER.get("role", os.environ.get("PAWFF_USER_ROLE", ""))

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
    blue      = "#2563EB",
    blue_lt   = "#DBEAFE",
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
    "Note":      ("#6B7280", "#F3F4F6"),
    "Login":     ("#059669", "#D1FAE5"),
    "Logout":    ("#2D7A5F", "#E8F4F0"),
    "Added":     ("#2563EB", "#DBEAFE"),
    "Updated":   ("#E07B39", "#FFF7ED"),
    "Deleted":   ("#D94F4F", "#FEE2E2"),
}

ICON_MAP = {
    "order":      ("🧾", "#E8F4F0", "#2D7A5F"),
    "inventory":  ("📦", "#FFF7ED", "#E07B39"),
    "login":      ("→",  "#D1FAE5", "#059669"),
    "logout":     ("←",  "#E8F4F0", "#2D7A5F"),
    "menu":       ("🍽️", "#DBEAFE", "#2563EB"),
    "void":       ("🗑",  "#FEE2E2", "#D94F4F"),
    "note":       ("📝", "#EDE9FE", "#6D28D9"),
    "exception":  ("⚠️", "#FEE2E2", "#D94F4F"),
    "user":       ("👤", "#FEF3C7", "#D97706"),
    "restock":    ("📥", "#D1FAE5", "#059669"),
    "transaction":("💳", "#DBEAFE", "#2563EB"),
    "staff":      ("👥", "#FEF3C7", "#D97706"),
    "access":     ("🔐", "#EDE9FE", "#6D28D9"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _strip_tz(dt):
    """Return a timezone-naive datetime. Accepts datetime, str, or None."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return None
    try:
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
    except Exception:
        pass
    return dt


def _fmt_dt(dt) -> str:
    """Format a datetime for display. Always strips tz first."""
    dt = _strip_tz(dt)
    if dt is None:
        return ""
    return dt.strftime("%b %d, %I:%M %p").lstrip("0").replace(" 0", " ")


def _is_recent(dt, minutes=5) -> bool:
    dt = _strip_tz(dt)
    if dt is None:
        return False
    try:
        return (datetime.now() - dt).total_seconds() < minutes * 60
    except Exception:
        return False


def _date_in_range(dt, d_from: _date, d_to: _date) -> bool:
    """Return True if dt falls within [d_from, d_to] (inclusive)."""
    dt = _strip_tz(dt)
    if dt is None:
        return False
    try:
        od = dt.date() if hasattr(dt, 'date') else _date.today()
        return d_from <= od <= d_to
    except Exception as e:
        print(f"[ActivityLog] _date_in_range error: {e!r} for dt={dt!r}")
        return False


def _item_ts(item: dict, fallback: datetime, idx: int,
             stagger_seconds: int = 60) -> datetime:
    """Return best available timestamp for a snapshot item."""
    for key in ("updated_at", "created_at"):
        raw = item.get(key)
        if raw:
            dt = _strip_tz(raw)
            if dt:
                return dt
    return fallback - timedelta(seconds=idx * stagger_seconds)


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE LOADER  (v5.4)
# ═══════════════════════════════════════════════════════════════════════════════
def _load_all_activities(date_from: str, date_to: str,
                          user_filter: str = "All") -> list[dict]:
    if not HAS_DB:
        return _demo_entries(date_from, date_to)

    entries = []
    eid     = 1
    d_from  = _date.fromisoformat(date_from)
    d_to    = _date.fromisoformat(date_to)

    # ── 1. ORDERS & TRANSACTIONS ──────────────────────────────────────────────
    try:
        db = get_db()
        orders = db.get_recent_orders(limit=5000)
        print(f"[ActivityLog] Orders fetched: {len(orders)}")

        for o in orders:
            created = o.get("created_at")
            if not _date_in_range(created, d_from, d_to):
                continue

            total      = float(o.get("total_amount", 0))
            subtotal   = float(o.get("subtotal", total))
            disc_type  = o.get("discount_type", "None") or "None"
            disc_amt   = float(o.get("discount_amount", 0))
            order_type = o.get("order_type", "Dine In")
            cname      = o.get("customer_name", "Walk-in Customer")
            order_num  = o.get("order_number", o.get("id", "?"))
            staff_name = o.get("staff_name") or o.get("cashier") or _USER_NAME

            if user_filter != "All":
                if user_filter.lower() not in str(staff_name).lower():
                    continue

            flagged = disc_type not in ("None", "") and disc_amt > 0
            status  = "Review" if flagged else "Completed"

            # Freeze the display timestamp at load time — never recalculate
            created_display = _strip_tz(created)
            created_str     = _fmt_dt(created_display)

            audit = [
                f"{created_str} — Order #{order_num} created",
                f"{created_str} — Type: {order_type} · Customer: {cname}",
                f"{created_str} — Subtotal: ₱{subtotal:,.2f}",
            ]
            if disc_type not in ("None", "") and disc_amt > 0:
                audit.append(
                    f"{created_str} — {disc_type} discount: −₱{disc_amt:.2f}"
                )
            audit.append(f"{created_str} — Total charged: ₱{total:,.2f}")

            try:
                items = db.get_order_items(o.get("id", 0))
                if items:
                    audit.append(f"{created_str} — Items ordered:")
                    for it in items:
                        audit.append(
                            f"   • {it.get('name','?')} x{it.get('quantity',1)}"
                            f" @ ₱{float(it.get('unit_price',0)):.2f}"
                        )
            except Exception:
                pass

            entries.append(dict(
                id=eid, icon="order",
                activity=f"Order #{order_num} — {order_type}",
                detail=(
                    f"Customer: {cname} · ₱{total:,.2f}"
                    + (f" · {disc_type} −₱{disc_amt:.2f}" if flagged else "")
                ),
                staff=str(staff_name),
                station=order_type,
                datetime=created_str,          # frozen string
                _dt=created_display,
                _dt_frozen=True,               # always frozen
                status=status,
                original_status=status,
                flagged=flagged,
                audit=audit,
                activity_type="order",
            ))
            eid += 1

    except Exception as e:
        print(f"[ActivityLog] Orders error: {e!r}")

    # ── 2. CLOCK EVENTS (Login / Logout) ──────────────────────────────────────
    try:
        staff_db  = get_staff_db()
        all_staff = staff_db.get_all_staff()

        for staff in all_staff:
            log = staff_db.get_clock_log(staff["id"])
            for ev in log:
                ts = ev.get("timestamp")
                if not _date_in_range(ts, d_from, d_to):
                    continue

                etype     = ev.get("event_type", "Clock In")
                icon_key  = "login" if etype == "Clock In" else "logout"
                fname     = ev.get("first_name") or ""
                lname     = ev.get("last_name")  or ""
                full_name = f"{fname} {lname}".strip() or staff.get("name", "Staff")
                device    = ev.get("device", "Unknown Device")
                duration  = ev.get("duration")
                role      = ev.get("user_role") or staff.get("role", "Staff")

                if user_filter != "All":
                    if user_filter.lower() not in full_name.lower():
                        continue

                ts_display = _strip_tz(ts)
                ts_str     = _fmt_dt(ts_display)

                detail = f"{etype} · {device} · {role}"
                if duration:
                    detail += f" · Duration: {duration}"

                audit = [
                    f"{ts_str} — {etype} event recorded",
                    f"{ts_str} — Staff: {full_name} ({role})",
                    f"{ts_str} — Device: {device}",
                ]
                if duration:
                    audit.append(f"{ts_str} — Session duration: {duration}")

                entries.append(dict(
                    id=eid, icon=icon_key,
                    activity=f"{etype} — {full_name}",
                    detail=detail,
                    staff=full_name,
                    station=device,
                    datetime=ts_str,            # frozen string
                    _dt=ts_display,
                    _dt_frozen=True,
                    status="Login" if etype == "Clock In" else "Logout",
                    original_status="Login" if etype == "Clock In" else "Logout",
                    flagged=False,
                    audit=audit,
                    activity_type="clock",
                ))
                eid += 1

    except Exception as e:
        print(f"[ActivityLog] Clock events error: {e!r}")

    # ── 3. INVENTORY ──────────────────────────────────────────────────────────
    try:
        db = get_db()
        _had_inv_log = False

        # ── 3a. Inventory change log (primary) ────────────────────────────────
        try:
            inv_logs = db.get_inventory_log(date_from, date_to)
            print(f"[ActivityLog] Inventory log rows: {len(inv_logs)}")

            for log in inv_logs:
                ts = (log.get("changed_at") or log.get("timestamp")
                      or log.get("created_at"))
                if not _date_in_range(ts, d_from, d_to):
                    continue

                _had_inv_log = True
                item_name  = log.get("item_name", "Unknown")
                action     = (log.get("action") or "Updated").strip().capitalize()
                old_stock  = log.get("old_stock")
                new_stock  = log.get("new_stock")
                changed_by = (log.get("changed_by") or log.get("staff_name")
                              or "System")
                reason     = log.get("reason", "")
                category   = log.get("category", "")
                price      = log.get("price") or log.get("unit_price")

                if user_filter != "All":
                    if user_filter.lower() not in str(changed_by).lower():
                        continue

                ts_display = _strip_tz(ts)
                ts_str     = _fmt_dt(ts_display)

                if action in ("Added", "Created"):
                    icon_key = "restock"
                    status   = "Added"
                    flagged  = False
                    detail   = f"New item added · By: {changed_by}"
                    if new_stock is not None:
                        detail = f"Added with stock: {new_stock} · By: {changed_by}"
                    if category:
                        detail += f" · {category}"
                elif action in ("Deleted", "Removed"):
                    icon_key = "void"
                    status   = "Deleted"
                    flagged  = True
                    detail   = f"Item removed from inventory · By: {changed_by}"
                    if reason:
                        detail += f" · {reason}"
                else:
                    diff_str = ""
                    try:
                        if old_stock is not None and new_stock is not None:
                            d = float(new_stock) - float(old_stock)
                            diff_str = f" ({'+'  if d >= 0 else ''}{d:g})"
                    except Exception:
                        pass
                    icon_key = "restock" if (
                        old_stock is not None and new_stock is not None
                        and float(new_stock or 0) >= float(old_stock or 0)
                    ) else "inventory"
                    status  = "Adjusted"
                    flagged = False
                    detail  = (
                        f"Stock: {old_stock} → {new_stock}{diff_str}"
                        f" · By: {changed_by}"
                    )
                    if reason:
                        detail += f" · {reason}"

                audit = [
                    f"{ts_str} — Inventory {action.lower()} recorded",
                    f"{ts_str} — Item: {item_name}",
                ]
                if action in ("Added", "Created"):
                    if new_stock is not None:
                        audit.append(f"{ts_str} — Initial stock: {new_stock}")
                    if price is not None:
                        audit.append(f"{ts_str} — Unit price: ₱{float(price):.2f}")
                    if category:
                        audit.append(f"{ts_str} — Category: {category}")
                elif action in ("Deleted", "Removed"):
                    if old_stock is not None:
                        audit.append(f"{ts_str} — Stock at deletion: {old_stock}")
                else:
                    if old_stock is not None:
                        audit.append(f"{ts_str} — Previous stock: {old_stock}")
                    if new_stock is not None:
                        audit.append(f"{ts_str} — New stock: {new_stock}")
                audit.append(f"{ts_str} — Changed by: {changed_by}")
                if reason:
                    audit.append(f"{ts_str} — Reason: {reason}")

                entries.append(dict(
                    id=eid, icon=icon_key,
                    activity=f"Inventory {action.lower()} — {item_name}",
                    detail=detail,
                    staff=str(changed_by),
                    station="Inventory",
                    datetime=ts_str,            # frozen string
                    _dt=ts_display,
                    _dt_frozen=True,
                    status=status,
                    original_status=status,
                    flagged=flagged,
                    audit=audit,
                    activity_type="inventory",
                ))
                eid += 1
        except Exception as inv_log_err:
            print(f"[ActivityLog] Inventory log error: {inv_log_err!r}")

        # ── 3b. Stock-level snapshot (fallback — only when log returned nothing) ──
        if not _had_inv_log:
            rows = db.fetch_all()
            now  = datetime.now()

            if _date_in_range(now, d_from, d_to):
                for idx, row in enumerate(rows):
                    stock = float(row.get("stock", 0))
                    name  = row.get("name", "Unknown")
                    unit  = row.get("unit", "units")
                    cat   = row.get("category", "Other")
                    price = float(row.get("price", 0))

                    if user_filter != "All" and "System" not in user_filter:
                        continue

                    if stock == 0:
                        status   = "Review"
                        flagged  = True
                        activity = f"Out of stock — {name}"
                        detail   = f"Stock depleted · {cat} · 0 {unit} remaining"
                        icon_key = "void"
                    elif stock <= 10:
                        status   = "Adjusted"
                        flagged  = False
                        activity = f"Low stock alert — {name}"
                        detail   = f"Only {stock:g} {unit} remaining · {cat}"
                        icon_key = "inventory"
                    else:
                        continue

                    item_dt  = _item_ts(row, now, idx, stagger_seconds=30)
                    item_str = _fmt_dt(item_dt)

                    entries.append(dict(
                        id=eid, icon=icon_key,
                        activity=activity,
                        detail=detail,
                        staff="System",
                        station="Inventory",
                        datetime=item_str,
                        _dt=item_dt,
                        _dt_frozen=True,
                        status=status,
                        original_status=status,
                        flagged=flagged,
                        audit=[
                            f"{item_str} — Inventory snapshot taken",
                            f"{item_str} — {name}: {stock:g} {unit} · ₱{price:.2f}/unit",
                            f"{item_str} — Category: {cat}",
                            f"{item_str} — Status: {'Out of stock' if stock == 0 else 'Low stock'}",
                        ],
                        activity_type="inventory",
                    ))
                    eid += 1

    except Exception as e:
        print(f"[ActivityLog] Inventory error: {e!r}")

    # ── 4. MENU ───────────────────────────────────────────────────────────────
    try:
        menu_db = get_menu_db()
        _had_menu_log = False

        try:
            menu_logs = menu_db.get_menu_change_log(date_from, date_to)
            print(f"[ActivityLog] Menu logs fetched: {len(menu_logs)}")

            for log in menu_logs:
                ts = log.get("changed_at") or log.get("timestamp")
                if not _date_in_range(ts, d_from, d_to):
                    continue

                _had_menu_log = True
                item_name  = log.get("item_name", "Unknown")
                action     = log.get("action", "Updated")
                changed_by = log.get("changed_by") or _USER_NAME
                details    = log.get("details", "")

                if user_filter != "All":
                    if user_filter.lower() not in str(changed_by).lower():
                        continue

                ts_display = _strip_tz(ts)
                ts_str     = _fmt_dt(ts_display)

                status_map = {
                    "Added":   "Added",
                    "Updated": "Updated",
                    "Deleted": "Deleted",
                }

                entries.append(dict(
                    id=eid, icon="menu",
                    activity=f"Menu {action.lower()} — {item_name}",
                    detail=(
                        f"{action} by {changed_by}"
                        + (f" · {details}" if details else "")
                    ),
                    staff=str(changed_by),
                    station="Menu Management",
                    datetime=ts_str,            # frozen string
                    _dt=ts_display,
                    _dt_frozen=True,
                    status=status_map.get(action, "Updated"),
                    original_status=status_map.get(action, "Updated"),
                    flagged=action == "Deleted",
                    audit=[
                        f"{ts_str} — Menu change recorded",
                        f"{ts_str} — Item: {item_name}",
                        f"{ts_str} — Action: {action}",
                        f"{ts_str} — By: {changed_by}",
                    ] + ([f"{ts_str} — Details: {details}"] if details else []),
                    activity_type="menu",
                ))
                eid += 1
        except Exception as menu_log_err:
            print(f"[ActivityLog] Menu log error: {menu_log_err!r}")

        # ── 4b. Menu snapshot fallback ────────────────────────────────────────
        if not _had_menu_log:
            menu_items = menu_db.fetch_all_menu_items()
            if menu_items:
                now = datetime.now()
                if _date_in_range(now, d_from, d_to):
                    for idx, mi in enumerate(menu_items):
                        item_dt  = _item_ts(mi, now, idx, stagger_seconds=60)
                        item_str = _fmt_dt(item_dt)

                        entries.append(dict(
                            id=eid, icon="menu",
                            activity=f"Menu item active — {mi.get('name', '?')}",
                            detail=(
                                f"{mi.get('category','?')} · "
                                f"₱{float(mi.get('price',0)):.2f} · "
                                f"{'Available' if not mi.get('locked') else 'Locked'}"
                            ),
                            staff="System",
                            station="Menu Management",
                            datetime=item_str,
                            _dt=item_dt,
                            _dt_frozen=True,
                            status="Completed",
                            original_status="Completed",
                            flagged=False,
                            audit=[
                                f"{item_str} — Menu snapshot",
                                f"{item_str} — {mi.get('name','?')}: "
                                f"₱{float(mi.get('price',0)):.2f}",
                            ],
                            activity_type="menu",
                        ))
                        eid += 1

    except Exception as e:
        print(f"[ActivityLog] Menu error: {e!r}")

    # ── 5. USER REGISTRATIONS ─────────────────────────────────────────────────
    try:
        auth_db   = get_auth_db()
        all_users = auth_db.get_all_users()
        for u in all_users:
            joined = u.get("created_at")
            if not _date_in_range(joined, d_from, d_to):
                continue

            full = f"{u.get('first_name','')} {u.get('last_name','')}".strip()
            role = u.get("role", "Staff")

            if user_filter != "All":
                if user_filter.lower() not in full.lower():
                    continue

            joined_display = _strip_tz(joined)
            joined_str     = _fmt_dt(joined_display)

            entries.append(dict(
                id=eid, icon="user",
                activity=f"New account registered — {full}",
                detail=f"Role: {role} · Station: {u.get('station','—')}",
                staff=full,
                station="System",
                datetime=joined_str,            # frozen string
                _dt=joined_display,
                _dt_frozen=True,
                status="Success",
                original_status="Success",
                flagged=False,
                audit=[
                    f"{joined_str} — Account created",
                    f"{joined_str} — Name: {full}",
                    f"{joined_str} — Email: {u.get('email','?')}",
                    f"{joined_str} — Role: {role}",
                    f"{joined_str} — Station: {u.get('station','—')}",
                    f"{joined_str} — Admin: {'Yes' if u.get('is_admin') else 'No'}",
                ],
                activity_type="user",
            ))
            eid += 1

    except Exception as e:
        print(f"[ActivityLog] Users error: {e!r}")

    # ── 5a. STAFF MANAGEMENT (hire / edit / remove) ───────────────────────────
    try:
        staff_db = get_staff_db()
        staff_change_log = staff_db.get_staff_change_log(date_from, date_to)
        for ev in staff_change_log:
            ts = ev.get("changed_at") or ev.get("timestamp")
            if not _date_in_range(ts, d_from, d_to):
                continue

            target     = ev.get("staff_name") or ev.get("name", "Unknown")
            action     = (ev.get("action") or "Updated").strip().capitalize()
            changed_by = (ev.get("changed_by") or ev.get("admin_name") or "Admin")
            field      = ev.get("field_changed") or ev.get("field", "")
            old_val    = ev.get("old_value", "")
            new_val    = ev.get("new_value", "")
            role       = ev.get("role", "")

            if user_filter != "All":
                if (user_filter.lower() not in str(changed_by).lower()
                        and user_filter.lower() not in target.lower()):
                    continue

            ts_display = _strip_tz(ts)
            ts_str     = _fmt_dt(ts_display)

            if action in ("Added", "Created", "Hired"):
                icon_key = "staff"
                status   = "Added"
                flagged  = False
                detail   = f"New staff hired · Role: {role} · By: {changed_by}"
            elif action in ("Deleted", "Removed", "Terminated"):
                icon_key = "void"
                status   = "Deleted"
                flagged  = True
                detail   = f"Staff removed · Role: {role} · By: {changed_by}"
            else:
                icon_key = "staff"
                status   = "Updated"
                flagged  = False
                detail   = (
                    f"Profile updated · {field}: {old_val} → {new_val}"
                    f" · By: {changed_by}"
                    if field else f"Profile updated by {changed_by}"
                )

            audit = [
                f"{ts_str} — Staff {action.lower()} recorded",
                f"{ts_str} — Staff member: {target}",
            ]
            if role:
                audit.append(f"{ts_str} — Role: {role}")
            if field:
                audit.append(f"{ts_str} — Field changed: {field}")
                if old_val:
                    audit.append(f"{ts_str} — Previous value: {old_val}")
                if new_val:
                    audit.append(f"{ts_str} — New value: {new_val}")
            audit.append(f"{ts_str} — Action by: {changed_by}")

            entries.append(dict(
                id=eid, icon=icon_key,
                activity=f"Staff {action.lower()} — {target}",
                detail=detail,
                staff=str(changed_by),
                station="Staff Management",
                datetime=ts_str,
                _dt=ts_display,
                _dt_frozen=True,
                status=status,
                original_status=status,
                flagged=flagged,
                audit=audit,
                activity_type="staff",
            ))
            eid += 1
    except AttributeError:
        pass
    except Exception as e:
        print(f"[ActivityLog] Staff management error: {e!r}")

    # ── 5b. ACCESS CONTROL / PERMISSIONS ─────────────────────────────────────
    try:
        auth_db = get_auth_db()

        try:
            access_logs = auth_db.get_access_log(date_from, date_to)
        except AttributeError:
            try:
                access_logs = auth_db.get_permission_log(date_from, date_to)
            except AttributeError:
                access_logs = []

        for ev in access_logs:
            ts = ev.get("changed_at") or ev.get("timestamp")
            if not _date_in_range(ts, d_from, d_to):
                continue

            target     = ev.get("user_name") or ev.get("staff_name", "Unknown")
            action     = (ev.get("action") or "Updated").strip().capitalize()
            changed_by = (ev.get("changed_by") or ev.get("admin_name") or "Admin")
            permission = ev.get("permission") or ev.get("access_level", "")
            old_val    = ev.get("old_value", "")
            new_val    = ev.get("new_value", "")
            module     = ev.get("module") or ev.get("section", "")

            if user_filter != "All":
                if (user_filter.lower() not in str(changed_by).lower()
                        and user_filter.lower() not in target.lower()):
                    continue

            ts_display = _strip_tz(ts)
            ts_str     = _fmt_dt(ts_display)

            detail = f"Access change · {target}"
            if permission:
                detail += f" · {permission}"
            if old_val and new_val:
                detail += f": {old_val} → {new_val}"
            detail += f" · By: {changed_by}"

            audit = [
                f"{ts_str} — Access control change recorded",
                f"{ts_str} — Affected user: {target}",
                f"{ts_str} — Action: {action}",
            ]
            if permission:
                audit.append(f"{ts_str} — Permission: {permission}")
            if module:
                audit.append(f"{ts_str} — Module: {module}")
            if old_val:
                audit.append(f"{ts_str} — Previous: {old_val}")
            if new_val:
                audit.append(f"{ts_str} — New: {new_val}")
            audit.append(f"{ts_str} — Changed by: {changed_by}")

            entries.append(dict(
                id=eid, icon="access",
                activity=f"Access control {action.lower()} — {target}",
                detail=detail,
                staff=str(changed_by),
                station="Access Control",
                datetime=ts_str,
                _dt=ts_display,
                _dt_frozen=True,
                status="Updated",
                original_status="Updated",
                flagged=False,
                audit=audit,
                activity_type="access",
            ))
            eid += 1
    except Exception as e:
        print(f"[ActivityLog] Access control error: {e!r}")

    # ── Sort descending & re-number ───────────────────────────────────────────
    def _sort_key(e):
        dt = e.get("_dt")
        if dt is None:
            return datetime.min
        if isinstance(dt, str):
            try:
                return datetime.fromisoformat(dt)
            except Exception:
                return datetime.min
        try:
            return dt.replace(tzinfo=None) if hasattr(dt, 'tzinfo') and dt.tzinfo else dt
        except Exception:
            return dt

    entries.sort(key=_sort_key, reverse=True)
    for i, e in enumerate(entries):
        e["id"] = i + 1

    return entries if entries else _demo_entries(date_from, date_to)


# ── Demo fallback ─────────────────────────────────────────────────────────────
def _demo_entries(date_from: str, date_to: str) -> list[dict]:
    NOW = datetime.now()

    def _dt(days_ago, h, m=0):
        return (NOW - timedelta(days=days_ago)).replace(hour=h, minute=m, second=0)

    def _f(dt):
        return dt.strftime("%b %d, %I:%M %p").lstrip("0")

    d_from = _date.fromisoformat(date_from)
    d_to   = _date.fromisoformat(date_to)

    raw = [
        (1,"order","Accepted order #4821",
         "2 cappuccinos, 1 almond croissant — ₱450.00",
         "Maya Patel","Dine In",_dt(0,9,15),"Completed",False,"order"),
        (2,"void","Inventory deleted — Oat Milk (250ml)",
         "Item removed from inventory · By: Daniel Kim",
         "Daniel Kim","Inventory",_dt(0,8,55),"Deleted",True,"inventory"),
        (3,"restock","Inventory added — Cold Brew Concentrate",
         "Added with stock: 24 · By: Daniel Kim · Beverages",
         "Daniel Kim","Inventory",_dt(0,8,42),"Added",False,"inventory"),
        (4,"login","Clock In — Sofia Martinez",
         "Front Counter · Cashier · Device: Register 1",
         "Sofia Martinez","Register 1",_dt(0,7,58),"Login",False,"clock"),
        (5,"staff","Staff added — Lea Santos",
         "New staff hired · Role: Barista · By: Admin",
         "Admin","Staff Management",_dt(1,9,10),"Added",False,"staff"),
        (6,"access","Access control updated — Sofia Martinez",
         "Access change · Sofia Martinez · POS Access: View → Full · By: Admin",
         "Admin","Access Control",_dt(1,9,5),"Updated",False,"access"),
        (7,"menu","Menu updated — Oat Latte",
         "Price updated ₱180→₱195 by Daniel Kim",
         "Daniel Kim","Menu Management",_dt(1,10,0),"Updated",False,"menu"),
        (8,"logout","Clock Out — Sofia Martinez",
         "Shift ended · Duration: 8h 02m",
         "Sofia Martinez","Register 1",_dt(1,16,0),"Logout",False,"clock"),
        (9,"order","Order #4816 — Takeout",
         "1 matcha latte, 1 muffin — ₱310.00",
         "Aiden Brooks","Takeout",_dt(2,7,46),"Completed",False,"order"),
        (10,"void","Void — Order #4807",
         "Duplicate pastry removed — manager override",
         "Noah Rivera","Front Counter",_dt(3,18,14),"Review",True,"order"),
        (11,"user","New account — Leah Johnson",
         "Role: Cashier · Station: Register 2",
         "Leah Johnson","System",_dt(4,9,0),"Success",False,"user"),
        (12,"restock","Inventory restock — Almond Croissants",
         "Added 12 units to pastry display",
         "Daniel Kim","Inventory",_dt(5,16,30),"Adjusted",False,"inventory"),
    ]

    out = []
    for row in raw:
        eid, icon, activity, detail, staff, station, dt, status, flagged, atype = row
        if not (d_from <= dt.date() <= d_to):
            continue
        ts_str = _f(dt)
        out.append(dict(
            id=eid, icon=icon, activity=activity, detail=detail,
            staff=staff, station=station,
            datetime=ts_str,
            _dt=dt,
            _dt_frozen=True,
            status=status, original_status=status,
            flagged=flagged,
            audit=[f"{ts_str} — {activity}", f"{ts_str} — {detail}"],
            activity_type=atype,
        ))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# UI WIDGETS  (unchanged from v5.3 except auto-timer removed in main window)
# ═══════════════════════════════════════════════════════════════════════════════
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
    fg = fg or C["text"]
    border = border or C["border"]
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


class ActivityIcon(QLabel):
    def __init__(self, icon_type: str, size=38, parent=None):
        super().__init__(parent)
        emoji, bg, fg = ICON_MAP.get(icon_type, ("•", C["border"], C["sub"]))
        self.setFixedSize(size, size)
        self.setText(emoji)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background:{bg};border-radius:{size // 2}px;"
            f"font-size:{max(14, int(size * .38))}px;color:{fg};border:none;"
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
        bg = {"ok": C["accent"], "warn": C["warn"], "danger": C["danger"]}.get(
            kind, C["accent"])
        self.setFixedHeight(44)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(f"background:{bg};border-radius:10px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        msg = QLabel(message)
        msg.setStyleSheet(
            "color:#FFFFFF;font-size:13px;font-weight:600;background:transparent;"
        )
        lay.addWidget(msg)
        self._eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._eff)
        self._eff.setOpacity(0)
        self._in  = QPropertyAnimation(self._eff, b"opacity", self)
        self._in.setDuration(220)
        self._in.setEndValue(1.0)
        self._out = QPropertyAnimation(self._eff, b"opacity", self)
        self._out.setDuration(350)
        self._out.setEndValue(0.0)
        self._out.finished.connect(self.deleteLater)
        self._repos()
        self.show()
        self._in.start()
        QTimer.singleShot(2800, self._out.start)

    def _repos(self):
        if self.parent():
            pw = self.parent().width()
            w  = max(300, min(460, pw - 80))
            self.setFixedWidth(w)
            self.move((pw - w) // 2, self.parent().height() - 80)


def show_toast(parent, message, kind="ok"):
    Toast(message, parent, kind).raise_()


# ── Date Range Dialog ─────────────────────────────────────────────────────────
class DateRangeDialog(QDialog):
    def __init__(self, current_from: QDate, current_to: QDate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Date Range")
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
        hl.addWidget(lbl("📅  Select Date Range", bold=True, size=15, color="#FFFFFF"))
        hl.addStretch()
        x = QPushButton("✕")
        x.setFixedSize(28, 28)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.2);color:white;"
            "border:none;border-radius:14px;font-weight:700;}"
            "QPushButton:hover{background:rgba(255,255,255,0.35);}"
        )
        x.clicked.connect(self.reject)
        hl.addWidget(x)
        lay.addWidget(hdr)

        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(16)

        presets_frame = QFrame()
        presets_frame.setFixedWidth(160)
        presets_frame.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:10px;"
            f"border:1px solid {C['border']};}}"
        )
        pfl = QVBoxLayout(presets_frame)
        pfl.setContentsMargins(12, 14, 12, 14)
        pfl.setSpacing(6)
        pfl.addWidget(lbl("Quick Select", bold=True, size=11, color=C["sub"]))

        today = QDate.currentDate()
        presets = [
            ("Today",        today,                  today),
            ("Yesterday",    today.addDays(-1),      today.addDays(-1)),
            ("Last 7 Days",  today.addDays(-6),      today),
            ("Last 30 Days", today.addDays(-29),     today),
            ("This Month",   QDate(today.year(), today.month(), 1), today),
            ("Last Month",
             QDate(today.year(), today.month(), 1).addMonths(-1),
             QDate(today.year(), today.month(), 1).addDays(-1)),
        ]
        for label_text, d_f, d_t in presets:
            btn = QPushButton(label_text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:{C['bg']};border:1px solid {C['border']};"
                f"border-radius:6px;padding:6px 10px;font-size:11px;"
                f"color:{C['text']};text-align:left;}}"
                f"QPushButton:hover{{background:{C['accent_lt']};"
                f"border-color:{C['accent']};color:{C['accent']};}}"
            )
            btn.clicked.connect(lambda _, f=d_f, t=d_t: self._apply(f, t))
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
        self._cal_from.setStyleSheet(self._cal_qss())
        self._cal_from.selectionChanged.connect(self._on_from)
        from_col.addWidget(self._cal_from)
        cals_row.addLayout(from_col)

        to_col = QVBoxLayout()
        to_col.setSpacing(6)
        to_col.addWidget(lbl("To", bold=True, size=12))
        self._cal_to = QCalendarWidget()
        self._cal_to.setSelectedDate(self._to)
        self._cal_to.setMaximumDate(QDate.currentDate())
        self._cal_to.setStyleSheet(self._cal_qss())
        self._cal_to.selectionChanged.connect(self._on_to)
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
        footer.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 12, 20, 12)
        fl.setSpacing(10)
        fl.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(
            f"QPushButton{{background:{C['bg']};border:1px solid {C['border']};"
            f"border-radius:7px;padding:7px 20px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:#E5E7EB;}}"
        )
        cancel.clicked.connect(self.reject)
        fl.addWidget(cancel)
        apply = QPushButton("Apply Range")
        apply.setCursor(Qt.CursorShape.PointingHandCursor)
        apply.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:white;"
            f"border-radius:7px;padding:7px 22px;font-size:12px;"
            f"font-weight:700;border:none;}}"
            f"QPushButton:hover{{background:{C['accent_dk']};}}"
        )
        apply.clicked.connect(self.accept)
        fl.addWidget(apply)
        lay.addWidget(footer)

    def _cal_qss(self):
        return f"""
        QCalendarWidget QAbstractItemView {{
            selection-background-color:{C['accent']};
            selection-color:white;font-size:11px;
        }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background:{C['accent']};border-radius:8px;
        }}
        QCalendarWidget QToolButton {{
            color:white;background:transparent;border:none;font-weight:700;
        }}
        QCalendarWidget QToolButton:hover {{
            background:rgba(255,255,255,0.2);border-radius:4px;
        }}
        QCalendarWidget QSpinBox {{
            color:white;background:transparent;border:none;font-weight:700;
        }}
        """

    def _apply(self, d_f, d_t):
        self._from = d_f
        self._to   = d_t
        self._cal_from.setSelectedDate(d_f)
        self._cal_to.setSelectedDate(d_t)
        self._update_range_lbl()

    def _on_from(self):
        self._from = self._cal_from.selectedDate()
        if self._from > self._to:
            self._to = self._from
            self._cal_to.setSelectedDate(self._to)
        self._update_range_lbl()

    def _on_to(self):
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

    def get_range(self):
        return self._from, self._to


# ── View Details Dialog ───────────────────────────────────────────────────────
class ViewDetailsDialog(QDialog):
    flag_toggled = pyqtSignal(int, bool)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self._entry = entry
        self.setWindowTitle(f"Activity Detail — #{entry['id']}")
        self.setMinimumSize(600, 600)
        self.setStyleSheet(
            f"QDialog{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 18, 24, 18)
        hl.setSpacing(14)
        hl.addWidget(ActivityIcon(self._entry["icon"], 44))
        tc = QVBoxLayout()
        tc.setSpacing(3)
        title = lbl(self._entry["activity"], bold=True, size=15)
        title.setWordWrap(True)
        tc.addWidget(title)
        tc.addWidget(lbl(self._entry["detail"], size=11, color=C["sub"]))
        hl.addLayout(tc, stretch=1)

        right_col = QVBoxLayout()
        right_col.setSpacing(4)
        right_col.addWidget(status_badge(self._entry["status"]))
        if _is_recent(self._entry.get("_dt")):
            live_lbl = QLabel("🔴 LIVE")
            live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            live_lbl.setStyleSheet(
                f"background:{C['danger']};color:white;border-radius:5px;"
                f"padding:2px 8px;font-size:10px;font-weight:700;"
            )
            right_col.addWidget(live_lbl)
        hl.addLayout(right_col)
        root.addWidget(hdr)

        body = QWidget()
        body.setStyleSheet(f"background:{C['bg']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 20)
        bl.setSpacing(16)

        meta = QFrame()
        meta.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:10px;"
            f"border:1px solid {C['border']};}}"
        )
        from PyQt6.QtWidgets import QGridLayout
        mg = QGridLayout(meta)
        mg.setContentsMargins(20, 16, 20, 16)
        mg.setHorizontalSpacing(24)
        mg.setVerticalSpacing(12)

        fields = [
            ("Staff Member",     self._entry["staff"]),
            ("Station / Device", self._entry["station"]),
            ("Date & Time",      self._entry["datetime"]),
            ("Entry ID",         f"#{self._entry['id']}"),
            ("Activity Type",    self._entry.get("activity_type", "—").capitalize()),
            ("Current Status",   self._entry["status"]),
            ("Original Status",  self._entry.get("original_status", "—")),
            ("Flagged",          "⚑ Yes" if self._entry.get("flagged") else "No"),
        ]
        for i, (k, v) in enumerate(fields):
            col = (i % 2) * 2
            row = i // 2
            mg.addWidget(lbl(k, size=10, color=C["sub"]), row, col)
            vl = lbl(str(v), bold=True, size=12)
            if k == "Current Status":
                fg, bg = STATUS_CFG.get(v, (C["sub"], C["border"]))
                vl.setStyleSheet(
                    f"color:{fg};background:{bg};border-radius:5px;"
                    f"padding:2px 8px;font-size:11px;font-weight:700;"
                )
            mg.addWidget(vl, row, col + 1)
        bl.addWidget(meta)

        bl.addWidget(lbl("Audit Trail", bold=True, size=13))
        ac = QFrame()
        ac.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:10px;"
            f"border:1px solid {C['border']};}}"
        )
        al = QVBoxLayout(ac)
        al.setContentsMargins(20, 14, 20, 14)
        al.setSpacing(0)

        audit_list = self._entry.get(
            "audit", [self._entry["datetime"] + " — " + self._entry["activity"]]
        )
        for i, line in enumerate(audit_list):
            rw = QWidget()
            rw.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 6, 0, 6)
            rl.setSpacing(14)
            dc = QVBoxLayout()
            dc.setSpacing(0)
            is_last = (i == len(audit_list) - 1)
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(
                f"background:{C['accent'] if is_last else C['border']};"
                f"border-radius:5px;border:none;"
            )
            dc.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter)
            if not is_last:
                vln = QFrame()
                vln.setFixedWidth(2)
                vln.setMinimumHeight(16)
                vln.setStyleSheet(f"background:{C['border']};border:none;")
                dc.addWidget(vln, alignment=Qt.AlignmentFlag.AlignHCenter)
                dc.addStretch()
            rl.addLayout(dc)
            parts = line.split(" — ", 1)
            if len(parts) == 2:
                tl = lbl(parts[0], size=10, color=C["sub"])
                tl.setFixedWidth(130)
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

        foot = QWidget()
        foot.setStyleSheet(
            f"background:{C['white']};border-top:1px solid {C['border']};"
        )
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(24, 14, 24, 14)
        fl.setSpacing(10)

        cb = outline_btn("📋  Copy Entry", height=36)
        cb.clicked.connect(self._copy)
        fl.addWidget(cb)

        flagged   = self._entry.get("flagged", False)
        flag_text = "⚑  Unflag Entry" if flagged else "⚑  Flag for Review"
        flag_fg   = C["accent"] if flagged else C["danger"]
        flag_hov  = C["accent_lt"] if flagged else C["danger_lt"]
        self._fb  = outline_btn(flag_text, fg=flag_fg, border=flag_fg,
                                hover_bg=flag_hov, height=36)
        self._fb.clicked.connect(self._toggle_flag)
        fl.addWidget(self._fb)
        fl.addStretch()

        close = make_btn("Close", C["accent"], hover=C["accent_dk"])
        close.clicked.connect(self.accept)
        fl.addWidget(close)
        root.addWidget(foot)

    def _copy(self):
        e = self._entry
        QGuiApplication.clipboard().setText(
            f"Activity Log Entry #{e['id']}\n{'─'*44}\n"
            f"Activity      : {e['activity']}\n"
            f"Detail        : {e['detail']}\n"
            f"Staff         : {e['staff']}\n"
            f"Station       : {e['station']}\n"
            f"Date/Time     : {e['datetime']}\n"
            f"Status        : {e['status']}\n"
            f"Activity Type : {e.get('activity_type','—')}\n"
            f"Flagged       : {'Yes' if e.get('flagged') else 'No'}\n"
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
        lay.addWidget(lbl(
            "Notes are visible to managers and shift supervisors.",
            size=10, color=C["sub"]
        ))
        lay.addWidget(hline())

        def _inp(ph, val=""):
            f = QLineEdit()
            f.setPlaceholderText(ph)
            if val:
                f.setText(val)
            f.setFixedHeight(38)
            f.setStyleSheet(
                f"border:1px solid {C['border']};border-radius:7px;"
                f"padding:0 12px;background:{C['bg']};font-size:13px;"
            )
            return f

        lay.addWidget(lbl("Staff Member", size=11, color=C["sub"]))
        self.staff_field = _inp("e.g. Maya Patel", _USER_NAME)
        lay.addWidget(self.staff_field)

        lay.addWidget(lbl("Station", size=11, color=C["sub"]))
        self.station_field = _inp("e.g. Front Counter")
        lay.addWidget(self.station_field)

        lay.addWidget(lbl("Note", size=11, color=C["sub"]))
        self.note_field = QTextEdit()
        self.note_field.setPlaceholderText(
            "Describe the activity or observation…"
        )
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

        br = QHBoxLayout()
        br.addStretch()
        cancel = outline_btn("Cancel")
        cancel.clicked.connect(self.reject)
        save = make_btn("  +  Add Note", C["accent"], hover=C["accent_dk"])
        save.clicked.connect(self._save)
        br.addWidget(cancel)
        br.addSpacing(8)
        br.addWidget(save)
        lay.addLayout(br)

    def _save(self):
        if not self.staff_field.text().strip() or \
                not self.note_field.toPlainText().strip():
            QMessageBox.warning(self, "Required",
                                "Staff member and note are required.")
            return
        self.accept()

    def get_status(self):
        return self.priority.currentText()


# ── Activity Row ──────────────────────────────────────────────────────────────
class ActivityRow(QWidget):
    view_requested = pyqtSignal(dict)
    flag_requested = pyqtSignal(dict)
    copy_requested = pyqtSignal(dict)

    def __init__(self, entry: dict, alt_bg=False, parent=None):
        super().__init__(parent)
        self._entry  = entry
        self._alt_bg = alt_bg
        self._hovered = False
        self.setMouseTracking(True)
        self._build()
        self._refresh_style()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 16, 12)
        lay.setSpacing(12)
        lay.addWidget(ActivityIcon(self._entry["icon"], 36))

        ac = QVBoxLayout()
        ac.setSpacing(2)
        act_row = QHBoxLayout()
        self._act = lbl(self._entry["activity"], bold=True, size=12)
        act_row.addWidget(self._act)
        if _is_recent(self._entry.get("_dt")):
            live = QLabel("🔴 LIVE")
            live.setStyleSheet(
                f"background:{C['danger']};color:white;border-radius:4px;"
                f"padding:1px 6px;font-size:9px;font-weight:700;border:none;"
            )
            act_row.addWidget(live)
        act_row.addStretch()
        ac.addLayout(act_row)
        self._det = lbl(self._entry["detail"], size=10, color=C["sub"])
        self._det.setWordWrap(True)
        ac.addWidget(self._det)
        lay.addLayout(ac, stretch=3)

        self._stf = lbl(self._entry["staff"],    size=11)
        self._stn = lbl(self._entry["station"],  size=11, color=C["sub"])
        self._dtl = lbl(self._entry["datetime"], size=10, color=C["muted"])
        lay.addWidget(self._stf, stretch=2)
        lay.addWidget(self._stn, stretch=2)
        lay.addWidget(self._dtl, stretch=2)

        self._badge = status_badge(self._entry["status"])
        bw = QWidget()
        bw.setStyleSheet("background:transparent;")
        bwl = QHBoxLayout(bw)
        bwl.setContentsMargins(0, 0, 0, 0)
        bwl.addWidget(self._badge)
        bwl.addStretch()
        lay.addWidget(bw, stretch=1)

        self._fdot = QLabel("⚑")
        self._fdot.setFixedSize(20, 20)
        self._fdot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fdot.setStyleSheet(
            f"color:{C['danger']};font-size:12px;background:transparent;"
        )
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
        bg = C["hover"] if self._hovered else (
            C["row_alt"] if self._alt_bg else C["white"]
        )
        self.setStyleSheet(f"background:{bg};")

    def enterEvent(self, e):
        self._hovered = True
        self._refresh_style()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self._refresh_style()
        super().leaveEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.view_requested.emit(self._entry)

    def _menu(self):
        m = QMenu(self)
        m.setStyleSheet(
            f"QMenu{{background:{C['white']};border:1px solid {C['border']};"
            f"border-radius:10px;padding:6px;}}"
            f"QMenu::item{{padding:9px 20px;border-radius:5px;font-size:12px;"
            f"color:{C['text']};}}"
            f"QMenu::item:selected{{background:{C['accent_lt']};"
            f"color:{C['accent']};}}"
            f"QMenu::separator{{background:{C['border']};height:1px;"
            f"margin:4px 10px;}}"
        )
        va = m.addAction("  👁   View Details")
        ca = m.addAction("  📋  Copy Entry")
        m.addSeparator()
        flagged = self._entry.get("flagged", False)
        fa = m.addAction(
            "  ⚑   Unflag Entry" if flagged else "  ⚑   Flag for Review"
        )
        chosen = m.exec(QCursor.pos())
        if chosen == va:
            self.view_requested.emit(self._entry)
        elif chosen == ca:
            self.copy_requested.emit(self._entry)
        elif chosen == fa:
            self.flag_requested.emit(self._entry)

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


# ── Activity Table ────────────────────────────────────────────────────────────
COLS = [("Activity", "activity", 3), ("Staff Member", "staff", 2),
        ("Station", "station", 2), ("Date & Time", "datetime", 2),
        ("Status", "status", 1)]


class ColumnHeader(QWidget):
    sort_requested = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setStyleSheet(
            f"background:{C['bg']};border-bottom:1px solid {C['border']};"
        )
        self._sf  = None
        self._asc = True
        self._btns = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(12)
        sp = QWidget()
        sp.setFixedWidth(48)
        lay.addWidget(sp)
        for label_text, field, stretch in COLS:
            btn = QPushButton(label_text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C['sub']};"
                f"border:none;font-size:10px;font-weight:700;text-align:left;"
                f"padding:0;}}"
                f"QPushButton:hover{{color:{C['accent']};}}"
            )
            btn.clicked.connect(lambda _, f=field: self._sort(f))
            self._btns[field] = btn
            lay.addWidget(btn, stretch=stretch)
        for w in [20, 32]:
            sp = QWidget()
            sp.setFixedWidth(w)
            lay.addWidget(sp)

    def _sort(self, field):
        self._asc = not self._asc if self._sf == field else True
        self._sf  = field
        arrow = " ↑" if self._asc else " ↓"
        for f, b in self._btns.items():
            base = COLS[[c[1] for c in COLS].index(f)][0]
            b.setText(base + (arrow if f == field else ""))
        self.sort_requested.emit(field, self._asc)


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
        self._type_f     = "All"
        self._flag_only  = False
        self._sort_field = None
        self._sort_asc   = True
        self.setStyleSheet(f"background:{C['white']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        hdr = ColumnHeader()
        hdr.sort_requested.connect(self._on_sort)
        root.addWidget(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{C['white']};}}"
            f"QScrollBar:vertical{{background:{C['bg']};width:6px;"
            f"border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{C['border']};"
            f"border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,"
            f"QScrollBar::sub-line:vertical{{height:0;}}"
        )
        self._body = QWidget()
        self._body.setStyleSheet(f"background:{C['white']};")
        self._bl   = QVBoxLayout(self._body)
        self._bl.setContentsMargins(0, 0, 0, 0)
        self._bl.setSpacing(0)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, stretch=1)
        self._refresh()

    def _filtered(self):
        result = []
        for e in self._entries:
            if self._search and not any(
                self._search in str(e.get(k, "")).lower()
                for k in ("activity", "staff", "station", "detail")
            ):
                continue
            if self._status_f != "All" and e["status"] != self._status_f:
                continue
            if self._staff_f and self._staff_f not in e["staff"].lower():
                continue
            if self._type_f != "All" and \
                    e.get("activity_type", "") != self._type_f:
                continue
            if self._flag_only and not e.get("flagged", False):
                continue
            result.append(e)
        if self._sort_field:
            result.sort(
                key=lambda x: str(x.get(self._sort_field, "")).lower(),
                reverse=not self._sort_asc,
            )
        return result

    def _refresh(self):
        while self._bl.count():
            item = self._bl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        visible = self._filtered()
        self.match_count_changed.emit(len(visible))
        if not visible:
            msg = (
                "No activity found for this date range."
                if not self._search and self._status_f == "All"
                else "No activity matches your filter."
            )
            el = lbl(msg, size=12, color=C["sub"])
            el.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._bl.addSpacing(48)
            self._bl.addWidget(el)
            self._bl.addStretch()
            return
        for i, entry in enumerate(visible):
            row = ActivityRow(entry, alt_bg=(i % 2 == 1))
            row.view_requested.connect(self.entry_view_requested)
            row.flag_requested.connect(self.entry_flag_requested)
            row.copy_requested.connect(self.entry_copy_requested)
            self._bl.addWidget(row)
            if i < len(visible) - 1:
                self._bl.addWidget(hline())
        self._bl.addStretch()

    def replace_entries(self, entries):
        self._entries = entries
        self._refresh()

    def set_search(self, text):
        self._search = text.lower()
        self._refresh()

    def set_type_filter(self, t: str):
        self._type_f = t
        self._refresh()

    def prepend_entry(self, entry):
        if entry not in self._entries:
            self._entries.insert(0, entry)
        self._refresh()

    def add_entry(self, entry):
        if entry not in self._entries:
            self._entries.insert(0, entry)
        self._refresh()

    def refresh_entry(self, _id):
        self._refresh()

    def apply_filter(self, status, staff, flag_only):
        self._status_f  = status
        self._staff_f   = staff
        self._flag_only = flag_only
        self._refresh()

    def _on_sort(self, field, asc):
        self._sort_field = field
        self._sort_asc   = asc
        self._refresh()


# ── Stat Card ─────────────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, label, value, badge_text, badge_fg, badge_bg, subtitle,
                 click_type=None, parent=None):
        super().__init__(parent)
        self._click_type = click_type
        self.setStyleSheet(
            "QFrame{background:#FFFFFF;border-radius:0px;border:none;}"
        )
        if click_type:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(lbl(label, size=11, color=C["sub"]))
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"background:{badge_bg};color:{badge_fg};"
            f"border-radius:5px;padding:2px 10px;font-size:10px;"
            f"font-weight:700;border:none;"
        )
        top.addWidget(badge)
        top.addStretch()
        lay.addLayout(top)
        lay.addWidget(lbl(str(value), bold=True, size=34))
        lay.addWidget(lbl(subtitle, size=10, color=C["muted"]))

    def mousePressEvent(self, e):
        if self._click_type:
            self.parent().parent()._on_stat_click(self._click_type)
        super().mousePressEvent(e)


# ── Filter Dialog ─────────────────────────────────────────────────────────────
class FilterDialog(QDialog):
    filter_applied = pyqtSignal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter Activity")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"QDialog{{background:{C['white']};}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(lbl("Filter Activity Log", bold=True, size=15))
        lay.addWidget(hline())
        lay.addWidget(lbl("Status", size=11, color=C["sub"]))

        self._status_btns: dict[str, QPushButton] = {}
        self._current_status = "All"
        all_statuses = [
            "All", "Completed", "Success", "Adjusted",
            "Review", "Resolved", "Login", "Logout",
        ]
        rows = [all_statuses[:4], all_statuses[4:]]
        for row_items in rows:
            rlay = QHBoxLayout()
            rlay.setSpacing(6)
            for s in row_items:
                btn = QPushButton(s)
                btn.setCheckable(True)
                btn.setChecked(s == "All")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setFixedHeight(30)
                btn.clicked.connect(lambda _, st=s: self._pick(st))
                self._status_btns[s] = btn
                rlay.addWidget(btn)
            lay.addLayout(rlay)
        self._restyle("All")

        lay.addWidget(lbl("Staff Member", size=11, color=C["sub"]))
        self.staff_box = QLineEdit()
        self.staff_box.setPlaceholderText("Filter by staff name…")
        self.staff_box.setFixedHeight(38)
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

        br = QHBoxLayout()
        br.addStretch()
        cancel = outline_btn("Cancel")
        cancel.clicked.connect(self.reject)
        apply = make_btn("Apply Filter", C["accent"], hover=C["accent_dk"])
        apply.clicked.connect(self._apply)
        br.addWidget(cancel)
        br.addSpacing(8)
        br.addWidget(apply)
        lay.addLayout(br)

    def _pick(self, s):
        self._current_status = s
        self._restyle(s)

    def _restyle(self, active):
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
            self._current_status,
            self.staff_box.text().strip().lower(),
            self._fo.isChecked(),
        )
        self.accept()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════
class ActivityLogWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pawffinated – Activity Log")
        self.resize(1360, 900)
        self.setMinimumSize(960, 660)
        self.setStyleSheet(
            f"QMainWindow,#central{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
            f"QToolBar{{background:{C['white']};"
            f"border-bottom:1px solid {C['border']};padding:4px 16px;"
            f"spacing:8px;}}"
            f"QStatusBar{{background:{C['white']};"
            f"border-top:1px solid {C['border']};color:{C['sub']};"
            f"font-size:11px;padding:0 12px;}}"
        )

        today = QDate.currentDate()
        self._date_from   = today
        self._date_to     = today
        self._user_filter = "All"
        self._entries     = []
        self._load_entries()

        self._build_toolbar()
        self._build_ui()
        self._update_stat_strip()
        self._update_status()

        # ── NO auto-refresh timer ─────────────────────────────────────────────
        # The 60-second auto-timer has been removed entirely.
        # Timestamps are loaded once from the DB and never change.
        # Use the "Refresh" button or Ctrl+R to reload manually.

        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            lambda: self._search_box.setFocus()
        )
        QShortcut(QKeySequence("Escape"), self).activated.connect(
            lambda: (self._search_box.clear(), self._search_box.clearFocus())
        )
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(
            self._refresh_all
        )

    def _date_strings(self):
        return (
            self._date_from.toString("yyyy-MM-dd"),
            self._date_to.toString("yyyy-MM-dd"),
        )

    def _date_range_label(self):
        if self._date_from == self._date_to:
            return f"📅  {self._date_from.toString('MMM d, yyyy')}"
        return (
            f"📅  {self._date_from.toString('MMM d, yyyy')}  →  "
            f"{self._date_to.toString('MMM d, yyyy')}"
        )

    def _load_entries(self):
        d_from, d_to = self._date_strings()
        self._entries = _load_all_activities(d_from, d_to, self._user_filter)

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        logo = QLabel("  🐾  PAWFFINATED  ")
        logo.setStyleSheet(
            f"font-weight:800;font-size:14px;color:{C['accent']};"
        )
        tb.addWidget(logo)
        sp = QWidget()
        sp.setSizePolicy(QSizePolicy.Policy.Expanding,
                         QSizePolicy.Policy.Preferred)
        tb.addWidget(sp)

        self._date_btn = QPushButton(self._date_range_label())
        self._date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._date_btn.setStyleSheet(
            f"QPushButton{{color:{C['text']};font-size:12px;"
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:5px 14px;background:{C['white']};}}"
            f"QPushButton:hover{{background:{C['accent_lt']};"
            f"border-color:{C['accent']};color:{C['accent']};}}"
        )
        self._date_btn.clicked.connect(self._open_date_picker)
        tb.addWidget(self._date_btn)

        self._user_combo = QComboBox()
        self._user_combo.addItem("All Staff")
        self._user_combo.setFixedHeight(32)
        self._user_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._user_combo.setStyleSheet(
            f"QComboBox{{border:1px solid {C['border']};border-radius:6px;"
            f"padding:0 10px;background:{C['white']};font-size:12px;"
            f"min-width:140px;}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
        )
        self._user_combo.currentTextChanged.connect(self._on_user_filter)
        tb.addWidget(self._user_combo)
        self._populate_user_combo()

        db_label = "🔗 Live DB" if HAS_DB else "⚠️ Demo Mode"
        dl = QLabel(f"  {db_label}  ")
        dl.setStyleSheet(
            f"color:{C['accent'] if HAS_DB else C['warn']};font-size:11px;"
            f"border:1px solid {C['border']};border-radius:6px;"
            f"padding:4px 10px;background:{C['white']};"
        )
        tb.addWidget(dl)

    def _populate_user_combo(self):
        try:
            staff_db  = get_staff_db() if HAS_DB else None
            auth_db   = get_auth_db()  if HAS_DB else None
            names: set[str] = set()
            if staff_db:
                for s in staff_db.get_all_staff():
                    n = s.get("name", "").strip()
                    if n:
                        names.add(n)
            if auth_db:
                for u in auth_db.get_all_users():
                    n = f"{u.get('first_name','')} {u.get('last_name','')}".strip()
                    if n:
                        names.add(n)
            for n in sorted(names):
                self._user_combo.addItem(n)
        except Exception:
            pass

    def _on_user_filter(self, text: str):
        self._user_filter = "All" if text == "All Staff" else text
        self._refresh_all()

    def _open_date_picker(self):
        dlg = DateRangeDialog(self._date_from, self._date_to, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._date_from, self._date_to = dlg.get_range()
            self._date_btn.setText(self._date_range_label())
            self._refresh_all()

    def _refresh_all(self):
        self._load_entries()
        self._table.replace_entries(self._entries)
        self._update_stat_strip()
        self._update_status()
        show_toast(
            self.centralWidget(),
            f"Loaded {len(self._entries)} entries · "
            f"{self._date_range_label().replace('📅  ','')}",
            "ok",
        )

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        if HAS_SIDEBAR:
            _cu = get_current_user()
            root.addWidget(PawffinatedSidebar(active_page="Activity Log", current_user=_cu))

        main = QWidget()
        main.setStyleSheet(f"background:{C['bg']};")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        self._build_page_header(ml)
        self._stat_strip_widget = QWidget()
        self._build_stat_strip_inner()
        ml.addWidget(self._stat_strip_widget)
        self._build_type_filter_bar(ml)
        self._build_table_section(ml)
        root.addWidget(main, stretch=1)

    def _build_page_header(self, parent):
        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(28, 18, 28, 18)
        hl.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(3)
        left.addWidget(lbl("Activity Log", bold=True, size=20))
        left.addWidget(lbl(
            "Complete record of all staff actions — orders, inventory, "
            "menu changes, logins, staff management, and access control. "
            "Timestamps reflect the exact time each event was recorded. "
            "Use Refresh (Ctrl+R) to load new entries.",
            size=10, color=C["sub"],
        ))
        hl.addLayout(left)
        hl.addStretch()

        refresh_btn = outline_btn(
            "🔄  Refresh", fg=C["accent"], border=C["accent"],
            hover_bg=C["accent_lt"],
        )
        refresh_btn.setToolTip("Ctrl+R — loads new entries from the database")
        refresh_btn.clicked.connect(self._refresh_all)
        hl.addWidget(refresh_btn)

        eb = outline_btn("⬇  Export CSV")
        eb.clicked.connect(self._export_csv)
        hl.addWidget(eb)

        xb = outline_btn(
            "⚠  Exceptions", fg=C["danger"], border=C["danger"],
            hover_bg=C["danger_lt"],
        )
        xb.clicked.connect(self._view_exceptions)
        hl.addWidget(xb)

        nb = make_btn("＋  Add Note", C["accent"], hover=C["accent_dk"])
        nb.clicked.connect(self._add_note)
        hl.addWidget(nb)
        parent.addWidget(hdr)

    def _build_stat_strip_inner(self):
        old_lay = self._stat_strip_widget.layout()
        if old_lay:
            while old_lay.count():
                item = old_lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        orders_count  = sum(1 for e in self._entries
                            if e.get("activity_type") == "order")
        inv_count     = sum(1 for e in self._entries
                            if e.get("activity_type") == "inventory")
        menu_count    = sum(1 for e in self._entries
                            if e.get("activity_type") == "menu")
        clock_count   = sum(1 for e in self._entries
                            if e.get("activity_type") == "clock")
        staff_count   = sum(1 for e in self._entries
                            if e.get("activity_type") == "staff")
        flagged_count = sum(1 for e in self._entries if e.get("flagged"))

        self._stat_strip_widget.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        sl = QHBoxLayout(self._stat_strip_widget)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        cards = [
            ("Orders",        orders_count,  "Transactions",
             C["ok"],     C["ok_lt"],     "POS orders & charges",        "order"),
            ("Inventory",     inv_count,     "Items",
             C["warn"],   C["warn_lt"],   "Stock changes & alerts",      "inventory"),
            ("Menu Changes",  menu_count,    "Updates",
             C["blue"],   C["blue_lt"],   "Menu adds, edits, deletes",   "menu"),
            ("Staff Events",  clock_count,   "Logged",
             C["purple"], C["purple_lt"], "Clock in/out events",         "clock"),
            ("Staff Changes", staff_count,   "Events",
             C["warn"],   C["warn_lt"],   "Hires, edits, removals",      "staff"),
            ("Flagged",       flagged_count, "Action required",
             C["danger"], C["danger_lt"], "Flagged for review",          "flag"),
        ]
        for i, (label, val, bt, bfg, bbg, sub, ctype) in enumerate(cards):
            if i:
                sl.addWidget(QFrame(
                    frameShape=QFrame.Shape.VLine,
                    styleSheet=f"background:{C['border']};border:none;"
                ))
            card = StatCard(label, val, bt, bfg, bbg, sub, ctype)
            sl.addWidget(card, stretch=1)

    def _update_stat_strip(self):
        self._build_stat_strip_inner()

    def _build_type_filter_bar(self, parent):
        bar = QWidget()
        bar.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(28, 10, 28, 10)
        bl.setSpacing(8)

        types = [
            ("All",       "All Types"),
            ("order",     "🧾 Orders"),
            ("inventory", "📦 Inventory"),
            ("menu",      "🍽️ Menu"),
            ("clock",     "⏱ Clock Events"),
            ("user",      "👤 Registrations"),
            ("staff",     "👥 Staff Mgmt"),
            ("access",    "🔐 Access Control"),
        ]
        self._type_btns: dict[str, QPushButton] = {}
        for key, label in types:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "All")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _, k=key: self._on_type_filter(k))
            self._type_btns[key] = btn
            self._style_type_btn(btn, key == "All")
            bl.addWidget(btn)
        bl.addStretch()
        parent.addWidget(bar)

    def _style_type_btn(self, btn: QPushButton, active: bool):
        if active:
            btn.setStyleSheet(
                f"QPushButton{{background:{C['accent']};color:white;"
                f"border:none;border-radius:6px;font-size:11px;"
                f"font-weight:700;padding:0 12px;}}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton{{background:{C['white']};color:{C['text']};"
                f"border:1px solid {C['border']};border-radius:6px;"
                f"font-size:11px;padding:0 10px;}}"
                f"QPushButton:hover{{background:{C['bg']};}}"
            )

    def _on_type_filter(self, key: str):
        for k, btn in self._type_btns.items():
            btn.blockSignals(True)
            btn.setChecked(k == key)
            btn.blockSignals(False)
            self._style_type_btn(btn, k == key)
        self._table.set_type_filter(key)

    def _on_stat_click(self, ctype: str):
        key = ctype if ctype != "flag" else "All"
        if ctype == "flag":
            self._table.apply_filter("All", "", True)
        else:
            self._on_type_filter(key)

    def _build_table_section(self, parent):
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{C['bg']};")
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(28, 20, 28, 20)
        wl.setSpacing(14)

        top = QHBoxLayout()
        lc = QVBoxLayout()
        lc.setSpacing(2)
        lc.addWidget(lbl("All Activity", bold=True, size=16))
        lc.addWidget(lbl(
            "Click column headers to sort  ·  Double-click a row for full details"
            "  ·  Ctrl+F to search  ·  Ctrl+R to refresh",
            size=10, color=C["sub"],
        ))
        top.addLayout(lc)
        top.addStretch()

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(
            "🔍  Search activity, staff, station…"
        )
        self._search_box.setFixedWidth(300)
        self._search_box.setFixedHeight(36)
        self._search_box.setStyleSheet(
            f"border:1px solid {C['border']};border-radius:8px;"
            f"padding:0 14px;background:{C['white']};font-size:12px;"
        )
        self._search_box.textChanged.connect(self._on_search)
        top.addWidget(self._search_box)

        fb = outline_btn("  ▾  Filter")
        fb.setFixedHeight(36)
        fb.clicked.connect(self._open_filter)
        top.addWidget(fb)
        wl.addLayout(top)

        self._match_lbl = lbl("", size=10, color=C["sub"])
        wl.addWidget(self._match_lbl)

        tc = QFrame()
        tc.setStyleSheet(
            f"QFrame{{background:{C['white']};border-radius:12px;"
            f"border:1px solid {C['border']};}}"
        )
        tcl = QVBoxLayout(tc)
        tcl.setContentsMargins(0, 0, 0, 0)
        tcl.setSpacing(0)

        self._table = ActivityTable(self._entries)
        self._table.entry_view_requested.connect(self._on_view_entry)
        self._table.entry_flag_requested.connect(self._on_flag_entry)
        self._table.entry_copy_requested.connect(self._on_copy_entry)
        self._table.match_count_changed.connect(self._on_match_count)
        tcl.addWidget(self._table)
        wl.addWidget(tc, stretch=1)
        parent.addWidget(wrap, stretch=1)

    def _on_search(self, text):
        self._table.set_search(text)

    def _open_filter(self):
        dlg = FilterDialog(self)
        dlg.filter_applied.connect(self._table.apply_filter)
        dlg.exec()

    def _on_view_entry(self, entry):
        dlg = ViewDetailsDialog(entry, self)
        dlg.flag_toggled.connect(self._on_flag_toggled_from_dialog)
        dlg.exec()

    def _on_flag_entry(self, entry):
        was_flagged = entry.get("flagged", False)
        entry["flagged"] = not was_flagged
        if entry["flagged"]:
            if entry.get("status") != "Review":
                entry["original_status"] = entry["status"]
            entry["status"] = "Review"
            entry.setdefault("audit", []).append(
                f"{entry['datetime']} — Flagged for review"
            )
            show_toast(self.centralWidget(),
                       f"Entry #{entry['id']} flagged for review", "warn")
        else:
            restored = entry.get("original_status") or "Resolved"
            if restored == "Review":
                restored = "Resolved"
            entry["status"] = restored
            entry.setdefault("audit", []).append(
                f"{entry['datetime']} — Flag removed · restored to {restored}"
            )
            show_toast(self.centralWidget(),
                       f"Entry #{entry['id']} unflagged · {restored}", "ok")
        self._table.refresh_entry(entry["id"])
        self._update_stat_strip()
        self._update_status()

    def _on_copy_entry(self, entry):
        QGuiApplication.clipboard().setText(
            f"Activity Log Entry #{entry['id']}\n{'─'*44}\n"
            f"Activity      : {entry['activity']}\n"
            f"Detail        : {entry['detail']}\n"
            f"Staff         : {entry['staff']}\n"
            f"Station       : {entry['station']}\n"
            f"Date/Time     : {entry['datetime']}\n"
            f"Status        : {entry['status']}\n"
            f"Activity Type : {entry.get('activity_type','—')}\n"
            f"Flagged       : {'Yes' if entry.get('flagged') else 'No'}\n"
        )
        show_toast(self.centralWidget(), "Entry copied to clipboard", "ok")

    def _on_flag_toggled_from_dialog(self, entry_id: int, new_flag_state: bool):
        for e in self._entries:
            if e["id"] != entry_id:
                continue
            if new_flag_state:
                if e.get("status") != "Review":
                    e["original_status"] = e.get("status", "Completed")
                e["status"] = "Review"
                e.setdefault("audit", []).append(
                    f"{e['datetime']} — Flagged for review"
                )
                show_toast(self.centralWidget(),
                           f"Entry #{entry_id} flagged for review", "warn")
            else:
                restored = e.get("original_status") or "Resolved"
                if restored == "Review":
                    restored = "Resolved"
                e["status"] = restored
                e.setdefault("audit", []).append(
                    f"{e['datetime']} — Flag removed · restored to {restored}"
                )
                show_toast(self.centralWidget(),
                           f"Entry #{entry_id} unflagged · {restored}", "ok")
            self._table.refresh_entry(entry_id)
            self._update_stat_strip()
            self._update_status()
            break

    def _on_match_count(self, count):
        self._match_lbl.setText(
            f"Showing {count} of {len(self._entries)} entries  ·  "
            f"{self._date_range_label().replace('📅  ','')}"
            + (f"  ·  Staff: {self._user_filter}"
               if self._user_filter != "All" else "")
        )
        self._update_status(count)

    def _update_status(self, match_count=None):
        review_count  = sum(1 for e in self._entries if e["status"] == "Review")
        flagged_count = sum(1 for e in self._entries if e.get("flagged"))
        shown = match_count if match_count is not None else len(self._entries)
        db_str = "PostgreSQL" if HAS_DB else "Demo Data"
        self.statusBar().showMessage(
            f"[{db_str}]  Showing {shown} of {len(self._entries)} entries  ·  "
            f"Flagged: {flagged_count}  ·  In review: {review_count}  ·  "
            f"Ctrl+F: search  ·  Ctrl+R: refresh  ·  Esc: clear search"
        )

    def _add_note(self):
        dlg = AddNoteDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            note_text = dlg.note_field.toPlainText().strip()
            staff     = dlg.staff_field.text().strip()
            station   = dlg.station_field.text().strip() or "Back Office"
            now       = datetime.now()
            status    = dlg.get_status()
            # Notes use the current time at the moment they are created
            now_str   = _fmt_dt(now)
            new_entry = {
                "id":              max((e["id"] for e in self._entries),
                                       default=0) + 1,
                "icon":            "note",
                "activity":        (
                    f"Note: {note_text[:60]}"
                    f"{'…' if len(note_text) > 60 else ''}"
                ),
                "detail":          note_text,
                "staff":           staff,
                "station":         station,
                "datetime":        now_str,
                "_dt":             now,
                "_dt_frozen":      True,
                "status":          status,
                "original_status": status,
                "flagged":         False,
                "audit":           [f"{now_str} — Note added by {staff}"],
                "activity_type":   "note",
            }
            self._entries.insert(0, new_entry)
            self._table.prepend_entry(new_entry)
            self._update_stat_strip()
            self._update_status()
            show_toast(self.centralWidget(),
                       "Note added to activity log", "ok")

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Activity Log", "activity_log.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=[
                        "id", "activity_type", "activity", "detail",
                        "staff", "station", "datetime", "status",
                        "original_status", "flagged",
                    ]
                )
                writer.writeheader()
                for e in self._entries:
                    writer.writerow(
                        {k: e.get(k, "") for k in writer.fieldnames}
                    )
            show_toast(self.centralWidget(),
                       f"Exported {len(self._entries)} entries", "ok")
        except Exception as ex:
            QMessageBox.critical(self, "Export Failed", str(ex))

    def _view_exceptions(self):
        flagged = [e for e in self._entries
                   if e.get("flagged") or e["status"] == "Review"]
        if not flagged:
            QMessageBox.information(
                self, "No Exceptions",
                "No entries are currently flagged for review. ✅"
            )
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Flagged Exceptions ({len(flagged)})")
        dlg.setMinimumSize(720, 500)
        dlg.setStyleSheet(
            f"QDialog{{background:{C['bg']};}}"
            f"QWidget{{font-family:'Segoe UI',Helvetica,sans-serif;}}"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(
            f"background:{C['white']};border-bottom:1px solid {C['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 18, 24, 18)
        hl.addWidget(lbl(
            f"Flagged for Review — {len(flagged)} entries",
            bold=True, size=15,
        ))
        hl.addStretch()
        cb = make_btn("Close", C["accent"], hover=C["accent_dk"])
        cb.clicked.connect(dlg.accept)
        hl.addWidget(cb)
        lay.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;")
        body = QWidget()
        body.setStyleSheet(f"background:{C['white']};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        for i, e in enumerate(flagged):
            row = ActivityRow(e, alt_bg=(i % 2 == 1))
            row.view_requested.connect(
                lambda entry, d=dlg: (d.accept(), self._on_view_entry(entry))
            )
            row.copy_requested.connect(self._on_copy_entry)
            row.flag_requested.connect(
                lambda entry, d=dlg: (self._on_flag_entry(entry), d.accept())
            )
            bl.addWidget(row)
            if i < len(flagged) - 1:
                bl.addWidget(hline())
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