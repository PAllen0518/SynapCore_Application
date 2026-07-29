# Changelog

All notable changes to `synaptic` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- Packaging via `pyproject.toml` (pinned deps, console script, ruff + pytest +
  coverage config); `docker-compose.yml` and `scripts/synapcores.sh` codify the
  SynapCores dependency; container lifecycle runbook in the README.
- Client resilience: bounded retry/backoff on connection failures, `request_id`
  surfaced on errors, batch embeddings (`embed_batch`) and bulk vector insert.
- Optional model pinning (`SYNAPCORES_EMBED_MODEL`, `SYNAPCORES_LLM_MODEL`) and a
  non-local-URL guard (`SYNAPTIC_ALLOW_REMOTE`) so candidate data isn't sent
  off-box by accident.
- `coverage.forget` retention/privacy control (`synaptic forget`), per-install
  salt via `SYNAPTIC_SALT`, and secondary indexes on the wallet-scoped columns
  (with the CE indexed-projection workaround).
- Free-permutation tokenlist mode (`generate_tokenlist(..., ordered=False)`).
- Structured logging with `-v/-vv`; MCP argument validation + bounded pagination.
- Governance scaffolding: CODEOWNERS, PR template, CONTRIBUTING, CodeQL +
  Dependabot + release workflows.
- Expanded tests: orchestrator, rankers, CLI, retention, guards, MCP validation.

### Changed
- Run recording is now transactional (a run row is written up front and
  finalized in a `finally`, so a mid-run failure still leaves an auditable row).
- `write_found_password` writes the restricted file directly instead of mutating
  the process CWD (no more `os.chdir`).

## [0.1.0] - 2026-07-29

### Added
- Initial `synaptic` layer: SynapCores-backed graph/vector/SQL/AutoML/LLM/MCP
  intelligence over BitCracker V2, with a reproducible demo against btcrecover's
  public test wallet.
