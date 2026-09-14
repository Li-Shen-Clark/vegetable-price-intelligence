# Pricing Intelligence Integration Contract

## Purpose

This is a **design contract**, not a live API. It specifies the minimum evidence a future pricing engine or pricing analyst workspace should receive from this project. The contract deliberately stops before price execution.

## Decision boundary

```text
Vegetable Price Intelligence
  ├─ measures market evidence
  ├─ publishes model / baseline / no-go status
  ├─ calculates risk and landed-cost scenarios
  └─ requests watch or human review
                     ↓
Pricing workflow
  ├─ joins current cost and inventory
  ├─ applies customer, contract and margin rules
  ├─ obtains required approval
  └─ optionally executes a price action
```

The intelligence layer may set `watch`, `review_required` or `insufficient_evidence`. It may not set `approved_price`, `price_change`, `purchase_order` or `supplier_award`.

## Evidence envelope

| Field | Type / unit | Meaning | Required governance |
|---|---|---|---|
| `evidence_version` | string | Immutable pipeline/model version | Must resolve to configuration and model card |
| `evidence_as_of` | date | Latest source observation used | Reject stale or future-dated evidence |
| `historical_only` | boolean | Whether output is a historical replay | Must be `true` for current v0.1 |
| `product_id` | string/integer | Product key | Must resolve to frozen product dimension |
| `city_id` | string | City key | Must resolve to frozen city dimension |
| `price_unit` | enum | Current contract uses `CNY/kg` | No silent unit conversion |
| `source_reliability` | 0–1 | Historical input reliability | Display with every action signal |
| `release_status` | enum | Model, baseline, scenario, alert, common shock or no-go | Downstream must preserve label |
| `fallback_reason` | nullable string | Why a stronger route was withheld | Required for baseline/no-go |
| `model_fit_end` | date | Last observation allowed in model fit | Must precede evaluation/action origin |
| `decision_status` | enum | `watch`, `review_required`, `insufficient_evidence` | Never an execution authorization |
| `recommended_review` | enum list | Cost, margin, inventory, supply or quote review | Must name human/team owner in production |
| `claim_boundary` | string list | Non-causal, non-real-time and missing-data limits | Must remain visible in analyst UI |

## Module payloads

### Market monitor

| Field | Unit | Use |
|---|---|---|
| `historical_price` | CNY/kg | Historical benchmark only |
| `peer_percentile` | 0–1 | Cross-city relative position |
| `seasonal_percentile` | 0–1 | Within-city historical position |
| `coverage_tier` | A/B/C | Whether comparison is formally eligible |

### Forecast

| Field | Unit | Use |
|---|---|---|
| `horizon_days` | days | Planning horizon |
| `released_point` | CNY/kg | Model or frozen baseline value |
| `point_source` | enum | Model, last value, weekly or seasonal baseline |
| `p10`, `p90` | CNY/kg / nullable | Show only when interval release gate passes |
| `interval_status` | enum | Calibrated, point-only or withheld |

### Risk alert

| Field | Unit | Use |
|---|---|---|
| `risk_probability` | 0–1 | Historical ranking score |
| `action_threshold` | 0–1 | Validation-frozen review threshold |
| `event_definition_version` | string | Resolves the 14-day spike label |
| `expected_review_window_days` | days | Review timing, not guaranteed lead time |

### Procurement scenario

| Field | Unit | Use |
|---|---|---|
| `released_input_price` | CNY/kg | Preserves P2 model/baseline route |
| `risk_buffer` | CNY/kg | Interval or historical-route uncertainty buffer |
| `estimated_transport` | CNY/kg | Parameterized, not a freight quote |
| `loss_rate` | 0–1 | Scenario assumption |
| `scenario_landed_cost` | CNY/kg | Input to inquiry/margin review |
| `rank_stability` | 0–1 | Sensitivity across configured scenarios |

### Common shock and exposure

| Field | Unit | Use |
|---|---|---|
| `common_factor_change` | log change | Product-wide historical movement |
| `positive_common_shock` | boolean | Training-P95 historical shock indicator |
| `city_exposure_score` | 0–100 | Descriptive review priority, not probability |
| `directional_network_status` | enum | Current value must be `not_released` |

## Downstream acceptance rules

1. A baseline fallback cannot be renamed as a model prediction.
2. A withheld interval must stay null; downstream cannot invent a confidence band.
3. `alert_release` can create a review task but cannot change a price.
4. Procurement outputs require actual quote, capacity and logistics checks before use.
5. `common_shock_only` forbids source-target edges, propagation paths and automatic geographic expansion.
6. Any observation after `evidence_as_of` must trigger a new version, not overwrite historical evidence.

## Production gaps

A live integration additionally needs current supplier costs, item specification/pack size, inventory and service levels, customer/contract terms, demand response, promotion calendar, freight quotes, supplier capacity, identity/authorization, audit logs and realized-outcome measurement. Those fields belong to the production pricing environment and are intentionally absent here.
