-- Stage 4: realized loan outcomes, used ONLY for loss severity (Module 3) and
-- realized profit (Module 4).
-- These are post-issue payment fields, so they live in their own table and are
-- never joined into loans_model (leakage control DQ-08 checks loans_model).
CREATE OR REPLACE TABLE loan_outcomes AS
SELECT
    m.loan_id,
    m.is_default,
    m.loan_amnt,
    TRY_CAST(r.total_rec_prncp AS DOUBLE)          AS principal_repaid,
    coalesce(TRY_CAST(r.total_rec_int AS DOUBLE), 0) AS interest_received,
    coalesce(TRY_CAST(r.recoveries AS DOUBLE), 0)  AS recoveries,
    coalesce(TRY_CAST(r.collection_recovery_fee AS DOUBLE), 0) AS collection_fee,
    -- Loss as a share of the original loan amount (folds exposure-at-default in):
    -- unpaid principal, less net recoveries after collection fees, floored at 0.
    CASE WHEN m.is_default = 1 THEN
        greatest(0.0, least(1.0,
            (m.loan_amnt - TRY_CAST(r.total_rec_prncp AS DOUBLE)
             - coalesce(TRY_CAST(r.recoveries AS DOUBLE), 0)
             + coalesce(TRY_CAST(r.collection_recovery_fee AS DOUBLE), 0)) / m.loan_amnt))
    END                                            AS loss_rate
FROM loans_model m
JOIN raw_loans r ON trim(r.id) = m.loan_id;
