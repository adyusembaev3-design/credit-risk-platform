"""US unemployment rate (FRED series UNRATE) and the macro shock each loan lived through."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import config

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE"
CACHE = config.RAW_DIR / "unrate.csv"


def load_unemployment(path: Path = CACHE, refresh: bool = False) -> pd.DataFrame:
    """Monthly unemployment rate (percent). Downloads from FRED once, then reads the cache."""
    if refresh or not path.exists():
        import requests

        resp = requests.get(FRED_URL, timeout=30)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text)
        print(f"Downloaded unemployment rate from FRED -> {path}")
    df = pd.read_csv(StringIO(path.read_text()))
    date_col = next(c for c in df.columns if c.lower() in ("observation_date", "date"))
    out = pd.DataFrame({"month": pd.to_datetime(df[date_col]).dt.to_period("M"),
                        "unrate": pd.to_numeric(df["UNRATE"], errors="coerce")}).dropna()
    return out.sort_values("month").reset_index(drop=True)


def unemployment_change(issue_months: pd.Series, unrate: pd.DataFrame, horizon: int) -> pd.Series:
    """Average unemployment over months 1..horizon after issue, minus the rate in the issue month.

    This is the macro shock a loan was exposed to during the period when most
    defaults happen. NaN when the series does not yet cover the full horizon.
    """
    s = unrate.set_index("month")["unrate"]
    months = pd.PeriodIndex(issue_months.dt.to_period("M").unique())
    table = {}
    for m in months:
        future = [m + k for k in range(1, horizon + 1)]
        if m not in s.index or any(f not in s.index for f in future):
            table[m] = np.nan
        else:
            table[m] = float(s.loc[future].mean() - s.loc[m])
    return issue_months.dt.to_period("M").map(table).astype(float)
