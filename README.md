# Consumer Credit Risk & Portfolio Decision Platform

End-to-end credit risk system on 2M+ public Lending Club loans: data pipeline, probability-of-default model, stress testing, portfolio optimization, real-time monitoring, model governance, and an AI risk analyst.

**Status:** Modules 1–2 complete (data pipeline, default model). Modules 3–10 in progress.

## Module 1: Data pipeline and data quality

Raw Lending Club CSV → typed staging table → modeling table → 14 automated data-quality controls → Parquet.

```
pipeline/
  sql/01_raw_loans.sql     load the file as text (one bad value can't break the load)
  sql/02_stg_loans.sql     type and clean every column
  sql/03_loans_model.sql   sample, target, split, application-time features only
  quality_checks.py        controls DQ-01 to DQ-14; any FAIL stops the pipeline
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

## Module 2: Probability-of-default model

Three ways to rank risk, compared on the same loans:

| Model | What it is |
| --- | --- |
| Sub-grade benchmark | Lending Club's own A1–G5 grade: the bar to beat |
| WOE scorecard | Logistic regression on weight-of-evidence bins, converted to points (600 = 50:1 odds, 20 points doubles the odds) |
| GBM | LightGBM with monotone constraints, exact SHAP reason codes per loan |

Inputs: 35 application-time fields, including 15 extended bureau attributes. Neither model uses grade, sub-grade or interest rate, since those are outputs of Lending Club's own model. Trained on Jan 2013–Jun 2014, early-stopped on Jul–Dec 2014, tested out-of-time on 2015. Results: [`reports/model_report.md`](reports/model_report.md).

```
models/
  features.py       inputs, excluded pricing fields, monotone directions, reason text
  woe.py            WOE binning, information value, points scorecard
  metrics.py        AUC, Gini, KS, Brier, calibration by decile, PSI
  reason_codes.py   top-3 SHAP reasons per loan
  train.py          trains all three, writes report, figures, artifacts, scored loans
```

Outputs: `reports/model_report.md`, `reports/figures/`, `reports/scorecard_points.csv`, `models/artifacts/`, and `data/processed/scored_loans.parquet` (PD, points and reason codes for every loan; input to Modules 3–4).

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
```

On a Mac, LightGBM needs OpenMP: `brew install libomp`.

Data: [Lending Club loan data on Kaggle](https://www.kaggle.com/datasets/wordsforthewise/lending-club). Raw and processed data are not committed.
