# Central place for “what we track” and how we label it.

SERIES_META: dict[str, dict[str, str]] = {
    # Establishment survey (CES)
    "CES0000000001": {
        "name": "All employees: Total nonfarm (Payrolls)",
        "unit": "Thousands",
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

    # Household survey (CPS / LNS)
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
        "name": "Unemployment rate (U-6 underutilization)",
        "unit": "Percent",
        "type": "rate",
        "source": "CPS",
    },
}

BLS_ENDPOINTS = {
    "v2": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
    "v1": "https://api.bls.gov/publicAPI/v1/timeseries/data/",
}
