"""Lifetime profit of a 36-month loan: expected (from predicted PD) and realized (from outcomes).

    scheduled interest = installment x 36 - principal
    expected profit    = (1 - PD) x scheduled interest x yield_good
                       +      PD  x (scheduled interest x yield_bad - LGD x principal)
                       - funding cost
    realized profit    = interest actually received - principal lost - funding cost

yield_good / yield_bad are the share of scheduled interest actually collected on
fully paid / defaulted loans (prepayment and early default cut it), measured by
grade on loans issued 2013-2014: the most recent matured vintages before the 2015
book, so borrower behavior is closest to it.
"""

from __future__ import annotations

import pandas as pd

TERM_MONTHS = 36
FUNDING_RATE = 0.04      # annual cost of the money lent
BALANCE_YEARS = 1.5      # average outstanding balance of a 36-month amortizing loan, in principal-years
YIELD_START = "2013-01-01"   # most recent vintages before the 2015 book
ESTIMATION_END = "2014-12-31"


def scheduled_interest(df: pd.DataFrame) -> pd.Series:
    return (df["installment"] * TERM_MONTHS - df["loan_amnt"]).clip(lower=0)


def funding_cost(df: pd.DataFrame) -> pd.Series:
    return df["loan_amnt"] * FUNDING_RATE * BALANCE_YEARS


def yield_factors(loans: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Share of scheduled interest collected, by grade and outcome, on 2013-2014 loans."""
    d = loans[["loan_id", "grade", "issue_date", "installment", "loan_amnt"]].merge(
        outcomes[["loan_id", "is_default", "interest_received"]], on="loan_id")
    issued = pd.to_datetime(d["issue_date"])
    d = d[(issued >= YIELD_START) & (issued <= ESTIMATION_END)].copy()
    d["sched"] = scheduled_interest(d)
    g = d.groupby(["grade", "is_default"]).agg(recv=("interest_received", "sum"), sched=("sched", "sum")).reset_index()
    g["factor"] = g["recv"] / g["sched"]
    t = g.pivot(index="grade", columns="is_default", values="factor").rename(columns={0: "yield_good", 1: "yield_bad"})
    return t.reset_index()


def expected_profit(book: pd.DataFrame, pd_col: str, factors: pd.DataFrame) -> pd.Series:
    f = book[["grade"]].merge(factors, on="grade", how="left")
    yg = f["yield_good"].fillna(factors["yield_good"].mean()).to_numpy()
    yb = f["yield_bad"].fillna(factors["yield_bad"].mean()).to_numpy()
    p = book[pd_col].to_numpy()
    sched = scheduled_interest(book).to_numpy()
    out = ((1 - p) * sched * yg + p * (sched * yb - book["lgd"].to_numpy() * book["loan_amnt"].to_numpy())
           - funding_cost(book).to_numpy())
    return pd.Series(out, index=book.index)


def realized_profit(book: pd.DataFrame) -> pd.Series:
    """Needs interest_received and loss_rate (from loan_outcomes) on the book."""
    loss = (book["loss_rate"].fillna(0) * book["loan_amnt"]).where(book["is_default"] == 1, 0.0)
    return book["interest_received"] - loss - funding_cost(book)
