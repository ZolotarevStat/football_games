# football_games

Private repository for tooling around two football prediction games:

- `7-40`
- `Так или иначе`

The repo is intentionally small: formalized docs, reproducible notebooks, and local-only data/output folders.

## Projects

| Project | Notebook | Docs |
|---|---|---|
| 7-40 | `notebooks/7_40_framework.ipynb` | `docs/7-40.md`, `docs/7-40-pipeline.md` |
| Так или иначе | `notebooks/tak_ili_inache_framework.ipynb` | `docs/tak_ili_inache.md` |

## 7-40 Parser

Reusable local pipeline:

```bash
MPLCONFIGDIR=output/7_40_analysis/.mpl \
python scripts/analyze_7_40.py --days 14 --out-dir output/7_40_analysis
```

Full local run:

```bash
MPLCONFIGDIR=output/7_40_analysis/.mpl \
python scripts/analyze_7_40.py --out-dir output/7_40_analysis/full_dataset --backup-results
```

The script has two framework layers:

- public blog/channel statistics parser;
- team-chat preview and recommendation parser.

See `docs/7-40-pipeline.md` for setup, inputs, outputs, current parser quality, and next steps.

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

- 7-40 has a working local parser/visualization pipeline for Telegram exports.
- Initial notebooks run on mock data.
- `Так или иначе` still needs real TXT/Excel examples for calibration.
