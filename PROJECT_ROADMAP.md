# Vegetable Price Intelligence — Project Roadmap

## Executive summary

This project converts 8.68 million historical wholesale-market records into a governed Pricing Intelligence layer. It measures market prices, forms historical expectations, flags review-worthy increases, compares risk-adjusted sourcing scenarios, and tests whether apparent city-to-city propagation survives common-shock controls.

The system is complementary to a pricing engine. It supplies evidence, uncertainty and review triggers; it does not set a retail price, approve a quote, select a supplier or execute a transaction.

```text
market measurement → price expectation → risk review → landed-cost scenario
                  ↘ common-shock exposure ↗
                              ↓
                 pricing engine / human approval
```

Current state: **P0–P7 completed as a historical portfolio prototype**. The public site is a data-free recruiter view; the five data-backed analytical workspaces remain local because the underlying dataset is not published.

The strongest methodological result is P5’s no-go. Common-factor adjustment removed 47.60% of apparent contemporaneous relationships, and sealed final testing rejected the remaining directional claim. Publishing zero directional edges—rather than a visually persuasive but non-replicating network—is evidence that the release governance worked.

## Roadmap at a glance

| Stage | Decision question | Economics and method | Formal outcome | Pricing handoff |
|---|---|---|---|---|
| P0 · Trusted data | Are market and city prices comparable enough for analysis? | Price measurement, market composition, two-level medians, mapping and reliability tiers | 8.68M market facts, 7.36M city-day facts and auditable quality flags | Establishes the cost/market evidence layer |
| P1 · Price monitor | Where is a city price relative to peers and its own season? | Price dispersion, seasonality, rankings, IQR and source reliability | Historical monitor for 30 products across 117 cities | Supports benchmark and anomaly review |
| P2 · Forecast | Does a model improve on information available at the time? | Rolling-origin backtests, strong naïve baselines and conformal uncertainty | `partial_release`; 6.30% overall WAPE improvement with slice-level fallbacks | Supplies qualified expectations or explicit baseline routes |
| P3 · Risk alert | Can large increases be detected under a fixed false-alert budget? | Event design, asymmetric action cost and a validation-frozen threshold | `alert_release`; 37.69% recall at 9.99% FPR | Triggers human supply/inventory/pricing review |
| P4 · Procurement | Does a lower quoted price survive transport, loss and uncertainty? | Spatial price dispersion, transaction costs, risk-adjusted landed cost and sensitivity | `scenario_release`; historical candidates for inquiry | Supplies scenario cost inputs, never a purchase order |
| P5 · Shock analysis | Does a source city add information beyond common movement? | Common shocks, geographic candidate restriction, FDR, bootstrap and final-test uplift | Direction network `no-go`; `common_shock_only` retained | Expands manual review scope without causal or automated claims |
| P6 · Career delivery | Can every claim be traced to evidence and a Pricing interface? | Evidence matrix, model governance and read-only integration contract | Data-free case study, career pack and code-only CI | Explains how evidence could enter an approval workflow |
| P7 · Public release | Can a recruiter verify ownership, economics and limitations quickly? | Content hierarchy, release-state preservation and publishable-data controls | GitHub Pages recruiter site released | Public proof of work without exposing source data |

## Phase 1 — Build a trustworthy measurement layer

### P0 · Data foundation

**Economic problem.** A quoted city price can change because the market changed, because the reporting markets changed, or because the source is sparse. Modeling before resolving that measurement problem would turn data composition into a false economic signal.

**What was built.** Versioned market-to-city mapping, row-level quality flags, market-day and city-day medians, source reliability scores, and A/B/C coverage tiers.

**Evidence.**

- 8,682,381 market records across 30 vegetables and 269 source market names;
- 7,358,606 city-day records across 117 cities;
- 3,510 product-city coverage classifications: 919 Tier A, 1,814 Tier B and 777 Tier C;
- 99.6535% record-weighted mapping coverage with unresolved records retained rather than guessed.

