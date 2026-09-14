# Data Access, Reproducibility and Publication Boundary

## 1. Repository modes

### Portfolio mode

The GitHub baseline is deliberately code-only. It contains source code, tests, configuration and Markdown documentation, but no source records, derived tables, reference CSV files, model-output artifacts or browser-data JSON.

This mode is sufficient to:

- inspect the complete P0–P4 implementation;
- inspect the four product-page implementations and their decision boundaries;
- run data-independent repository, narrative and production-build checks;
- review the methodology and test contracts. Execution logs remain local by policy.

It is not sufficient to populate the four product pages, retrain models or rerun the full-data tests. A fresh clone builds successfully, but the pages show their data-unavailable state until an authorized local copy of `web/public/data` is restored or regenerated.

### Full-data mode

Full reproduction requires authorized copies of the 2014–2022 wholesale-price CSV files and the locally generated Bronze/Silver/Gold/modeling Parquet tables.

Expected source placement:

```text
dataSource/rawData/*.csv
```

The current project contains 30 product files. The pipeline identifies products through the versioned reference/configuration layer and writes all derived tables under `data/`.

Start with:

```bash
python3 src/pipeline/build_p0.py
```

Then follow the P1–P4 runbooks in stage order. Only after all required inputs are restored should the full suite be run:

```bash
python3 -m unittest discover -s tests -v
```

## 2. What is not tracked

| Local content | Approximate size | Reason excluded |
|---|---:|---|
| `OneDrive_1_8-31-2026.zip` | 4.1GB | Local source archive; too large and not reviewed for redistribution |
| `dataSource/` | 3.8GB | Raw and duplicate source extracts, including 585MB/557MB migration CSV files |
| `data/` generated tables | 399MB | Rebuildable Bronze/Silver/Gold/modeling data; full source rights required |
| `artifacts/` and `baselines/` | local generated outputs | Predictions, evaluation details and frozen model evidence are data-derived |
| `reference/*.csv` and worklists | local reference data | City, market and product mappings are not part of the code-only publication |
| `web/public/data/` | about 30MB | Historical browser snapshots are data and are kept local |
| data-formatted files under `docs/` | local audit outputs | CSV/JSON evidence is excluded even when small |
| `web/node_modules` and build caches | environment-dependent | Recreated from `package-lock.json` |

No local files are deleted by this policy. `.gitignore` only prevents accidental Git tracking.

## 3. What is tracked

- `src/`, `tests/` and non-data `config/` files;
- Markdown documentation under `docs/`;
- P0–P4 plans and Guidebook; append-only execution logs remain local and untracked;
- Web source, static non-data assets and lockfile;
- repository-boundary verification code.

No tracked file is intended to reconstruct the underlying price observations. Local browser JSON remains a historical demonstration artifact, not a current quote feed.

## 4. Verification

From a portfolio clone:

```bash
python3 scripts/verify_portfolio_bundle.py
cd web
npm ci
npm run build
```

The bundle verifier checks required code/documentation, ignore rules, accidental local paths, the Git candidate list and every path reachable from the branch history that would be pushed. It rejects data directories, CSV, Parquet, data-derived artifacts and browser snapshots.

To run a populated local demo, restore or regenerate `web/public/data` in an authorized full-data workspace and then run `npm run dev`. From that complete workspace, run the full Python suite in addition to the commands above.

## 5. Publication and licensing

The first GitHub repository must remain private. Before changing visibility to public:

1. confirm that the Git tree remains code-only and contains no wholesale-price source or derived browser data;
2. decide and add an explicit code license;
3. rerun the no-data, credential, absolute-path and tracked-size audits;
4. confirm that no documentation implies the excluded data ships with the repository.

Until these steps are complete, no license for reuse is granted and the project must not be presented as an openly licensed dataset.
