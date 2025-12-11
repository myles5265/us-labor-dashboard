"""
app.py

Streamlit dashboard for the US Labor Statistics project.

One key requirement: there is a single time-series chart, and every series can
be selected or deselected for plotting over time. No small-multiple grids.

Design principle:
- The dashboard does NOT call the BLS API at runtime.
- A separate script (src/update_data.py), usually run by GitHub Actions,
  updates data/bls_monthly.csv in the repository.
- This app reads that CSV, applies simple transformations, and plots it.

This version adds:
- Legend labels that include units and reflect the chosen view mode.
- Dynamic chart titles based on which series are selected.
- Clearer labeling and captions for MoM and YoY transformations.
"""

from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from src.config import SERIES_META

# ---------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "bls_monthly.csv"
BUILD_INFO_PATH = ROOT / "data" / "build_info.json"


# ---------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------
@st.cache_data
def load_data() -> pd.DataFrame:
    """Load the stored dataset (wide format: date + one column per series_id)."""
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


@st.cache_data
def load_build_info() -> dict:
    """Load metadata produced by the updater script, if available."""
    if BUILD_INFO_PATH.exists():
        return json.loads(BUILD_INFO_PATH.read_text())
    return {}


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
def apply_view_mode(wide: pd.DataFrame, view_mode: str) -> pd.DataFrame:
    """
    Apply the chosen transformation to a wide DataFrame indexed by date.

    view_mode options:
      - "Levels": raw series values
      - "Indexed (100 at start)": first non-missing value in range is scaled to 100
      - "MoM change": current value minus previous month
      - "YoY % change": percent change vs same month one year earlier
    """
    if view_mode == "Levels":
        return wide

    if view_mode == "Indexed (100 at start)":
        def _index(s: pd.Series) -> pd.Series:
            s_nonmissing = s.dropna()
            if s_nonmissing.empty:
                return s
            return (s / s_nonmissing.iloc[0]) * 100

        return wide.apply(_index)

    if view_mode == "MoM change":
        return wide.diff()

    if view_mode == "YoY % change":
        return wide.pct_change(12) * 100

    raise ValueError(f"Unknown view_mode: {view_mode}")


def compute_latest_metrics(df: pd.DataFrame, series_id: str) -> dict:
    """
    Compute latest value, MoM change, and YoY change (differences, not %).

    Returns dict with keys:
      latest, mom, yoy, latest_date
    """
    s = df[["date", series_id]].dropna().set_index("date")[series_id].sort_index()

    if s.empty:
        return {"latest": np.nan, "mom": np.nan, "yoy": np.nan, "latest_date": None}

    latest = float(s.iloc[-1])
    latest_date = s.index[-1]
    mom = float(s.iloc[-1] - s.iloc[-2]) if len(s) >= 2 else np.nan
    yoy = float(s.iloc[-1] - s.iloc[-13]) if len(s) >= 13 else np.nan

    return {"latest": latest, "mom": mom, "yoy": yoy, "latest_date": latest_date}


def fmt_series_label(series_id: str) -> str:
    """Label used in the sidebar multiselect (name + series ID)."""
    meta = SERIES_META.get(series_id, {})
    return f"{meta.get('name', series_id)} ({series_id})"


def build_series_label(series_id: str, view_mode: str) -> str:
    """
    Legend label for the chart, including units and transformation.

    Examples:
      Levels:   "Unemployment rate (U-3) (Percent)"
      Indexed:  "Unemployment rate (U-3) (index, 100 = start)"
      MoM:      "Unemployment rate (U-3) (MoM change, percentage points)"
      YoY %:    "Unemployment rate (U-3) (YoY % change)"
    """
    meta = SERIES_META[series_id]
    name = meta["name"]
    unit = meta["unit"]
    base = f"{name} ({unit})"

    if view_mode == "Levels":
        return base
    if view_mode == "Indexed (100 at start)":
        return f"{name} (index, 100 = start)"
    if view_mode == "MoM change":
        if meta["type"] == "rate":
            return f"{name} (MoM change, percentage points)"
        return f"{name} (MoM change)"
    if view_mode == "YoY % change":
        return f"{name} (YoY % change)"

    return base


