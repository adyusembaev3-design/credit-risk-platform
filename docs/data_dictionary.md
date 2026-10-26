# Data dictionary: `loans_model`

One row per loan. Source: Lending Club accepted loans 2007–2018Q4 (Kaggle `wordsforthewise/lending-club`).

**Sample:** 36-month loans issued 2007–2015 with a final outcome (Fully Paid, Charged Off, or Default). These loans had all reached maturity by the 2018Q4 snapshot, so the default rate is not biased by loans that have not had time to go bad.

**Rule:** every feature is known on the day the loan was issued. Fields recorded later (payments, recoveries, last FICO pull, settlement flags) are excluded and checked by DQ-08.

## Keys, target and split

| Column | Type | Definition |
| --- | --- | --- |
| `loan_id` | text | Lending Club loan id (unique, DQ-02) |
| `issue_date` | date | Month the loan was funded (first of the month) |
| `issue_year` | int | Year of `issue_date` |
| `is_default` | int | **Target.** 1 if Charged Off or Default, 0 if Fully Paid |
| `split` | text | `history` 2007–2012 (stress testing only), `train` Jan 2013–Jun 2014, `valid` Jul–Dec 2014, `oot` 2015 (out-of-time test) |

## Loan terms

| Column | Type | Definition |
| --- | --- | --- |
| `loan_amnt` | double | Amount requested, USD |
| `int_rate` | double | Annual interest rate, percent (13.5 = 13.5%) |
| `installment` | double | Monthly payment, USD (reconciled in DQ-13) |
| `grade` | text | Lending Club risk grade, A (best) to G |
| `sub_grade` | text | A1 to G5 |
| `purpose` | text | Borrower's stated purpose |

## Borrower

| Column | Type | Definition |
| --- | --- | --- |
| `emp_length_years` | int | Years employed; "< 1 year" = 0, "10+ years" = 10, "n/a" = null |
| `home_ownership` | text | RENT, MORTGAGE, OWN, OTHER |
| `annual_inc` | double | Self-reported annual income, USD |
| `verification_status` | text | Whether income was verified |
| `addr_state` | text | Two-letter state |
| `dti` | double | Debt-to-income ratio, percent, excluding the new loan |

## Credit bureau at application

| Column | Type | Definition |
| --- | --- | --- |
| `fico_mid` | double | Midpoint of the FICO range at application |
| `delinq_2yrs` | double | 30+ day delinquencies in the past 2 years |
| `inq_last_6mths` | double | Credit inquiries in the past 6 months |
| `open_acc` | double | Open credit lines |
| `pub_rec` | double | Derogatory public records |
| `revol_bal` | double | Revolving balance, USD |
| `revol_util` | double | Revolving utilization, percent |
| `total_acc` | double | Total credit lines ever |
| `mort_acc` | double | Mortgage accounts |
| `pub_rec_bankruptcies` | double | Bankruptcies on record |
| `earliest_cr_line_date` | date | Month the first credit line opened |
| `credit_history_years` | double | Years from first credit line to issue date |

## Extended bureau attributes (reported from 2013; null for `history` loans)

| Column | Type | Definition |
| --- | --- | --- |
| `mths_since_last_delinq` | double | Months since most recent delinquency (null = none on file) |
| `mths_since_recent_inq` | double | Months since most recent inquiry (null = none in window) |
| `acc_open_past_24mths` | double | Accounts opened in the past 24 months |
| `num_tl_op_past_12m` | double | Accounts opened in the past 12 months |
| `bc_util` | double | Bankcard utilization, percent |
| `bc_open_to_buy` | double | Unused bankcard credit, USD |
| `percent_bc_gt_75` | double | Share of bankcards above 75% utilization, percent |
| `tot_hi_cred_lim` | double | Total credit limit across accounts, USD |
| `total_rev_hi_lim` | double | Total revolving credit limit, USD |
| `tot_cur_bal` | double | Total current balance, USD |
| `avg_cur_bal` | double | Average current balance per account, USD |
| `mo_sin_old_rev_tl_op` | double | Months since oldest revolving account opened |
| `mo_sin_rcnt_tl` | double | Months since most recent account opened |
| `num_actv_rev_tl` | double | Active revolving accounts |
| `pct_tl_nvr_dlq` | double | Share of accounts never delinquent, percent |

## Derived ratios

| Column | Type | Definition |
| --- | --- | --- |
| `loan_to_income` | double | `loan_amnt / annual_inc` |
| `payment_to_income` | double | `installment × 12 / annual_inc` |

# Data dictionary: `loan_outcomes`

Realized results of each loan, used **only** to measure loss severity in Module 3. Kept in a separate table so post-issue payment data can never enter the default model (DQ-08).

| Column | Type | Definition |
| --- | --- | --- |
| `loan_id` | text | Joins to `loans_model` |
| `is_default` | int | Same target as `loans_model` |
| `loan_amnt` | double | Original principal, USD |
| `principal_repaid` | double | Principal repaid before charge-off, USD |
| `recoveries` | double | Post-charge-off recoveries, USD |
| `collection_fee` | double | Collection fees on recoveries, USD |
| `loss_rate` | double | Defaults only: (principal − repaid − recoveries + fees) / principal, clipped to [0, 1] |
