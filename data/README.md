# Local full-data workspace

This directory is intentionally excluded from the portfolio Git repository except for this file.

The local project currently contains generated Bronze, Silver, Gold and modeling Parquet tables derived from the 2014–2022 wholesale-price source files. These tables are large and may carry source redistribution restrictions, so they are not part of the GitHub baseline.

Two reproducibility modes are supported:

- **Code-only portfolio mode:** GitHub contains implementation, tests and Markdown documentation only. It does not contain browser JSON or any other data, so a fresh clone shows the product pages' data-unavailable state until local data is restored.
- **Full-data mode:** an authorized user restores the source files under `dataSource/rawData`, follows `docs/data_access_and_reproducibility.md`, rebuilds this directory, and then runs all Python contracts.

Do not manually edit generated Parquet files. Their row counts and hashes are recorded by the stage manifests.
