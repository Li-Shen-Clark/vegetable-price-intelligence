# Vegetable Price Intelligence

## From market signals to governed pricing decisions

I built an economics-informed decision system from 2014–2022 Chinese wholesale vegetable prices covering 117 cities and 30 products. The project does not generate an “optimal retail price.” It answers the upstream questions a pricing team must resolve first: Is the market price trustworthy? What is likely to happen next? Is a large increase worth reviewing? Does a cheaper source remain cheaper after friction and risk? Is a multi-city movement a common shock or a reproducible lead-lag signal?

## The decision problem

A production pricing engine normally combines current cost, inventory, customer terms, margin rules and approval logic. This dataset contains none of those transaction fields. I therefore positioned the project as a complementary **Pricing Intelligence layer**:

```text
market measurement → price expectation → risk review → landed-cost scenario
                  ↘ common-shock exposure ↗
                              ↓
                 pricing engine / human approval
```

The intelligence layer supplies evidence and review triggers. It never bypasses business constraints to execute a price.

## What I built

| Stage | Decision question | Method | Formal outcome |
|---|---|---|---|
| P0 · Data | Can markets and city prices be compared reliably? | Versioned market mapping, two-level medians, quality flags and coverage tiers | 8.68M market facts; 7.36M city-day facts; auditable P0 release |
| P1 · Monitor | Where is a city price relative to peers and its own season? | Historical trends, rankings, IQR, seasonality and source reliability | Historical monitor for 30 products; descriptive, not causal |
| P2 · Forecast | Does a model improve on what was knowable at the time? | Rolling-origin 7/14/28-day backtests, strong naïve baselines and conformal intervals | `partial_release`; overall WAPE improvement 6.30%, only qualified slices released |
| P3 · Alert | Can large increases be found under a fixed false-alert budget? | Independent event label, logistic model, validation-frozen threshold | `alert_release`; recall 37.69% at FPR 9.99%, for human review only |
| P4 · Procurement | Does a low market price survive transport, loss and uncertainty? | Risk-adjusted landed-cost scenario and 36-parameter sensitivity grid | `scenario_release`; candidates for inquiry, not suppliers or realized savings |
| P5 · Shock | Does a source city add reproducible information beyond common movement? | Leave-one-out factor, geographic candidates, FDR, bootstrap and one-time final test | Direction network `no-go`; product falls back to `common_shock_only` |

## The most important modeling choice

I treated every advanced method as a claim that could be rejected.

- P2 preserved last-price and seasonal baselines when the model did not earn release.
- P3 selected an action threshold under a predeclared 10% false-positive-rate constraint and disclosed that 78.69% of alerts were false positives.
- P4 carried P2’s fallback labels into downstream costs instead of relabeling all inputs as AI forecasts.
- P5 reduced 2,736 geographic candidates to 15 validation/stability edges, then rejected the directional network when only 4/15 improved final-test RMSE and median uplift was −1.39%.

This is the project’s core governance result: **evidence quality determines the product state**—model, baseline, human review, scenario, or no-go.

## Economics in the implementation

- **Price dispersion and measurement:** market composition and sparse observations can imitate economic differences, so quality and coverage enter before modeling.
- **Expectations and uncertainty:** forecasts are distributions or explicit baselines, not unqualified point estimates.
- **Transaction costs and spatial choice:** a cheaper source is evaluated after estimated distance, transport, loss and risk buffers.
- **Common shocks versus propagation:** nationwide supply, weather or seasonal movement is a competing explanation for city co-movement; after common-factor adjustment, contemporaneous FDR relationships fell 47.60%.
- **Decision under uncertainty:** ranking, fixed false-alert budgets, sensitivity and release thresholds determine actions, not statistical significance alone.

## Why it is relevant to Pricing roles

The project demonstrates the workflow behind pricing decisions rather than only model training:

1. define the business decision and the available information set;
2. establish a strong “do nothing / simple rule” baseline;
3. measure uncertainty, reliability and false-action cost;
4. translate evidence into cost, margin-review or sourcing-review inputs;
5. preserve fallbacks and approval boundaries when evidence is weak;
6. communicate limitations to both technical and commercial users.

## What I would need for production pricing

The historical data ends on 2022-06-22 and contains quoted wholesale prices rather than transactions. Production use would require refreshed sources, freshness monitoring, product specifications, volumes, inventory, customer/contract terms, actual freight and loss, supplier capacity, realized orders and controlled outcome measurement. Without those fields, the project cannot estimate demand elasticity, willingness to pay, causal pass-through, realized ROI or an optimal retail price.

## How to review the work

- `README.md` explains the full build, release states and local-only data mode.
- `docs/p6_evidence_matrix.md` maps every claim to its baseline, result and limitation.
- `docs/pricing_integration_contract.md` defines how evidence could enter a pricing workflow without authorizing price execution.
- `/case-study` is the data-free recruiter view; the five analytical routes require the authorized local browser data that is intentionally excluded from Git.
