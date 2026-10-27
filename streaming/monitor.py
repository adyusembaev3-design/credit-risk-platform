"""Rolling monitors for a live scoring stream, with alerting.

Every metric is computed on the last WINDOW applications and compared with a
reference (the training population, or the stream's own first window).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from streaming import config as C


def psi(reference_counts: np.ndarray, actual_counts: np.ndarray) -> float:
    e = np.clip(reference_counts / max(reference_counts.sum(), 1), 1e-6, None)
    a = np.clip(actual_counts / max(actual_counts.sum(), 1), 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


class RollingPSI:
    """PSI of a rolling window against a fixed reference, using the reference's deciles."""

    def __init__(self, reference: np.ndarray, window: int = C.WINDOW, bins: int = 10):
        ref = np.asarray(reference, float)
        ref = ref[~np.isnan(ref)]
        edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
        edges[0], edges[-1] = -np.inf, np.inf
        self.edges = edges
        self.ref_counts = np.histogram(ref, edges)[0].astype(float)
        self.window = deque(maxlen=window)

    def update(self, values) -> None:
        self.window.extend(v for v in np.asarray(values, float) if not np.isnan(v))

    @property
    def value(self) -> float:
        if not self.window:
            return 0.0
        return psi(self.ref_counts, np.histogram(np.fromiter(self.window, float), self.edges)[0].astype(float))


class RollingMean:
    def __init__(self, window: int = C.WINDOW):
        self.window = deque(maxlen=window)

    def update(self, values) -> None:
        self.window.extend(np.asarray(values, float))

    @property
    def value(self) -> float:
        return float(np.mean(self.window)) if self.window else float("nan")

    def __len__(self) -> int:
        return len(self.window)


@dataclass
class Alert:
    rule: str
    first_at: int           # applications processed when it first fired
    value: float
    threshold: float
    active: bool = True


@dataclass
class StreamMonitor:
    score_reference: np.ndarray
    feature_reference: dict[str, np.ndarray]
    window: int = C.WINDOW
    processed: int = 0
    alerts: dict[str, Alert] = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)
    _approval_baseline: float | None = None

    def __post_init__(self):
        self.score_psi = RollingPSI(self.score_reference, self.window)
        self.feature_psi = {f: RollingPSI(v, self.window) for f, v in self.feature_reference.items()}
        self.approval = RollingMean(self.window)
        self.pred = RollingMean(self.window)
        self.observed = RollingMean(self.window)
        self.latency_ms = deque(maxlen=self.window)

    def update(self, pd_scores, features: dict[str, np.ndarray], approved, outcomes=None,
               latency_ms: float | None = None, n: int | None = None) -> dict:
        n = n or len(pd_scores)
        self.processed += n
        self.score_psi.update(pd_scores)
        for f, m in self.feature_psi.items():
            m.update(features[f])
        self.approval.update(approved)
        self.pred.update(pd_scores)
        if outcomes is not None:
            self.observed.update(outcomes)
        if latency_ms is not None:
            self.latency_ms.extend([latency_ms] * n)
        snap = self.snapshot()
        self._check(snap)
        self.timeline.append(snap)
        return snap

    def snapshot(self) -> dict:
        lat_p95 = float(np.percentile(np.fromiter(self.latency_ms, float), 95)) if self.latency_ms else float("nan")
        obs, pred = self.observed.value, self.pred.value
        return {
            "processed": self.processed,
            "score_psi": self.score_psi.value,
            **{f"psi_{f}": m.value for f, m in self.feature_psi.items()},
            "approval_rate": self.approval.value,
            "mean_pd": pred,
            "observed_default_rate": obs,
            "calibration_ratio": obs / pred if pred and not np.isnan(obs) else float("nan"),
            "latency_p95_ms": lat_p95,
        }

    def _fire(self, rule: str, value: float, threshold: float, breached: bool) -> None:
        if breached and rule not in self.alerts:
            self.alerts[rule] = Alert(rule, self.processed, value, threshold)
        elif rule in self.alerts:
            self.alerts[rule].active = breached

    def _check(self, s: dict) -> None:
        if len(self.approval) < min(C.MIN_WINDOW, self.window):
            return
        if self._approval_baseline is None:
            self._approval_baseline = s["approval_rate"]
        self._fire("score_psi", s["score_psi"], C.PSI_ALERT, s["score_psi"] > C.PSI_ALERT)
        for f in self.feature_psi:
            self._fire(f"feature_psi:{f}", s[f"psi_{f}"], C.PSI_ALERT, s[f"psi_{f}"] > C.PSI_ALERT)
        drop = self._approval_baseline - s["approval_rate"]
        self._fire("approval_rate_drop", drop, C.APPROVAL_DROP, drop > C.APPROVAL_DROP)
        if not np.isnan(s["calibration_ratio"]):
            self._fire("calibration", s["calibration_ratio"], C.CALIBRATION_ALERT,
                       s["calibration_ratio"] > C.CALIBRATION_ALERT)
        if not np.isnan(s["latency_p95_ms"]):
            self._fire("latency_p95", s["latency_p95_ms"], C.LATENCY_P95_MS, s["latency_p95_ms"] > C.LATENCY_P95_MS)