# ---------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------
st.set_page_config(page_title="US Labor Statistics Dashboard (BLS)", layout="wide")
st.title("US Labor Statistics Dashboard (BLS)")

# Ensure the dataset exists.
if not DATA_PATH.exists():
    st.error(
        "Missing data/bls_monthly.csv.\n\n"
        "Run the updater script once:\n"
        "  python -m src.update_data"
    )
    st.stop()

df = load_data()
build_info = load_build_info()

series_ids = list(SERIES_META.keys())

# Remember selected series between interactions; default to all series.
if "selected_series" not in st.session_state:
    st.session_state.selected_series = series_ids.copy()

latest_month = df["date"].max().date()
generated_at = build_info.get("generated_at_utc", "Unknown")
st.caption(f"Latest month in dataset: **{latest_month}** • Data build time (UTC): **{generated_at}**")

# ---------------------------------------------------------------------
# Headline metrics (required: payrolls + unemployment rate)
# ---------------------------------------------------------------------
st.subheader("Latest headline indicators")
payroll = compute_latest_metrics(df, "CES0000000001")
u3 = compute_latest_metrics(df, "LNS14000000")

st.metric(
    "Total nonfarm payroll employment (thousands)",
    f"{payroll['latest']:,.0f}" if pd.notna(payroll["latest"]) else "NA",
    f"{payroll['mom']:+,.0f} MoM" if pd.notna(payroll["mom"]) else None,
)
st.metric(
    "Unemployment rate (U-3)",
    f"{u3['latest']:.1f}%" if pd.notna(u3["latest"]) else "NA",
    f"{u3['mom']:+.1f} pp MoM" if pd.notna(u3["mom"]) else None,
)

st.divider()

# ---------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------
with st.sidebar:
    st.header("Chart controls")

    if st.button("Select all series"):
        st.session_state.selected_series = series_ids.copy()

    if st.button("Clear selection"):
        st.session_state.selected_series = []

    selected = st.multiselect(
        "Select series to plot",
        options=series_ids,
        format_func=fmt_series_label,
        key="selected_series",
        help="Select one or many series. You can deselect any series to hide it from the chart.",
    )

    view_mode = st.radio(
        "View mode",
        ["Levels", "Indexed (100 at start)", "MoM change", "YoY % change"],
        index=1,  # Indexed is a nice default when mixing units
        help="Use Indexed if you plot series with different units (%, dollars, thousands, hours).",
    )

    min_d = df["date"].min().date()
    max_d = df["date"].max().date()
    date_input = st.date_input(
        "Date range",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d,
    )

    if isinstance(date_input, tuple) and len(date_input) == 2:
        start_d, end_d = date_input
    else:
        start_d, end_d = min_d, max_d

    show_table = st.checkbox("Show latest-values table", value=True)
    show_download = st.checkbox("Enable CSV download", value=True)

# If the user cleared everything, guide them.
if not selected:
    st.info("Select one or more series in the sidebar (or click 'Select all series').")
    st.stop()

# ---------------------------------------------------------------------
# Filter to date range and apply view mode
# ---------------------------------------------------------------------
mask = (df["date"].dt.date >= start_d) & (df["date"].dt.date <= end_d)
df_f = df.loc[mask].copy()

wide = df_f[["date"] + selected].set_index("date").sort_index()
wide_view = apply_view_mode(wide, view_mode)

# Long format for Altair
df_long = (
    wide_view.reset_index()
    .melt("date", var_name="series_id", value_name="value")
    .dropna()
)
df_long["unit"] = df_long["series_id"].map(lambda sid: SERIES_META[sid]["unit"])
df_long["series_label"] = df_long["series_id"].map(
    lambda sid: build_series_label(sid, view_mode)
)

# Warning if plotting mixed units in Levels
if view_mode == "Levels":
    units = {SERIES_META[sid]["unit"] for sid in selected}
    if len(units) > 1:
        st.warning(
            "You selected series with different units on a single y-axis. "
            "To see all series clearly on one chart, switch to **Indexed (100 at start)** "
            "or plot fewer series with the same unit."
        )

