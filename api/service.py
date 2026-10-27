"""The decision service behind the API: loads the bundle once, scores applications.

Kept free of web-framework code so it can be tested and reused on its own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from models import features as F
from streaming.scorer import PolicyScorer
from stress.glm import expit, logit

SMALL_BATCH = 64
BUNDLE = Path(os.environ.get("BUNDLE_DIR", Path(__file__).resolve().parent / "bundle"))


class Platform:
    def __init__(self, bundle: Path = BUNDLE, predict=None, contrib=None):
        bundle = Path(bundle)
        if not (bundle / "scorer.json").exists():
            raise FileNotFoundError(f"No bundle in {bundle}. Run: python -m api.export")
        cfg = json.loads((bundle / "scorer.json").read_text())
        if predict is None:                                    # real model; tests pass stand-ins
            import lightgbm as lgb

            booster = lgb.Booster(model_file=str(bundle / "lgbm_model.txt"))
            # One thread for small requests: each API request already runs in its own worker thread,
            # and letting every request start a full OpenMP thread pool makes them fight over the CPU.
            threads = lambda X: 1 if len(X) < SMALL_BATCH else 0  # noqa: E731  (0 = LightGBM default)
            predict = lambda X: booster.predict(X, num_threads=threads(X))  # noqa: E731
            contrib = lambda X: booster.predict(X, pred_contrib=True, num_threads=threads(X))[:, :-1]  # noqa: E731
        self.cfg = cfg
        self.version = cfg["model_version"]
        self.beta, self.d_train = cfg["beta_per_pp"], cfg["d_unemp_train"]
        self.scenarios: dict[str, float] = cfg["scenarios"]
        self.scorer = PolicyScorer(predict, contrib, self.beta, self.d_train, np.array(cfg["band_edges"]),
                                   pd.DataFrame(cfg["policy"]), cfg["categories"])
        self.grid = json.loads((bundle / "stress_grid.json").read_text())
        self.samples = json.loads((bundle / "samples.json").read_text())
        self.dashboard = json.loads((bundle / "dashboard.json").read_text())

    # --- scoring -----------------------------------------------------------------
    def score(self, applications: list[dict]) -> list[dict]:
        df = pd.DataFrame(applications)
        for c in F.FEATURES:                                   # missing fields -> missing values
            if c not in df:
                df[c] = np.nan if c in F.NUMERIC else None
        df[F.NUMERIC] = df[F.NUMERIC].astype(float)
        if "loan_id" not in df:
            df["loan_id"] = None
        df["loan_id"] = [lid if lid is not None else f"app-{i + 1}" for i, lid in enumerate(df["loan_id"])]
        dec = self.scorer.score(df)
        lp = logit(dec["pd"].to_numpy())
        out = []
        for i, r in enumerate(dec.itertuples(index=False)):
            out.append({
                "loan_id": r.loan_id,
                "decision": "approve" if r.approve else "decline",
                "pd": float(r.pd),
                "pd_baseline": float(r.pd_baseline),
                "risk_band": int(r.risk_band),
                "grade": df["grade"].iloc[i],
                "pd_by_scenario": {s: float(expit(lp[i] + self.beta * (d - self.d_train)))
                                   for s, d in self.scenarios.items()},
                "reasons": [{"feature": getattr(r, f"reason_{k}_feature"), "text": getattr(r, f"reason_{k}")}
                            for k in (1, 2, 3) if isinstance(getattr(r, f"reason_{k}"), str)],  # empty slot: None or NaN
                "missing_fields": int(df.loc[i, F.FEATURES].isna().sum()),
            })
        return out

    # --- read-only views ------------------------------------------------------------
    def stress(self, d_unemp: float) -> dict:
        """Book loss at an unemployment change (pp), snapped to the nearest 0.25 pp."""
        lo, hi = self.grid[0]["d_unemp"], self.grid[-1]["d_unemp"]
        if not lo <= d_unemp <= hi:
            raise ValueError(f"d_unemp must be between {lo} and {hi}")
        return min(self.grid, key=lambda g: abs(g["d_unemp"] - d_unemp))

    def sample(self, n: int = 1, seed: int | None = None) -> list[dict]:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(self.samples), size=min(n, len(self.samples)), replace=False)
        return [self.samples[i] for i in idx]

    def meta(self) -> dict:
        return {"model_version": self.version, "bundle_created_at": self.cfg.get("created_at"),
                "features": {"numeric": F.NUMERIC, "categorical": {c: self.cfg["categories"][c] for c in F.CATEGORICAL}},
                "excluded_for_fair_lending": F.FAIR_LENDING_EXCLUDED, "grades": list("ABCDEFG"),
                "scenarios": self.scenarios, "stress_range": [self.grid[0]["d_unemp"], self.grid[-1]["d_unemp"]],
                "reason_text": F.REASON_TEXT}
