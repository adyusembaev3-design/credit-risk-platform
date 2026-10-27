"""Fixed-income analytics for the loan book: amortization, spreads, duration, and market-signal GLMs.

All loans are 36-month level-payment loans. Prepayment is ignored, which makes the
weighted-average life and duration upper bounds (Lending Club borrowers prepay often).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stress.glm import expit, fit_binomial

TERM = 36
FICO_BANDS = [(0, 680), (680, 700), (700, 720), (720, 750), (750, 900)]   # same bands as stress/run.py


# --- cash-flow math ----------------------------------------------------------------
def schedule(rate_pct: float, months: int = TERM) -> tuple[np.ndarray, np.ndarray]:
    """(payment per $1, principal repaid per $1 in each month) for a level-payment loan."""
    r = rate_pct / 1200
    pay = 1 / months if r == 0 else r / (1 - (1 + r) ** -months)
    bal = 1.0
    principal = np.empty(months)
    for t in range(months):
        p = pay - bal * r
        principal[t] = p
        bal -= p
    return np.full(months, pay), principal


def wal_years(rate_pct: float, months: int = TERM) -> float:
    """Weighted-average life: average time until each dollar of principal comes back."""
    _, principal = schedule(rate_pct, months)
    t = np.arange(1, months + 1)
    return float((t * principal).sum() / principal.sum() / 12)


def price(rate_pct: float, yield_pct: float, months: int = TERM) -> float:
    """Value per $1 of principal of the loan's cash flows discounted at yield_pct (monthly compounding)."""
    pay, _ = schedule(rate_pct, months)
    t = np.arange(1, months + 1)
    return float((pay / (1 + yield_pct / 1200) ** t).sum())


def modified_duration(rate_pct: float, months: int = TERM) -> float:
    """-(1/P) dP/dy in years, at the loan's own rate (central difference over +/- 1 bp)."""
    up, down = price(rate_pct, rate_pct + 0.01, months), price(rate_pct, rate_pct - 0.01, months)
    return float((down - up) / (2 * price(rate_pct, rate_pct, months) * 0.0001))


def _by_rate(rates: pd.Series, fn) -> pd.Series:
    """Apply a per-rate function once per distinct rate (a few hundred), then map back."""
    uniq = {r: fn(r) for r in rates.round(2).unique()}
    return rates.round(2).map(uniq)


# --- 1. pricing and relative value --------------------------------------------------
def spread_table(book: pd.DataFrame, baa_spread_pct: float) -> pd.DataFrame:
    """Per grade, dollar-weighted: coupon, Treasury, spread, expected and realized annual loss, both in bp.

    book needs: grade, loan_amnt, int_rate, ust3 (3-yr Treasury at issue), pd, lgd, is_default, loss_rate.
    Annual loss = lifetime loss rate / weighted-average life.
    """
    b = book.copy()
    b["wal"] = _by_rate(b["int_rate"], wal_years)
    b["spread_bp"] = (b["int_rate"] - b["ust3"]) * 100
    b["el_bp"] = b["pd"] * b["lgd"] / b["wal"] * 1e4
    b["rl_bp"] = b["is_default"] * b["loss_rate"].fillna(0) / b["wal"] * 1e4
    def agg(g: pd.DataFrame) -> pd.Series:
        ww = g["loan_amnt"]
        avg = lambda c: float(np.average(g[c], weights=ww))  # noqa: E731
        return pd.Series({"loans": len(g), "principal_usd_m": ww.sum() / 1e6, "coupon": avg("int_rate"),
                          "treasury_3y": avg("ust3"), "spread_bp": avg("spread_bp"), "wal_years": avg("wal"),
                          "pd": avg("pd"), "lgd": avg("lgd"), "expected_loss_bp": avg("el_bp"),
                          "realized_loss_bp": avg("rl_bp")})

    t = b.groupby("grade").apply(agg, include_groups=False).reset_index()
    total = agg(b).to_frame().T.assign(grade="Book")
    t = pd.concat([t, total[t.columns]], ignore_index=True)
    t["loss_adjusted_spread_bp"] = t["spread_bp"] - t["expected_loss_bp"]
    t["realized_loss_adjusted_spread_bp"] = t["spread_bp"] - t["realized_loss_bp"]
    t["vs_baa_bp"] = t["loss_adjusted_spread_bp"] - baa_spread_pct * 100
    t["loans"] = t["loans"].astype(int)
    return t


