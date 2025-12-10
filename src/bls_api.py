from __future__ import annotations

import time
from typing import Any, Optional

import pandas as pd
import requests

from src.config import BLS_ENDPOINTS


class BLSError(RuntimeError):
    pass


def _extract_series_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    BLS responses can vary:
      - {"Results": {"series": [...]}}
      - {"Results": [{"series": [...]}]}
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
    Returns tidy monthly data:
      columns = [date, series_id, value, footnotes]

    - Filters to M01..M12 (ignores annual averages like M13).
    """
    if api_version not in BLS_ENDPOINTS:
        raise ValueError(f"api_version must be one of {list(BLS_ENDPOINTS)}")

    url = BLS_ENDPOINTS[api_version]
    headers = {"Content-type": "application/json"}

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

            # Retry on transient errors
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * attempt)
                continue

            resp.raise_for_status()
            data = resp.json()

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
                    period = item.get("period")
                    if not isinstance(period, str):
                        continue
                    if not ("M01" <= period <= "M12"):
                        continue

                    year = int(item["year"])
                    month = int(period[1:])
                    date = pd.Timestamp(year=year, month=month, day=1)

                    value = pd.to_numeric(item.get("value"), errors="coerce")
                    footnote_texts = []
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
    Returns wide monthly data:
      date + one column per series_id
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
    wide.columns.name = None
    return wide
