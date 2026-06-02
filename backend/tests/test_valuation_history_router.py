# backend/tests/test_valuation_history_router.py
# ═══════════════════════════════════════════════════════════════
# Phase 1 — Fair-Value History router contract tests (Agent D).
#
# Pins the empty-shape contract that Agent B's stub returns so
# Agent A's real query is forced to preserve it. Also pins the
# Provenance / AnnotationConfidence literal unions and the named
# threshold constant — three places where a future drive-by edit
# would silently break the wire format.
#
# All copy in this module is verified SEBI-clean (no banned vocab
# in docstrings, comments, or assertion messages).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


class TestValuationHistoryRouter:
    def test_empty_shape_for_unknown_ticker(self):
        """Stub guarantees an empty-but-valid shape, never a 404 or 500.

        Agent A's real query must preserve this contract.
        """
        r = client.get("/api/valuation-history/UNKNOWN_TICKER_XYZ")
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "UNKNOWN_TICKER_XYZ"
        assert body["points"] == []
        assert body["annotations"] == []
        assert body["starts_at"] is None
        assert body["points_count"] == 0
        assert body["is_sparse"] is True

    def test_ticker_normalized_uppercase(self):
        r = client.get("/api/valuation-history/tcs")
        assert r.status_code == 200
        assert r.json()["ticker"] == "TCS"

    def test_response_validates_against_pydantic_model(self):
        from backend.models.fair_value_history import FairValueHistoryResponse

        r = client.get("/api/valuation-history/TCS")
        # Will raise ValidationError if shape drifts.
        FairValueHistoryResponse(**r.json())

    def test_known_provenance_values(self):
        """Provenance literal union is the discriminator for series origin.

        Any future addition must update the Provenance Literal AND the
        backfill script's allowed-list.
        """
        from backend.models.fair_value_history import Provenance

        assert set(get_args(Provenance)) == {"snapshot", "golden", "live"}

    def test_known_confidence_values(self):
        from backend.models.fair_value_history import AnnotationConfidence

        assert set(get_args(AnnotationConfidence)) == {
            "high",
            "inferred",
            "data_refresh",
        }

    def test_annotation_threshold_named_constant(self):
        """Threshold MUST be a named constant. Inline magic numbers in the
        annotation logic are a regression.
        """
        from backend.services.analysis.constants import (
            FV_ANNOTATION_THRESHOLD_PCT,
        )

        assert FV_ANNOTATION_THRESHOLD_PCT == 2.0
        assert isinstance(FV_ANNOTATION_THRESHOLD_PCT, (int, float))

    def test_annotation_cause_labels_are_sebi_clean(self):
        """All hardcoded cause_label string literals in the annotation
        logic must pass the SEBI vocabulary lint.

        Manifest rationale strings inherit SEBI compliance from the
        cache invalidation work; this test pins the new hardcoded
        labels emitted by the valuation-history pipeline.
        """
        banned = [
            "should",
            "appears",
            "strong",
            "weak",
            "cheap",
            "poor",
            "buy",
            "sell",
            "hold",
            "recommend",
            "target",
            "expensive",
        ]
        repo_root = Path(__file__).resolve().parent.parent.parent
        paths = [
            repo_root / "backend" / "routers" / "valuation_history.py",
            # Agent A may add a helper module — extend this list when known.
            repo_root
            / "backend"
            / "services"
            / "analysis"
            / "valuation_history_service.py",
        ]
        for p in paths:
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8")
            # Word-boundary literal-in-quotes scan. Comments are
            # caught separately by scripts/check_sebi_words.py; this
            # test is the runtime-string subset.
            for word in banned:
                pattern = rf'["\']([^"\']*\b{word}\b[^"\']*)["\']'
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    pytest.fail(
                        f"Banned word '{word}' in quoted string at {p}: "
                        f"{m.group(1)}"
                    )
