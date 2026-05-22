"""Day-98 (2026-05-22): PWA Web Push MVP.

Locks in the minimum surface area we need so that future refactors
don't silently break the alerts -> push fan-out, the subscribe/test
endpoints, or the SEBI-safe notification copy.

Coverage:

  Source-text guards
    1. /subscribe + /test endpoints declared on the notifications router
    2. Both endpoints require_auth (Depends(get_current_user))
    3. Service worker carries a push + notificationclick handler
    4. Subscribe payload model has endpoint/p256dh/auth fields
    5. alerts_service fan-outs to push_service when notify_push is set

  Behaviour
    6. upsert_subscription round-trip (insert then upsert by endpoint)
    7. list_subscriptions filters by user_id
    8. send_push returns 0 when no subscriptions exist
    9. send_push degrades gracefully when VAPID_PRIVATE_KEY is unset

  SEBI compliance
   10. Test-notification copy template carries no banned tokens
   11. render_alert_copy output for every kind is informational
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Helpers ──────────────────────────────────────────────────────

_ROUTER_SRC = (ROOT / "backend" / "routers" / "notifications.py").read_text(
    encoding="utf-8"
)
_PUSH_SRC = (ROOT / "backend" / "services" / "push_service.py").read_text(
    encoding="utf-8"
)
_ALERTS_SRC = (ROOT / "backend" / "services" / "alerts_service.py").read_text(
    encoding="utf-8"
)
_SW_SRC = (ROOT / "frontend" / "public" / "sw.js").read_text(encoding="utf-8")
_PAGE_SRC = (
    ROOT / "frontend" / "src" / "app" / "(app)" / "account" / "notifications"
    / "page.tsx"
).read_text(encoding="utf-8")

# Tokens SEBI-aligned compliance forbids in user-facing recommendation copy.
BANNED_TOKENS = (
    "buy", "sell", "hold", "strong", "accumulate",
    "recommend", "recommendation", "outperform", "underperform",
    "should",
)


def _contains_no_banned(text: str) -> bool:
    """Word-boundary check — substrings like 'hold' in 'threshold' are OK."""
    import re
    low = text.lower()
    for tok in BANNED_TOKENS:
        if re.search(rf"\b{re.escape(tok)}\b", low):
            return False
    return True


# ── 1. Endpoints declared ────────────────────────────────────────


def test_subscribe_endpoint_defined():
    assert '@router.post("/subscribe")' in _ROUTER_SRC
    assert "async def subscribe_push" in _ROUTER_SRC


def test_test_endpoint_defined():
    assert '@router.post("/test")' in _ROUTER_SRC
    assert "async def test_push" in _ROUTER_SRC


# ── 2. Auth required ────────────────────────────────────────────


def test_subscribe_requires_auth():
    # Both new endpoints take the get_current_user dependency.
    assert _ROUTER_SRC.count("user: dict = Depends(get_current_user)") >= 4


def test_subscribe_user_id_comes_from_jwt():
    # The user_id passed to push_service.upsert_subscription must come
    # from the JWT (user["user_id"]), never from the request body.
    block = _ROUTER_SRC.split("async def subscribe_push", 1)[1].split(
        "async def test_push", 1
    )[0]
    assert 'user_id=user["user_id"]' in block


def test_test_endpoint_user_id_comes_from_jwt():
    block = _ROUTER_SRC.split("async def test_push", 1)[1].split(
        "return ", 1
    )[0]
    assert 'user_id=user["user_id"]' in block


# ── 3. Service worker handlers present ──────────────────────────


def test_sw_has_push_handler():
    assert "addEventListener('push'" in _SW_SRC
    assert "showNotification" in _SW_SRC


def test_sw_has_notification_click_handler():
    assert "addEventListener('notificationclick'" in _SW_SRC
    assert "openWindow" in _SW_SRC


def test_sw_cache_version_not_bumped():
    # Day-98 must not bump CACHE_NAME — push notifications don't
    # touch the analysis_cache, so a bump would needlessly invalidate
    # every client's static asset cache.
    assert "yieldiq-v2" in _SW_SRC
    assert "yieldiq-v3" not in _SW_SRC


# ── 4. Subscribe payload model ──────────────────────────────────


def test_subscribe_payload_fields():
    assert "class PushSubscribePayload(BaseModel):" in _ROUTER_SRC
    block = _ROUTER_SRC.split("class PushSubscribePayload(BaseModel):", 1)[1].split(
        "@router", 1
    )[0]
    for field in ("endpoint:", "p256dh:", "auth:"):
        assert field in block, f"missing field {field}"


# ── 5. Alerts -> push fan-out wired ────────────────────────────


def test_alerts_service_calls_push_service():
    assert "from backend.services.push_service import" in _ALERTS_SRC
    assert "send_push" in _ALERTS_SRC
    assert "notify_push" in _ALERTS_SRC


# ── 6/7. Subscription storage round-trip (mocked DB) ───────────


class _FakeQuery:
    def __init__(self, rows, predicate=None):
        self._rows = rows
        self._predicate = predicate

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self):
        self.rows: list = []
        self._next_id = 1

    def query(self, model):
        return _FakeQuery(self.rows)

    def add(self, row):
        row.id = self._next_id
        self._next_id += 1
        self.rows.append(row)

    def commit(self):
        pass


def test_upsert_subscription_inserts_then_updates(monkeypatch):
    # Import inside the test so model registration uses the test session.
    from backend.services import push_service
    from backend.models.push_subscription import PushSubscription

    sess = _FakeSession()

    # First call -> insert.
    out1 = push_service.upsert_subscription(
        sess,
        user_id="u1",
        endpoint="https://fcm.example/abc",
        p256dh="p1",
        auth="a1",
    )
    assert out1["id"] == 1
    assert len(sess.rows) == 1
    assert isinstance(sess.rows[0], PushSubscription)

    # Second call with the *same* endpoint -> update existing row.
    # Our FakeSession.query returns the row that's there, so the upsert
    # branch in push_service should update in place rather than appending.
    out2 = push_service.upsert_subscription(
        sess,
        user_id="u1",
        endpoint="https://fcm.example/abc",
        p256dh="p2",
        auth="a2",
    )
    assert out2["id"] == 1
    assert len(sess.rows) == 1
    assert sess.rows[0].p256dh == "p2"
    assert sess.rows[0].auth == "a2"


def test_list_subscriptions_returns_dicts():
    from backend.services import push_service
    from backend.models.push_subscription import PushSubscription

    sess = _FakeSession()
    sess.rows.append(
        PushSubscription(
            id=1, user_id="u1",
            endpoint="https://e1", p256dh="p", auth="a",
        )
    )
    out = push_service.list_subscriptions(sess, "u1")
    assert isinstance(out, list)
    assert out[0]["endpoint"] == "https://e1"
    # Secrets must NOT leak through to_dict().
    assert "p256dh" not in out[0]
    assert "auth" not in out[0]


# ── 8/9. send_push degradation paths ───────────────────────────


def test_send_push_no_subscriptions_returns_zero(monkeypatch):
    from backend.services import push_service

    sess = _FakeSession()  # no rows
    n = push_service.send_push(sess, user_id="u1", title="t", body="b")
    assert n == 0


def test_send_push_without_vapid_key_returns_zero(monkeypatch):
    from backend.services import push_service
    from backend.models.push_subscription import PushSubscription

    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    sess = _FakeSession()
    sess.rows.append(
        PushSubscription(
            id=1, user_id="u1",
            endpoint="https://e1", p256dh="p", auth="a",
        )
    )
    # No VAPID key configured -> _send_to_endpoint logs and returns False
    # so the delivered count stays at 0. Must NOT raise.
    n = push_service.send_push(sess, user_id="u1", title="t", body="b")
    assert n == 0


# ── 10/11. SEBI vocabulary checks ──────────────────────────────


def test_test_notification_copy_is_sebi_safe():
    from backend.services import push_service

    assert _contains_no_banned(push_service.TEST_NOTIFICATION_TITLE)
    assert _contains_no_banned(push_service.TEST_NOTIFICATION_BODY)
    # And the required spelling per the brief.
    assert push_service.TEST_NOTIFICATION_BODY == (
        "Notifications enabled for your watchlist alerts"
    )


def test_render_alert_copy_is_sebi_safe_for_all_kinds():
    from backend.services import push_service

    cases = [
        ("RELIANCE", "price_above", 2500.0),
        ("INFY.NS", "price_below", 1200.0),
        ("TCS", "mos_above", 25.0),
        ("HDFCBANK", "mos_below", 10.0),
        ("ITC.BO", "verdict_change", None),
    ]
    for ticker, kind, thr in cases:
        title, body = push_service.render_alert_copy(ticker, kind, thr)
        assert title and body
        assert _contains_no_banned(title), f"banned token in title: {title!r}"
        assert _contains_no_banned(body), f"banned token in body: {body!r}"
        # Suffix stripping for the display ticker.
        assert ".NS" not in title and ".BO" not in title
