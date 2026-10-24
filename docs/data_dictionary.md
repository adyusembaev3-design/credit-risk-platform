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
| `split` | text | `train` 2007–2012, `valid` 2013, `oot` 2014–2015 (out-of-time test) |

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

## Derived ratios

| Column | Type | Definition |
| --- | --- | --- |
| `loan_to_income` | double | `loan_amnt / annual_inc` |
| `payment_to_income` | double | `installment × 12 / annual_inc` |
