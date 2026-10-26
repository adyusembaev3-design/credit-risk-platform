# Data quality report

Run: 2026-10-26 16:23 UTC · Table: `loans_model` · **83 passed, 0 warnings, 0 failures**

| ID | Check | Severity | Status | Observed | Expected |
| --- | --- | --- | --- | --- | --- |
| DQ-01 | Table has enough rows to model | fail | PASS | 618,584 rows | >= 100,000 rows |
| DQ-02 | loan_id is unique | fail | PASS | 0 duplicate ids | 0 duplicates |
| DQ-03.annual_inc | annual_inc is never null | fail | PASS | 0 nulls | 0 nulls |
| DQ-03.fico_mid | fico_mid is never null | fail | PASS | 0 nulls | 0 nulls |
| DQ-03.grade | grade is never null | fail | PASS | 0 nulls | 0 nulls |
| DQ-03.int_rate | int_rate is never null | fail | PASS | 0 nulls | 0 nulls |
| DQ-03.is_default | is_default is never null | fail | PASS | 0 nulls | 0 nulls |
| DQ-03.issue_date | issue_date is never null | fail | PASS | 0 nulls | 0 nulls |
| DQ-03.loan_amnt | loan_amnt is never null | fail | PASS | 0 nulls | 0 nulls |
| DQ-03.loan_id | loan_id is never null | fail | PASS | 0 nulls | 0 nulls |
| DQ-04 | is_default is 0 or 1 | fail | PASS | 0 invalid values | 0 invalid values |
| DQ-05 | Default rate is in a plausible range | fail | PASS | 13.90% | 5% to 30% |
| DQ-06.annual_inc | annual_inc within [0, 10,000,000] | fail | PASS | 0.000% out of range | <= 0.1% |
| DQ-06.bc_util | bc_util within [0, 200] | warn | PASS | 0.001% out of range | <= 0.1% |
| DQ-06.credit_history_years | credit_history_years within [0, 70] | warn | PASS | 0.000% out of range | <= 0.1% |
| DQ-06.dti | dti within [0, 60] | warn | PASS | 0.002% out of range | <= 0.1% |
| DQ-06.fico_mid | fico_mid within [600, 850] | fail | PASS | 0.000% out of range | <= 0.1% |
| DQ-06.int_rate | int_rate within [5, 31] | fail | PASS | 0.000% out of range | <= 0.1% |
| DQ-06.loan_amnt | loan_amnt within [500, 40,000] | fail | PASS | 0.000% out of range | <= 0.1% |
| DQ-06.pct_tl_nvr_dlq | pct_tl_nvr_dlq within [0, 100] | warn | PASS | 0.000% out of range | <= 0.1% |
| DQ-06.percent_bc_gt_75 | percent_bc_gt_75 within [0, 100] | warn | PASS | 0.000% out of range | <= 0.1% |
| DQ-06.revol_util | revol_util within [0, 150] | warn | PASS | 0.002% out of range | <= 0.1% |
| DQ-07.acc_open_past_24mths | acc_open_past_24mths null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.addr_state | addr_state null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.avg_cur_bal | avg_cur_bal null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.bc_open_to_buy | bc_open_to_buy null share is acceptable (model splits) | warn | PASS | 1.0% null | <= 20% |
| DQ-07.bc_util | bc_util null share is acceptable (model splits) | warn | PASS | 1.1% null | <= 20% |
| DQ-07.credit_history_years | credit_history_years null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.delinq_2yrs | delinq_2yrs null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.dti | dti null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.earliest_cr_line_date | earliest_cr_line_date null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.emp_length_years | emp_length_years null share is acceptable (model splits) | warn | PASS | 6.2% null | <= 20% |
| DQ-07.home_ownership | home_ownership null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.inq_last_6mths | inq_last_6mths null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.installment | installment null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.issue_year | issue_year null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.loan_to_income | loan_to_income null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.mo_sin_old_rev_tl_op | mo_sin_old_rev_tl_op null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.mo_sin_rcnt_tl | mo_sin_rcnt_tl null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.mort_acc | mort_acc null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.num_actv_rev_tl | num_actv_rev_tl null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.num_tl_op_past_12m | num_tl_op_past_12m null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.open_acc | open_acc null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.payment_to_income | payment_to_income null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.pct_tl_nvr_dlq | pct_tl_nvr_dlq null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.percent_bc_gt_75 | percent_bc_gt_75 null share is acceptable (model splits) | warn | PASS | 1.1% null | <= 20% |
| DQ-07.pub_rec | pub_rec null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.pub_rec_bankruptcies | pub_rec_bankruptcies null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.purpose | purpose null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.revol_bal | revol_bal null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.revol_util | revol_util null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.split | split null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.sub_grade | sub_grade null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.tot_cur_bal | tot_cur_bal null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.tot_hi_cred_lim | tot_hi_cred_lim null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.total_acc | total_acc null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.total_rev_hi_lim | total_rev_hi_lim null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-07.verification_status | verification_status null share is acceptable (model splits) | warn | PASS | 0.0% null | <= 20% |
| DQ-08 | No post-issue (leakage) fields in the model table | fail | PASS | none found | none |
| DQ-09 | Credit history starts before the issue date | fail | PASS | 0.000% after issue date | <= 0.1% |
| DQ-10 | Every loan is in the sample window and has a split | fail | PASS | 0 loans outside | 0 loans outside |
| DQ-11.history | 'history' split has loans | fail | PASS | 72,566 loans | > 0 loans |
| DQ-11.oot | 'oot' split has loans | fail | PASS | 283,026 loans | > 0 loans |
| DQ-11.train | 'train' split has loans | fail | PASS | 172,377 loans | > 0 loans |
| DQ-11.valid | 'valid' split has loans | fail | PASS | 90,615 loans | > 0 loans |
| DQ-12 | Default rate increases from grade A to G | warn | PASS | 5.5% < 11.2% < 17.9% < 23.3% < 28.6% < 32.8% < 39.9% | non-decreasing |
| DQ-13 | Installment reconciles to amount, rate and term (within 2%) | warn | PASS | 0.14% mismatched | <= 1% |
| DQ-14.acc_open_past_24mths | acc_open_past_24mths populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.avg_cur_bal | avg_cur_bal populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.bc_open_to_buy | bc_open_to_buy populated for model-split loans | fail | PASS | 99.0% populated | >= 95% |
| DQ-14.bc_util | bc_util populated for model-split loans | fail | PASS | 98.9% populated | >= 95% |
| DQ-14.mo_sin_old_rev_tl_op | mo_sin_old_rev_tl_op populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.mo_sin_rcnt_tl | mo_sin_rcnt_tl populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.num_actv_rev_tl | num_actv_rev_tl populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.num_tl_op_past_12m | num_tl_op_past_12m populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.pct_tl_nvr_dlq | pct_tl_nvr_dlq populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.percent_bc_gt_75 | percent_bc_gt_75 populated for model-split loans | fail | PASS | 98.9% populated | >= 95% |
| DQ-14.tot_cur_bal | tot_cur_bal populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.tot_hi_cred_lim | tot_hi_cred_lim populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-14.total_rev_hi_lim | total_rev_hi_lim populated for model-split loans | fail | PASS | 100.0% populated | >= 95% |
| DQ-15 | Every model loan has an outcomes row | fail | PASS | 618,584 of 618,584 | all loans |
| DQ-16 | Loss rate computable for defaulted loans | fail | PASS | 100.0% of defaults | >= 99% |
| DQ-17 | Average loss given default is plausible | warn | PASS | 51.9% | 40% to 95% |
