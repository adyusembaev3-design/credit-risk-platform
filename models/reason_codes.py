"""Turn per-loan SHAP contributions into adverse-action style reason codes.

A lender that declines an applicant must say why. The top reasons are the
features that pushed this borrower's predicted risk up the most.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from models.features import REASON_TEXT


def top_reasons(contrib: np.ndarray, feature_names: list[str], k: int = 3) -> pd.DataFrame:
    """contrib: (n_loans, n_features) SHAP values in log-odds; positive = riskier.

    Returns one row per loan with reason_1..reason_k (plain text) and the
    matching feature names. Slots are empty when fewer than k features
    raised the risk.
    """
    order = np.argsort(-contrib, axis=1)[:, :k]
    out = {}
    for j in range(k):
        idx = order[:, j]
        positive = contrib[np.arange(len(contrib)), idx] > 0
        names = np.array(feature_names, dtype=object)[idx]
        out[f"reason_{j + 1}_feature"] = np.where(positive, names, None)
        out[f"reason_{j + 1}"] = [REASON_TEXT.get(n, n) if ok else None for n, ok in zip(names, positive)]
    return pd.DataFrame(out)


def mean_abs_contribution(contrib: np.ndarray, feature_names: list[str]) -> pd.DataFrame:
    """Global importance: mean |SHAP| per feature, largest first."""
    imp = np.abs(contrib).mean(axis=0)
    return (pd.DataFrame({"feature": feature_names, "mean_abs_shap": imp})
            .sort_values("mean_abs_shap", ascending=False, ignore_index=True))
