# dashboard/utils/notifications.py
# ═══════════════════════════════════════════════════════════════
# In-app notification system for YieldIQ
# Generates contextual, outcome-focused notifications.
# Stored in session state (future: database persistence).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
import uuid

NotificationType = Literal[
    "mos_drift",
    "red_flag_new",
    "earnings_coming",
    "fair_value_hit",
    "yieldiq50_change",
    "portfolio_health",
    "conviction_drop",
    "top_pick_change",
]


@dataclass
class Notification:
    id: str
    type: NotificationType
    ticker: str | None
    title: str
    body: str
    created_at: datetime
    read: bool = False
    action_label: str | None = None
    action_tab: str | None = None


# ═══════════════════════════════════════════════════════════════
# NOTIFICATION GENERATORS
# ═══════════════════════════════════════════════════════════════

def notify_mos_drift(ticker: str, old_mos: float, new_mos: float,
                     fair_value_changed: bool) -> Notification:
    """MoS changed by > 5 percentage points."""
    _display = ticker.replace(".NS", "").replace(".BO", "")
    _direction = "improved" if new_mos > old_mos else "dropped"

    if fair_value_changed:
        _reason = "Our model revised its fair value estimate after new data."
    else:
        _reason = "Fair value unchanged — the stock price moved."

    return Notification(
        id=_make_id(),
        type="mos_drift",
        ticker=ticker,
        title=f"{_display} margin of safety {_direction}",
        body=(
            f"{_display}'s margin of safety {_direction} from {old_mos:+.0f}% to {new_mos:+.0f}% "
            f"this week. {_reason}"
        ),
        created_at=datetime.now(),
        action_label=f"Review {_display}",
        action_tab="stock",
    )


def notify_red_flag(ticker: str, new_flags: list[str],
                    total_flags: int) -> Notification:
    """New red flag detected on held/watched stock."""
    _display = ticker.replace(".NS", "").replace(".BO", "")
    _flag_text = new_flags[0] if new_flags else "potential risk detected"

    return Notification(
        id=_make_id(),
        type="red_flag_new",
        ticker=ticker,
        title=f"New red flag on {_display}",
        body=(
            f"New red flag on {_display}: {_flag_text}. "
            f"Now {total_flags} total flag{'s' if total_flags != 1 else ''}. "
            f"Worth reviewing your position."
        ),
        created_at=datetime.now(),
        action_label=f"Review {_display}",
        action_tab="stock",
    )


def notify_earnings_coming(ticker: str, company_name: str, days_until: int,
                           earnings_date: str, est_eps: float | None,
                           model_bullish: bool) -> Notification:
    """Triggered 7 days and 2 days before earnings."""
    _display = ticker.replace(".NS", "").replace(".BO", "")
    _eps_text = f"Analyst consensus: {est_eps:.2f} EPS. " if est_eps else ""
    _model_text = (
        "YieldIQ model is more bullish — expects stronger FCF."
        if model_bullish
        else "YieldIQ model is cautious — watch for downside surprise."
    )

    return Notification(
        id=_make_id(),
        type="earnings_coming",
        ticker=ticker,
        title=f"{_display} reports in {days_until} day{'s' if days_until != 1 else ''}",
        body=(
            f"{company_name or _display} reports in {days_until} day{'s' if days_until != 1 else ''} "
            f"({earnings_date}). {_eps_text}{_model_text}"
        ),
        created_at=datetime.now(),
        action_label=f"Review {_display}",
        action_tab="stock",
    )


