-- Stage 2: one typed, cleaned row per loan.
-- Handles both file versions: rates as "13.56" or "13.56%", terms as " 36 months".
CREATE OR REPLACE TABLE stg_loans AS
SELECT
    trim(id)                                                     AS loan_id,
    TRY_CAST(loan_amnt AS DOUBLE)                                AS loan_amnt,
    TRY_CAST(regexp_extract(term, '(\d+)', 1) AS INTEGER)        AS term_months,
    TRY_CAST(replace(trim(int_rate), '%', '') AS DOUBLE)         AS int_rate,
    TRY_CAST(installment AS DOUBLE)                              AS installment,
    trim(grade)                                                  AS grade,
    trim(sub_grade)                                              AS sub_grade,
    CASE
        WHEN emp_length IS NULL OR trim(emp_length) IN ('', 'n/a') THEN NULL
        WHEN emp_length LIKE '<%' THEN 0
        ELSE TRY_CAST(regexp_extract(emp_length, '(\d+)', 1) AS INTEGER)
    END                                                          AS emp_length_years,
    upper(trim(home_ownership))                                  AS home_ownership,
    TRY_CAST(annual_inc AS DOUBLE)                               AS annual_inc,
    trim(verification_status)                                    AS verification_status,
    trim(purpose)                                                AS purpose,
    trim(addr_state)                                             AS addr_state,
    TRY_CAST(dti AS DOUBLE)                                      AS dti,
    TRY_CAST(delinq_2yrs AS DOUBLE)                              AS delinq_2yrs,
    TRY_CAST(fico_range_low AS DOUBLE)                           AS fico_low,
    TRY_CAST(fico_range_high AS DOUBLE)                          AS fico_high,
    TRY_CAST(inq_last_6mths AS DOUBLE)                           AS inq_last_6mths,
    TRY_CAST(open_acc AS DOUBLE)                                 AS open_acc,
    TRY_CAST(pub_rec AS DOUBLE)                                  AS pub_rec,
    TRY_CAST(revol_bal AS DOUBLE)                                AS revol_bal,
    TRY_CAST(replace(trim(revol_util), '%', '') AS DOUBLE)       AS revol_util,
    TRY_CAST(total_acc AS DOUBLE)                                AS total_acc,
    TRY_CAST(mort_acc AS DOUBLE)                                 AS mort_acc,
    TRY_CAST(pub_rec_bankruptcies AS DOUBLE)                     AS pub_rec_bankruptcies,
    -- Extended bureau attributes (reported from 2013)
    TRY_CAST(acc_open_past_24mths AS DOUBLE)                     AS acc_open_past_24mths,
    TRY_CAST(bc_util AS DOUBLE)                                  AS bc_util,
    TRY_CAST(bc_open_to_buy AS DOUBLE)                           AS bc_open_to_buy,
    TRY_CAST(num_tl_op_past_12m AS DOUBLE)                       AS num_tl_op_past_12m,
    TRY_CAST(percent_bc_gt_75 AS DOUBLE)                         AS percent_bc_gt_75,
    TRY_CAST(tot_hi_cred_lim AS DOUBLE)                          AS tot_hi_cred_lim,
    TRY_CAST(total_rev_hi_lim AS DOUBLE)                         AS total_rev_hi_lim,
    TRY_CAST(tot_cur_bal AS DOUBLE)                              AS tot_cur_bal,
    TRY_CAST(avg_cur_bal AS DOUBLE)                              AS avg_cur_bal,
    TRY_CAST(mo_sin_old_rev_tl_op AS DOUBLE)                     AS mo_sin_old_rev_tl_op,
    TRY_CAST(mo_sin_rcnt_tl AS DOUBLE)                           AS mo_sin_rcnt_tl,
    TRY_CAST(num_actv_rev_tl AS DOUBLE)                          AS num_actv_rev_tl,
    TRY_CAST(pct_tl_nvr_dlq AS DOUBLE)                           AS pct_tl_nvr_dlq,
    TRY_CAST(mths_since_last_delinq AS DOUBLE)                   AS mths_since_last_delinq,
    TRY_CAST(mths_since_recent_inq AS DOUBLE)                    AS mths_since_recent_inq,
    CAST(TRY_STRPTIME(trim(issue_d), '%b-%Y') AS DATE)           AS issue_date,
    CAST(TRY_STRPTIME(trim(earliest_cr_line), '%b-%Y') AS DATE)  AS earliest_cr_line_date,
    trim(loan_status)                                            AS loan_status
FROM raw_loans
-- Drops summary/footer rows some Lending Club files include.
WHERE TRY_CAST(loan_amnt AS DOUBLE) IS NOT NULL;
