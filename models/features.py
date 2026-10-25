"""Feature definitions for the probability-of-default model.

Lending Club's own grade, sub-grade and interest rate are outputs of
Lending Club's risk model. Using them as inputs would just copy that model,
so they are excluded and sub-grade is kept only as a BENCHMARK: the question
is whether our model ranks risk better than the lender's own grade.
"""

NUMERIC = [
    "loan_amnt",
    "emp_length_years",
    "annual_inc",
    "dti",
    "fico_mid",
    "delinq_2yrs",
    "inq_last_6mths",
    "open_acc",
    "pub_rec",
    "revol_bal",
    "revol_util",
    "total_acc",
    "mort_acc",
    "pub_rec_bankruptcies",
    "credit_history_years",
    "loan_to_income",
    # Extended bureau attributes (reported from 2013)
    "mths_since_last_delinq",
    "mths_since_recent_inq",
    "acc_open_past_24mths",
    "num_tl_op_past_12m",
    "bc_util",
    "bc_open_to_buy",
    "percent_bc_gt_75",
    "tot_hi_cred_lim",
    "total_rev_hi_lim",
    "tot_cur_bal",
    "avg_cur_bal",
    "mo_sin_old_rev_tl_op",
    "mo_sin_rcnt_tl",
    "num_actv_rev_tl",
    "pct_tl_nvr_dlq",
]

CATEGORICAL = [
    "home_ownership",
    "verification_status",
    "purpose",
    "addr_state",
]

FEATURES = NUMERIC + CATEGORICAL
TARGET = "is_default"
BENCHMARK = "sub_grade"

# Pricing outputs of Lending Club's model, never used as inputs.
EXCLUDED = ["grade", "sub_grade", "int_rate", "installment", "payment_to_income"]

# Direction of risk the model is allowed to learn (+1 = more risk as value rises).
# Enforcing these keeps the model explainable and defensible in a model review.
MONOTONE = {
    "fico_mid": -1,
    "annual_inc": -1,
    "dti": +1,
    "inq_last_6mths": +1,
    "delinq_2yrs": +1,
    "pub_rec": +1,
    "pub_rec_bankruptcies": +1,
    "revol_util": +1,
    "loan_to_income": +1,
    "acc_open_past_24mths": +1,
    "num_tl_op_past_12m": +1,
    "bc_util": +1,
    "percent_bc_gt_75": +1,
    "bc_open_to_buy": -1,
    "tot_hi_cred_lim": -1,
    "mo_sin_old_rev_tl_op": -1,
    "pct_tl_nvr_dlq": -1,
}

# Plain-language reason text for each feature (used in reason codes).
REASON_TEXT = {
    "loan_amnt": "Loan amount requested",
    "emp_length_years": "Length of employment",
    "annual_inc": "Income level",
    "dti": "Debt-to-income ratio",
    "fico_mid": "Credit score",
    "delinq_2yrs": "Recent delinquencies",
    "inq_last_6mths": "Number of recent credit inquiries",
    "open_acc": "Number of open credit lines",
    "pub_rec": "Derogatory public records",
    "revol_bal": "Revolving balance",
    "revol_util": "Revolving credit utilization",
    "total_acc": "Total number of credit lines",
    "mort_acc": "Number of mortgage accounts",
    "pub_rec_bankruptcies": "Bankruptcies on record",
    "credit_history_years": "Length of credit history",
    "loan_to_income": "Loan amount relative to income",
    "mths_since_last_delinq": "Time since most recent delinquency",
    "mths_since_recent_inq": "Time since most recent credit inquiry",
    "acc_open_past_24mths": "Accounts opened in the past 24 months",
    "num_tl_op_past_12m": "Accounts opened in the past 12 months",
    "bc_util": "Bankcard utilization",
    "bc_open_to_buy": "Available bankcard credit",
    "percent_bc_gt_75": "Share of bankcards above 75% utilization",
    "tot_hi_cred_lim": "Total credit limit",
    "total_rev_hi_lim": "Total revolving credit limit",
    "tot_cur_bal": "Total current balance",
    "avg_cur_bal": "Average balance per account",
    "mo_sin_old_rev_tl_op": "Age of oldest revolving account",
    "mo_sin_rcnt_tl": "Time since most recent account opened",
    "num_actv_rev_tl": "Number of active revolving accounts",
    "pct_tl_nvr_dlq": "Share of accounts never delinquent",
    "home_ownership": "Housing status",
    "verification_status": "Income verification status",
    "purpose": "Loan purpose",
    "addr_state": "State of residence",
}

SUB_GRADES = [f"{g}{n}" for g in "ABCDEFG" for n in range(1, 6)]
