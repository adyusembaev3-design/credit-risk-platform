# Probability-of-default model report

The GBM ranks risk best on the Jan 2015–Dec 2015 out-of-time test: GBM AUC **0.688**, WOE scorecard **0.675**, Lending Club sub-grade **0.679** (GBM vs. sub-grade: +0.010). Neither model uses grade or interest rate as an input.

Loans: train 172,377 (Jan 2013–Jun 2014) · validation 90,615 (Jul 2014–Dec 2014) · out-of-time 283,026 (Jan 2015–Dec 2015). GBM trees: 473 (early-stopped on validation). Loans issued before 2013 are excluded because the extended credit-bureau fields were not reported yet.

## Performance

| model | split | auc | gini | ks | brier | mean_pd | default_rate | n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sub-grade benchmark | train | 0.649 | 0.298 | 0.220 |  |  | 12.70% | 172,377 |
| WOE scorecard | train | 0.667 | 0.333 | 0.241 | 0.1065 | 12.70% | 12.70% | 172,377 |
| GBM | train | 0.745 | 0.491 | 0.360 | 0.1006 | 12.68% | 12.70% | 172,377 |
| Sub-grade benchmark | valid | 0.667 | 0.334 | 0.249 |  |  | 14.13% | 90,615 |
| WOE scorecard | valid | 0.668 | 0.337 | 0.245 | 0.1161 | 13.43% | 14.13% | 90,615 |
| GBM | valid | 0.685 | 0.370 | 0.268 | 0.1151 | 13.75% | 14.13% | 90,615 |
| Sub-grade benchmark | oot | 0.679 | 0.357 | 0.262 |  |  | 14.89% | 283,026 |
| WOE scorecard | oot | 0.675 | 0.349 | 0.254 | 0.1209 | 13.07% | 14.89% | 283,026 |
| GBM | oot | 0.688 | 0.377 | 0.275 | 0.1198 | 13.62% | 14.89% | 283,026 |

Brier and mean PD are blank for the benchmark because sub-grade is a rank, not a probability.

![ROC](figures/roc_oot.png)

## Calibration (GBM, out-of-time)

| decile | loans | predicted | actual | ratio |
| --- | --- | --- | --- | --- |
| 1 | 28,303 | 3.03% | 3.17% | 1.05 |
| 2 | 28,303 | 5.51% | 6.09% | 1.11 |
| 3 | 28,302 | 7.35% | 8.24% | 1.12 |
| 4 | 28,303 | 9.05% | 10.09% | 1.12 |
| 5 | 28,302 | 10.78% | 12.61% | 1.17 |
| 6 | 28,303 | 12.70% | 14.69% | 1.16 |
| 7 | 28,302 | 14.96% | 17.58% | 1.18 |
| 8 | 28,303 | 17.83% | 20.25% | 1.14 |
| 9 | 28,302 | 22.12% | 24.10% | 1.09 |
| 10 | 28,303 | 32.85% | 32.04% | 0.98 |

![Calibration](figures/calibration_oot.png)

## Stability

Population stability index of the predicted PD, training vs. out-of-time (< 0.10 stable, 0.10–0.25 moderate shift, > 0.25 significant):

| model | psi |
| --- | --- |
| GBM | 0.014 |
| WOE scorecard | 0.005 |

## What drives the GBM (mean |SHAP|, out-of-time)

| feature | mean_abs_shap |
| --- | --- |
| fico_mid | 0.2080 |
| annual_inc | 0.1486 |
| acc_open_past_24mths | 0.1453 |
| loan_to_income | 0.1314 |
| dti | 0.1061 |
| addr_state | 0.1004 |
| purpose | 0.0880 |
| bc_open_to_buy | 0.0855 |
| total_acc | 0.0831 |
| mo_sin_old_rev_tl_op | 0.0795 |

## Scorecard features by information value

| feature | iv | in_scorecard |
| --- | --- | --- |
| fico_mid | 0.122 | yes |
| annual_inc | 0.100 | yes |
| tot_hi_cred_lim | 0.084 | yes |
| bc_open_to_buy | 0.078 | yes |
| avg_cur_bal | 0.074 | yes |
| tot_cur_bal | 0.067 | yes |
| total_rev_hi_lim | 0.059 | yes |
| mort_acc | 0.048 | yes |
| acc_open_past_24mths | 0.046 | yes |
| dti | 0.042 | yes |
| home_ownership | 0.042 | yes |
| num_tl_op_past_12m | 0.042 | yes |

Full points table: `reports/scorecard_points.csv`.

## Example reason codes (5 highest-risk out-of-time loans)

| loan_id | sub_grade | pd_gbm | reason_1 | reason_2 | reason_3 |
| --- | --- | --- | --- | --- | --- |
| 38547294 | F4 | 83.3% | Revolving balance | State of residence | Loan amount relative to income |
| 63336407 | D5 | 81.2% | Age of oldest revolving account | Loan amount relative to income | Income level |
| 66483918 | D3 | 79.6% | Accounts opened in the past 24 months | Accounts opened in the past 12 months | Income level |
| 65612026 | D1 | 75.5% | Accounts opened in the past 24 months | Loan amount relative to income | Credit score |
| 68443713 | E1 | 74.6% | Accounts opened in the past 24 months | Income level | Loan amount relative to income |

## Design choices

- **No pricing inputs.** Grade, sub-grade, interest rate and installment are outputs of Lending Club's model; sub-grade is used only as the benchmark to beat.
- **Out-of-time validation.** The test period comes after the training period, as it would in production.
- **Full credit file.** 35 application-time inputs, including 15 extended bureau attributes (utilization, recent account openings, credit limits, delinquency history) reported from 2013.
- **Monotone constraints** on credit score, income, DTI, inquiries, delinquencies, public records, bankruptcies, utilization and loan-to-income, so the model can never reward a worse value.
- **Reason codes** are each loan's top three SHAP contributions that raised its risk.
