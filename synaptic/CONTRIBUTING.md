# Contributing to synaptic

Small subsystem, simple rules.

## Workflow

1. Branch off `master` (`feature/...` or `fix/...`) - never commit directly to `master`.
2. Open a PR using the template. CI (lint + format + tests, Python 3.10-3.12) must pass.
3. Keep PRs scoped to one concern; separate style from behavior.

**Branch protection (maintainer setup):** enable on `master` - require the CI
status check to pass and require a PR before merge. This is a GitHub repo
setting (Settings -> Branches), not something the repo can enforce by itself.

## Local checks

```bash
pip install -e "synaptic[dev]"
ruff check  --config synaptic/pyproject.toml synaptic/
ruff format --check --config synaptic/pyproject.toml synaptic/
pytest synaptic/tests/                       # DB-free; what CI runs
# opt-in end-to-end (needs a live SynapCores):
SYNAPTIC_LIVE=1 SYNAPCORES_URL=... SYNAPCORES_PASSWORD=... \
  pytest synaptic/tests/test_integration.py
```

## Never commit

Wallet key files, hint sets (`*hints*.json`), generated tokenlists
(`synaptic_tokens_*.txt`), `RECOVERED_PASSWORD.txt`, or any secret. `.gitignore`
covers these; keep it that way.

## Releasing

Bump `version` in `synaptic/pyproject.toml`, add a `CHANGELOG.md` entry, then tag
`vX.Y.Z`. The release workflow builds the sdist/wheel on the tag.
