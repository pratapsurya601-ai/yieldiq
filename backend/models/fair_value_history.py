# backend/models/fair_value_history.py
# ═══════════════════════════════════════════════════════════════
# Phase 1 — Fair-Value History contract (Agent B / contract-first).
#
# Pydantic response models for the new
# ``GET /api/valuation-history/{ticker}`` endpoint. The shapes here
# are the locked interface that Agent A (data layer) will populate
# and Agent C (chart UI) will consume. Treat as frozen — coordinate
# any change with both before editing.
#
# Design decisions (see .audit/design-synthesis-2026-05-27.md
# "Phase 1 — FV History contract" for the long form):
#
#   1. Provenance tag on every point ("snapshot" / "golden" / "live").
#      Series is production-faithful only — every row is the FV a
#      user would have seen on that date, computed by the engine
#      version that was live then.
#
#   2. Annotations are driven by the FV series itself, not by the
#      cache-invalidation manifest. A wildcard manifest entry that
#      did not materially move this ticker emits no annotation. A
#      real input refresh (financials, price recalibration) that
#      DID move FV emits an annotation even with no manifest entry.
#
#   3. Material-move threshold lives in a single named constant
#      (``FV_ANNOTATION_THRESHOLD_PCT`` in
#      backend/services/analysis/constants.py).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from datetime import date as Date
from typing import Literal, Optional

from pydantic import BaseModel, Field


Provenance = Literal["snapshot", "golden", "live"]
AnnotationConfidence = Literal["high", "inferred", "data_refresh"]


class FairValueHistoryPoint(BaseModel):
    """One row of FV history for a ticker.

    Production-faithful only. Each row is the FV a user would have seen
    on this date, computed by the engine version live at the time.
    """

    date: Date
    fair_value: float = Field(..., description="₹ per share, base-case scenario")
    bear_iv: Optional[float] = None
    bull_iv: Optional[float] = None
    scenario_weights: Optional[dict] = Field(
        None,
        description="Triplet {bear, base, bull} used to compute this point. "
                    "Null for points where the engine version did not record them.",
    )
    model_version: str = Field(
        ...,
        description="Engine version slug (e.g. 'v_phase_c2_2026_05_25') at the "
                    "time this FV was computed.",
    )
    provenance: Provenance = Field(
        ...,
        description="'snapshot' = scripts/snapshots/*.json. 'golden' = "
                    "scripts/dcf_golden.json. 'live' = written by recompute hook.",
    )
    manifest_id: Optional[str] = Field(
        None,
        description="version_id of the manifest entry that caused this row "
                    "to be written (null for non-manifest writes).",
    )


class FairValueAnnotation(BaseModel):
    """A material FV move worth showing on the chart.

    Driven by the FV series itself, NOT by the manifest. A wildcard
    manifest entry that did not materially move this ticker produces no
    annotation. A real input refresh (new financials, price recalibration)
    that DID move FV produces an annotation even with no manifest entry.
    """

    date: Date
    fv_delta_pct: float = Field(
        ...,
        description="(this_fv - prev_fv) / prev_fv * 100. Sign preserved. "
                    "Only emitted when |delta| >= FV_ANNOTATION_THRESHOLD_PCT.",
    )
    manifest_id: Optional[str] = Field(
        None,
        description="Linked manifest version_id when the cause is attributable.",
    )
    cause_label: str = Field(
        ...,
        description="Short neutral noun phrase. Examples below. SEBI-clean.",
    )
    confidence: AnnotationConfidence = Field(
        ...,
        description="'high' = explicit-ticker manifest entry on this date. "
                    "'inferred' = wildcard manifest entry whose fields overlap "
                    "this ticker's FV inputs. 'data_refresh' = no manifest "
                    "entry; cause is upstream financials or price refresh.",
    )


class FairValueHistoryResponse(BaseModel):
    """Composite payload for /api/valuation-history/{ticker}."""

    ticker: str
    points: list[FairValueHistoryPoint] = Field(default_factory=list)
    annotations: list[FairValueAnnotation] = Field(default_factory=list)
    starts_at: Optional[Date] = Field(
        None,
        description="Date of earliest point. null if series is empty. "
                    "Use to render 'Fair value history starts <date>' caption.",
    )
    points_count: int = 0
    is_sparse: bool = Field(
        False,
        description="True when the series has < 3 points. UI renders a "
                    "single-marker variant rather than a line.",
    )
