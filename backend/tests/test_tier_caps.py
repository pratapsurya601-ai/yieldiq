"""Tests for the tier-cap single-source-of-truth helper.

Pricing-page text MUST match these numbers. If a cap changes, update
both `frontend/src/app/(marketing)/pricing/page.tsx` AND this file.
"""
from __future__ import annotations

import pytest

from backend.services.tier_caps import cap_for


class TestBrokerAccountCaps:
    def test_free_tier_cap(self):
        assert cap_for("free", "broker_accounts") == 1

    def test_analyst_tier_cap(self):
        assert cap_for("analyst", "broker_accounts") == 5

    def test_pro_tier_cap(self):
        assert cap_for("pro", "broker_accounts") == 10

    def test_unknown_tier_falls_back_to_free(self):
        # Safe-fallback: unknown tier gets the most restrictive cap.
        assert cap_for("unknown_tier", "broker_accounts") == 1

    def test_empty_tier_falls_back_to_free(self):
        assert cap_for("", "broker_accounts") == 1


class TestCompareTickerCaps:
    def test_free_tier_cap(self):
        assert cap_for("free", "compare_tickers") == 2

    def test_analyst_tier_cap(self):
        assert cap_for("analyst", "compare_tickers") == 3

    def test_pro_tier_cap(self):
        assert cap_for("pro", "compare_tickers") == 5

    def test_unknown_tier_falls_back_to_free(self):
        assert cap_for("unknown_tier", "compare_tickers") == 2


class TestUnknownFeature:
    def test_unknown_feature_raises(self):
        with pytest.raises(ValueError, match="Unknown tier-cap feature"):
            cap_for("free", "made_up_feature")

    def test_unknown_feature_raises_even_for_pro(self):
        with pytest.raises(ValueError):
            cap_for("pro", "api_calls_per_day")
