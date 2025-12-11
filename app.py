"""
app.py

Streamlit dashboard for the US labor statistics project.

Key design principle:
- The dashboard does NOT call the BLS API when users open the page.
- Instead, a GitHub Action runs src/update_data.py on a schedule and commits
  an updated CSV (data/bls_monthly.csv) to this repository.
- Streamlit simply reads that CSV, so page loads are fast and reliable.

What users can do:
- Choose one or many series to display
- Filter the date range
- Transform the data (levels, indexed, MoM change, YoY % change)
- View either:
    * Combined lines (all selected series on one chart), OR
    * Small multiples (one chart per series with independent y-axes)
- Download the filtered data as CSV

New: "All series overview" tab
- Always graphs every series in SERIES_META so all data is visible over time.
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
# File locations
# ---------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "bls_monthly.csv"
BUILD_INFO_PATH = ROOT / "data" / "build_info.json"


# ---------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------
# Streamlit re-runs your script on every interaction, so caching avoids
# re-reading the CSV repeatedly and makes the app feel snappy.
@st.cache_data
def load_data() -> pd.DataFrame:
    """Load the stored dataset (wide monthly format)."""
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


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
    Apply a transformation to a wide DataFrame indexed by date.

    wide:
        DataFrame with date index and one column per series_id.
    view_mode:
        One of:
        - "Levels"
        - "Indexed (100 at start)"
        - "MoM change"
        - "YoY % change"
    """
    if view_mode == "Levels":
        return wide

    if view_mode == "Indexed (100 at start)":
        # Index each series separately: first non-missing value in the window becomes 100.
        def _index(s: pd.Series) -> pd.Series:
            s_nonmissing = s.dropna()
            if s_nonmissing.empty:
                return s
            return (s / s_nonmissing.iloc[0]) * 100

        return wide.apply(_index)

    if view_mode == "MoM change":
        # Difference from the previous month.
        return wide.diff()

    if view_mode == "YoY % change":
        # Percent change relative to 12 months ago.
        return wide.pct_change(12) * 100

    raise ValueError(f"Unknown view_mode: {view_mode}")


def compute_latest_metrics(df: pd.DataFrame, series_id: str) -> dict:
    """
    Compute latest value and simple changes for a given series.

    Returns:
      latest: latest value in df
      mom:    month-over-month change (difference)
      yoy:    year-over-year change (difference, not %)
      latest_date: Timestamp for the latest value
    """
    s = df[["date", series_id]].dropna().set_index("date")[series_id].sort_index()

    if len(s) == 0:
        return {"latest": np.nan, "mom": np.nan, "yoy": np.nan, "latest_date": None}

    latest = float(s.iloc[-1])
    latest_date = s.index[-1]
    mom = float(s.iloc[-1] - s.iloc[-2]) if len(s) >= 2 else np.nan
    yoy = float(s.iloc[-1] - s.iloc[-13]) if len(s) >= 13 else np.nan

    return {"latest": latest, "mom": mom, "yoy": yoy, "latest_date": latest_date}


def fmt_series_label(series_id: str) -> str:
    """Pretty label for the sidebar multiselect."""
    meta = SERIES_META.get(series_id, {})
    return f"{meta.get('name', series_id)}  ({series_id})"


# ---------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------
st.set_page_config(page_title="US Labor Statistics Dashboard (BLS)", layout="wide")
st.title("US Labor Statistics Dashboard (BLS)")

# Ensure the dataset exists (it will after you run src/update_data.py once).
if not DATA_PATH.exists():
    st.error("Missing data/bls_monthly.csv. Run the updater script once to create it.")
    st.stop()

# Load data + build info.
df = load_data()
build_info = load_build_info()

# Series universe (driven by config).
series_ids = list(SERIES_META.keys())

# Initialize session state for multiselect so we can have "Select all / Clear" buttons.
if "selected_series" not in st.session_state:
    # Default = ALL series so the user can immediately see everything over time.
    st.session_state.selected_series = series_ids.copy()

# Show dataset freshness.
latest_month = df["date"].max().date()
generated_at = build_info.get("generated_at_utc", "Unknown")
st.caption(f"Latest month in dataset: **{latest_month}**  •  Data build time (UTC): **{generated_at}**")

