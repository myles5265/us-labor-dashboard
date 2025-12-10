from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Make imports work whether you run:
#   python -m src.update_data
# or:
#   python src/update_data.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bls_api import BLSError, fetch_bls_wide
from src.config import SERIES_META


def _utc_now_iso() -> str:
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
    - If no dataset exists: downloads initial_years.
    - If dataset exists: refreshes last refresh_months to capture revisions.
    Returns (updated_df, api_version_used).
    """
    api_key = os.getenv("BLS_API_KEY")  # optional
    series_ids = list(SERIES_META.keys())

    today_utc = pd.Timestamp.utcnow()
    endyear = int(today_utc.year)

    if data_path.exists():
        old = pd.read_csv(data_path, parse_dates=["date"]).sort_values("date")
        max_date = old["date"].max()
        refresh_start = max_date - pd.DateOffset(months=refresh_months)
        startyear = int(refresh_start.year)
        old_cutoff = pd.Timestamp(year=startyear, month=1, day=1)
        old_keep = old.loc[old["date"] < old_cutoff].copy()
    else:
        old_keep = pd.DataFrame()
        startyear = int(endyear - initial_years + 1)

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
        # If v2 fails and no key exists, fall back to v1.
        if preferred_api_version == "v2" and not api_key:
            print(f"[warn] v2 failed without BLS_API_KEY; falling back to v1. Error was: {e}")
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

    # Combine (keep older history, refresh recent window)
    if not old_keep.empty:
        combined = pd.concat([old_keep, new], ignore_index=True)
    else:
        combined = new.copy()

    expected_cols = ["date"] + series_ids
    for c in expected_cols:
        if c not in combined.columns:
            combined[c] = pd.NA
    combined = combined[expected_cols]

    combined = (
        combined.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )

    data_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(data_path, index=False)

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
    print(f"Updated {len(df)} monthly rows using BLS API {api_used}. Latest month: {df['date'].max().date()}")


if __name__ == "__main__":
    main()
