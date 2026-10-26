# Model card: probability-of-default model (LightGBM)

Generated 2026-10-26 from the current results by `python -m governance.run`.

## Purpose

- **Intended use:** rank and estimate the lifetime default probability of 36-month unsecured personal-loan applicants, as input to expected-loss stress testing (Module 3) and credit-policy decisions (Module 4).
- **Not for:** 60-month loans, other products or lenders without revalidation, pricing on its own, or any use involving protected attributes.
- **Decision support only:** policy changes go through a champion/challenger test (Module 5).

## Data

- Lending Club accepted loans, 36-month term, final outcome known. Train 2013-01-01 to 2014-06-01, validation 2014-07-01 to 2014-12-01, out-of-time test 2015-01-01 to 2015-12-01.
- 35 application-time inputs (31 numeric, 4 categorical). Excluded by design: grade, sub_grade, int_rate, installment, payment_to_income (outputs of Lending Club's own pricing).
- Target: charged off or default = 1; fully paid = 0.

## Performance (out-of-time)

| model | auc | gini | ks | brier | mean_pd | default_rate | n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Sub-grade benchmark | 0.679 | 0.357 | 0.262 |  |  | 14.89% | 283,026 |
| WOE scorecard | 0.675 | 0.349 | 0.254 | 0.1209 | 13.07% | 14.89% | 283,026 |
| GBM | 0.688 | 0.377 | 0.275 | 0.1198 | 13.62% | 14.89% | 283,026 |

- Stability (PSI, train vs. out-of-time): 0.014.
- Trees: 473 (early-stopped on validation).

## Design safeguards

- Monotone constraints on 17 inputs (e.g. higher credit score can never raise PD); verified by control C-07 (PASS).
- Top-3 SHAP reason codes for every loan, for adverse-action notices; control C-08 (PASS).
- Post-issue fields kept out of the model table; control C-02 (PASS).

## Use in stress testing

- Each 1-point rise in unemployment multiplies default odds by 1.16; out-of-time loss backtest ratio 0.95 (control C-09: PASS).

## Known limitations

- Trained on loans Lending Club approved; applicants it declined are unseen (no reject inference).
- One recession in the macro data; sensitivity estimates rest mostly on 2007-2008 vintages.
- Profit estimates built on this model overstate realized profit (incident INC-003, control C-12).
- Protected attributes are absent, so fair-lending review uses geography as a proxy (control C-14).

## Monitoring

| id | control | frequency | status |
| --- | --- | --- | --- |
| C-01 | Data-quality controls DQ-01 to DQ-17 gate the pipeline; any failure stops it | Every pipeline run | PASS |
| C-02 | Payment and recovery fields are kept out of the model table | Every pipeline run | PASS |
| C-03 | Out-of-time AUC floor and benchmark comparison | Every retrain | PASS |
| C-04 | Gap between training and out-of-time AUC | Every retrain | PASS |
| C-05 | Population stability index of predicted PD | Monthly | PASS |
| C-06 | Calibration in the large and by decile, out-of-time | Every retrain | PASS |
| C-07 | Perturbation test of every monotone-constrained input | Every retrain | PASS |
| C-08 | Every high-risk loan carries SHAP reason codes | Every scoring run | PASS |
| C-09 | Out-of-time backtest of expected vs. actual loss | Quarterly | PASS |
| C-10 | Significance of the unemployment coefficient after overdispersion adjustment | Quarterly | PASS |
| C-11 | Optimized policy checked against loss budget, volume floor, concentration cap | Every policy change | PASS |
| C-12 | Expected vs. realized lifetime profit on the full book | Quarterly | WARN |
| C-13 | Launch decision must follow the pre-registered rule | Every experiment | PASS |
| C-14 | Approval-rate ratio across states (4/5ths rule), reviewed as a proxy | Every policy change | WARN |
| C-15 | 28-question evaluation: accuracy, invented citations, judged faithfulness | Every prompt or model change | PASS |
| C-16 | Tracked files scanned for API keys and credential files | Every commit | PASS |

## Ownership

- Model owner and developer: Akhmad Dyussembayev. Independent validation: not yet performed.