# --- 2. interest-rate risk -----------------------------------------------------------
def rate_risk(book: pd.DataFrame, shocks_bp=(-100, 100, 200)) -> dict:
    """Value and funding-cost sensitivity of the book to parallel rate moves.

    Value: each loan's fixed cash flows re-discounted at (its own rate + shock).
    Funding: if the book were funded at a floating rate, extra interest paid over the
    loans' life per 100 bp = principal x WAL x 1%.
    """
    amt, rate = book["loan_amnt"].to_numpy(float), book["int_rate"]
    value = amt.sum()
    out = {"principal_usd_m": value / 1e6,
           "wal_years": float(np.average(_by_rate(rate, wal_years), weights=amt)),
           "modified_duration": float(np.average(_by_rate(rate, modified_duration), weights=amt)),
           "shocks": []}
    for s in shocks_bp:
        rel = _by_rate(rate, lambda r, s=s: price(r, r + s / 100) - 1).to_numpy()
        out["shocks"].append({"shock_bp": s, "value_change_usd_m": float((amt * rel).sum() / 1e6),
                              "value_change_pct": float((amt * rel).sum() / value)})
    dv01 = _by_rate(rate, lambda r: price(r, r + 0.01) - 1).to_numpy()
    out["dv01_usd"] = float((amt * dv01).sum())
    out["floating_funding_cost_per_100bp_usd_m"] = float((amt * _by_rate(rate, wal_years).to_numpy() * 0.01).sum() / 1e6)
    return out


# --- 3. do market signals explain defaults? -------------------------------------------
def fico_band(fico: pd.Series) -> pd.Series:
    labels = [f"{lo}-{hi - 1}" if lo else f"<{hi}" for lo, hi in FICO_BANDS]
    labels[-1] = f"{FICO_BANDS[-1][0]}+"
    edges = [b[0] for b in FICO_BANDS] + [FICO_BANDS[-1][1]]
    return pd.cut(fico, edges, right=False, labels=labels).astype(str)


def cohorts(loans: pd.DataFrame, covariates: list[str]) -> pd.DataFrame:
    """Issue-month x FICO-band cohorts with defaults, loans and the (cohort-constant) covariates."""
    d = loans.dropna(subset=covariates).copy()
    d["band"] = fico_band(d["fico_mid"])
    d["month"] = d["issue_date"].dt.to_period("M")
    agg = {"loans": ("is_default", "size"), "defaults": ("is_default", "sum"),
           **{c: (c, "first") for c in covariates}}
    return d.groupby(["month", "band"], observed=True).agg(**agg).reset_index()


def _design(c: pd.DataFrame, bands: list[str], covs: list[str]) -> np.ndarray:
    return np.column_stack([(c["band"] == b).astype(float) for b in bands] + [c[v].to_numpy(float) for v in covs])


def _deviance(y, n, p) -> float:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    with np.errstate(divide="ignore", invalid="ignore"):
        a = np.where(y > 0, y * np.log(y / (n * p)), 0.0)
        b = np.where(n - y > 0, (n - y) * np.log((n - y) / (n * (1 - p))), 0.0)
    return float(2 * (a + b).sum())


def compare_models(c: pd.DataFrame, models: dict[str, list[str]], split_month: str) -> pd.DataFrame:
    """Fit each covariate set on all cohorts (AIC, overdispersion-adjusted z), and on cohorts up to
    split_month to score deviance on the later ones (out-of-time). Lower AIC / deviance is better."""
    bands = sorted(c["band"].unique())
    early = c["month"] <= pd.Period(split_month, "M")
    rows = []
    for name, covs in models.items():
        X, y, n = _design(c, bands, covs), c["defaults"].to_numpy(float), c["loans"].to_numpy(float)
        res = fit_binomial(X, y, n, [f"band {b}" for b in bands] + covs)
        p = expit(X @ res.coef)
        pearson = float(np.sum((y - n * p) ** 2 / (n * p * (1 - p))))
        scale = max(1.0, pearson / (len(c) - X.shape[1]))
        Xe, ye, ne = X[early.to_numpy()], y[early.to_numpy()], n[early.to_numpy()]
        res_e = fit_binomial(Xe, ye, ne, res.names)
        late = ~early.to_numpy()
        oot = _deviance(y[late], n[late], expit(X[late] @ res_e.coef)) if late.any() else float("nan")
        row = {"model": name, "covariates": " + ".join(covs), "aic": _deviance(y, n, p) + 2 * X.shape[1],
               "oot_deviance": oot, "dispersion": scale}
        for v, b_, s in zip(covs, res.coef[len(bands):], res.se[len(bands):]):
            row[f"{v}_coef"] = float(b_)
            row[f"{v}_z_adj"] = float(b_ / (s * np.sqrt(scale)))
        rows.append(row)
    out = pd.DataFrame(rows)
    out["delta_aic"] = out["aic"] - out["aic"].min()
    return out
