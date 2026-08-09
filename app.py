"""
staff_analytics.py — Read-only analytics view for the AquaAssist Staff Portal.

Purely additive: built entirely from data already in reports_df (no new
dependencies, no external services, no changes to how reports are saved).
Safe to drop into the Staff Portal without touching customer-facing code.

INTEGRATION (in app.py, inside the Staff Portal section, right after the
status_count_cols metrics block and before the "Reports map" section):

    from staff_analytics import render_staff_analytics
    ...
    render_staff_analytics(reports_df, GRENADA_PARISHES)
"""

import streamlit as st


def _extract_parish(location_text, parishes):
    """Best-effort match of a known parish name inside the free-text
    location field. Returns None if nothing recognizable is found —
    the caller decides what to do with sparse results."""
    if not isinstance(location_text, str) or not location_text:
        return None
    for parish in parishes:
        # "St. George's (Capital area)" -> "St. George's" ; "St. Andrew's" -> "St. Andrew's"
        short_name = parish.split(" (")[0].strip()
        if short_name and short_name in location_text:
            return parish
    return None


def render_staff_analytics(reports_df, parishes):
    """Renders a small analytics section: reports by issue type, reports by
    parish (if enough location data is recognizable), and average
    resolution time (only if a `resolved_at` column exists and is
    populated — this is optional and the view degrades gracefully
    without it)."""
    if reports_df is None or reports_df.empty:
        return

    st.markdown('<div class="aqua-section-label">📊 Analytics</div>', unsafe_allow_html=True)

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.caption("Reports by issue type")
        if "issue_type" in reports_df.columns:
            issue_counts = reports_df["issue_type"].value_counts()
            if not issue_counts.empty:
                st.bar_chart(issue_counts)
            else:
                st.caption("No issue type data yet.")

    with chart_col2:
        st.caption("Reports by parish")
        if "location" in reports_df.columns:
            parish_series = reports_df["location"].apply(lambda loc: _extract_parish(loc, parishes)).dropna()
            if len(parish_series) >= 3:
                st.bar_chart(parish_series.value_counts())
            else:
                st.caption("Not enough recognizable parish data yet to chart.")

    if "resolved_at" in reports_df.columns:
        try:
            import pandas as pd
            resolved = reports_df[
                (reports_df["status"] == "Resolved")
                & (reports_df["resolved_at"].astype(str).str.strip() != "")
            ]
            if not resolved.empty:
                durations = pd.to_datetime(resolved["resolved_at"]) - pd.to_datetime(resolved["timestamp"])
                avg_hours = durations.mean().total_seconds() / 3600
                st.metric(
                    "Avg. time to resolve", f"{avg_hours:.1f} hrs",
                    help=f"Based on {len(resolved)} resolved report(s) with a recorded resolution time.",
                )
        except Exception:
            pass
    else:
        st.caption(
            "💡 Track a `resolved_at` timestamp when a report is marked Resolved "
            "to unlock an average resolution time metric here."
        )