# Y-axis label depends on view mode and selection
if view_mode == "Levels":
    if len(selected) == 1:
        y_title = SERIES_META[selected[0]]["unit"]
    else:
        y_title = "Value (units differ; see legend)"
elif view_mode == "Indexed (100 at start)":
    y_title = "Index (100 = first value in selected range)"
elif view_mode == "MoM change":
    y_title = "Change vs previous month"
elif view_mode == "YoY % change":
    y_title = "Percent change vs same month a year ago"
else:
    y_title = "Value"

# Chart title depends on how many series and view mode
if len(selected) == 1:
    meta_single = SERIES_META[selected[0]]
    if view_mode == "Levels":
        chart_title = f"{meta_single['name']} over time ({meta_single['unit']})"
    elif view_mode == "Indexed (100 at start)":
        chart_title = f"{meta_single['name']} (indexed to 100 at start of selected range)"
    elif view_mode == "MoM change":
        if meta_single["type"] == "rate":
            chart_title = f"{meta_single['name']} (month-over-month change, percentage points)"
        else:
            chart_title = f"{meta_single['name']} (month-over-month change)"
    elif view_mode == "YoY % change":
        chart_title = f"{meta_single['name']} (year-over-year % change)"
    else:
        chart_title = "Selected series over time"
else:
    if view_mode == "Levels":
        chart_title = "Selected series over time (levels)"
    elif view_mode == "Indexed (100 at start)":
        chart_title = "Selected series over time (indexed to 100 at start)"
    elif view_mode == "MoM change":
        chart_title = "Selected series over time (month-over-month change)"
    elif view_mode == "YoY % change":
        chart_title = "Selected series over time (year-over-year % change)"
    else:
        chart_title = "Selected series over time"

# Legend click interaction (click legend to fade/hide series)
legend_click = alt.selection_point(fields=["series_label"], bind="legend", empty="all")

chart = (
    alt.Chart(df_long)
    .mark_line()
    .encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("value:Q", title=y_title),
        color=alt.Color("series_label:N", title="Series"),
        opacity=alt.condition(legend_click, alt.value(1.0), alt.value(0.15)),
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("series_label:N", title="Series"),
            alt.Tooltip(
                "value:Q",
                title="Value",
                format=",.3f",
            ),
        ],
    )
    .add_params(legend_click)
    .properties(title=chart_title, height=500)
    .interactive()
)

st.subheader("Selected series over time")
st.altair_chart(chart, use_container_width=True)

# Extra explanation for MoM and YoY views
if view_mode == "MoM change":
    st.caption(
        "Month-over-month change is the current month minus the previous month. "
        "For rate series, the units are percentage points; for level series, the units "
        "match the original series (thousands, dollars, hours, etc.)."
    )
elif view_mode == "YoY % change":
    st.caption(
        "Year-over-year % change is the percentage difference between the current month "
        "and the same month one year earlier."
    )

# ---------------------------------------------------------------------
# Optional: latest-values table
# ---------------------------------------------------------------------
if show_table:
    st.subheader("Latest values (selected series)")
    rows = []
    for sid in selected:
        meta = SERIES_META[sid]
        m = compute_latest_metrics(df_f, sid)

        if meta["type"] == "rate":
            mom_str = f"{m['mom']:+.2f} pp" if pd.notna(m["mom"]) else ""
        else:
            mom_str = f"{m['mom']:+,.2f}" if pd.notna(m["mom"]) else ""

        rows.append(
            {
                "Series": meta["name"],
                "ID": sid,
                "Unit": meta["unit"],
                "Latest": m["latest"],
                "MoM change": mom_str,
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True)

# ---------------------------------------------------------------------
# Optional: CSV download (raw levels, not transformed)
# ---------------------------------------------------------------------
if show_download:
    st.download_button(
        "Download filtered data (CSV)",
        data=df_f[["date"] + selected].to_csv(index=False).encode("utf-8"),
        file_name="bls_filtered.csv",
        mime="text/csv",
    )
