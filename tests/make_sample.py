"""Write a small synthetic file in the Lending Club 'accepted loans' format.

It deliberately includes the things the pipeline must handle:
- rates written both as "13.56" and "13.56%", terms as " 36 months"
- 60-month loans and loans still "Current" (must be filtered out)
- post-issue columns such as total_pymnt and recoveries (must not leak)
- a summary footer row with no loan amount (must be dropped)

Usage: python -m tests.make_sample tests/sample.csv
"""

from __future__ import annotations

import csv
import math
import random
import sys
from pathlib import Path

COLUMNS = [
    "id", "loan_amnt", "term", "int_rate", "installment", "grade", "sub_grade",
    "emp_length", "home_ownership", "annual_inc", "verification_status", "issue_d",
    "loan_status", "purpose", "addr_state", "dti", "delinq_2yrs", "earliest_cr_line",
    "fico_range_low", "fico_range_high", "inq_last_6mths", "open_acc", "pub_rec",
    "revol_bal", "revol_util", "total_acc", "mort_acc", "pub_rec_bankruptcies",
    "mths_since_last_delinq",
    # extended bureau fields: blank before 2013, as in the real file
    "acc_open_past_24mths", "bc_util", "bc_open_to_buy", "num_tl_op_past_12m",
    "percent_bc_gt_75", "tot_hi_cred_lim", "total_rev_hi_lim", "tot_cur_bal",
    "avg_cur_bal", "mo_sin_old_rev_tl_op", "mo_sin_rcnt_tl", "num_actv_rev_tl",
    "pct_tl_nvr_dlq", "mths_since_recent_inq",
    # post-issue fields that exist in the real file and must never reach the model
    "total_pymnt", "recoveries", "last_pymnt_d",
]

GRADES = {  # grade: (base interest rate, default probability, sampling weight)
    "A": (7.0, 0.06, 0.20), "B": (11.0, 0.11, 0.30), "C": (14.0, 0.16, 0.25),
    "D": (18.0, 0.21, 0.13), "E": (21.0, 0.26, 0.07), "F": (25.0, 0.31, 0.03),
    "G": (28.0, 0.36, 0.02),
}
GRADE_CUTS = [("A", 0.07), ("B", 0.11), ("C", 0.16), ("D", 0.21), ("E", 0.26), ("F", 0.31)]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PURPOSES = ["debt_consolidation", "credit_card", "home_improvement", "other", "major_purchase"]
STATES = ["PA", "NJ", "NY", "CA", "TX", "FL", "DE", "IL"]
# Lending Club grew fast: most loans were issued 2013 onward
YEARS = list(range(2007, 2019))
YEAR_WEIGHTS = [1, 1, 1, 1, 2, 3, 6, 8, 10, 4, 4, 4]


def installment(amount: float, rate: float, months: int) -> float:
    r = rate / 1200
    return round(amount * r / (1 - (1 + r) ** -months), 2)


