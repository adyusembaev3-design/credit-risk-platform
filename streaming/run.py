"""Module 6: live scoring and monitoring of loan applications.

The 2015 book is replayed as a stream of applications. Each micro-batch is scored
(PD, baseline-scenario PD, risk band, approve/decline, reason codes), and rolling
monitors track population stability, approval rate, calibration and latency.
Part-way through, a riskier acquisition channel is injected to test the alerts.

Backends
  memory   everything in one process; no Docker needed (tests, quick demo)
  kafka    producer -> Kafka topic -> scorer -> decisions topic, with Prometheus metrics
           (start the stack with: docker compose -f streaming/infra/docker-compose.yml up -d)

Usage:
    python -m streaming.run                                   # memory, 60K applications, drift at 30K
    python -m streaming.run --metrics-port 8000 --rate 500    # watch it live in Grafana
    python -m streaming.run --backend kafka --role producer --rate 500
    python -m streaming.run --backend kafka --role scorer --metrics-port 8000
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

from models.train import md_table  # noqa: E402
from pipeline import config  # noqa: E402
from streaming import config as C  # noqa: E402
from streaming.monitor import StreamMonitor  # noqa: E402
from streaming.source import inject_drift, load_applications  # noqa: E402


# --- metrics -----------------------------------------------------------------------
class Metrics:
    """Prometheus metrics; a no-op when no port is given."""

    def __init__(self, port: int | None):
        self.on = port is not None
        if not self.on:
            return
        from prometheus_client import Counter, Gauge, Histogram, start_http_server

        self.scored = Counter("credit_applications_scored_total", "Applications scored")
        self.approved = Counter("credit_applications_approved_total", "Applications approved")
        self.latency = Histogram("credit_score_latency_seconds", "Scoring latency per application",
                                 buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1))
        self.gauges = {k: Gauge(f"credit_{k}", k.replace("_", " ")) for k in
                       ("score_psi", "approval_rate", "mean_pd", "observed_default_rate", "calibration_ratio",
                        "latency_p95_ms")}
        self.feature_psi = Gauge("credit_feature_psi", "Feature PSI vs training", ["feature"])
        self.alerts = Gauge("credit_alert_active", "Alert active (1) or not (0)", ["rule"])
        start_http_server(port)
        print(f"Prometheus metrics on http://localhost:{port}/metrics")

    def record(self, n: int, n_approved: int, seconds_per_app: float, snap: dict, alerts) -> None:
        if not self.on:
            return
        self.scored.inc(n)
        self.approved.inc(n_approved)
        for _ in range(min(n, 50)):           # sample observations; enough for quantiles
            self.latency.observe(seconds_per_app)
        for k, g in self.gauges.items():
            if not np.isnan(snap[k]):
                g.set(snap[k])
        for f in C.MONITORED_FEATURES:
            self.feature_psi.labels(feature=f).set(snap[f"psi_{f}"])
        for rule, a in alerts.items():
            self.alerts.labels(rule=rule).set(1 if a.active else 0)


# --- core loop ---------------------------------------------------------------------
def make_monitor(loans: pd.DataFrame, scored: pd.DataFrame, window: int) -> StreamMonitor:
    train = loans[loans["split"] == "train"]
    return StreamMonitor(scored.loc[scored["split"] == "train", "pd_gbm"].to_numpy(),
                         {f: train[f].to_numpy(float) for f in C.MONITORED_FEATURES}, window=window)


def process_batch(scorer, monitor: StreamMonitor, batch: pd.DataFrame, metrics: Metrics) -> pd.DataFrame:
    t0 = time.perf_counter()
    dec = scorer.score(batch)
    per_app = (time.perf_counter() - t0) / max(len(batch), 1)
    snap = monitor.update(dec["pd"].to_numpy(), {f: batch[f].to_numpy(float) for f in C.MONITORED_FEATURES},
                          dec["approve"].to_numpy(float),
                          batch["is_default"].to_numpy(float) if "is_default" in batch else None,
                          latency_ms=per_app * 1000, n=len(batch))
    metrics.record(len(batch), int(dec["approve"].sum()), per_app, snap, monitor.alerts)
    return dec


def run_memory(scorer, apps: pd.DataFrame, monitor: StreamMonitor, drift_at: int | None, metrics: Metrics,
               rate: float = 0, batch: int = C.BATCH, seed: int = 0) -> pd.DataFrame:
    out = []
    t_start = time.time()
    for start in range(0, len(apps), batch):
        b = inject_drift(apps.iloc[start:start + batch], start, drift_at, seed)
        out.append(process_batch(scorer, monitor, b, metrics))
        if rate:
            ahead = (start + len(b)) / rate - (time.time() - t_start)
            if ahead > 0:
                time.sleep(ahead)
    return pd.concat(out, ignore_index=True)


def _json_default(v):
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        return str(v)[:10]
    if isinstance(v, np.generic):
        return v.item()
    return str(v)


def run_producer(apps: pd.DataFrame, drift_at: int | None, rate: float, seed: int = 0) -> None:
    from confluent_kafka import Producer

    p = Producer({"bootstrap.servers": C.KAFKA_BOOTSTRAP, "linger.ms": 20})
    t_start, sent = time.time(), 0
    for start in range(0, len(apps), C.BATCH):
        b = inject_drift(apps.iloc[start:start + C.BATCH], start, drift_at, seed)
        for rec in b.to_dict(orient="records"):
            rec = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in rec.items()}
            p.produce(C.TOPIC_APPLICATIONS, key=str(rec["loan_id"]), value=json.dumps(rec, default=_json_default))
        p.poll(0)
        sent += len(b)
        if rate:
            ahead = sent / rate - (time.time() - t_start)
            if ahead > 0:
                time.sleep(ahead)
        if sent % 10_000 < C.BATCH:
            print(f"  sent {sent:,} applications")
    p.flush()
    print(f"Producer done: {sent:,} applications -> {C.TOPIC_APPLICATIONS}")


def run_kafka_scorer(scorer, monitor: StreamMonitor, metrics: Metrics, limit: int | None,
                     idle_seconds: float = 30) -> pd.DataFrame:
    from confluent_kafka import Consumer, Producer

    cons = Consumer({"bootstrap.servers": C.KAFKA_BOOTSTRAP, "group.id": "credit-scorer",
                     "auto.offset.reset": "earliest", "enable.auto.commit": True})
    cons.subscribe([C.TOPIC_APPLICATIONS])
    prod = Producer({"bootstrap.servers": C.KAFKA_BOOTSTRAP})
    out, last = [], time.time()
    try:
        while limit is None or monitor.processed < limit:
            msgs = cons.consume(num_messages=C.BATCH, timeout=1.0)
            msgs = [m for m in msgs if m.error() is None]
            if not msgs:
                if time.time() - last > idle_seconds:
                    print(f"No applications for {idle_seconds:.0f}s; stopping.")
                    break
                continue
            last = time.time()
            batch = pd.DataFrame([json.loads(m.value()) for m in msgs])
            dec = process_batch(scorer, monitor, batch, metrics)
            for rec in dec.to_dict(orient="records"):
                prod.produce(C.TOPIC_DECISIONS, key=str(rec["loan_id"]), value=json.dumps(rec, default=_json_default))
            prod.poll(0)
            out.append(dec)
            if monitor.processed % 10_000 < C.BATCH:
                print(f"  scored {monitor.processed:,}")
    finally:
        prod.flush()
        cons.close()
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# --- report ------------------------------------------------------------------------
def plot_timeline(tl: pd.DataFrame, drift_at: int | None, path: Path) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    ax1.plot(tl["processed"], tl["score_psi"], color="#1f4e8c", linewidth=2, label="Predicted PD")
    for f, c in zip(C.MONITORED_FEATURES, ("#c0504d", "#e39b3a", "#6a9f58", "#8064a2", "#7f7f7f", "#4bacc6")):
        ax1.plot(tl["processed"], tl[f"psi_{f}"], color=c, linewidth=1, alpha=0.8, label=f)
    ax1.axhline(C.PSI_ALERT, color="grey", linestyle="--", linewidth=0.8)
    ax1.text(tl["processed"].iloc[0], C.PSI_ALERT * 1.05, "alert threshold", fontsize=8, color="grey")
    ax1.set(ylabel="PSI vs. training", title="Population stability over the stream")
    ax1.legend(fontsize=7, ncol=1, frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    ax2.plot(tl["processed"], tl["approval_rate"], color="#1f4e8c", linewidth=1.6)
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax2.set(xlabel="Applications processed", ylabel="Approval rate (rolling)")
    ax2.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    for ax in (ax1, ax2):
        if drift_at:
            ax.axvline(drift_at, color="#c0504d", linestyle=":", linewidth=1)
    if drift_at:
        ax2.text(drift_at, ax2.get_ylim()[0], " drift starts", fontsize=8, color="#c0504d", va="bottom")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_report(path: Path, monitor: StreamMonitor, decisions: pd.DataFrame, drift_at: int | None,
                 seconds: float, backend: str) -> dict:
    tl = pd.DataFrame(monitor.timeline)
    n = monitor.processed
    alerts = pd.DataFrame([{"rule": a.rule, "first_fired_at": a.first_at,
                            "detection_delay": (a.first_at - drift_at) if drift_at and a.first_at >= drift_at else None,
                            "value": a.value, "threshold": a.threshold, "active_at_end": a.active}
                           for a in monitor.alerts.values()])
    pre = decisions.iloc[:drift_at] if drift_at else decisions
    post = decisions.iloc[drift_at:] if drift_at else decisions.iloc[0:0]
    drift_alerts = alerts[alerts["detection_delay"].notna()] if len(alerts) else alerts
    first = drift_alerts.sort_values("first_fired_at").iloc[0] if len(drift_alerts) else None
    false_alarms = alerts[alerts["first_fired_at"] < drift_at] if drift_at and len(alerts) else alerts.iloc[0:0]
    summary = {
        "backend": backend, "applications": n, "seconds": seconds, "throughput_per_s": n / seconds if seconds else None,
        "latency_p95_ms": tl["latency_p95_ms"].iloc[-1] if len(tl) else None, "drift_at": drift_at,
        "first_alert": None if first is None else {"rule": first["rule"], "at": int(first["first_fired_at"]),
                                                   "delay": int(first["detection_delay"])},
        "false_alarms_before_drift": int(len(false_alarms)),
        "approval_rate_before": float(pre["approve"].mean()) if len(pre) else None,
        "approval_rate_after": float(post["approve"].mean()) if len(post) else None,
    }
    lead = (f"Injected drift at application {drift_at:,} was detected after **{summary['first_alert']['delay']:,} "
            f"applications** by the `{summary['first_alert']['rule']}` alert, with "
            f"{summary['false_alarms_before_drift']} false alarm(s) before it." if first is not None and drift_at
            else "No drift alert fired." if drift_at else "No drift was injected in this run.")
    lines = [
        "# Live scoring and monitoring report",
        "",
        lead,
        "",
        f"Backend: {backend} · {n:,} applications in {seconds:,.0f}s ({summary['throughput_per_s']:,.0f}/s) · "
        f"p95 scoring latency {summary['latency_p95_ms']:.2f} ms per application · rolling window {monitor.window:,}.",
        "",
        "## Alerts",
        "",
        md_table(alerts, {"first_fired_at": ",", "detection_delay": ",.0f", "value": ".3f", "threshold": ".2f"})
        if len(alerts) else "None fired.",
        "",
        "![Timeline](figures/monitoring_timeline.png)",
        "",
        "## Decisions",
        "",
        md_table(pd.DataFrame([
            {"period": "before drift" if drift_at else "all", "applications": len(pre),
             "approval_rate": pre["approve"].mean() if len(pre) else float("nan"),
             "mean_pd": pre["pd"].mean() if len(pre) else float("nan")},
            *([{"period": "after drift", "applications": len(post), "approval_rate": post["approve"].mean(),
                "mean_pd": post["pd"].mean()}] if len(post) else []),
        ]), {"applications": ",", "approval_rate": ".1%", "mean_pd": ".2%"}),
        "",
        "## Drift scenario",
        "",
        f"From application {drift_at:,}, {C.DRIFT_SHARE:.0%} of applicants come from a riskier channel: "
        + ", ".join(f"{k} {v:+g}" for k, v in C.DRIFT_SHIFT.items()) + "." if drift_at else "None.",
        "",
        "## Monitors",
        "",
        "| Monitor | Alert when |",
        "| --- | --- |",
        f"| PSI of predicted PD and of {len(C.MONITORED_FEATURES)} key inputs vs. training | > {C.PSI_ALERT} |",
        f"| Approval rate vs. its first window | drops by more than {C.APPROVAL_DROP:.0%} |",
        f"| Observed / predicted default rate | > {C.CALIBRATION_ALERT} |",
        f"| p95 scoring latency | > {C.LATENCY_P95_MS:.0f} ms |",
        "",
        "In this replay the outcome labels are the loans' real outcomes, so they do not react to injected drift: "
        "the calibration monitor shows the live-model gap but is not expected to fire for the synthetic drift.",
        "",
    ]
    path.write_text("\n".join(lines))
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend", choices=["memory", "kafka"], default="memory")
    p.add_argument("--role", choices=["producer", "scorer"], help="kafka backend only")
    p.add_argument("--limit", type=int, default=60_000, help="applications to replay (0 = all 283K)")
    p.add_argument("--drift-at", type=int, default=30_000, help="0 = no drift")
    p.add_argument("--rate", type=float, default=0, help="applications per second (0 = as fast as possible)")
    p.add_argument("--metrics-port", type=int)
    p.add_argument("--window", type=int, default=C.WINDOW)
    a = p.parse_args()
    limit, drift_at = (a.limit or None), (a.drift_at or None)

    loans = pd.read_parquet(config.PROCESSED_DIR / "loans_model.parquet")
    apps = load_applications(loans, limit)

    if a.backend == "kafka" and a.role == "producer":
        run_producer(apps, drift_at, a.rate)
        return

    from streaming.scorer import PolicyScorer

    scored = pd.read_parquet(config.PROCESSED_DIR / "scored_loans.parquet", columns=["split", "pd_gbm"])
    monitor = make_monitor(loans, scored, a.window)
    scorer = PolicyScorer.from_artifacts()
    metrics = Metrics(a.metrics_port)
    t0 = time.time()
    if a.backend == "kafka":
        decisions = run_kafka_scorer(scorer, monitor, metrics, limit)
    else:
        decisions = run_memory(scorer, apps, monitor, drift_at, metrics, a.rate)
    secs = time.time() - t0
    (config.REPORTS_DIR / "figures").mkdir(parents=True, exist_ok=True)
    plot_timeline(pd.DataFrame(monitor.timeline), drift_at, config.REPORTS_DIR / "figures" / "monitoring_timeline.png")
    summary = write_report(config.REPORTS_DIR / "monitoring_report.md", monitor, decisions, drift_at, secs, a.backend)
    (config.REPORTS_DIR / "monitoring_results.json").write_text(json.dumps(summary, indent=2, default=float))
    decisions.to_parquet(config.PROCESSED_DIR / "stream_decisions.parquet", index=False)
    pd.DataFrame(monitor.timeline).to_json(config.REPORTS_DIR / "monitoring_timeline.json", orient="records")
    fa = summary["first_alert"]
    print(f"Scored {summary['applications']:,} applications in {secs:,.0f}s "
          f"({summary['throughput_per_s']:,.0f}/s, p95 {summary['latency_p95_ms']:.2f} ms)")
    if fa:
        print(f"Drift at {drift_at:,} detected after {fa['delay']:,} applications by {fa['rule']}; "
              f"{summary['false_alarms_before_drift']} false alarm(s) before drift")
    print(f"Report: {config.REPORTS_DIR / 'monitoring_report.md'}")
    if a.metrics_port:
        input("Metrics still served for Grafana. Press Enter to exit.")


if __name__ == "__main__":
    main()
