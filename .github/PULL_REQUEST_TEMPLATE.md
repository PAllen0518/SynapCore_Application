<!-- Keep PRs scoped to one concern (behavior vs. style). -->

## What & why

<!-- One or two sentences: what this changes and the motivation. -->

## Type

- [ ] Feature
- [ ] Fix
- [ ] Refactor / cleanup
- [ ] Docs / tests / CI only

## Checklist

- [ ] `ruff check --config synaptic/pyproject.toml synaptic/` passes
- [ ] `ruff format --check --config synaptic/pyproject.toml synaptic/` passes
- [ ] `pytest synaptic/tests/` passes (DB-free)
- [ ] If it touches the live path, `SYNAPTIC_LIVE=1 pytest synaptic/tests/test_integration.py` was run
- [ ] No secret, wallet key, hint set, or recovered password is committed
- [ ] Docs updated if behavior or interfaces changed

## How tested

<!-- Commands run and results. -->
