# Consumer Credit Risk & Portfolio Decision Platform

End-to-end credit risk system on 2M+ public Lending Club loans: data pipeline, probability-of-default model, stress testing, portfolio optimization, real-time monitoring, model governance, and an AI risk analyst.

**Status:** Module 1 (data pipeline and data quality) complete. Modules 2–10 in progress.

## Module 1: Data pipeline and data quality

Raw Lending Club CSV → typed staging table → modeling table → 13 automated data-quality checks → Parquet.

```
pipeline/
  sql/01_raw_loans.sql     load the file as text (one bad value can't break the load)
  sql/02_stg_loans.sql     type and clean every column
  sql/03_loans_model.sql   sample, target, split, application-time features only
  quality_checks.py        controls DQ-01 to DQ-13; any FAIL stops the pipeline
  build.py                 runs the stages and the checks
docs/data_dictionary.md    every column in the modeling table
reports/data_quality.md    latest check results (written on each run)
```

**Sample:** matured 36-month loans issued 2007–2015 with a final outcome.
**Target:** `is_default` = 1 if Charged Off or Default.
**Split:** train 2007–2012, validation 2013, out-of-time test 2014–2015.

### Data-quality controls

| ID | Control | Blocks pipeline |
| --- | --- | --- |
| DQ-01 | Enough rows to model | Yes |
| DQ-02 | `loan_id` unique | Yes |
| DQ-03 | Required fields never null | Yes |
| DQ-04 | Target is 0/1 | Yes |
| DQ-05 | Default rate in 5–30% | Yes |
| DQ-06 | Values in valid ranges | Yes (some warn) |
| DQ-07 | Feature null share ≤ 20% | Warn |
| DQ-08 | No post-issue (leakage) fields | Yes |
| DQ-09 | No feature dated after issue | Yes |
| DQ-10 | Every loan in sample window with a split | Yes |
| DQ-11 | Every split populated | Yes |
| DQ-12 | Default rate rises A → G | Warn |
| DQ-13 | Installment reconciles to amount, rate, term | Warn |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. Test on a synthetic sample first (takes seconds)
pytest -q

# 2. Download the real data (needs a Kaggle API token in ~/.kaggle/kaggle.json)
kaggle datasets download -d wordsforthewise/lending-club -p data/raw --unzip

# 3. Build
python -m pipeline.build
```

Data: [Lending Club loan data on Kaggle](https://www.kaggle.com/datasets/wordsforthewise/lending-club). Raw and processed data are not committed.
