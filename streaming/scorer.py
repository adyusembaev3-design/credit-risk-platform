"""Scores applications exactly as the batch modules do, one micro-batch at a time.

  PD (Module 2 LightGBM)
  -> baseline-scenario PD (Module 3 shift: beta x (0 - training-period unemployment change))
  -> risk band (deciles of baseline PD on the 2015 book, as in Module 4)
  -> decision from the optimized policy table (grade x risk band, Module 4)
  -> top-3 reason codes (SHAP)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from models import features as F
from models.reason_codes import top_reasons
from pipeline import config
from stress.glm import expit, logit


class PolicyScorer:
    def __init__(self, predict, contrib, beta: float, d_train: float, band_edges: np.ndarray,
                 policy: pd.DataFrame, categories: dict):
        self.predict, self.contrib = predict, contrib          # callables on a feature DataFrame
        self.shift = beta * (0.0 - d_train)
        self.band_edges = band_edges                             # 9 inner edges -> bands 1..10
        self.approve = {(g, int(b)): bool(a) for g, b, a in policy[["grade", "risk_band", "approve"]].itertuples(index=False)}
        self.categories = categories

    @classmethod
    def from_artifacts(cls, root: Path = config.ROOT) -> "PolicyScorer":
        import lightgbm as lgb

        art = root / "models" / "artifacts"
        booster = lgb.Booster(model_file=str(art / "lgbm_model.txt"))
        stress = json.loads((root / "reports" / "stress_results.json").read_text())
        book = pd.read_parquet(root / "data" / "processed" / "stressed_book.parquet", columns=["pd_baseline"])
        edges = np.quantile(book["pd_baseline"], np.linspace(0, 1, 11)[1:-1])
        policy = pd.read_parquet(root / "data" / "processed" / "policy_segments.parquet")
        return cls(booster.predict, lambda X: booster.predict(X, pred_contrib=True)[:, :-1],
                   stress["sensitivity"]["beta_per_pp"], stress["d_unemp_train"], edges, policy,
                   json.loads((art / "gbm_categories.json").read_text()))

    def matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        from models.train import gbm_matrix

        return gbm_matrix(df, self.categories)

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        X = self.matrix(df)
        p = np.asarray(self.predict(X), float)
        p_base = expit(logit(p) + self.shift)
        band = np.searchsorted(self.band_edges, p_base, side="right") + 1
        approve = np.array([self.approve.get((g, int(b)), False) for g, b in zip(df["grade"], band)])
        reasons = top_reasons(np.asarray(self.contrib(X)), F.FEATURES)
        out = pd.DataFrame({"loan_id": df["loan_id"].to_numpy(), "pd": p, "pd_baseline": p_base,
                            "risk_band": band, "approve": approve})
        return pd.concat([out, reasons[["reason_1", "reason_2", "reason_3"]]], axis=1)
