# Contributing

Thanks for your interest! This is a personal portfolio project, but issues and
pull requests are welcome.

## Development setup

```bash
make install          # uv venv + deps (Python 3.12)
pre-commit install    # enable formatting/lint hooks
make seed             # load demo data
make test             # run the suite
```

## Before opening a PR

Run the full quality gate — CI runs the same checks:

```bash
make format   # black + ruff --fix
make lint     # ruff + black --check + mypy
make test     # pytest + coverage
```

- Keep the **matching engine (`app/matching`) pure and deterministic** — no I/O,
  no randomness. Add unit tests for any rule change.
- Maintain **≥ 80 % coverage on the matching core**.
- New DB fields → generate a migration: `make revision m="describe change"`.
- Follow the existing layering (api → services → matching/repositories → models).

## Commit style

Conventional-ish prefixes are appreciated (`feat:`, `fix:`, `docs:`, `test:`,
`refactor:`, `chore:`).

## Data & compliance

Do not add scrapers or any code that bypasses a site's authentication,
robots.txt, or rate limits. New data sources must implement the `DataSource`
interface and respect the upstream's Terms of Service.
