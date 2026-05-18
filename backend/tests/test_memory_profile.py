"""
Tests for scripts/profile_memory_anchors.py.

Mocks psutil so we don't depend on real RSS values, and patches the
ASGI app + httpx client so we don't have to spin up the full backend
in a unit test.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "profile_memory_anchors.py"


def _load_module():
    """Load scripts/profile_memory_anchors.py without running it."""
    spec = importlib.util.spec_from_file_location("profile_memory_anchors", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["profile_memory_anchors"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def profile_mod():
    return _load_module()


class _FakeMemInfo:
    def __init__(self, rss_bytes: int) -> None:
        self.rss = rss_bytes


def _mk_process(rss_sequence_mb: list[float]) -> MagicMock:
    """Returns a MagicMock whose memory_info() returns the next value each call."""
    proc = MagicMock()
    proc.memory_info.side_effect = [
        _FakeMemInfo(int(mb * 1024 * 1024)) for mb in rss_sequence_mb
    ]
    return proc


def test_rss_mb_reads_psutil(profile_mod):
    with patch.object(profile_mod.psutil, "Process") as proc_cls:
        proc_cls.return_value = _mk_process([100.0])
        assert profile_mod._rss_mb() == pytest.approx(100.0, abs=0.01)


def test_compare_passes_when_below_baseline(profile_mod):
    measured = {"peak_rss_mb": 800}
    baseline = {"peak_rss_mb": 850, "tolerance": 1.20}
    ok, msg = profile_mod._compare(measured, baseline)
    assert ok is True
    assert "ratio=" in msg


def test_compare_passes_at_tolerance_edge(profile_mod):
    measured = {"peak_rss_mb": 1020}  # 850 * 1.20 = 1020 — exact edge
    baseline = {"peak_rss_mb": 850, "tolerance": 1.20}
    ok, _ = profile_mod._compare(measured, baseline)
    assert ok is True


def test_compare_fails_above_tolerance(profile_mod):
    measured = {"peak_rss_mb": 1100}  # > 850 * 1.20
    baseline = {"peak_rss_mb": 850, "tolerance": 1.20}
    ok, msg = profile_mod._compare(measured, baseline)
    assert ok is False
    assert "1100" in msg or "1100.0" in msg
    assert "850" in msg


def test_compare_uses_default_tolerance_when_missing(profile_mod):
    measured = {"peak_rss_mb": 1000}
    baseline = {"peak_rss_mb": 850}  # no tolerance key → defaults to 1.20
    ok, _ = profile_mod._compare(measured, baseline)
    assert ok is True  # 1000 < 1020


def test_profile_records_per_anchor_deltas(profile_mod):
    """Mock psutil + httpx so _profile() runs without a real app."""
    # 1 baseline read + (2 reads × 12 anchors) = 25 calls.
    # Anchors RSS sequence: each anchor grows by +5MB then settles.
    rss_seq = [500.0]  # baseline
    for i in range(12):
        rss_seq.append(500.0 + i * 5.0)         # before
        rss_seq.append(500.0 + i * 5.0 + 5.0)   # after (+5 delta)

    class _FakeResponse:
        status_code = 200

    class _FakeClient:
        def __init__(self, *_, **__): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def get(self, url, timeout=30.0):
            return _FakeResponse()

    with patch.object(profile_mod.psutil, "Process") as proc_cls:
        proc_cls.return_value = _mk_process(rss_seq)
        with patch("httpx.AsyncClient", _FakeClient), \
             patch("httpx.ASGITransport", lambda app: app):
            import asyncio
            result = asyncio.run(profile_mod._profile(app=object()))

    assert set(result["anchor_rss_deltas_mb"].keys()) == set(profile_mod.ANCHOR_TICKERS)
    # Every anchor saw a +5MB jump in our fake sequence.
    for ticker, delta in result["anchor_rss_deltas_mb"].items():
        assert delta == pytest.approx(5.0, abs=0.01), f"{ticker}: {delta}"
    assert result["peak_rss_mb"] == pytest.approx(500.0 + 11 * 5.0 + 5.0)
    assert result["baseline_rss_mb"] == pytest.approx(500.0)


def test_baseline_json_is_valid_and_has_required_fields():
    baseline_path = _REPO_ROOT / "scripts" / "memory_baseline.json"
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    for key in ("version", "captured_at", "peak_rss_mb", "anchor_rss_deltas_mb", "tolerance"):
        assert key in data, f"baseline missing {key}"
    assert isinstance(data["peak_rss_mb"], (int, float)) and data["peak_rss_mb"] > 0
    assert 1.0 < float(data["tolerance"]) <= 2.0
    # Anchors covered match the script's list.
    mod = _load_module()
    assert set(data["anchor_rss_deltas_mb"].keys()) == set(mod.ANCHOR_TICKERS)


def test_twelve_anchors(profile_mod):
    assert len(profile_mod.ANCHOR_TICKERS) == 12
    assert len(set(profile_mod.ANCHOR_TICKERS)) == 12  # unique
