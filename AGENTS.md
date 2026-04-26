# AGENTS.md

## Purpose

This repository contains private tooling for football prediction games:

- 7-40
- Так или иначе

The repository is personal and should be treated as private by default.

## Access And Change Policy

- Codex may work in this repository only when the current task is explicitly about `football_games`.
- Codex must not make code, notebook, data, commit, push, branch, or pull-request changes without explicit user agreement in the current conversation.
- For every non-trivial change, first state the planned files and intended behavior, then wait for confirmation unless the user has already approved the exact action.
- Do not use Avito integrations from this repository.
- Do not mix work context into this repository.
- Do not publish or upload local datasets unless the user explicitly asks.

## Privacy Rules

- Treat Telegram exports, player bets, odds snapshots, and moderation notes as private.
- Never commit raw Telegram exports, personal betting inputs, or generated private outputs by default.
- Keep raw inputs under `data/raw/`; this folder is ignored by git except for `.gitkeep`.
- Keep generated files under `output/`; this folder is ignored by git except for `.gitkeep`.

## Project Standards

- Prefer explicit parameters over hidden state.
- Validate inputs before trusting outputs.
- Keep parsers conservative and surface unparsed rows for manual review.
- Keep notebooks reproducible end to end:
  - load
  - validate
  - transform
  - score
  - export
- For Excel outputs, keep a validation sheet with errors or `ok` status.

## Repository Layout

- `docs/` - project docs, rules, data contracts, operating notes.
- `notebooks/` - runnable frameworks.
- `data/raw/` - private raw exports, ignored by git.
- `data/processed/` - derived local data, ignored by git.
- `output/` - generated Excel and reports, ignored by git.