def notify_fair_value_hit(ticker: str,
                          direction: Literal["crossed_above", "crossed_below"],
                          price: float, fair_value: float) -> Notification:
    """Price crossed fair value."""
    _display = ticker.replace(".NS", "").replace(".BO", "")

    if direction == "crossed_above":
        _title = f"{_display} crossed above fair value"
        _mos = ((fair_value - price) / fair_value) * 100
        _body = (
            f"{_display} just crossed above our fair value estimate of {fair_value:,.0f}. "
            f"The stock is now fairly valued by our model."
        )
    else:
        _mos = ((fair_value - price) / fair_value) * 100
        _title = f"{_display} dropped below fair value"
        _body = (
            f"{_display} dropped below our fair value of {fair_value:,.0f}. "
            f"At {price:,.0f}, the model now shows a {_mos:.0f}% margin of safety."
        )

    return Notification(
        id=_make_id(),
        type="fair_value_hit",
        ticker=ticker,
        title=_title,
        body=_body,
        created_at=datetime.now(),
        action_label=f"Analyse {_display}",
        action_tab="stock",
    )


def notify_yieldiq50_change(added: list[str], removed: list[str]) -> Notification:
    """YieldIQ 50 rebalanced."""
    _added_text = ", ".join(t.replace(".NS", "").replace(".BO", "") for t in added[:3])
    _removed_text = ", ".join(t.replace(".NS", "").replace(".BO", "") for t in removed[:3])

    _parts = []
    if added:
        _parts.append(f"Added: {_added_text}" + (f" +{len(added)-3} more" if len(added) > 3 else ""))
    if removed:
        _parts.append(f"Removed: {_removed_text}" + (f" +{len(removed)-3} more" if len(removed) > 3 else ""))

    return Notification(
        id=_make_id(),
        type="yieldiq50_change",
        ticker=None,
        title="YieldIQ 50 rebalanced",
        body=" · ".join(_parts) if _parts else "Weekly rebalance complete — no changes this week.",
        created_at=datetime.now(),
        action_label="View YieldIQ 50",
        action_tab="yieldiq50",
    )


def notify_portfolio_health(score: int, grade: str,
                            issues: list[str]) -> Notification:
    """Weekly portfolio health update."""
    _issues_text = ". ".join(issues[:2]) if issues else "No issues found."

    return Notification(
        id=_make_id(),
        type="portfolio_health",
        ticker=None,
        title=f"Portfolio health: {score}/100 ({grade})",
        body=f"Your portfolio health this week: {score}/100 ({grade}). {_issues_text}",
        created_at=datetime.now(),
        action_label="View portfolio",
        action_tab="portfolio",
    )


def notify_conviction_drop(ticker: str, old_confidence: int,
                           new_confidence: int, reason: str) -> Notification:
    """Confidence dropped by > 15 points."""
    _display = ticker.replace(".NS", "").replace(".BO", "")

    return Notification(
        id=_make_id(),
        type="conviction_drop",
        ticker=ticker,
        title=f"Confidence in {_display} dropped",
        body=(
            f"Confidence in our {_display} analysis dropped from {old_confidence} to {new_confidence}. "
            f"Reason: {reason}. Fair value estimate updated."
        ),
        created_at=datetime.now(),
        action_label=f"Review {_display}",
        action_tab="stock",
    )


def notify_top_pick_change(old_ticker: str, new_ticker: str,
                           new_score: int, new_mos: float) -> Notification:
    """Today's top pick changed."""
    _old = old_ticker.replace(".NS", "").replace(".BO", "")
    _new = new_ticker.replace(".NS", "").replace(".BO", "")

    return Notification(
        id=_make_id(),
        type="top_pick_change",
        ticker=new_ticker,
        title=f"New top pick: {_new}",
        body=(
            f"Today's top pick changed from {_old} to {_new}. "
            f"Score: {new_score}, MoS: {new_mos:+.0f}%. Worth a look."
        ),
        created_at=datetime.now(),
        action_label=f"Analyse {_new}",
        action_tab="stock",
    )


# ═══════════════════════════════════════════════════════════════
# NOTIFICATION STORE
# ═══════════════════════════════════════════════════════════════