# ---------------------------------------------------------------------
# Required headline metrics (always shown)
# ---------------------------------------------------------------------
# The assignment requires "total nonfarm" + unemployment rate. We display those
# as metrics at the top so your dashboard clearly meets the requirement.
req_payroll = compute_latest_metrics(df, "CES0000000001")
req_u3 = compute_latest_metrics(df, "LNS14000000")
req_u6 = compute_latest_metrics(df, "LNS13327709")

c1, c2, c3 = st.columns(3)
c1.metric(
    "Total nonfarm payroll employment (thousands)",
    f"{req_payroll['latest']:,.0f}",
    f"{req_payroll['mom']:+,.0f} MoM",
)
c2.metric(
    "Unemployment rate (U-3)",
    f"{req_u3['latest']:.1f}%",
    f"{req_u3['mom']:+.1f} pp MoM",
)
c3.metric(
    "Underutilization rate (U-6)",
    f"{req_u6['latest']:.1f}%",
    f"{req_u6['mom']:+.1f} pp MoM",
)

st.divider()

# ---------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------
with st.sidebar:
    st.header("Controls")

    # Quick selection buttons.
    b1, b2 = st.columns(2)
    if b1.button("Select all"):
        st.session_state.selected_series = series_ids.copy()
    if b2.button("Clear"):
        st.session_state.selected_series = []

    selected = st.multiselect(
        "Series to display",
        options=series_ids,
        format_func=fmt_series_label,
        key="selected_series",  # session-state key
        help="Pick one or multiple BLS series to plot.",
    )

    # Chart layout controls whether we force independent y-axes.
    chart_layout = st.radio(
        "Chart layout",
        ["Combined lines", "Small multiples (one chart per series)"],
        index=1,  # default to small multiples so all series are readable
        help="Small multiples are best when series have different units (%, thousands, dollars, hours).",
    )

    view_mode = st.radio(
        "View mode",
        ["Levels", "Indexed (100 at start)", "MoM change", "YoY % change"],
        index=0,
        help="Transform the data before plotting.",
    )

    # Default date range = full history in the dataset.
    min_d = df["date"].min().date()
    max_d = df["date"].max().date()
    date_input = st.date_input(
        "Date range",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d,
    )

    # Streamlit may return either a tuple (start, end) or a single date depending on UI state.
    if isinstance(date_input, tuple) and len(date_input) == 2:
        start_d, end_d = date_input
    else:
        start_d, end_d = min_d, max_d

    # Only show grid layout options when small multiples are selected.
    if chart_layout.startswith("Small multiples"):
        n_cols = st.slider("Small multiples columns", 1, 3, 2)
    else:
        n_cols = 2  # unused

    st.caption("Tip: 'Indexed (100 at start)' is great for comparing trends across different units.")

# ---------------------------------------------------------------------
# Filter data to the requested date range
# ---------------------------------------------------------------------
mask = (df["date"].dt.date >= start_d) & (df["date"].dt.date <= end_d)
df_f = df.loc[mask].copy()

# If nothing selected, show a helpful message.
if not selected:
    st.info("Select at least one series in the sidebar (or click 'Select all').")
    st.stop()

# ---------------------------------------------------------------------
# Prepare the transformed dataset for plotting
# ---------------------------------------------------------------------
# wide:  index=date, columns=series_id
wide = df_f[["date"] + selected].set_index("date").sort_index()

# Apply the chosen view transformation.
wide_view = apply_view_mode(wide, view_mode)

# Tabs:
# - Explorer: uses user's selected series
# - All series overview: guarantees that *every* tracked series is graphed
tab_explorer, tab_all = st.tabs(["Explorer", "All series overview"])

