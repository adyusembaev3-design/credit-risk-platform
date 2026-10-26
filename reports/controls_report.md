# Model risk controls report

Run 2026-10-26: **14 of 16 controls pass**, 2 need review, 0 fail, 0 not yet run. 1 incident(s) open.

## Needs attention

| id | risk | status | observed | owner |
| --- | --- | --- | --- | --- |
| C-12 | Profit estimates used for decisions are biased | WARN | expected $20.1M vs realized $12.4M profit (ratio 1.62) | Credit strategy |
| C-14 | Policy has disparate impact across geographies | WARN | lowest/highest state approval rate 0.41 (MS 33% vs NH 80%; 39 states with 1,000+ applicants) | Compliance |

## Risk and controls register

| id | category | risk | control | kind | threshold | status | observed | owner | frequency |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C-01 | Data | Corrupt or incomplete input data reaches the model | Data-quality controls DQ-01 to DQ-17 gate the pipeline; any failure stops it | preventive | 0 failing checks | PASS | 83 checks, 0 warnings, 0 failures | Data engineering | Every pipeline run |
| C-02 | Data | Post-issue information leaks into the default model | Payment and recovery fields are kept out of the model table | preventive | 0 leakage columns | PASS | no post-issue fields in model table | Data engineering | Every pipeline run |
| C-03 | Model | Default model ranks risk worse than the lender's own grade | Out-of-time AUC floor and benchmark comparison | detective | AUC >= 0.66 and >= benchmark - 0.01 | PASS | GBM out-of-time AUC 0.688 vs benchmark 0.679 | Model owner | Every retrain |
| C-04 | Model | Model overfits training vintages | Gap between training and out-of-time AUC | detective | <= 0.08 pass, <= 0.12 warn | PASS | train 0.745 - out-of-time 0.688 = 0.057 | Model owner | Every retrain |
| C-05 | Model | Applicant population drifts away from training data | Population stability index of predicted PD | detective | < 0.10 pass, <= 0.25 warn | PASS | PSI 0.014 | Model owner | Monthly |
| C-06 | Model | Predicted default rates are biased, misstating expected loss | Calibration in the large and by decile, out-of-time | detective | mean ratio within 10%, deciles within 35% | PASS | mean PD / default rate 0.91; worst decile actual/predicted off by 18% | Model owner | Every retrain |
| C-07 | Model | Model rewards worse credit attributes (indefensible decisions) | Perturbation test of every monotone-constrained input | preventive | 0 violations | PASS | 17 constrained inputs, 0 violations on 2,000 loans | Model validation | Every retrain |
| C-08 | Compliance | Declined applicants cannot be given reasons (adverse action) | Every high-risk loan carries SHAP reason codes | preventive | 0% missing in top risk decile | PASS | 0.00% of highest-risk decile without a reason code | Model owner | Every scoring run |
| C-09 | Model | Stress test misstates losses | Out-of-time backtest of expected vs. actual loss | detective | ratio 0.85-1.15 pass, 0.70-1.30 warn | PASS | expected / actual loss 0.95 | Risk analytics | Quarterly |
| C-10 | Model | Macro sensitivity is noise | Significance of the unemployment coefficient after overdispersion adjustment | detective | z >= 2 | PASS | z = 9.5 (overdispersion-adjusted) | Risk analytics | Quarterly |
| C-11 | Decision | Credit policy breaches its risk appetite | Optimized policy checked against loss budget, volume floor, concentration cap | preventive | all constraints met | PASS | severe loss 9.8% (limit 10%), volume 60% (floor 50%) | Credit strategy | Every policy change |
| C-12 | Decision | Profit estimates used for decisions are biased | Expected vs. realized lifetime profit on the full book | detective | ratio 0.80-1.25 pass, 0.5-2 warn | WARN | expected $20.1M vs realized $12.4M profit (ratio 1.62) | Credit strategy | Quarterly |
| C-13 | Decision | Policy launched without evidence or against guardrails | Launch decision must follow the pre-registered rule | preventive | decision consistent with rule | PASS | decision 'Launch the challenger', uplift CI low $62.46, default 12.1% vs 15.0% | Credit strategy | Every experiment |
| C-14 | Compliance | Policy has disparate impact across geographies | Approval-rate ratio across states (4/5ths rule), reviewed as a proxy | detective | >= 0.80 pass, else review | WARN | lowest/highest state approval rate 0.41 (MS 33% vs NH 80%; 39 states with 1,000+ applicants) | Compliance | Every policy change |
| C-15 | AI | AI analyst gives wrong or unsupported answers | 28-question evaluation: accuracy, invented citations, judged faithfulness | detective | accuracy >= 95%, 0 invented citations, faithfulness >= 85% | PASS | accuracy 100%, answers with invented citations 0, faithfulness 95% | AI owner | Every prompt or model change |
| C-16 | Technology | Credentials committed to the repository | Tracked files scanned for API keys and credential files | preventive | 0 findings | PASS | 69 tracked files, no credentials | Engineering | Every commit |

