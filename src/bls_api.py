"""
src/bls_api.py

Small wrapper around the BLS Public Data API.

Why this file exists:
- Keeps API request/response parsing isolated from the rest of the project
- Makes it easy to test API logic in a notebook or from the command line
- Provides a consistent pandas DataFrame output format for downstream code

Main outputs:
- fetch_bls_tidy(...): long/tidy format (one row per series per month)
- fetch_bls_wide(...): wide format (one row per month, one column per series)

Notes about BLS API responses:
- BLS returns monthly data labeled "M01" .. "M12".
- Some series include annual averages labeled "M13" (we ignore those).
- The JSON shape differs slightly between the v1 and v2 endpoints, so we
  defensively handle both.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import pandas as pd
import requests

from src.config import BLS_ENDPOINTS


class BLSError(RuntimeError):
    """Raised when the BLS API returns a non-success status or unusable payload."""
    pass


def _extract_series_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract the list of series objects from a BLS response.

    BLS docs/examples show slightly different shapes across endpoints and versions:
      - {"Results": {"series": [...]}}
      - {"Results": [{"series": [...]}]}

    This function makes our parsing robust to either shape.
    """
    results = payload.get("Results")
    if isinstance(results, dict):
        return list(results.get("series", []))
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return list(results[0].get("series", []))
    return []


def fetch_bls_tidy(
    series_ids: list[str],
    startyear: int,
    endyear: int,
    *,
    api_key: Optional[str] = None,
    api_version: str = "v2",
    timeout_s: int = 30,
    max_retries: int = 3,
) -> pd.DataFrame:
    """
    Call the BLS API and return a tidy/long DataFrame with monthly observations.

    Parameters
    ----------
    series_ids:
        List of BLS series IDs (strings).
    startyear, endyear:
        Inclusive year bounds for the request.
    api_key:
        Optional BLS API key (recommended). If None, the v2 endpoint may reject
        large requests; our update script can fall back to v1 when needed.
    api_version:
        Either "v2" or "v1". (See src/config.py)
    timeout_s:
        HTTP timeout seconds.
    max_retries:
        Retries for transient errors (rate limiting or temporary server issues).

    Returns
    -------
    pd.DataFrame with columns:
      - date (Timestamp at first day of the month)
      - series_id
      - value (float)
      - footnotes (comma-separated string; may be empty)

    Important behavior:
    - Filters to monthly periods M01..M12.
    - Drops rows where value could not be parsed to numeric.
    - Sorts output by [series_id, date].
    """
    if api_version not in BLS_ENDPOINTS:
        raise ValueError(f"api_version must be one of {list(BLS_ENDPOINTS)}")

    url = BLS_ENDPOINTS[api_version]
    headers = {"Content-type": "application/json"}

    # BLS expects a JSON POST body.
    payload: dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": str(startyear),
        "endyear": str(endyear),
    }
    if api_key:
        payload["registrationkey"] = api_key

    last_err: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout_s)

            # Retry some transient status codes.
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * attempt)
                continue

            resp.raise_for_status()
            data = resp.json()

            # BLS includes a "status" field indicating success/failure.
            status = data.get("status")
            if status != "REQUEST_SUCCEEDED":
                msg = "; ".join(data.get("message", []) or [])
                raise BLSError(f"BLS request failed (status={status}): {msg}")

            series_list = _extract_series_list(data)
            if not series_list:
                raise BLSError("BLS response had no series data.")

            rows: list[dict[str, Any]] = []
            for series in series_list:
                sid = series.get("seriesID")
                for item in series.get("data", []):
                    # Example fields: year, period, periodName, value, footnotes, ...
                    period = item.get("period")

                    # We only want monthly values: M01..M12.
                    # Some series include "M13" annual average; ignore it.
                    if not isinstance(period, str):
                        continue
                    if not ("M01" <= period <= "M12"):
                        continue

                    year = int(item["year"])
                    month = int(period[1:])  # "M01" -> 1
                    date = pd.Timestamp(year=year, month=month, day=1)

                    # Values come back as strings; convert to numeric.
                    value = pd.to_numeric(item.get("value"), errors="coerce")

                    # Footnotes: list of dicts like {"code":"...","text":"..."}.
                    footnote_texts: list[str] = []
                    for fn in item.get("footnotes", []) or []:
                        if fn and fn.get("text"):
                            footnote_texts.append(fn["text"])
                    footnotes = ", ".join(footnote_texts)

                    rows.append(
                        {
                            "date": date,
                            "series_id": sid,
                            "value": value,
                            "footnotes": footnotes,
                        }
                    )

            df = pd.DataFrame(rows).dropna(subset=["value"])
            df = df.sort_values(["series_id", "date"]).reset_index(drop=True)
            return df

        except Exception as e:
            last_err = e
            # Backoff: 1s, 2s, 3s, ...
            time.sleep(1 * attempt)

    raise BLSError(f"BLS request failed after {max_retries} attempts: {last_err}")


def fetch_bls_wide(
    series_ids: list[str],
    startyear: int,
    endyear: int,
    *,
    api_key: Optional[str] = None,
    api_version: str = "v2",
) -> pd.DataFrame:
    """
    Convenience wrapper that returns wide format:

      date | SERIES1 | SERIES2 | ... (one column per series_id)

    This is the format we store in data/bls_monthly.csv because it is:
    - easy to load into Streamlit
    - easy to compute transformations (diff, pct_change, indexing)
    - easy to export for users
    """
    tidy = fetch_bls_tidy(
        series_ids=series_ids,
        startyear=startyear,
        endyear=endyear,
        api_key=api_key,
        api_version=api_version,
    )

    wide = (
        tidy.pivot(index="date", columns="series_id", values="value")
        .sort_index()
        .reset_index()
    )
    wide.columns.name = None  # cleaner header for CSV
    return wide
