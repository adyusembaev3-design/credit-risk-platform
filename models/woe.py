"""Weight-of-evidence binning and a points-based credit scorecard.

WOE is the classic way banks prepare data for a logistic scorecard:
each feature is cut into bins, and each bin is replaced by
    WOE = ln(share of all bads in the bin / share of all goods in the bin)
so a positive WOE means the bin is riskier than average. Information value
(IV) summarizes how well a feature separates goods from bads.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

MISSING = "MISSING"


def _num(x: float) -> str:
    if math.isinf(x):
        return "-inf" if x < 0 else "inf"
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.3g}"
OTHER = "OTHER"


class WoeBinner:
    def __init__(self, n_bins: int = 10, min_cat_share: float = 0.01, smoothing: float = 0.5):
        self.n_bins = n_bins
        self.min_cat_share = min_cat_share
        self.smoothing = smoothing
        self.edges: dict[str, list[float]] = {}
        self.levels: dict[str, list[str]] = {}
        self.woe: dict[str, dict[str, float]] = {}
        self.iv: dict[str, float] = {}
        self.tables: dict[str, pd.DataFrame] = {}

    # --- binning -------------------------------------------------------------
    def _bin_numeric(self, s: pd.Series, col: str) -> pd.Series:
        edges = self.edges[col]
        idx = np.searchsorted(edges, s.to_numpy(dtype=float), side="right")
        labels = pd.Series([f"bin{int(i):02d}" for i in idx], index=s.index)
        labels[s.isna()] = MISSING
        return labels

    def _bin_categorical(self, s: pd.Series, col: str) -> pd.Series:
        known = set(self.levels[col])
        out = s.astype("object").where(s.notna(), MISSING).astype(str)
        return out.where(out.isin(known) | (out == MISSING), OTHER)

    def _bin(self, s: pd.Series, col: str) -> pd.Series:
        return self._bin_numeric(s, col) if col in self.edges else self._bin_categorical(s, col)

    def _bin_label(self, col: str, label: str) -> str:
        """Human-readable range for a numeric bin, e.g. '[680, 700)'."""
        if col not in self.edges or label in (MISSING, OTHER):
            return label
        i = int(label[3:])
        bounds = [-math.inf] + self.edges[col] + [math.inf]
        return f"[{_num(bounds[i])}, {_num(bounds[i + 1])})"

    # --- fit / transform -----------------------------------------------------
    def fit(self, X: pd.DataFrame, y: pd.Series, numeric: list[str], categorical: list[str]) -> "WoeBinner":
        y = y.to_numpy()
        n_bad, n_good = y.sum(), len(y) - y.sum()
        for col in numeric:
            vals = X[col].dropna().to_numpy(dtype=float)
            qs = np.quantile(vals, np.linspace(0, 1, self.n_bins + 1)[1:-1]) if len(vals) else []
            self.edges[col] = sorted(set(float(q) for q in qs))
        for col in categorical:
            share = X[col].value_counts(normalize=True, dropna=True)
            self.levels[col] = sorted(share[share >= self.min_cat_share].index.astype(str))

        for col in numeric + categorical:
            bins = self._bin(X[col], col)
            tab = pd.DataFrame({"bin": bins.to_numpy(), "bad": y}).groupby("bin")["bad"].agg(["count", "sum"])
            tab.columns = ["n", "bads"]
            tab["goods"] = tab["n"] - tab["bads"]
            s = self.smoothing
            pct_bad = (tab["bads"] + s) / (n_bad + s * len(tab))
            pct_good = (tab["goods"] + s) / (n_good + s * len(tab))
            tab["woe"] = np.log(pct_bad / pct_good)
            tab["iv"] = (pct_bad - pct_good) * tab["woe"]
            tab["bad_rate"] = tab["bads"] / tab["n"]
            tab["range"] = [self._bin_label(col, b) for b in tab.index]
            self.woe[col] = tab["woe"].to_dict()
            self.iv[col] = float(tab["iv"].sum())
            self.tables[col] = tab
        return self

    def transform(self, X: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        out = {}
        for col in cols:
            mapping = self.woe[col]
            out[col] = self._bin(X[col], col).map(mapping).fillna(0.0).astype(float)
        return pd.DataFrame(out, index=X.index)


class Scorecard:
    """Logistic regression on WOE features, converted to scorecard points.

    Points scale: 600 points = 50:1 odds of good to bad; every 20 points
    doubles the odds (industry-standard PDO scaling). Higher score = safer.
    """

    def __init__(self, min_iv: float = 0.02, base_score: float = 600, base_odds: float = 50, pdo: float = 20):
        self.min_iv = min_iv
        self.factor = pdo / math.log(2)
        self.offset = base_score - self.factor * math.log(base_odds)
        self.binner = WoeBinner()
        self.selected: list[str] = []
        self.model = LogisticRegression(C=1.0, max_iter=1000)

    def fit(self, X: pd.DataFrame, y: pd.Series, numeric: list[str], categorical: list[str]) -> "Scorecard":
        self.binner.fit(X, y, numeric, categorical)
        self.selected = [c for c in numeric + categorical if self.binner.iv[c] >= self.min_iv]
        self.model.fit(self.binner.transform(X, self.selected), y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self.binner.transform(X, self.selected))[:, 1]

    def score(self, X: pd.DataFrame) -> np.ndarray:
        p = np.clip(self.predict_proba(X), 1e-9, 1 - 1e-9)
        return self.offset + self.factor * np.log((1 - p) / p)

    def points_table(self) -> pd.DataFrame:
        """Points per bin. A borrower's score = sum of their bins' points."""
        coefs = dict(zip(self.selected, self.model.coef_[0]))
        n = len(self.selected)
        intercept = self.model.intercept_[0]
        rows = []
        for col in self.selected:
            tab = self.binner.tables[col]
            for b, r in tab.iterrows():
                pts = self.offset / n - self.factor * (coefs[col] * r["woe"] + intercept / n)
                rows.append({"feature": col, "bin": r["range"], "loans": int(r["n"]),
                             "bad_rate": round(float(r["bad_rate"]), 4), "woe": round(float(r["woe"]), 4),
                             "points": round(pts)})
        return pd.DataFrame(rows)

    def to_dict(self) -> dict:
        return {
            "selected_features": self.selected,
            "coefficients": dict(zip(self.selected, map(float, self.model.coef_[0]))),
            "intercept": float(self.model.intercept_[0]),
            "information_value": self.binner.iv,
            "numeric_edges": self.binner.edges,
            "categorical_levels": self.binner.levels,
            "woe": {c: {str(k): float(v) for k, v in m.items()} for c, m in self.binner.woe.items()},
            "scaling": {"offset": self.offset, "factor": self.factor},
        }