**Decision outcome.** Downstream experiments use explicit eligibility and reliability rules rather than treating every observed quote as equally informative.

### P1 · Historical Price Monitor

**Economic problem.** Pricing and procurement users first need context: peer-city dispersion, seasonal position and data reliability.

**What was built.** Historical monthly trends, city rankings, cross-city median and IQR, seasonal ranges, market counts and quality-state explanations. The browser consumes a compact 285,723-row monthly mart rather than the full city-day table.

**Decision outcome.** P1 supports descriptive benchmark and exception review. It does not infer arbitrage profits, market power or causal integration.

## Phase 2 — Turn expectations into governed decisions

### P2 · Probabilistic Price Forecasting

**Economic problem.** A pricing team needs to know whether a forecast beats a credible “do nothing” rule under the information available at the decision date.

**Design.** Ten products and 366 Tier A product-city series were evaluated at 7/14/28-day horizons. The formal MVP decision focus is 14/28 days; 7 days remains a stress test with an explicit baseline route. Model selection used validation only; final test was consumed once. Last valid price, weekly pattern and historical seasonal median were registered as baselines.

**Result.**

- final-test model WAPE: 17.54%; best baseline: 18.72%; relative improvement: 6.30%;
- 80% interval coverage: 70.91%, below the desired calibration range;
- by horizon, 7 days fell back for 8/10 products and averaged −4.24% relative improvement, while 14 and 28 days released model points for 9/10 products and averaged +4.42% and +11.33%;
- release matrix: 1 `model_target`, 3 `model_minimum`, 16 `point_only_model`, 10 `baseline_fallback` groups.

**Decision outcome.** `partial_release`. Qualified slices expose model evidence; weak slices retain a named baseline. The product never relabels a current-price baseline as a model forecast.

### P3 · Price Risk Alert

**Economic problem.** A large increase may justify early review even when an exact price forecast is uncertain, but false alerts consume attention.

**Design.** An independent 14-day event label, weekly historical alert origins and a threshold selected on validation under a 10% FPR constraint.

**Result.** Final-test PR-AUC 0.2204 versus 0.0775 for the best simple baseline; precision 21.31%, recall 37.69%, FPR 9.99%, and mean lead time 7.18 days.

**Decision outcome.** `alert_release` for offline human review. Because 78.69% of alerts are false positives, it is not an automated repricing rule.

### P4 · Procurement Scenario Engine

**Economic problem.** Observed price dispersion is not an actionable sourcing opportunity until transport, handling loss and uncertainty are included.

**Design.** A frozen historical scenario compares local and external cities using:

```text
landed unit cost = (released price + transport + risk buffer) / (1 - loss rate)
```

P2 release labels remain visible. Published forecast intervals are used where qualified; other groups use pre-origin historical residual buffers that are explicitly not called forecast intervals. A 36-scenario grid tests ranking sensitivity.

**Decision outcome.** `scenario_release`. The output is a shortlist for inquiry, not a supplier award, realized saving or executable order.

## Phase 3 — Test the advanced propagation claim

### P5 · Common Shock & City Exposure

**Economic problem.** Co-movement may reflect shared weather, national supply or seasonality rather than information flowing from one city to another.

**Design.** Geography reduced the candidate set to 2,736 directed pairs. The experiment removed training-period seasonality and a leave-one-out common factor, controlled false discovery within product, tested window/bootstrap stability, and required one-time final-test predictive uplift over a target-history-plus-common-factor baseline.

**Result.** Common-factor adjustment first reduced contemporaneous training-period FDR relationships from 1,481 to 776, a 47.60% decline. In the separate directional pipeline, product-level BH-FDR reduced 174 raw train-significant pairs to 51; fifteen edges passed validation and stability, but only 4/15 improved final-test RMSE and median improvement was −1.39%.

**Decision outcome.** The directional network was rejected and zero edges were released. This is the intended methodological outcome—not a missing deliverable. The released product is `common_shock_only`: common movement and historical city exposure can widen manual review, but no source-target edge, causal propagation path or automatic price action is published.