class NotificationStore:
    """
    Session-state-backed notification store.
    Future: replace with Supabase persistence.
    """
    _KEY = "_yiq_notifications"

    def _get_list(self) -> list[Notification]:
        import streamlit as st
        if self._KEY not in st.session_state:
            st.session_state[self._KEY] = []
        return st.session_state[self._KEY]

    def add(self, notification: Notification) -> None:
        _notifications = self._get_list()
        # Deduplicate by type+ticker within last hour
        _dominated = False
        for n in _notifications:
            if (n.type == notification.type
                    and n.ticker == notification.ticker
                    and (notification.created_at - n.created_at).total_seconds() < 3600):
                _dominated = True
                break
        if not _dominated:
            _notifications.insert(0, notification)
            # Keep max 50
            if len(_notifications) > 50:
                _notifications[:] = _notifications[:50]

    def get_unread(self) -> list[Notification]:
        return [n for n in self._get_list() if not n.read]

    def mark_read(self, notification_id: str) -> None:
        for n in self._get_list():
            if n.id == notification_id:
                n.read = True
                break

    def mark_all_read(self) -> None:
        for n in self._get_list():
            n.read = True

    def get_all(self, limit: int = 20) -> list[Notification]:
        return self._get_list()[:limit]

    def unread_count(self) -> int:
        return len(self.get_unread())


def _make_id() -> str:
    return uuid.uuid4().hex[:12]


def render_notification_dropdown() -> None:
    """Render notification bell + dropdown in navbar area."""
    import streamlit as st

    store = NotificationStore()
    _count = store.unread_count()

    # Toggle state
    _open_key = "_notif_dropdown_open"
    if _open_key not in st.session_state:
        st.session_state[_open_key] = False

    # Bell button with badge
    _badge = f' ({_count})' if _count > 0 else ''
    _bell_label = f"Notifications{_badge}"

    if st.button(_bell_label, key="_notif_bell", use_container_width=True):
        st.session_state[_open_key] = not st.session_state[_open_key]

    # Dropdown
    if st.session_state[_open_key]:
        _notifications = store.get_all(limit=5)
        if not _notifications:
            st.html("""
            <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
                        padding:16px;text-align:center;margin-top:4px;">
              <div style="font-size:12px;color:#94A3B8;">No notifications yet</div>
            </div>
            """)
        else:
            for n in _notifications:
                _bg = "#F8FAFC" if n.read else "#EFF6FF"
                _dot = "" if n.read else '<span style="display:inline-block;width:6px;height:6px;background:#DC2626;border-radius:50%;margin-right:6px;"></span>'
                _time_ago = _format_time_ago(n.created_at)
                st.html(f"""
                <div style="background:{_bg};border:1px solid #E2E8F0;border-radius:8px;
                            padding:10px 12px;margin-top:4px;">
                  <div style="font-size:12px;font-weight:600;color:#0F172A;margin-bottom:2px;">
                    {_dot}{n.title}</div>
                  <div style="font-size:11px;color:#64748B;line-height:1.5;
                              display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
                              overflow:hidden;">{n.body}</div>
                  <div style="font-size:9px;color:#94A3B8;margin-top:4px;">{_time_ago}</div>
                </div>
                """)

            # Actions
            _ac1, _ac2 = st.columns(2)
            with _ac1:
                if _count > 0 and st.button("Mark all read", key="_notif_read_all"):
                    store.mark_all_read()
                    st.rerun()
            with _ac2:
                if st.button("View all", key="_notif_view_all"):
                    st.session_state.active_tab = "Account"
                    st.session_state[_open_key] = False
                    st.rerun()


def _format_time_ago(dt: datetime) -> str:
    _diff = (datetime.now() - dt).total_seconds()
    if _diff < 60:
        return "just now"
    elif _diff < 3600:
        return f"{int(_diff // 60)}m ago"
    elif _diff < 86400:
        return f"{int(_diff // 3600)}h ago"
    else:
        return f"{int(_diff // 86400)}d ago"
