"""Interest-rate and credit-spread series from FRED, cached under data/raw/fred/.

  DGS3     3-year Treasury yield         (matches the 36-month loan term)
  DGS2     2-year Treasury yield
  DGS10    10-year Treasury yield
  BAA10Y   Moody's seasoned Baa corporate bond yield minus the 10-year Treasury

The Treasury series are US government data. BAA10Y includes Moody's data, which FRED
publishes with "citation required": it is cited in the report and is never copied into
the repository or the API bundle (data/raw/ is git-ignored). The ICE BofA option-adjusted
spread series are not used because FRED now carries only their last three years.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd

from pipeline import config

SERIES = {
    "DGS3": "3-year Treasury yield",
    "DGS2": "2-year Treasury yield",
    "DGS10": "10-year Treasury yield",
    "BAA10Y": "Baa corporate spread over 10-year Treasury",
}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
CACHE_DIR = config.RAW_DIR / "fred"
CITATION = ("Board of Governors of the Federal Reserve System (DGS2, DGS3, DGS10) and Moody's (BAA10Y), "
            "retrieved from FRED, Federal Reserve Bank of St. Louis, https://fred.stlouisfed.org/")


def parse_fred_csv(text: str, series_id: str) -> pd.Series:
    """FRED CSV (daily or monthly) -> monthly average, indexed by Period('M'). '.' and blanks are missing."""
    df = pd.read_csv(StringIO(text))
    date_col = next(c for c in df.columns if c.lower() in ("observation_date", "date"))
    s = pd.Series(pd.to_numeric(df[series_id], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df[date_col]).dt.to_period("M"), name=series_id)
    return s.dropna().groupby(level=0).mean().sort_index()


def load_series(ids=tuple(SERIES), cache_dir: Path = CACHE_DIR, refresh: bool = False) -> pd.DataFrame:
    """Monthly averages of the requested series, one column each. Downloads once, then reads the cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for sid in ids:
        path = cache_dir / f"{sid}.csv"
        if refresh or not path.exists():
            import requests

            resp = requests.get(URL.format(sid), timeout=30)
            resp.raise_for_status()
            path.write_text(resp.text)
            print(f"Downloaded {sid} from FRED -> {path}")
        out[sid] = parse_fred_csv(path.read_text(), sid)
    return pd.DataFrame(out).sort_index()


def forward_change(issue_dates: pd.Series, series: pd.Series, horizon: int) -> pd.Series:
    """Average of the series over months 1..horizon after issue, minus its value in the issue month.

    Same definition as the unemployment shock in Module 3 (stress/macro.py). NaN when the
    series does not cover the full horizon.
    """
    s = series.dropna()
    months = issue_dates.dt.to_period("M")
    table = {}
    for m in months.unique():
        future = [m + k for k in range(1, horizon + 1)]
        table[m] = (float(s.loc[future].mean() - s.loc[m])
                    if m in s.index and all(f in s.index for f in future) else float("nan"))
    return months.map(table).astype(float)


def at_issue(issue_dates: pd.Series, series: pd.Series) -> pd.Series:
    """Value of a monthly series in each loan's issue month."""
    return issue_dates.dt.to_period("M").map(series.to_dict()).astype(float)