## Phase 4 — Package the evidence for review

### P6 · Evidence and integration governance

P6 converted technical results into an evidence matrix, recruiter case study, role-specific interview material and a read-only Pricing integration contract. The contract separates intelligence outputs from the fields a production engine would still require: current cost, demand, inventory, margin rules, customer terms and approvals.

### P7 · Public portfolio release

P7 published a six-file static GitHub Pages bundle with no raw data, analytical marts or model artifacts. Automated checks enforce the public payload, role positioning, release states, historical cutoff and non-production boundary.

## Governance decisions that changed the product

| Evidence condition | Product behavior |
|---|---|
| Model earns slice-level uplift and acceptable uncertainty | Release the qualified model output |
| Point model improves but interval calibration fails | Release P50 only; suppress the interval |
| Model fails the registered comparison | Fall back to the frozen simple baseline |
| Alert meets the fixed FPR budget | Use as a human-review trigger with false-alert burden shown |
| Procurement inputs rely on assumptions | Label the result as a scenario and expose sensitivity |
| Directional network fails final-test uplift | Publish no network; retain only common-shock exposure |

This is the central product principle: **evidence quality determines the release state**. More complex modeling does not automatically produce a stronger product claim.

## Economics and Pricing thread

The same economic questions are checked across the roadmap:

1. **Measurement:** could composition or reporting quality explain the observed difference?
2. **Expectations:** does the forecast outperform a feasible baseline using only past information?
3. **Decision cost:** what are the consequences of false alerts, interval failure or unstable rankings?
4. **Spatial friction:** does a quoted price advantage survive distance, transport, loss and risk?
5. **Competing explanations:** is apparent propagation actually a common shock?
6. **Workflow boundary:** is the output evidence, a review trigger, a scenario, or an executable decision?

The formal seven-question control is documented in [`docs/economics_pricing_stage_gate.md`](docs/economics_pricing_stage_gate.md).

## Evidence map

- [`PORTFOLIO_CASE_STUDY.md`](PORTFOLIO_CASE_STUDY.md): concise recruiter narrative and formal outcomes.
- [`docs/p6_evidence_matrix.md`](docs/p6_evidence_matrix.md): claim-to-baseline-to-limitation traceability.
- [`docs/pricing_integration_contract.md`](docs/pricing_integration_contract.md): proposed read-only handoff to a pricing workflow.
- [`docs/data_access_and_reproducibility.md`](docs/data_access_and_reproducibility.md): public code mode versus authorized full-data mode.
- [`docs/p2_final_model_card.md`](docs/p2_final_model_card.md), [`docs/p3_final_model_card.md`](docs/p3_final_model_card.md), and [`docs/p5_model_card.md`](docs/p5_model_card.md): frozen evaluations and release decisions.
- [`docs/data_dictionary.md`](docs/data_dictionary.md) and [`docs/data_quality_report.md`](docs/data_quality_report.md): units, grain, quality and use boundaries.
- [Live GitHub Pages portfolio](https://li-shen-clark.github.io/vegetable-price-intelligence/): data-free public review surface.

## What a production phase would require

The historical prototype ends at evidence and review support. A production phase would require refreshed licensed data, freshness monitoring, standardized product specifications, transaction volumes, inventory, supplier capacity, actual freight and loss, customer and contract terms, realized orders, demand outcomes and controlled business measurement.

Those additions would enable questions this dataset cannot answer: elasticity, willingness to pay, causal pass-through, realized procurement ROI, margin optimization and executable retail pricing. Until then, the correct product boundary remains **Pricing Intelligence upstream of human approval and the pricing engine**.

## Public repository boundary

The public repository contains code, configuration, tests and curated evidence documents. Raw/derived data, model artifacts, detailed internal execution plans and execution logs remain local. Git history and automated tests provide implementation evidence without requiring recruiters to navigate operational work notes.
