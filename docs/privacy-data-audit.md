# Repository privacy and size audit

Audit date: 2026-11-07

## Current branches

Only two branch names exist locally and on the remote:

- `dev/backtest`
- `main`

The local `dev/backtest` branch has 11 commits that have not yet been pushed. The dashboard files are not published until those commits are pushed or the site is generated on another branch.

## What is safe to leave local

The checkout itself is about 4.2 GB, while Git history is about 33 MB. Most of the local size is intentionally ignored:

- `.venv`
- raw price, financial, and stock-pool caches under `data/input/backtesting/`
- generated backtesting output under `data/processed/backtesting/`
- multiple `intermediate.pkl` files, each about 192-214 MB

These files are needed for local calculation and are not present in the current Git trees.

## Current tracked material that can be reduced

Both current branches still track:

- 934 per-stock valuation CSVs under `data/processed/stock-valuation/all/` (about 19.6 MiB)
- `.DS_Store`
- `server.pid`
- two identical copies of the stock-name lookup CSV
- a few large notebook files, including a 4.2 MB notebook

The 934 valuation CSVs are caches that can be regenerated. They create very large diffs and are not needed by the static dashboard. The dashboard only publishes one derived JSON file.

These are cleanup candidates, but they were not deleted during this audit because the current working tree already contains hundreds of modified data files that belong to the user.

## Privacy risk in history

A historical notebook named `notebooks/[manual]_portfolio_intrinsic_value_calculator.ipynb` was committed in older revisions and later removed. Its saved outputs contained private position counts and unit costs.

No such file exists in the current `main` or `dev/backtest` tree. The current local portfolio detail files are ignored and the dashboard generator strips share counts, amounts, and cost fields before writing the public JSON.

Removing the file from the current branch does not remove it from old commits. If the repository has ever been public, treat those values as exposed and rewrite repository history before making it public again. If the repository remains private, access is limited to the repository account and its collaborators.

An anonymous GitHub API response for the repository returned `404`, which is consistent with a private repository or an unavailable repository path. Repository visibility was not independently verifiable without GitHub credentials.

## Secrets

No live SMTP passwords, GitHub tokens, cloud access keys, or private-key blocks were found. Email scripts read credentials from environment variables, and the README contains placeholders only.

## Publication boundary

The public dashboard output is limited to:

- stock code, name, weight percentage, price, return percentage
- PE, PB, PR, ROE
- screening thresholds and candidate status
- derived portfolio and benchmark return series

It does not contain:

- number of shares
- acquisition cost
- position market value
- cash balance
- transaction amounts
- email or account credentials
