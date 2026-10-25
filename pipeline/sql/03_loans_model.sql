-- Stage 3: the modeling table.
-- Only matured 36-month loans with a final outcome, only fields known at
-- application time, plus the target and the time-based split
-- (history = pre-2013, kept for stress testing; train/valid/oot = PD model).
CREATE OR REPLACE TABLE loans_model AS
SELECT
    loan_id,
    issue_date,
    year(issue_date)                                             AS issue_year,
    CASE WHEN loan_status IN (__BAD_STATUSES__) THEN 1 ELSE 0 END AS is_default,
    __SPLIT_CASE__                                                AS split,

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
    mths_since_last_delinq,
    mths_since_recent_inq,
    acc_open_past_24mths,
    num_tl_op_past_12m,
    bc_util,
    bc_open_to_buy,
    percent_bc_gt_75,
    tot_hi_cred_lim,
    total_rev_hi_lim,
    tot_cur_bal,
    avg_cur_bal,
    mo_sin_old_rev_tl_op,
    mo_sin_rcnt_tl,
    num_actv_rev_tl,
    pct_tl_nvr_dlq,
    earliest_cr_line_date,
    date_diff('month', earliest_cr_line_date, issue_date) / 12.0 AS credit_history_years,

    -- Derived ratios
    CASE WHEN annual_inc > 0 THEN loan_amnt / annual_inc END     AS loan_to_income,
    CASE WHEN annual_inc > 0 THEN installment * 12 / annual_inc END AS payment_to_income
FROM stg_loans
WHERE term_months = __TERM__
  AND year(issue_date) BETWEEN __YEAR_MIN__ AND __YEAR_MAX__
  AND loan_status IN (__FINAL_STATUSES__);
