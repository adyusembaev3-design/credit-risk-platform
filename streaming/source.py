"""Application stream: the 2015 book replayed in issue order, with optional injected drift."""

from __future__ import annotations

import numpy as np
import pandas as pd

from models import features as F
from streaming import config as C

# dict.fromkeys keeps order and drops duplicates (loan_amnt is also a model input)
KEEP = list(dict.fromkeys(["loan_id", "issue_date", "grade", "loan_amnt", "is_default"] + F.FEATURES))


def load_applications(loans: pd.DataFrame, limit: int | None = None, seed: int = 0) -> pd.DataFrame:
    """2015 loans in issue order (shuffled within each month, since only the month is known)."""
    oot = loans.loc[loans["split"] == "oot", [c for c in KEEP if c in loans.columns]].copy()
    rng = np.random.default_rng(seed)
    oot["_r"] = rng.random(len(oot))
    oot = oot.sort_values(["issue_date", "_r"]).drop(columns="_r").reset_index(drop=True)
    return oot.head(limit) if limit else oot


def inject_drift(batch: pd.DataFrame, start_index: int, drift_at: int | None, seed: int) -> pd.DataFrame:
    """From application number drift_at on, a share of applicants comes from a riskier channel."""
    if drift_at is None or start_index + len(batch) <= drift_at:
        return batch
    b = batch.copy()
    idx = np.arange(start_index, start_index + len(b))
    rng = np.random.default_rng(seed + start_index)
    hit = (idx >= drift_at) & (rng.random(len(b)) < C.DRIFT_SHARE)
    for col, delta in C.DRIFT_SHIFT.items():
        if col in b:
            b.loc[hit, col] = b.loc[hit, col] + delta
    if "fico_mid" in b:
        b["fico_mid"] = b["fico_mid"].clip(300, 850)
    if "bc_util" in b:
        b["bc_util"] = b["bc_util"].clip(0, 150)
    return b
