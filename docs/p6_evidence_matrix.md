# P0–P5 Evidence Matrix

This matrix is the source of truth for public portfolio claims. A stronger-sounding sentence is not allowed unless it is supported here and remains within the stated boundary.

| Stage | User decision | Economic mechanism | Counterfactual / baseline | Formal evidence | Release state | Allowed claim | Not allowed |
|---|---|---|---|---|---|---|---|
| P0 | Whether a market/city series is reliable enough for analysis | Measurement error, market composition, non-random missingness | Raw source record before mapping/quality logic | 8,682,381 market rows; 7,358,606 city-day rows; 3,510 product-city tiers | `data_release` | Versioned and auditable historical price facts | Transactions, quantities, representative market-clearing price |
| P1 | Whether a city price is high/low versus peers or its own historical season | Spatial price dispersion and seasonality | Cross-city median/IQR and within-city seasonal history | 285,723 city-month records; 30 products | `historical_monitor` | Historical relative position and source quality | Current price, causal reason, arbitrage profit |
| P2 | Whether a forecast should replace a simple rule for a product×horizon | Adaptive expectations, persistence and seasonal supply | Last valid price, weekly pattern and historical seasonal median | Final WAPE 17.54% vs 18.72%; 6.30% relative improvement; 1/3/16/10 release matrix | `partial_release` | Qualified model slices and explicit baseline fallbacks | All models beat baseline; all intervals calibrated |
| P3 | Whether a possible future price spike merits manual review | Asymmetric false-action cost and risk screening | Event prevalence, series event rate and volatility/momentum heuristic | PR-AUC 0.2204; recall 37.69%; precision 21.31%; FPR 9.99%; lead 7.18 days | `alert_release` | Historical ranking and fixed-threshold review trigger | Real-time alert, high precision, automatic repricing |
| P4 | Which city is worth requesting a quote from under stated assumptions | Spatial arbitrage bounded by transaction cost, loss and uncertainty | Same-formula local-city landed cost | 843 snapshot rows; 36 scenarios; 1,080 sensitivity rows | `scenario_release` | Risk-adjusted candidate comparison and rank stability | Actual freight, supplier capacity, realized saving, optimal supplier |
| P5 | Whether source-city history adds information beyond target/common history | Information diffusion or trade linkage versus common supply shock | Target residual lags plus leave-one-out common-factor lags | 2,736 candidates; 51 FDR; 15 validation/stable; 4 final-positive; median final uplift −1.39% | `common_shock_only` | Common movement and historical city exposure | Direction network, causal trade flow, propagation center/path |

## Cross-stage governance

| Governance question | Project answer |
|---|---|
| What if an advanced model is weaker? | Preserve the frozen baseline and label the fallback. |
| What if uncertainty is not calibrated? | Withhold the interval while retaining only the eligible point route. |
| What if a risk model has many false alerts? | Treat it as a human review queue and display precision/FPR. |
| What if a cost ranking depends on assumptions? | Show parameter sensitivity and call options “candidates for inquiry.” |
| What if a network is significant in train but fails final test? | Publish no directional edges; fall back to common-shock exposure. |
| What does this project send to a pricing engine? | Evidence, reliability, fallback status and requested human action—not an executable price. |

## Claim-review rule

Public text, résumé bullets, interview answers and `/case-study` must preserve three qualifiers:

1. **Historical:** source period ends 2022-06-22.
2. **Predictive or descriptive, not causal:** no experiment or valid causal identification strategy is present.
3. **Decision support, not execution:** no customer, inventory, contract, demand or approval data is present.
