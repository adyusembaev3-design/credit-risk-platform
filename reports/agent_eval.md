# AI risk analyst evaluation

The analyst (claude-sonnet-5-5) passed **100%** of 28 test questions; **95%** of its cited claims were supported by the cited passage (judged by claude-haiku-5-5), and 0% of answers contained a citation the tools never returned.

| Category | What passes |
| --- | --- |
| numeric | Final number matches the module's results file (2% tolerance) |
| sql | Final number matches a value computed directly from the portfolio table (1%) |
| abstain | Says NOT_FOUND for a question the data cannot answer |
| filings | Answers a cross-lender question citing 10-K passages from at least two lenders |

| category | questions | accuracy | avg_tool_calls | answers_with_invalid_citation | faithfulness |
| --- | --- | --- | --- | --- | --- |
| numeric | 15 | 100% | 2.1 | 0% | 92% |
| sql | 4 | 100% | 2.0 | 0% | 88% |
| abstain | 4 | 100% | 2.0 | 0% | 100% |
| filings | 5 | 100% | 4.2 | 0% | 98% |

Tokens: 230,871 in, 17,675 out · median 4s per question.

## Claims the judge marked unsupported

- It was measured on 283,026 loans issued Jan 2015–Dec 2015. [R:model_metrics]
- The out-of-time test covers 283,026 loans issued January–December 2015. [project/model_report#performance]
- Expected loss is $364.8M on the 2015 book. [R:stress_results]
- It also matches the 2015 stressed book. [Q3]
- The 2015 book had 141,513 applicants available per arm, far more than the 7,035 required. [project/experiment_report#design-before-outcomes]
- The `stressed_book` table, which holds the 2015 book, also has 77,423 grade C loans. [Q2]
- It mentions national unemployment rates only as a factor in the timing of its marketing spend, not in its loss estimates. [ATLC-10K-2026#0109]

## Every question

| category | question | final | correct | tool_calls | citations | invalid_citations |
| --- | --- | --- | --- | --- | --- | --- |
| numeric | What is the GBM's out-of-time AUC? | 0.688 | pass | 2 | 2 | 0 |
| numeric | What out-of-time AUC does Lending Club's sub-grade benchmark reach? | 0.679 | pass | 2 | 3 | 0 |
| numeric | What is the WOE scorecard's out-of-time KS statistic? | 0.254 | pass | 1 | 1 | 0 |
| numeric | What is the population stability index of the GBM between training and out-of-time? | 0.0138 | pass | 2 | 3 | 0 |
| numeric | What is the expected loss on the 2015 book under the severe scenario, in $ millions? | 474.0 | pass | 2 | 2 | 0 |
| numeric | What is the expected loss rate under the adverse scenario? | 10.07% | pass | 2 | 2 | 0 |
| numeric | By what factor does a 1-point rise in unemployment multiply default odds? | 1.16 | pass | 2 | 2 | 0 |
| numeric | What was the ratio of expected to actual losses in the stress-test backtest? | 0.95 | pass | 2 | 2 | 0 |
| numeric | What is the average loss given default used in the stress test? | 0.5166 | pass | 3 | 3 | 0 |
| numeric | What realized profit did the optimized credit policy earn, in $ millions? | 33.5 | pass | 1 | 1 | 0 |
| numeric | What realized profit would approving every 2015 loan have earned, in $ millions? | 12.37 | pass | 2 | 2 | 0 |
| numeric | What share of the 2015 book (by principal) does the optimized policy fund? | 0.5955 | pass | 4 | 4 | 0 |
| numeric | In the champion/challenger experiment, what was the profit uplift per applicant in dollars? | 84.12 | pass | 2 | 4 | 0 |
| numeric | How many applicants per arm did the experiment's power calculation require? | 7035 | pass | 2 | 2 | 0 |
| numeric | What was the default rate of loans funded by the challenger policy? | 12.13% | pass | 2 | 2 | 0 |
| sql | How many loans of grade C are in the 2015 book? | 77423 | pass | 2 | 2 | 0 |
| sql | What is the average predicted default probability (pd_gbm) of grade E loans in the 2015 book? | 0.2537 | pass | 2 | 2 | 0 |
| sql | What is the realized default rate of grade B loans in the 2015 book? | 11.90% | pass | 2 | 2 | 0 |
| sql | What is the total principal of the 2015 book in $ millions? | 3624.3 | pass | 2 | 2 | 0 |
| abstain | What was the default rate of 60-month loans in the portfolio? | NOT_FOUND | pass | 2 | 3 | 0 |
| abstain | What AUC did the GBM reach on loans issued in 2017? | NOT_FOUND | pass | 2 | 2 | 0 |
| abstain | How many loans did the portfolio originate in Canada? | NOT_FOUND | pass | 2 | 2 | 0 |
| abstain | What will the US unemployment rate be in 2027? | NOT_FOUND | pass | 2 | 3 | 0 |
| filings | How do consumer lenders in the peer filings describe the effect of unemployment on credit losses? |  | pass | 5 | 9 | 0 |
| filings | How do the peer lenders estimate their allowance for credit losses? |  | pass | 4 | 10 | 0 |
| filings | What risks do the peer lenders describe about lending to near-prime or subprime borrowers? |  | pass | 4 | 10 | 0 |
| filings | How do the peer lenders describe the risk that rising interest rates raise their funding costs? |  | pass | 4 | 10 | 0 |
| filings | What regulatory risks do the peer consumer lenders highlight in their 10-Ks? |  | pass | 4 | 14 | 0 |
