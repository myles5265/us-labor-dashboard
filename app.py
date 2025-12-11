"""
app.py

Streamlit dashboard for the US Labor Statistics project.

User requirement (your clarification):
- There should be ONE chart.
- All series should be selectable to graph over time (or deselectable).
- No "columns of charts" / no small-multiple chart grids.

Design principle:
- The Streamlit app does NOT call the BLS API when users open the dashboard.
- A separate script (src/update_data.py), typically run by GitHub Actions,
  updates data/bls_monthly.csv in the repository.
- This app only reads the CSV and visualizes it.

What this app provides:
- Multiselect for series (default: ALL series selected)
- Date range filter
- View modes:
    * Levels
    * Indexed (100 at start)  <-- recommended if you plot mixed units
    * MoM change
    * YoY % change
- ONE combined line chart for the selected series
- Optional: latest-values table + CSV download
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
# Paths to data files (stored in the repo)
# ---------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "bls_monthly.csv"
BUILD_INFO_PATH = ROOT / "data" / "build_info.json"


# ---------------------------------------------------------------------
# Cached loaders
# Streamlit re-runs your script on every interaction; caching prevents
# repeatedly reading the same CSV from disk.
# ---------------------------------------------------------------------
@st.cache_data
def load_data() -> pd.DataFrame:
    """Load the stored dataset (wide format): date + one column per series_id."""
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


@st.cache_data
def load_build_info() -> dict:
    """Load metadata written by the updater script (if present)."""
    if BUILD_INFO_PATH.exists():
        return json.loads(BUILD_INFO_PATH.read_text())
    return {}


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
def apply_view_mode(wide: pd.DataFrame, view_mode: str) -> pd.DataFrame:
    """
    Apply transformation to a wide DataFrame that is indexed by date.

    wide:
        DataFrame indexed by date, with one column per series_id.
    view_mode:
        One of: "Levels", "Indexed (100 at start)", "MoM change", "YoY % change"
    """
    if view_mode == "Levels":
        return wide

    if view_mode == "Indexed (100 at start)":
        # Index each series independently so mixed units can be compared.
        def _index(s: pd.Series) -> pd.Series:
            s_nonmissing = s.dropna()
            if s_nonmissing.empty:
                return s
            return (s / s_nonmissing.iloc[0]) * 100

        return wide.apply(_index)

    if view_mode == "MoM change":
        # Month-over-month absolute difference.
        return wide.diff()

    if view_mode == "YoY % change":
        # Year-over-year percent change.
        return wide.pct_change(12) * 100

    raise ValueError(f"Unknown view_mode: {view_mode}")


def compute_latest_metrics(df: pd.DataFrame, series_id: str) -> dict:
    """
    Compute latest value + changes for a series.

    Returns:
      latest: latest numeric value
      mom: month-over-month difference
      yoy: year-over-year difference (not percent)
      latest_date: timestamp of latest observation
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
    """Pretty label for the multiselect dropdown."""
    meta = SERIES_META.get(series_id, {})
    return f"{meta.get('name', series_id)} ({series_id})"


# ---------------------------------------------------------------------
# Streamlit page setup
# ---------------------------------------------------------------------
st.set_page_config(page_title="US Labor Statistics Dashboard (BLS)", layout="wide")
st.title("US Labor Statistics Dashboard (BLS)")

# Ensure data exists (created by running src/update_data.py at least once).
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

# Initialize selection (default = ALL series selected).
# We store this in session state so it persists across interactions.
if "selected_series" not in st.session_state:
    st.session_state.selected_series = series_ids.copy()

# Show dataset freshness metadata (helpful to prove your pipeline works).
latest_month = df["date"].max().date()
generated_at = build_info.get("generated_at_utc", "Unknown")
st.caption(f"Latest month in dataset: **{latest_month}** • Data build time (UTC): **{generated_at}**")

