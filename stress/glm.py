"""Binomial logistic regression on grouped data (defaults out of loans), fit by IRLS.

Small and dependency-free so the macro-sensitivity fit is transparent: it
returns coefficients with standard errors, which a model reviewer will ask for.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class GLMResult:
    coef: np.ndarray
    se: np.ndarray
    names: list[str]
    iterations: int

    @property
    def z(self) -> np.ndarray:
        return self.coef / self.se

    def as_dict(self) -> dict:
        return {n: {"coef": float(c), "se": float(s), "z": float(c / s)}
                for n, c, s in zip(self.names, self.coef, self.se)}


def fit_binomial(X: np.ndarray, successes: np.ndarray, trials: np.ndarray, names: list[str],
                 max_iter: int = 100, tol: float = 1e-10) -> GLMResult:
    X = np.asarray(X, dtype=float)
    y = np.asarray(successes, dtype=float)
    n = np.asarray(trials, dtype=float)
    p0 = np.clip((y + 0.5) / (n + 1.0), 1e-6, 1 - 1e-6)
    eta = np.log(p0 / (1 - p0))
    beta = np.linalg.lstsq(X, eta, rcond=None)[0]
    for it in range(1, max_iter + 1):
        eta = X @ beta
        p = 1.0 / (1.0 + np.exp(-eta))
        w = np.clip(n * p * (1 - p), 1e-12, None)
        z = eta + (y - n * p) / w
        XtW = X.T * w
        new = np.linalg.solve(XtW @ X, XtW @ z)
        if np.max(np.abs(new - beta)) < tol:
            beta = new
            break
        beta = new
    eta = X @ beta
    p = 1.0 / (1.0 + np.exp(-eta))
    w = n * p * (1 - p)
    cov = np.linalg.inv((X.T * w) @ X)
    return GLMResult(beta, np.sqrt(np.diag(cov)), names, it)


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def expit(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))