def make_rows(n: int, seed: int = 7) -> list[dict]:
    """Default risk depends on credit score, DTI, inquiries, recent account
    openings and bankcard utilization; the grade is assigned from that risk,
    as a lender's pricing model would."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        fico_low = rng.randrange(660, 800, 5)
        dti = rng.uniform(0, 35)
        inq = rng.randint(0, 4)
        acc_open_24 = rng.randint(0, 12)
        bc_util = rng.uniform(0, 110)
        z = (-1.9 - 0.025 * (fico_low + 2 - 715) + 0.05 * (dti - 17) + 0.25 * (inq - 1)
             + 0.08 * (acc_open_24 - 6) + 0.01 * (bc_util - 55))
        p_default = 1 / (1 + math.exp(-z))
        noisy = p_default * rng.uniform(0.7, 1.3)  # the lender sees risk imperfectly
        grade = next((g for g, cut in GRADE_CUTS if noisy < cut), "G")
        rate = round(GRADES[grade][0] + rng.uniform(-1.5, 1.5), 2)
        term = 36 if rng.random() < 0.8 else 60
        amount = float(rng.randrange(1_000, 35_000, 25))
        year = rng.choices(YEARS, YEAR_WEIGHTS)[0]
        month = rng.choice(MONTHS)

        matured = term == 36 and year <= 2015
        if matured and rng.random() < 0.97:
            status = "Charged Off" if rng.random() < p_default else "Fully Paid"
        else:
            status = rng.choice(["Current", "Late (31-120 days)", "Fully Paid"])

        delinq = rng.choice([0, 0, 0, 1, 2])
        limit = rng.randrange(10_000, 400_000, 500)
        n_active = rng.randint(1, 15)
        bureau = {
            "acc_open_past_24mths": str(acc_open_24),
            "bc_util": f"{bc_util:.1f}",
            "bc_open_to_buy": str(rng.randint(0, 50_000)),
            "num_tl_op_past_12m": str(min(acc_open_24, rng.randint(0, 6))),
            "percent_bc_gt_75": f"{min(100.0, bc_util * rng.uniform(0.5, 1.0)):.1f}",
            "tot_hi_cred_lim": str(limit),
            "total_rev_hi_lim": str(int(limit * rng.uniform(0.1, 0.5))),
            "tot_cur_bal": str(int(limit * rng.uniform(0.1, 0.9))),
            "avg_cur_bal": str(int(limit * rng.uniform(0.1, 0.9) / n_active)),
            "mo_sin_old_rev_tl_op": str(rng.randint(24, 400)),
            "mo_sin_rcnt_tl": str(rng.randint(0, 60)),
            "num_actv_rev_tl": str(n_active),
            "pct_tl_nvr_dlq": f"{100 - 5 * delinq - rng.uniform(0, 5):.1f}",
            "mths_since_recent_inq": str(rng.randint(0, 5)) if inq else "",
        }
        if year < 2013:
            bureau = {k: "" for k in bureau}

        rows.append({
            "id": str(100000 + i),
            "loan_amnt": f"{amount:.0f}",
            "term": f" {term} months",
            "int_rate": f"{rate}%" if i % 2 else f"{rate}",
            "installment": f"{installment(amount, rate, term):.2f}",
            "grade": grade,
            "sub_grade": f"{grade}{rng.randint(1, 5)}",
            "emp_length": rng.choice(["< 1 year", "1 year", "5 years", "10+ years", "n/a"]),
            "home_ownership": rng.choice(["RENT", "MORTGAGE", "OWN"]),
            "annual_inc": f"{rng.randrange(25_000, 200_000, 500)}",
            "verification_status": rng.choice(["Verified", "Not Verified", "Source Verified"]),
            "issue_d": f"{month}-{year}",
            "loan_status": status,
            "purpose": rng.choice(PURPOSES),
            "addr_state": rng.choice(STATES),
            "dti": f"{dti:.2f}",
            "delinq_2yrs": str(delinq),
            "mths_since_last_delinq": str(rng.randint(1, 24)) if delinq else (
                str(rng.randint(25, 120)) if rng.random() < 0.3 else ""),
            "earliest_cr_line": f"{rng.choice(MONTHS)}-{rng.randint(1980, 2005)}",
            "fico_range_low": str(fico_low),
            "fico_range_high": str(fico_low + 4),
            "inq_last_6mths": str(inq),
            "open_acc": str(rng.randint(2, 25)),
            "pub_rec": str(rng.choice([0, 0, 0, 1])),
            "revol_bal": str(rng.randint(0, 40_000)),
            "revol_util": f"{rng.uniform(0, 100):.1f}%" if i % 3 else f"{rng.uniform(0, 100):.1f}",
            "total_acc": str(rng.randint(5, 50)),
            "mort_acc": str(rng.randint(0, 5)),
            "pub_rec_bankruptcies": str(rng.choice([0, 0, 0, 1])),
            **bureau,
            "total_pymnt": f"{amount * rng.uniform(0.3, 1.3):.2f}",
            "recoveries": "0.0",
            "last_pymnt_d": f"{rng.choice(MONTHS)}-2018",
        })
    return rows


def write_sample(path: Path, n: int = 4000, seed: int = 7) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(make_rows(n, seed))
        # Footer row like the ones in some real Lending Club files
        writer.writerow({"id": "Total amount funded in policy code 1: 1234567"})
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/sample.csv")
    print(f"Wrote {write_sample(out)}")
