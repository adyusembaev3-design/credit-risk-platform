# Credit policy optimization report

The optimized policy funds **60%** of the 2015 book and earned **$33.5M** of realized profit (1.55% of principal), vs. $12.4M (0.34%) for approving every loan and $19.2M (0.55%) for a grade A–D cutoff, while holding severe-recession losses to 9.8% (budget 10%).

Book: 283,026 loans issued in 2015, $3,624M of principal. The policy is chosen from model predictions only; 2015 outcomes are used afterwards to measure realized profit.

## Policies compared

| policy | loans | volume_share | exposure_usd_m | expected_profit_usd_m | expected_profit_severe_usd_m | severe_loss_rate | realized_profit_usd_m | realized_return | meets_constraints |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Approve all | 283,026 | 100% | 3,624 | 23.5 | -189.5 | 13.08% | 12.4 | 0.34% | no |
| Grades A-D only | 271,977 | 96% | 3,486 | 22.1 | -176.5 | 12.56% | 19.2 | 0.55% | no |
| Optimized | 162,188 | 60% | 2,158 | 63.5 | -40.0 | 9.83% | 33.5 | 1.55% | yes |

Constraints: severe-scenario loss ≤ 10% of approved principal · approved volume ≥ 50% of the book · grades E, F, G ≤ 15% of approved principal. Solver: highs.

## Which segments are approved

Rows are Lending Club grades; columns are deciles of predicted default risk (band 1 safest, band 10 riskiest). Blank = no loans.

| grade | band 1 | band 2 | band 3 | band 4 | band 5 | band 6 | band 7 | band 8 | band 9 | band 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | approve | approve | · | · | · | · | · | · | · | · |
| B | approve | approve | approve | approve | approve | · | · | · | · | · |
| C | approve | approve | approve | approve | approve | approve | approve | · | · | · |
| D | approve | approve | approve | approve | approve | approve | approve | approve | approve | · |
| E | approve | approve | approve | approve | approve | approve | approve | approve | approve | · |
| F | approve | approve | approve | approve | approve | approve | approve | approve | approve | · |
| G |  |  |  | approve | approve | approve | approve | approve | approve | · |

## Profit frontier

Best expected profit at each severe-loss budget (no volume floor), and what that policy actually earned.

![Frontier](figures/profit_frontier.png)

| severe_loss_budget | volume_share | expected_profit_usd_m | realized_profit_usd_m | severe_loss_rate |
| --- | --- | --- | --- | --- |
| 6.0% | 33% | 33.9 | 25.0 | 5.99% |
| 6.5% | 35% | 39.6 | 25.7 | 6.50% |
| 7.0% | 38% | 44.4 | 28.3 | 7.00% |
| 7.5% | 43% | 50.0 | 32.3 | 7.49% |
| 8.0% | 47% | 54.2 | 33.6 | 8.00% |
| 8.5% | 49% | 57.5 | 33.3 | 8.45% |
| 9.0% | 52% | 60.2 | 33.7 | 8.96% |
| 9.5% | 57% | 62.6 | 35.5 | 9.32% |
| 10.0% | 60% | 63.5 | 33.5 | 9.83% |
| 10.5% | 67% | 64.1 | 34.0 | 10.49% |
| 11.0% | 67% | 64.1 | 34.0 | 10.49% |
| 11.5% | 67% | 64.1 | 34.0 | 10.49% |
| 12.0% | 67% | 64.1 | 34.0 | 10.49% |
| 12.5% | 67% | 64.1 | 34.0 | 10.49% |
| 13.0% | 67% | 64.1 | 34.0 | 10.49% |
| 13.5% | 67% | 64.1 | 34.0 | 10.49% |
| 14.0% | 67% | 64.1 | 34.0 | 10.49% |
| 14.5% | 67% | 64.1 | 34.0 | 10.49% |
| 15.0% | 67% | 64.1 | 34.0 | 10.49% |
| 15.5% | 67% | 64.1 | 34.0 | 10.49% |
| 16.0% | 67% | 64.1 | 34.0 | 10.49% |

## Profit model

Expected profit = (1 − PD) × scheduled interest × yield_good + PD × (scheduled interest × yield_bad − LGD × principal) − funding cost (4% a year on 1.5 principal-years). Yield factors are the share of scheduled interest actually collected on loans issued before 2015 (prepayment and default cut it):

| grade | yield_good | yield_bad |
| --- | --- | --- |
| A | 84.1% | 69.4% |
| B | 82.8% | 67.0% |
| C | 81.0% | 64.2% |
| D | 80.2% | 60.7% |
| E | 78.6% | 57.3% |
| F | 78.6% | 52.3% |
| G | 76.4% | 51.1% |

Calibration check, every 2015 loan: expected profit $23.5M vs. realized $12.4M.

## Limitations

- Lending Club data only contains approved loans, so this chooses which approved loans to fund; applicants Lending Club declined are unseen (reject inference is out of scope).
- Approve/decline by segment; credit-line size and pricing are held at what Lending Club offered.
- Funding cost and balance-years are simple assumptions; prepayment also shortens funding need.