# ---------------------------------------------------------------------
# Explorer tab
# ---------------------------------------------------------------------
with tab_explorer:
    st.subheader("Interactive chart")

    if chart_layout == "Combined lines":
        # For a multi-line chart, Altair wants data in long format.
        df_long = (
            wide_view.reset_index()
            .melt("date", var_name="series_id", value_name="value")
            .dropna()
        )
        df_long["series_name"] = df_long["series_id"].map(lambda sid: SERIES_META[sid]["name"])

        # Warn about mixed units if the user plots levels on one shared y-axis.
        if view_mode == "Levels":
            units = {SERIES_META[sid]["unit"] for sid in selected}
            if len(units) > 1:
                st.warning(
                    "You selected series with different units on a single y-axis. "
                    "Consider switching to 'Indexed (100 at start)' or using 'Small multiples'."
                )

        y_title = {
            "Levels": "Value",
            "Indexed (100 at start)": "Index (100 = start)",
            "MoM change": "Month-over-month change",
            "YoY % change": "Year-over-year % change",
        }[view_mode]

        chart = (
            alt.Chart(df_long)
            .mark_line()
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("value:Q", title=y_title),
                color=alt.Color("series_name:N", title="Series"),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip("series_name:N", title="Series"),
                    alt.Tooltip("value:Q", title="Value", format=",.3f"),
                ],
            )
            .properties(height=420)
            .interactive()
        )

        st.altair_chart(chart, use_container_width=True)

    else:
        # Small multiples = one chart per series, which makes it easy to see
        # every series even when units differ.
        st.caption(
            "Small multiples show each series on its own y-axis so you can see all values clearly over time."
        )

        cols = st.columns(n_cols)
        for i, sid in enumerate(selected):
            meta = SERIES_META[sid]

            # Pull the transformed series values into a simple 2-column dataframe for plotting.
            sub = wide_view[[sid]].reset_index().rename(columns={sid: "value"}).dropna()

            # Choose a y-axis label that matches the transformation.
            y_axis_title = meta["unit"] if view_mode == "Levels" else {
                "Indexed (100 at start)": "Index",
                "MoM change": "Change",
                "YoY % change": "% change",
            }[view_mode]

            c = (
                alt.Chart(sub)
                .mark_line()
                .encode(
                    x=alt.X("date:T", title=""),
                    y=alt.Y("value:Q", title=y_axis_title),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date"),
                        alt.Tooltip("value:Q", title="Value", format=",.3f"),
                    ],
                )
                .properties(
                    title=f"{meta['name']} ({sid})",
                    height=220,
                )
                .interactive()
            )

            cols[i % n_cols].altair_chart(c, use_container_width=True)

    # -----------------------------------------------------------------
    # Summary table for selected series
    # -----------------------------------------------------------------
    st.subheader("Latest values (selected series)")

    rows = []
    for sid in selected:
        meta = SERIES_META[sid]
        m = compute_latest_metrics(df_f, sid)

        # Rates: show changes in percentage points (pp)
        # Levels: show numeric differences in units
        if meta["type"] == "rate":
            mom_str = f"{m['mom']:+.2f} pp" if pd.notna(m["mom"]) else ""
            yoy_str = f"{m['yoy']:+.2f} pp" if pd.notna(m["yoy"]) else ""
        else:
            mom_str = f"{m['mom']:+,.2f}" if pd.notna(m["mom"]) else ""
            yoy_str = f"{m['yoy']:+,.2f}" if pd.notna(m["yoy"]) else ""

        rows.append(
            {
                "Series": meta["name"],
                "ID": sid,
                "Unit": meta["unit"],
                "Latest": m["latest"],
                "MoM change": mom_str,
                "YoY change": yoy_str,
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # Download the filtered raw levels (not transformed) for user convenience.
    st.download_button(
        "Download filtered data (CSV)",
        data=df_f[["date"] + selected].to_csv(index=False).encode("utf-8"),
        file_name="bls_filtered.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------------
# All series overview tab
# ---------------------------------------------------------------------
with tab_all:
    st.subheader("All series over time")

    st.caption(
        "This tab always graphs **every** series defined in `SERIES_META`. "
        "Use it to quickly confirm that the dataset includes all series and that you can see them over time."
    )

    all_wide = df_f[["date"] + series_ids].set_index("date").sort_index()
    all_view = apply_view_mode(all_wide, view_mode)

    # Fixed 2-column grid for readability.
    cols2 = st.columns(2)
    for i, sid in enumerate(series_ids):
        meta = SERIES_META[sid]
        sub = all_view[[sid]].reset_index().rename(columns={sid: "value"}).dropna()

        y_axis_title = meta["unit"] if view_mode == "Levels" else {
            "Indexed (100 at start)": "Index",
            "MoM change": "Change",
            "YoY % change": "% change",
        }[view_mode]

        c = (
            alt.Chart(sub)
            .mark_line()
            .encode(
                x=alt.X("date:T", title=""),
                y=alt.Y("value:Q", title=y_axis_title),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip("value:Q", title="Value", format=",.3f"),
                ],
            )
            .properties(
                title=f"{meta['name']} ({sid})",
                height=220,
            )
            .interactive()
        )

        cols2[i % 2].altair_chart(c, use_container_width=True)
