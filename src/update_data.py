"""
src/update_data.py

This is the "monthly updater" script.

What it does:
1) Reads the existing dataset in data/bls_monthly.csv (if it exists).
2) Requests BLS data for a recent window of time (to capture revisions).
3) Merges the refreshed window back with the older history already stored.
4) Writes:
   - data/bls_monthly.csv      (the dataset used by the Streamlit app)
   - data/build_info.json      (metadata about the build, for transparency)

Design goals:
- The Streamlit dashboard must NOT hit the BLS API on every page load.
  Instead, we update the dataset upstream via GitHub Actions.
- BLS data can be revised. By re-downloading the last N months each run, we
  keep the dataset accurate over time without re-downloading everything.

How to run locally:
  python -m src.update_data

Environment variables:
- BLS_API_KEY (optional): If provided, uses the v2 API registration key.

GitHub Actions:
- A workflow can run this script on a schedule and commit updated CSVs back to
  the repo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------
# Import setup
# ---------------------------------------------------------------------
# When running as "python -m src.update_data", imports work naturally.
# When running as "python src/update_data.py", Python may not include the repo
# root on sys.path. This block makes both run modes work consistently.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bls_api import BLSError, fetch_bls_wide
from src.config import SERIES_META


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as ISO string (no microseconds)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def update_dataset(
    data_path: Path,
    build_info_path: Path,
    *,
    refresh_months: int = 24,
    initial_years: int = 10,
    preferred_api_version: str = "v2",
) -> tuple[pd.DataFrame, str]:
    """
    Update (or create) the local dataset used by the dashboard.

    Parameters
    ----------
    data_path:
        Path to the CSV we store in the repo (e.g., data/bls_monthly.csv).
    build_info_path:
        Path to build metadata JSON (e.g., data/build_info.json).
    refresh_months:
        Number of months back from the newest observation to re-download.
        This captures BLS revisions.
    initial_years:
        If the dataset doesn't exist yet, download this many years of history.
        Note: without an API key, BLS may limit you to ~10 years.
    preferred_api_version:
        "v2" (recommended). If v2 fails and no API key is provided, we fall back
        to v1 so the project still works.

    Returns
    -------
    (combined_df, api_version_used)
    """
    # Optional: API key in environment variables (safe for GitHub Actions secrets).
    api_key = os.getenv("BLS_API_KEY")

    # The series list comes directly from SERIES_META so config drives everything.
    series_ids = list(SERIES_META.keys())

    # We request through the current year.
    today_utc = pd.Timestamp.utcnow()
    endyear = int(today_utc.year)

    # -----------------------------------------------------------------
    # Step 1: Determine the start year for the new API request
    # -----------------------------------------------------------------
    if data_path.exists():
        # Existing dataset: keep the older part, and refresh the most recent window.
        old = pd.read_csv(data_path, parse_dates=["date"]).sort_values("date")

        # Example: if latest observation is 2025-11 and refresh_months=24,
        # refresh_start ≈ 2023-11.
        max_date = old["date"].max()
        refresh_start = max_date - pd.DateOffset(months=refresh_months)

        # BLS API takes year bounds, so we request from the start year of that window.
        startyear = int(refresh_start.year)

        # We'll keep everything BEFORE Jan 1 of startyear, and replace the rest.
        old_cutoff = pd.Timestamp(year=startyear, month=1, day=1)
        old_keep = old.loc[old["date"] < old_cutoff].copy()
    else:
        # No dataset yet: pull an initial history window.
        old_keep = pd.DataFrame()
        startyear = int(endyear - initial_years + 1)

    # -----------------------------------------------------------------
    # Step 2: Download data from BLS
    # -----------------------------------------------------------------
    api_used = preferred_api_version

    try:
        new = fetch_bls_wide(
            series_ids=series_ids,
            startyear=startyear,
            endyear=endyear,
            api_key=api_key,
            api_version=preferred_api_version,
        )
    except BLSError as e:
        # If the user didn't set a key and v2 fails, fall back to v1.
        # This makes the project resilient even for students without API keys.
        if preferred_api_version == "v2" and not api_key:
            print(f"[warn] BLS v2 failed without BLS_API_KEY; falling back to v1. Error was: {e}")
            api_used = "v1"
            new = fetch_bls_wide(
                series_ids=series_ids,
                startyear=startyear,
                endyear=endyear,
                api_key=None,
                api_version="v1",
            )
        else:
            raise

    # -----------------------------------------------------------------
    # Step 3: Merge old + refreshed data
    # -----------------------------------------------------------------
    if not old_keep.empty:
        combined = pd.concat([old_keep, new], ignore_index=True)
    else:
        combined = new.copy()

    # Ensure stable column order in the CSV.
    expected_cols = ["date"] + series_ids
    for c in expected_cols:
        if c not in combined.columns:
            combined[c] = pd.NA
    combined = combined[expected_cols]

    # One row per month. If BLS revisions exist, keep the newest version ("last").
    combined = (
        combined.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )

    # -----------------------------------------------------------------
    # Step 4: Write outputs to disk
    # -----------------------------------------------------------------
    data_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(data_path, index=False)

    # build_info.json is helpful for transparency in the dashboard.
    build_info = {
        "generated_at_utc": _utc_now_iso(),
        "api_version_used": api_used,
        "startyear_requested": startyear,
        "endyear_requested": endyear,
        "min_date": str(combined["date"].min().date()),
        "max_date": str(combined["date"].max().date()),
        "n_rows": int(combined.shape[0]),
        "series": SERIES_META,
    }
    build_info_path.parent.mkdir(parents=True, exist_ok=True)
    build_info_path.write_text(json.dumps(build_info, indent=2))

    return combined, api_used


def main() -> None:
    """
    CLI entrypoint so the script can be run with:
        python -m src.update_data

    You can override defaults:
        python -m src.update_data --refresh-months 36 --initial-years 10
    """
    parser = argparse.ArgumentParser(description="Update BLS monthly dataset stored in the repo.")
    parser.add_argument("--data-path", default="data/bls_monthly.csv")
    parser.add_argument("--build-info-path", default="data/build_info.json")
    parser.add_argument("--refresh-months", type=int, default=24)
    parser.add_argument("--initial-years", type=int, default=10)
    parser.add_argument("--api-version", choices=["v2", "v1"], default="v2")
    args = parser.parse_args()

    df, api_used = update_dataset(
        data_path=ROOT / args.data_path,
        build_info_path=ROOT / args.build_info_path,
        refresh_months=args.refresh_months,
        initial_years=args.initial_years,
        preferred_api_version=args.api_version,
    )

    print(
        f"Updated {len(df)} monthly rows using BLS API {api_used}. "
        f"Latest month: {df['date'].max().date()}"
    )


if __name__ == "__main__":
    main()
