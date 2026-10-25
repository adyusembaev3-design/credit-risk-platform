"""Credit-model performance metrics: discrimination, calibration, stability."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score, roc_curve


def ks_statistic(y: np.ndarray, p: np.ndarray) -> float:
    """Max distance between cumulative bad and good distributions (0-1)."""
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def summarize(y: np.ndarray, p: np.ndarray) -> dict:
    auc = roc_auc_score(y, p)
    return {
        "auc": float(auc),
        "gini": float(2 * auc - 1),
        "ks": ks_statistic(y, p),
        "brier": float(brier_score_loss(y, p)) if p.min() >= 0 and p.max() <= 1 else None,
        "mean_pd": float(np.mean(p)) if p.min() >= 0 and p.max() <= 1 else None,
        "default_rate": float(np.mean(y)),
        "n": int(len(y)),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Predicted vs. actual default rate by predicted-risk decile."""
    df = pd.DataFrame({"y": y, "p": p})
    df["decile"] = pd.qcut(df["p"].rank(method="first"), n_bins, labels=range(1, n_bins + 1))
    out = df.groupby("decile", observed=True).agg(loans=("y", "size"), predicted=("p", "mean"), actual=("y", "mean"))
    out["ratio"] = out["actual"] / out["predicted"]
    return out.reset_index()


def psi(expected: np.ndarray, actual: np.ndarray, n_bins: int = 10) -> float:
    """Population stability index between two score distributions.

    < 0.10 stable, 0.10-0.25 moderate shift, > 0.25 significant shift.
    Bins are deciles of the expected (training) distribution.
    """
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, n_bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    e = np.histogram(expected, edges)[0] / len(expected)
    a = np.histogram(actual, edges)[0] / len(actual)
    e, a = np.clip(e, 1e-6, None), np.clip(a, 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))
