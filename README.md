# Vegetable Price Intelligence

**[View the live portfolio](https://li-shen-clark.github.io/vegetable-price-intelligence/)** · [Project Case Study](PORTFOLIO_CASE_STUDY.md) · [Project Roadmap](PROJECT_ROADMAP.md)

I built a historical market intelligence project that connects wholesale vegetable prices to forecasting, risk review, and procurement scenarios. It covers **117 Chinese cities and 30 vegetables**, using observations from 2014 through **June 22, 2022**.

I began assembling and harmonizing the underlying data in **2021**, then developed the forecasting, risk, and decision applications in **2026**. The public website presents the methods and results; the analytical applications run locally with authorized data.

## My contribution

- **Data engineering:** I built an auditable pipeline for **8.68 million market records**, producing 7.36 million city-day records with market mappings, quality flags, and coverage tiers.
- **Modeling and evaluation:** I developed price forecasts and an independent price-spike classifier, compared them with simple baselines, and separated model selection from final testing.
- **Decision applications:** I built five local interfaces for historical monitoring, forecasts, risk alerts, procurement scenarios, and common price shocks. The procurement tool compares sourcing options under transport, loss, and risk assumptions.
- **Release decisions:** I defined when to use a model, retain a baseline, withhold an unreliable interval, or reject a feature. I implemented tests and publication checks, and built the public case study.

The implementation uses Python, pandas, NumPy, SciPy, and Parquet for analysis; TypeScript and React with Vinext/Vite for the local applications; and GitHub Actions and GitHub Pages for checks and the public website.

## Selected results

These results come from historical backtests and a final test set held apart from model selection.

| Area | Result | What it means for the product |
| --- | --- | --- |
| **Price forecasting** | Weighted absolute percentage error (WAPE) was **17.54%**, versus **18.72%** for the selected baseline combination: a **6.30% relative improvement**, below the 8% overall target. | The main decision horizons are 14 and 28 days. Only qualifying product–horizon combinations use model forecasts; weaker combinations retain baselines, and unreliable intervals are withheld. |
| **Price-spike alerts** | Precision–recall area under the curve (PR-AUC) was **0.2204**, versus **0.0775** for the best simple baseline. At the frozen threshold, precision was **21.31%** and recall was **37.69%**. | Alerts help prioritize human review. Most alerts were false positives, so the system does not trigger automatic pricing actions. |
| **City relationships** | Only **4 of 15** relationships selected before the final test improved prediction error in that test. Median improvement was **−1.39%**. | I withheld the directional network and retained common-shock and city-exposure analysis. The results do not establish causal price transmission. |

The project supports historical analysis and decisions under stated assumptions. The data does not include current quotes, inventory, supplier capacity, or actual freight costs. Procurement rankings identify candidates for inquiry; they do not establish realized savings or authorize orders.

See the [evidence matrix](docs/p6_evidence_matrix.md) for the results, baselines, and limitations behind each claim.

## Run locally

### Preview the public website

From the repository root, use Python 3 to serve the same static files published on GitHub Pages:

```bash
python3 -m http.server 8765 --directory portfolio-site
```

Open [localhost:8765](http://localhost:8765/). This preview requires no source data or JavaScript build.

### Run the local application

Use **Node.js 22.13 or later**:

```bash
cd web
npm ci
npm run dev
```

Open [localhost:3000/case-study](http://localhost:3000/case-study) for the case study. The five analytical pages require authorized local data and show a data-unavailable state in a fresh clone.

The public repository includes code, tests, configuration, documentation, and static assets. Source price records, generated datasets, model outputs, and browser data are excluded. Full reproduction requires authorized inputs and the steps in [Data Access and Reproducibility](docs/data_access_and_reproducibility.md).

### Check the public repository

From the repository root, use Python 3.11 or later:

```bash
python3 scripts/verify_portfolio_bundle.py
python3 scripts/verify_pages_bundle.py
python3 -m unittest tests.test_portfolio_bundle tests.test_p7_pages_site -v
```

These checks need no source data. Use a full Git clone because the publication checks inspect commit history.

After installing the web dependencies, check the local application with:

```bash
cd web
npm run lint
npm run build
```

Full analysis also requires the dependencies in [requirements.txt](requirements.txt). Follow the stage runbooks below when restoring an authorized workspace; existing final-test results remain frozen.

## Documentation

- The [Project Case Study](PORTFOLIO_CASE_STUDY.md) explains the decisions, methods, and results.
- The [Project Roadmap](PROJECT_ROADMAP.md) maps the implementation stages to their outcomes.
- The model cards document [forecasting](docs/p2_final_model_card.md), [risk alerts](docs/p3_final_model_card.md), and [common shocks and city relationships](docs/p5_model_card.md).
- The runbooks describe [forecasting](docs/p2_runbook.md), [risk alerts](docs/p3_runbook.md), [procurement scenarios](docs/p4_runbook.md), and [common-shock analysis](docs/p5_runbook.md).
- The [Pricing Integration Contract](docs/pricing_integration_contract.md) describes how the outputs could support a pricing workflow with human approval.
- The [Data Access and Reproducibility guide](docs/data_access_and_reproducibility.md) explains data requirements and publication boundaries.
