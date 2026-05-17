"""
Unit tests for backend/services/news_filters.py.

Covers the four regressions from the audit:
  - HDFCBANK page must drop "CMS Info Systems Q4 Earnings Call"
  - PARADEEP must deprioritise GuruFocus (US aggregator) below
    any Indian Tier 1/2 source
  - TCS must drop "Newspaper Advertisement for e-voting"
  - ITC must drop "Annual Secretarial Compliance Report"
"""
from __future__ import annotations

import pytest

from backend.services.news_filters import (
    classify_topic,
    filter_and_rank,
    is_boilerplate,
    matches_ticker,
    source_tier,
)


# ── Ticker-exact filter ────────────────────────────────────────

def test_hdfcbank_rejects_cms_info_systems():
    item = {
        "headline": "CMS Info Systems Q4 Earnings Call Transcript",
        "summary": "CMS Info Systems reported Q4 results...",
        "source": "Seeking Alpha",
        "url": "https://example.com/cms",
        "published_at": "2026-05-10T10:00:00Z",
    }
    assert not matches_ticker(item, "HDFCBANK")


def test_hdfcbank_accepts_actual_hdfc_bank_news():
    item = {
        "headline": "HDFC Bank reports Q4 profit growth of 18%",
        "summary": "HDFC Bank Limited posted...",
        "source": "Moneycontrol",
        "url": "https://moneycontrol.com/news/hdfcbank-q4",
        "published_at": "2026-05-10T10:00:00Z",
    }
    assert matches_ticker(item, "HDFCBANK")


def test_paradeep_accepts_paradeep_phosphates():
    item = {
        "headline": "Paradeep Phosphates plans capacity expansion",
        "summary": "Paradeep Phosphates Limited announced...",
        "source": "BusinessLine",
        "url": "https://thehindubusinessline.com/x",
        "published_at": "2026-05-10T10:00:00Z",
    }
    assert matches_ticker(item, "PARADEEP")


def test_unrelated_item_rejected_for_paradeep():
    item = {
        "headline": "RIL announces new refinery",
        "summary": "Reliance Industries...",
        "source": "Reuters",
        "url": "https://reuters.com/x",
        "published_at": "2026-05-10T10:00:00Z",
    }
    assert not matches_ticker(item, "PARADEEP")


# ── Source tier ────────────────────────────────────────────────

def test_gurufocus_is_tier3():
    item = {"source": "GuruFocus", "url": "https://gurufocus.com/x"}
    assert source_tier(item) == 3


def test_moneycontrol_is_tier1():
    item = {"source": "Moneycontrol", "url": "https://moneycontrol.com/x"}
    assert source_tier(item) == 1


def test_reuters_is_tier1():
    assert source_tier({"source": "Reuters", "url": ""}) == 1


def test_ndtv_profit_is_tier2():
    assert source_tier({"source": "NDTV Profit", "url": ""}) == 2


def test_paradeep_prefers_indian_press_over_gurufocus():
    items = [
        {
            "headline": "Paradeep Phosphates: deep value or value trap?",
            "summary": "GuruFocus analysis of Paradeep Phosphates...",
            "source": "GuruFocus",
            "url": "https://gurufocus.com/p",
            "published_at": "2026-05-15T10:00:00Z",
        },
        {
            "headline": "Paradeep Phosphates Q4 results beat estimates",
            "summary": "Paradeep Phosphates Limited reported...",
            "source": "Moneycontrol",
            "url": "https://moneycontrol.com/p",
            "published_at": "2026-05-10T10:00:00Z",
        },
    ]
    out = filter_and_rank(items, ticker="PARADEEP")
    assert len(out) == 2
    assert out[0]["source"] == "Moneycontrol"  # Tier 1 first
    assert out[1]["source"] == "GuruFocus"     # Tier 3 last


# ── Boilerplate drop ──────────────────────────────────────────

@pytest.mark.parametrize(
    "headline",
    [
        "Newspaper Advertisement for e-voting",
        "Annual Secretarial Compliance Report",
        "Intimation under Regulation 30 of SEBI LODR",
        "Form 8-K filed with the SEC",
        "Copy of Newspaper Advertisement",
    ],
)
def test_boilerplate_dropped(headline):
    assert is_boilerplate({"headline": headline, "summary": ""})


def test_tcs_drops_evoting_newspaper_ad():
    items = [
        {
            "headline": "Newspaper Advertisement for e-voting",
            "summary": "Tata Consultancy Services Limited",
            "source": "BSE",
            "url": "https://bseindia.com/x",
            "published_at": "2026-05-16T10:00:00Z",
        },
        {
            "headline": "TCS wins $1bn deal with global retailer",
            "summary": "Tata Consultancy Services bagged the order...",
            "source": "Economic Times",
            "url": "https://economictimes.indiatimes.com/x",
            "published_at": "2026-05-15T10:00:00Z",
        },
    ]
    out = filter_and_rank(items, ticker="TCS")
    headlines = [i["headline"] for i in out]
    assert "Newspaper Advertisement for e-voting" not in headlines
    assert any("TCS wins" in h for h in headlines)


def test_itc_drops_secretarial_compliance_report():
    items = [
        {
            "headline": "Annual Secretarial Compliance Report",
            "summary": "ITC Limited submitted...",
            "source": "BSE",
            "url": "https://bseindia.com/itc-scr",
            "published_at": "2026-05-12T10:00:00Z",
        },
        {
            "headline": "ITC Q4 net profit rises 12% YoY",
            "summary": "ITC Limited reported quarterly results...",
            "source": "Livemint",
            "url": "https://livemint.com/itc-q4",
            "published_at": "2026-05-11T10:00:00Z",
        },
    ]
    out = filter_and_rank(items, ticker="ITC")
    assert all("Secretarial Compliance" not in i["headline"] for i in out)
    assert any("Q4 net profit" in i["headline"] for i in out)


# ── Topic classifier ──────────────────────────────────────────

def test_classify_earnings():
    assert classify_topic({"headline": "TCS Q4 results beat estimates", "summary": ""}) == "earnings"


def test_classify_deal():
    assert classify_topic({"headline": "HDFC Bank acquires fintech startup", "summary": ""}) == "deal"


def test_classify_governance():
    assert classify_topic({"headline": "Infosys appoints new CFO", "summary": ""}) == "governance"


def test_classify_analyst_update():
    assert classify_topic({"headline": "Brokerage upgrades Reliance to Buy, target Rs 3200", "summary": ""}) == "analyst-update"


def test_classify_general_fallthrough():
    assert classify_topic({"headline": "Markets edge higher", "summary": ""}) == "general"
