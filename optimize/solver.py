"""Approve-or-decline credit policy as a mixed-integer program.

Each segment s (grade x predicted-risk decile) is approved (x_s = 1) or declined (x_s = 0).

    maximize   sum_s x_s * profit_s                          (expected, baseline economy)
    subject to sum_s x_s * (severe_loss_s - L * exposure_s) <= 0     severe-scenario loss <= L
               sum_s x_s * exposure_s >= V * total exposure          keep origination volume
               sum_s x_s * (risky_s - C) * exposure_s <= 0           grades E-G <= C of approved
               x_s in {0, 1}

Solved with HiGHS (via SciPy) by default, or Gurobi when gurobipy is installed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Constraints:
    max_severe_loss_rate: float = 0.10
    min_volume_share: float = 0.50
    max_risky_share: float = 0.15


@dataclass
class Solution:
    approve: np.ndarray
    status: str
    objective: float


def _rows(profit, exposure, severe_loss, risky, total_exposure, c: Constraints):
    A = np.vstack([
        severe_loss - c.max_severe_loss_rate * exposure,
        -exposure,
        (risky.astype(float) - c.max_risky_share) * exposure,
    ])
    ub = np.array([0.0, -c.min_volume_share * total_exposure, 0.0])
    return A, ub


def solve(profit: np.ndarray, exposure: np.ndarray, severe_loss: np.ndarray, risky: np.ndarray,
          c: Constraints, solver: str = "highs") -> Solution:
    profit, exposure, severe_loss = map(np.asarray, (profit, exposure, severe_loss))
    A, ub = _rows(profit, exposure, severe_loss, np.asarray(risky), exposure.sum(), c)
    if solver == "gurobi":
        return _solve_gurobi(profit, A, ub)
    from scipy.optimize import Bounds, LinearConstraint, milp

    res = milp(c=-profit, constraints=LinearConstraint(A, -np.inf, ub),
               integrality=np.ones_like(profit), bounds=Bounds(0, 1))
    if res.x is None:
        return Solution(np.zeros(len(profit), dtype=bool), "infeasible", float("nan"))
    x = np.round(res.x).astype(bool)
    return Solution(x, "optimal" if res.success else res.message, float(profit[x].sum()))


def _solve_gurobi(profit: np.ndarray, A: np.ndarray, ub: np.ndarray) -> Solution:
    import gurobipy as gp

    m = gp.Model("credit_policy")
    m.Params.OutputFlag = 0
    x = m.addMVar(len(profit), vtype=gp.GRB.BINARY)
    m.setObjective(profit @ x, gp.GRB.MAXIMIZE)
    m.addConstr(A @ x <= ub)
    m.optimize()
    if m.Status != gp.GRB.OPTIMAL:
        return Solution(np.zeros(len(profit), dtype=bool), "infeasible", float("nan"))
    xs = np.round(x.X).astype(bool)
    return Solution(xs, "optimal", float(profit[xs].sum()))


def is_feasible(approve: np.ndarray, exposure, severe_loss, risky, c: Constraints, tol: float = 1e-6) -> bool:
    A, ub = _rows(None, np.asarray(exposure), np.asarray(severe_loss), np.asarray(risky), np.sum(exposure), c)
    return bool(np.all(A @ approve.astype(float) <= ub + tol * np.sum(exposure)))
