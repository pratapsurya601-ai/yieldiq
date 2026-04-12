# dashboard/ui/components/conviction_ring.py
# ═══════════════════════════════════════════════════════════════
# Animated SVG conviction ring — YieldIQ Score + Confidence
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st
import math


def render_conviction_ring(
    yieldiq_score: int,
    confidence_score: int,
    size: int = 120,
) -> None:
    """Renders animated SVG conviction ring."""
    score = max(0, min(100, yieldiq_score))
    conf = max(0, min(100, confidence_score))

    # Grade logic
    if score >= 85:
        grade, grade_color, grade_bg = "A", "#059669", "#ECFDF5"
    elif score >= 70:
        grade, grade_color, grade_bg = "B", "#1D4ED8", "#EFF6FF"
    elif score >= 55:
        grade, grade_color, grade_bg = "C", "#D97706", "#FFFBEB"
    elif score >= 40:
        grade, grade_color, grade_bg = "D", "#EA580C", "#FFF7ED"
    else:
        grade, grade_color, grade_bg = "F", "#DC2626", "#FEF2F2"

    # Confidence label
    if conf >= 75:
        conf_label, conf_color = "High confidence", "#059669"
    elif conf >= 50:
        conf_label, conf_color = "Medium confidence", "#D97706"
    else:
        conf_label, conf_color = "Low confidence", "#DC2626"

    # SVG geometry
    cx, cy = size // 2, size // 2
    r_outer = size // 2 - 8
    r_inner = size // 2 - 18
    circumference_outer = 2 * math.pi * r_outer
    circumference_inner = 2 * math.pi * r_inner
    dash_outer = circumference_outer * (score / 100)
    dash_inner = circumference_inner * (conf / 100)

    st.html(f"""
    <div style="text-align:center;margin-bottom:8px;">
      <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
        <!-- Background rings -->
        <circle cx="{cx}" cy="{cy}" r="{r_outer}"
                fill="none" stroke="#E2E8F0" stroke-width="6"/>
        <circle cx="{cx}" cy="{cy}" r="{r_inner}"
                fill="none" stroke="#F1F5F9" stroke-width="4"/>

        <!-- Score ring (outer) -->
        <circle cx="{cx}" cy="{cy}" r="{r_outer}"
                fill="none" stroke="{grade_color}" stroke-width="6"
                stroke-linecap="round"
                stroke-dasharray="{dash_outer} {circumference_outer}"
                transform="rotate(-90 {cx} {cy})"
                style="transition: stroke-dasharray 0.8s ease-out;"/>

        <!-- Confidence ring (inner) -->
        <circle cx="{cx}" cy="{cy}" r="{r_inner}"
                fill="none" stroke="{conf_color}" stroke-width="4"
                stroke-linecap="round" opacity="0.5"
                stroke-dasharray="{dash_inner} {circumference_inner}"
                transform="rotate(-90 {cx} {cy})"
                style="transition: stroke-dasharray 0.8s ease-out;"/>

        <!-- Centre text -->
        <text x="{cx}" y="{cy - 6}" text-anchor="middle"
              font-size="28" font-weight="900" fill="{grade_color}"
              font-family="IBM Plex Mono, monospace">{score}</text>
        <text x="{cx}" y="{cy + 14}" text-anchor="middle"
              font-size="14" font-weight="700" fill="{grade_color}"
              font-family="Inter, sans-serif">{grade}</text>
      </svg>

      <!-- Confidence label -->
      <div style="font-size:10px;color:{conf_color};font-weight:600;
                  margin-top:2px;">{conf_label} · {conf}/100</div>
    </div>
    """)
