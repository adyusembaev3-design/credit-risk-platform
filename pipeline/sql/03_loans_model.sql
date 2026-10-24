-- Stage 3: the modeling table.
-- Only matured 36-month loans with a final outcome, only fields known at
-- application time, plus the target and the time-based split.
CREATE OR REPLACE TABLE loans_model AS
SELECT
    loan_id,
    issue_date,
    year(issue_date)                                             AS issue_year,
    CASE WHEN loan_status IN (__BAD_STATUSES__) THEN 1 ELSE 0 END AS is_default,
    CASE
        WHEN year(issue_date) BETWEEN __TRAIN_START__ AND __TRAIN_END__ THEN 'train'
        WHEN year(issue_date) BETWEEN __VALID_START__ AND __VALID_END__ THEN 'valid'
        WHEN year(issue_date) BETWEEN __OOT_START__ AND __OOT_END__ THEN 'oot'
    END                                                          AS split,

    -- Loan terms
    loan_amnt,
    int_rate,
    installment,
    grade,
    sub_grade,
    purpose,

    -- Borrower
    emp_length_years,
    home_ownership,
    annual_inc,
    verification_status,
    addr_state,
    dti,

    -- Credit bureau at application
    (fico_low + fico_high) / 2.0                                 AS fico_mid,
    delinq_2yrs,
    inq_last_6mths,
    open_acc,
    pub_rec,
    revol_bal,
    revol_util,
    total_acc,
    mort_acc,
    pub_rec_bankruptcies,
    earliest_cr_line_date,
    date_diff('month', earliest_cr_line_date, issue_date) / 12.0 AS credit_history_years,

    -- Derived ratios
    CASE WHEN annual_inc > 0 THEN loan_amnt / annual_inc END     AS loan_to_income,
    CASE WHEN annual_inc > 0 THEN installment * 12 / annual_inc END AS payment_to_income
FROM stg_loans
WHERE term_months = __TERM__
  AND year(issue_date) BETWEEN __YEAR_MIN__ AND __YEAR_MAX__
  AND loan_status IN (__FINAL_STATUSES__);