# ---------------------------------------------------------------------
# Requirement visibility: show the required series clearly (no chart columns)
# This is optional, but it makes it obvious you included payrolls + unemployment.
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
# Sidebar controls: pick series, date range, view mode
# ---------------------------------------------------------------------
with st.sidebar:
    st.header("Chart controls")

    # Simple buttons (no column layout)
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
        index=1,  # default to Indexed so mixed-units charts are readable
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

    # Streamlit date_input usually returns a tuple for range selection.
    if isinstance(date_input, tuple) and len(date_input) == 2:
        start_d, end_d = date_input
    else:
        start_d, end_d = min_d, max_d

    show_table = st.checkbox("Show latest-values table", value=True)
    show_download = st.checkbox("Enable CSV download", value=True)

# If nothing selected, guide the user.
if not selected:
    st.info("Select one or more series in the sidebar (or click 'Select all series').")
    st.stop()

# ---------------------------------------------------------------------
# Filter to date range and compute the transformed view
# ---------------------------------------------------------------------
mask = (df["date"].dt.date >= start_d) & (df["date"].dt.date <= end_d)
df_f = df.loc[mask].copy()

# Build a wide matrix: index=date, columns=selected series IDs
wide = df_f[["date"] + selected].set_index("date").sort_index()

# Apply transformation (levels/indexed/diffs)
wide_view = apply_view_mode(wide, view_mode)

# Convert to long format for Altair
df_long = (
    wide_view.reset_index()
    .melt("date", var_name="series_id", value_name="value")
    .dropna()
)
df_long["series_name"] = df_long["series_id"].map(lambda sid: SERIES_META[sid]["name"])
df_long["unit"] = df_long["series_id"].map(lambda sid: SERIES_META[sid]["unit"])

# Helpful warning if user tries to plot mixed units in Levels mode
if view_mode == "Levels":
    units = {SERIES_META[sid]["unit"] for sid in selected}
    if len(units) > 1:
        st.warning(
            "You selected series with different units on a single y-axis. "
            "To see all series clearly on one chart, switch to **Indexed (100 at start)** "
            "or plot fewer series with the same unit."
        )

# Axis title based on view mode
y_title = {
    "Levels": "Value",
    "Indexed (100 at start)": "Index (100 = start)",
    "MoM change": "Month-over-month change",
    "YoY % change": "Year-over-year % change",
}[view_mode]

# ---------------------------------------------------------------------
# SINGLE CHART: combined lines
# Optional: allow toggling series by clicking legend (in addition to multiselect)
# ---------------------------------------------------------------------
legend_click = alt.selection_point(fields=["series_name"], bind="legend", empty="all")

chart = (
    alt.Chart(df_long)
    .mark_line()
    .encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("value:Q", title=y_title),
        color=alt.Color("series_name:N", title="Series"),
        opacity=alt.condition(legend_click, alt.value(1.0), alt.value(0.15)),
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("series_name:N", title="Series"),
            alt.Tooltip("value:Q", title="Value", format=",.3f"),
            alt.Tooltip("unit:N", title="Unit"),
        ],
    )
    .add_params(legend_click)
    .properties(height=500)
    .interactive()
)

st.subheader("Selected series over time")
st.altair_chart(chart, use_container_width=True)

# ---------------------------------------------------------------------
# Optional: table of latest values
# ---------------------------------------------------------------------
if show_table:
    st.subheader("Latest values (selected series)")
    rows = []
    for sid in selected:
        meta = SERIES_META[sid]
        m = compute_latest_metrics(df_f, sid)

        # Format month-to-month change:
        # - rates: show percentage points (pp)
        # - levels: show numeric difference
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
# Optional: CSV download (raw filtered levels, not transformed)
# ---------------------------------------------------------------------
if show_download:
    st.download_button(
        "Download filtered data (CSV)",
        data=df_f[["date"] + selected].to_csv(index=False).encode("utf-8"),
        file_name="bls_filtered.csv",
        mime="text/csv",
    )