## Incident log

| id | opened | closed | severity | control | title | status |
| --- | --- | --- | --- | --- | --- | --- |
| INC-001 | 2026-10-24 | 2026-10-25 | high | C-03 | Default model ranked risk worse than Lending Club's sub-grade | closed |
| INC-002 | 2026-10-24 | 2026-10-24 | low | C-01 | Duplicate-ID data-quality test did not exercise the control | closed |
| INC-003 | 2026-10-26 |  | medium | C-12 | Expected profit overstates realized profit | open |
| INC-004 | 2026-10-26 | 2026-10-26 | high | C-15 | 10-K text extraction dropped most of each filing | closed |
| INC-005 | 2026-10-26 | 2026-10-26 | medium | C-15 | Faithfulness judge under-reported supported claims | closed |

### INC-001: Default model ranked risk worse than Lending Club's sub-grade

- **Detected:** First out-of-time run: GBM AUC 0.647 vs. sub-grade benchmark 0.671.
- **Root cause:** Model trained on 2007-2012 loans (72K) using 16 basic bureau fields; the extended credit-bureau attributes are 0% populated before 2012, so the model saw only part of the credit file.
- **Remediation:** Measured field coverage by vintage; moved to a date-based split starting 2013 (172K training loans), added 15 extended bureau attributes with monotone constraints, kept pre-2013 loans for stress testing, and added control DQ-14 (bureau fields >= 95% populated).
- **Outcome:** GBM out-of-time AUC 0.688 vs. benchmark 0.679. · **Status:** closed

### INC-002: Duplicate-ID data-quality test did not exercise the control

- **Detected:** Unit test expected the pipeline to stop on a duplicated loan, but it passed.
- **Root cause:** The test duplicated a loan that the sample filter removes (still current or 60-month), so the duplicate never reached check DQ-02.
- **Remediation:** Test now duplicates a loan inside the modeling sample; DQ-02 correctly stops the pipeline.
- **Outcome:** Control DQ-02 verified to block duplicates. · **Status:** closed

### INC-003: Expected profit overstates realized profit

- **Detected:** Policy backtest: expected $23.5M vs. realized $12.4M profit for approving the full 2015 book.
- **Root cause:** Loss predictions are calibrated (stress backtest 0.95); the gap is in interest collected. Prepayment and interest-yield factors estimated on older vintages overstate what 2015 borrowers paid.
- **Remediation:** Partial: yield factors re-estimated on 2013-2014 vintages (expected $20.1M). Policy ranking held in every test, so decisions are unaffected. Next step: recalibrate yield on the most recent vintage and model prepayment by grade.
- **Outcome:** Accepted with monitoring by control C-12 (currently WARN). · **Status:** open

### INC-004: 10-K text extraction dropped most of each filing

- **Detected:** Index held 247 filing chunks from about 21 MB of 10-Ks; expected well over 1,000.
- **Root cause:** HTML parser entered skip mode on a hidden inline-XBRL block and never left it, discarding the rest of the document.
- **Remediation:** Removed the faulty hidden-block rule (XBRL headers are stripped separately) and added a regression test that text after a hidden block is kept.
- **Outcome:** 1,223 filing chunks indexed. · **Status:** closed

### INC-005: Faithfulness judge under-reported supported claims

- **Detected:** Numeric answers were all correct but judged only 33% faithful; filings answers were not judged at all.
- **Root cause:** Judge saw only the first 2,500 characters of each source, SQL results were shown without their query, the verdict parser failed on extra text, and bullet lists were split into broken claims.
- **Remediation:** Judge sees 15,000 characters and the SQL behind each result; robust verdict parsing that records raw replies when unparseable; claim splitting per list item; tests for each case.
- **Outcome:** Faithfulness 88-100% by category; remaining rejections reviewed and documented. · **Status:** closed
