"""Settings for live scoring and monitoring (Module 6)."""

import os

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
TOPIC_APPLICATIONS = "credit.applications"
TOPIC_DECISIONS = "credit.decisions"
METRICS_PORT = 8000

WINDOW = 5_000            # applications in each rolling monitoring window
BATCH = 250               # applications scored per micro-batch
MIN_WINDOW = 2_000        # do not alert until the window holds this many applications

# Monitored inputs (PSI vs. training distribution)
MONITORED_FEATURES = ("fico_mid", "dti", "bc_util", "acc_open_past_24mths", "annual_inc", "loan_to_income")

# Alert thresholds (mirrored in streaming/infra/alert_rules.yml)
PSI_ALERT = 0.20          # score or feature population shift
APPROVAL_DROP = 0.10      # approval rate falls this far below its first-window level
CALIBRATION_ALERT = 1.30  # observed / predicted default rate (hindsight labels in replay)
LATENCY_P95_MS = 50.0     # per-application scoring latency

# Drift scenario injected into the replay: a riskier acquisition channel
DRIFT_SHARE = 0.6         # share of applicants affected after drift starts
DRIFT_SHIFT = {"fico_mid": -40.0, "bc_util": +25.0, "acc_open_past_24mths": +3.0}
