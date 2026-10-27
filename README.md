# Consumer Credit Risk & Portfolio Decision Platform

**Live demo:** [https://credit-console.kp7p4tar0xwyc.ca-central-1.cs.amazonlightsail.com/](https://credit-console.kp7p4tar0xwyc.ca-central-1.cs.amazonlightsail.com/) (dashboard) · [API docs](https://credit-console.kp7p4tar0xwyc.ca-central-1.cs.amazonlightsail.com/docs)

End-to-end credit risk system on 2M+ public Lending Club loans: data pipeline, probability-of-default model, stress testing, portfolio optimization, real-time monitoring, model governance, and an AI risk analyst.

**Status:** Modules 1–8 complete (data pipeline, default model, stress testing, policy optimization, champion/challenger test, live monitoring, governance, AI risk analyst). Modules 9–10 in progress.

## Module 1: Data pipeline and data quality

Raw Lending Club CSV → typed staging table → modeling table → 17 automated data-quality controls → Parquet.

```
pipeline/
  sql/01_raw_loans.sql     load the file as text (one bad value can't break the load)
  sql/02_stg_loans.sql     type and clean every column
  sql/03_loans_model.sql   sample, target, split, application-time features only
  sql/04_loan_outcomes.sql realized losses, kept apart from the model table (loss severity only)
  quality_checks.py        controls DQ-01 to DQ-17; any FAIL stops the pipeline
  build.py                 runs the stages and the checks
docs/data_dictionary.md    every column in the modeling table
reports/data_quality.md    latest check results (written on each run)
```

**Sample:** matured 36-month loans issued 2007–2015 with a final outcome.
**Target:** `is_default` = 1 if Charged Off or Default.
**Split:** `history` 2007–2012 (kept for stress testing), train Jan 2013–Jun 2014, validation Jul–Dec 2014, out-of-time test 2015. The PD model starts in 2013 because the extended credit-bureau fields (utilization, recent account openings, credit limits) are 0% populated before 2012 and 99–100% from 2013.

### Data-quality controls

| ID | Control | Blocks pipeline |
| --- | --- | --- |
| DQ-01 | Enough rows to model | Yes |
| DQ-02 | `loan_id` unique | Yes |
| DQ-03 | Required fields never null | Yes |
| DQ-04 | Target is 0/1 | Yes |
| DQ-05 | Default rate in 5–30% | Yes |
| DQ-06 | Values in valid ranges | Yes (some warn) |
| DQ-07 | Feature null share ≤ 20% (model splits) | Warn |
| DQ-08 | No post-issue (leakage) fields | Yes |
| DQ-09 | No feature dated after issue | Yes |
| DQ-10 | Every loan in sample window with a split | Yes |
| DQ-11 | Every split populated | Yes |
| DQ-12 | Default rate rises A → G | Warn |
| DQ-13 | Installment reconciles to amount, rate, term | Warn |
| DQ-14 | Extended bureau fields ≥ 95% populated (model splits) | Yes |
| DQ-15 | Every model loan has an outcomes row | Yes |
| DQ-16 | Loss rate computable for ≥ 99% of defaults | Yes |
| DQ-17 | Average loss given default in 40–95% | Warn |

## Module 2: Probability-of-default model

Three ways to rank risk, compared on the same loans:

| Model | What it is |
| --- | --- |
| Sub-grade benchmark | Lending Club's own A1–G5 grade: the bar to beat |
| WOE scorecard | Logistic regression on weight-of-evidence bins, converted to points (600 = 50:1 odds, 20 points doubles the odds) |
| GBM | LightGBM with monotone constraints, exact SHAP reason codes per loan |

Inputs: 34 application-time fields, including 15 extended bureau attributes. Neither model uses grade, sub-grade or interest rate, since those are outputs of Lending Club's own model, nor state of residence, which was removed for fair-lending reasons (incident INC-006: state approval-rate ratio 0.41 → 0.84 at an AUC cost of 0.0007). Trained on Jan 2013–Jun 2014, early-stopped on Jul–Dec 2014, tested out-of-time on 2015. Results: [`reports/model_report.md`](reports/model_report.md).

```
models/
  features.py       inputs, excluded pricing fields, monotone directions, reason text
  woe.py            WOE binning, information value, points scorecard
  metrics.py        AUC, Gini, KS, Brier, calibration by decile, PSI
  reason_codes.py   top-3 SHAP reasons per loan
  train.py          trains all three, writes report, figures, artifacts, scored loans
```

Outputs: `reports/model_report.md`, `reports/figures/`, `reports/scorecard_points.csv`, `models/artifacts/`, and `data/processed/scored_loans.parquet` (PD, points and reason codes for every loan; input to Modules 3–4).

## Module 3: Macroeconomic stress test

How much would the 2015 book lose if unemployment rose? Results: [`reports/stress_report.md`](reports/stress_report.md).

1. **Macro sensitivity.** Binomial GLM of realized default rate on the unemployment change each issue-month × FICO-band cohort lived through over its first 24 months (FRED `UNRATE`), with overdispersion-adjusted standard errors. The pre-2013 `history` loans supply the 2008–09 recession.
2. **Loss given default.** Realized principal loss net of recoveries and collection fees, by grade.
3. **Scenarios.** Each 2015 loan's model PD is shifted in log-odds by β × (scenario change − training-period change): Baseline 0, Adverse +2.5 pp, Severe +5 pp.
4. **Expected loss** = PD × LGD × principal, by scenario and grade.
5. **Backtest.** Expected loss under the unemployment path 2015 loans actually saw vs. their realized losses.

All parameters are estimated on loans issued before 2015.

```
stress/
  macro.py   FRED unemployment download/cache, unemployment change per loan
  glm.py     binomial GLM (IRLS) with standard errors
  run.py     sensitivity, LGD, scenarios, backtest, report; writes data/processed/stressed_book.parquet
```

## Module 4: Credit policy optimization

Which 2015 loans should be funded to maximize profit while severe-recession losses stay within budget? Results: [`reports/policy_report.md`](reports/policy_report.md).

- **Profit per loan:** expected lifetime interest (scheduled interest × the share actually collected on 2013–2014 loans, since prepayment and default cut it) minus expected loss (PD × LGD × principal) minus funding cost.
- **Decision:** approve or decline each of ~70 segments (grade × predicted-risk decile), solved as a mixed-integer program with HiGHS (or Gurobi with `--solver gurobi`).
- **Constraints:** severe-scenario loss ≤ 10% of approved principal, approved volume ≥ 50% of the book, grades E–G ≤ 15% of approved principal.
- **Evaluation:** the policy is chosen from predictions only; realized 2015 profit is then compared with approving every loan and with a grade A–D cutoff. A frontier shows profit at each loss budget.

```
optimize/
  profit.py   expected and realized lifetime profit, yield factors
  solver.py   approve/decline MIP (HiGHS or Gurobi), feasibility check
  run.py      segments, benchmark policies, frontier, report; writes data/processed/policy_segments.parquet
```

## Module 5: Champion/challenger experiment

Would the optimized policy win a randomized test against the status quo? Results: [`reports/experiment_report.md`](reports/experiment_report.md).

- **Arms:** 2015 applicants split 50/50 at random. Champion funds everyone Lending Club approved; challenger applies the Module 4 policy; a declined applicant earns $0.
- **Design first:** the test is sized with a power calculation from model predictions and 2013–2014 profit variance, before any 2015 outcome is used.
- **Readout:** profit uplift per applicant with a Welch t-test and a bootstrap CI; guardrails on approval rate and default rate of funded loans.
- **Robustness:** 50 re-randomizations and an empirical power curve at smaller test sizes.
- **Decision rule:** launch only if the uplift CI is above $0 and funded loans do not default more than the champion's.

```
experiment/
  stats.py   Welch test, bootstrap CI, two-proportion test, sample-size formula
  run.py     design, randomized readout, robustness, decision, report
```

## Module 6: Live scoring and monitoring

The 2015 book replayed as a live stream of applications, scored and monitored in real time. Results: [`reports/monitoring_report.md`](reports/monitoring_report.md).

- **Scoring** reuses the batch logic exactly: LightGBM PD, baseline-scenario shift, risk band, approve/decline from the optimized policy, top-3 reason codes.
- **Monitors** on a rolling window: PSI of predicted PD and six key inputs vs. training, approval rate, observed vs. predicted default rate, p95 latency, each with an alert threshold.
- **Drift test:** part-way through, a riskier acquisition channel is injected (lower FICO, higher utilization, more new accounts); the report shows how many applications it took to alert and whether anything fired before.
- **Backends:** `memory` (one process, no Docker) or `kafka` (producer → Kafka → scorer → decisions topic) with Prometheus metrics, alert rules and a provisioned Grafana dashboard.

```
streaming/
  source.py    replay of 2015 applications, drift injection
  scorer.py    PD -> stressed PD -> risk band -> policy decision -> reason codes
  monitor.py   rolling PSI, approval, calibration, latency; alerting
  run.py       memory and Kafka backends, Prometheus metrics, report
  infra/       docker-compose (Kafka, Prometheus, Grafana), alert rules, dashboard
```

## Module 7: Model governance and controls

A risk and controls register with 16 automated control tests that read the project's real outputs. Results: [`reports/controls_report.md`](reports/controls_report.md) · Model card: [`docs/model_card.md`](docs/model_card.md).

| Area | Controls |
| --- | --- |
| Data | Data-quality gate, leakage block |
| Model | Performance floor vs. benchmark, overfitting gap, stability (PSI), calibration, monotonicity perturbation test |
| Compliance | Reason codes for every high-risk loan, geographic disparity review (4/5ths rule) |
| Stress and decisions | Loss backtest, macro significance, policy limits, profit calibration, launch rule |
| AI and technology | AI analyst evaluation thresholds, credential scan of tracked files |

- Each control has a risk, threshold, owner and frequency, and returns PASS, WARN (review), FAIL or N/A.
- A failing control opens an incident in [`governance/incidents.json`](governance/incidents.json) automatically. The log is seeded with the real issues found while building this project, each with root cause and remediation.
- `python -m governance.run --strict` exits non-zero on any failure, so it can gate a CI pipeline.

```
governance/
  controls.py      register and control tests
  run.py           runs controls, updates incidents, writes report and model card
  incidents.json   incident log
```

## Module 8: AI risk analyst (Claude + RAG + evaluation)

A Claude agent that answers risk questions and writes risk memos, citing every claim. Evaluation: [`reports/agent_eval.md`](reports/agent_eval.md).

| Tool | What it does |
| --- | --- |
| `query_portfolio` | Read-only SQL over the scored, stressed and policy tables (DuckDB in memory, file access disabled, single SELECT only) |
| `search_documents` | BM25 search over this project's reports and the latest 10-Ks of Atlanticus, Synchrony, Capital One and LendingClub (SEC EDGAR) |
| `get_results` | Exact numbers from each module's results file |

- **Citations are verified:** every cited id must have been returned by a tool in that conversation, so invented citations are caught deterministically.
- **Evaluation set:** about 30 questions whose answer keys are computed from the project's own results and tables (so they update when models are rerun), plus questions the data cannot answer (must abstain) and open 10-K questions.
- **Metrics:** answer accuracy, abstention accuracy, invalid-citation rate, and citation faithfulness (an LLM judge checks each cited passage supports its sentence).

```
agent/
  ingest.py     download 10-Ks from EDGAR, chunk filings and reports, build the BM25 index
  retrieval.py  BM25 search
  tools.py      the three tools and their schemas; SQL sandbox
  core.py       Claude tool-use loop, citation check
  ask.py        CLI: answer a question or write a memo to reports/memos/
  evaluate.py   question set, scoring, LLM judge, report
```

## Module 9: Decision API and dashboard

The whole platform behind one HTTP service: send an application, get back a decision with its PD, risk band, stress-scenario PDs and adverse-action reasons.

- **`POST /api/score`** scores 1-1,000 applications per call with the same code path as the live stream (Module 6). Inputs are validated: unknown fields are rejected, so a protected attribute such as `addr_state` cannot reach the model.
- **Every decision carries the model version** (hash of the model file), for audit.
- **Read endpoints** for the dashboard: stress loss at any unemployment shock, policy frontier, monitoring timeline, controls.
- **Prometheus metrics** at `/metrics`, interactive docs at `/docs`, and a load test that measures latency and throughput.

```
api/
  export.py    packages model, policy and results into api/bundle/ (no raw data in the service)
  service.py   loads the bundle, scores applications
  main.py      FastAPI app
  loadtest.py  concurrent requests -> p50/p95/p99 latency, throughput
dashboard/     React (Vite) console served by the API: decide an application, model and policy,
               recession stress slider, live monitoring timeline, control register
```

The dashboard's main view takes a real 2015 application and re-scores it as you edit any input, showing where the
applicant sits among the ten risk bands today and under adverse and severe recessions.

## Module 10: Rates and credit spreads

The 2015 book viewed as a fixed-income asset, using Treasury yields and the Baa corporate spread from FRED. Results: [`reports/market_report.md`](reports/market_report.md).

- **Relative value:** each grade's coupon spread over the 3-year Treasury at issue, less expected and realized annual credit losses, next to the Baa corporate spread.
- **Rate risk:** weighted-average life, modified duration, DV01, value change for parallel shocks, and the extra cost of floating-rate funding.
- **Market signals:** does the Baa-spread change explain cohort default rates better than the unemployment change in Module 3? Compared by AIC and out-of-time deviance.

```
market/
  fred.py      FRED download and cache, monthly averages, forward changes
  analysis.py  amortization, WAL, duration, spread table, cohort GLM comparison
  run.py       report, figures, results JSON
```

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. Test on a synthetic sample first (takes seconds)
pytest -q

# 2. Download the real data (needs a Kaggle API token in ~/.kaggle/kaggle.json)
kaggle datasets download -d wordsforthewise/lending-club -p data/raw --unzip

# 3. Build the modeling table (Module 1)
python -m pipeline.build

# 4. Train and validate the default models (Module 2)
python -m models.train
mlflow ui   # optional: browse the experiment at http://127.0.0.1:5000

# 5. Stress test (Module 3; downloads unemployment from FRED on first run)
python -m stress.run

# 6. Optimize the credit policy (Module 4)
python -m optimize.run

# 7. Champion/challenger experiment (Module 5)
python -m experiment.run

# 8. AI risk analyst (Module 8): needs ANTHROPIC_API_KEY in .env
python -m agent.ingest --email you@school.edu
python -m agent.ask "How much would the 2015 book lose in a severe recession?"
python -m agent.ask --memo "Risk review of the 2015 book and peer lenders"
python -m agent.evaluate

# 9. Live scoring and monitoring (Module 6)
python -m streaming.run                                    # memory backend, no Docker
docker compose -f streaming/infra/docker-compose.yml up -d # optional: Kafka + Prometheus + Grafana
python -m streaming.run --metrics-port 8000 --rate 500     # watch at http://localhost:3000

# 10. Governance: run all controls, update incidents, regenerate the model card (Module 7)
python -m governance.run

# 11. Decision API (Module 9)
python -m api.export
uvicorn api.main:app --port 8000          # docs at http://localhost:8000/docs
python -m api.loadtest                    # in a second terminal
cd dashboard && npm install && npm run build && cd ..   # then restart uvicorn: dashboard at http://localhost:8000

# 12. Rates and credit spreads (Module 10; downloads Treasury and Baa series from FRED on first run)
python -m market.run

# 13. Docker image and AWS deployment (Module 9): see docs/deploy_aws.md
docker build -t credit-console . && docker run --rm -p 8000:8000 credit-console
```

On a Mac, LightGBM needs OpenMP: `brew install libomp`.

Data: [Lending Club loan data on Kaggle](https://www.kaggle.com/datasets/wordsforthewise/lending-club). Raw and processed data are not committed.
