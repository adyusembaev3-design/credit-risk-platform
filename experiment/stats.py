"""Two-arm test statistics for a champion/challenger credit experiment."""

from __future__ import annotations

import numpy as np
from scipy import stats


def welch(a: np.ndarray, b: np.ndarray, alpha: float = 0.05) -> dict:
    """Difference in means b - a with a Welch t-test and confidence interval."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    diff, se = b.mean() - a.mean(), np.sqrt(va + vb)
    dof = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    t = diff / se
    q = stats.t.ppf(1 - alpha / 2, dof)
    return {"diff": float(diff), "se": float(se), "ci_low": float(diff - q * se), "ci_high": float(diff + q * se),
            "p_value": float(2 * stats.t.sf(abs(t), dof)), "dof": float(dof)}


def bootstrap_ci(a: np.ndarray, b: np.ndarray, n_boot: int = 500, alpha: float = 0.05, seed: int = 0) -> tuple:
    """Percentile bootstrap CI for b.mean() - a.mean() (robust to heavy-tailed loan profits)."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    draws = np.empty(n_boot)
    for i in range(n_boot):
        draws[i] = b[rng.integers(0, len(b), len(b))].mean() - a[rng.integers(0, len(a), len(a))].mean()
    return float(np.quantile(draws, alpha / 2)), float(np.quantile(draws, 1 - alpha / 2))


def two_proportion(xa: int, na: int, xb: int, nb: int) -> dict:
    """Difference in rates b - a with a pooled z-test."""
    pa, pb = xa / na, xb / nb
    p = (xa + xb) / (na + nb)
    se = np.sqrt(p * (1 - p) * (1 / na + 1 / nb))
    z = (pb - pa) / se if se > 0 else 0.0
    return {"rate_a": pa, "rate_b": pb, "diff": pb - pa, "p_value": float(2 * stats.norm.sf(abs(z)))}


def required_n_per_arm(effect: float, sd_a: float, sd_b: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Applicants per arm to detect a mean difference `effect` with a two-sided test."""
    if effect == 0:
        return int(1e12)
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return int(np.ceil(z ** 2 * (sd_a ** 2 + sd_b ** 2) / effect ** 2))
