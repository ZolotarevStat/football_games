# football_games

Private repository for tooling around two football prediction games:

- `7-40`
- `Так или иначе`

The repo is intentionally small: formalized docs, reproducible notebooks, and local-only data/output folders.

## Projects

| Project | Notebook | Docs |
|---|---|---|
| 7-40 | `notebooks/7_40_framework.ipynb` | `docs/7-40.md` |
| Так или иначе | `notebooks/tak_ili_inache_framework.ipynb` | `docs/tak_ili_inache.md` |

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Data Policy

Raw exports and generated outputs are private and ignored by git:

- `data/raw/`
- `data/processed/`
- `output/`

Commit only reusable code, notebooks, and documentation unless explicitly decided otherwise.

## Current Status

- Initial notebooks run on mock data.
- Real Telegram exports, odds snapshots, player TXT inputs, and target Excel examples are still needed for calibration.

