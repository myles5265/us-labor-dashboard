"""
src/config.py

This file is the "single source of truth" for:

1) Which BLS time-series we collect (SERIES_META keys)
2) How we display them in the Streamlit dashboard (friendly name/unit/type)

If you want to add more series to your project, this is the only place you need
to edit. After you add an entry here:

- The updater script (src/update_data.py) will automatically pull that series
  from the BLS API and add it as a new column in data/bls_monthly.csv
- The Streamlit app (app.py) will automatically show it as an option to graph

Important vocabulary:
- "CES..." series are from the Establishment Survey (payroll jobs, earnings, hours)
- "LNS..." series are from the Household Survey (unemployment rate, participation, etc.)

Series IDs are *exactly* as defined by BLS.
"""

# Metadata for each series we track.
#
# Fields:
# - name:   What users see in the dashboard
# - unit:   Human-readable unit label used in axes/tables
# - type:   "level" for counts/amounts, "rate" for percent rates (helps formatting)
# - source: A short tag describing the BLS program (CES, CPS, etc.)
SERIES_META: dict[str, dict[str, str]] = {
    # --- Establishment survey (CES): payroll jobs, earnings, hours ---
    "CES0000000001": {
        "name": "Total nonfarm payroll employment",
        "unit": "Thousands of jobs",
        "type": "level",
        "source": "CES",
    },
    "CES0500000003": {
        "name": "Average hourly earnings: Total private",
        "unit": "Dollars per hour",
        "type": "level",
        "source": "CES",
    },
    "CES0500000002": {
        "name": "Average weekly hours: Total private",
        "unit": "Hours",
        "type": "level",
        "source": "CES",
    },

    # --- Household survey (CPS/LNS): unemployment and labor force measures ---
    "LNS14000000": {
        "name": "Unemployment rate (U-3)",
        "unit": "Percent",
        "type": "rate",
        "source": "CPS",
    },
    "LNS11300000": {
        "name": "Labor force participation rate",
        "unit": "Percent",
        "type": "rate",
        "source": "CPS",
    },
    "LNS12300000": {
        "name": "Employment-population ratio",
        "unit": "Percent",
        "type": "rate",
        "source": "CPS",
    },
    "LNS13327709": {
        "name": "Underutilization rate (U-6)",
        "unit": "Percent",
        "type": "rate",
        "source": "CPS",
    },
}

# Public API endpoints.
# - v2 supports higher limits with an API key
# - v1 is older but can be used without registration
BLS_ENDPOINTS = {
    "v2": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
    "v1": "https://api.bls.gov/publicAPI/v1/timeseries/data/",
}
