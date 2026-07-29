# synaptic backlog

Lightweight, tracked list of open work for the subsystem. When the repo's GitHub
Issues are enabled, migrate these and reference the issue IDs in commits/PRs
(see CONTRIBUTING.md). Closed items are kept briefly for history, then pruned.

## Open

| ID | Priority | Item | Notes |
|----|----------|------|-------|
| SYN-1 | med | Adopt PR + branch-protection workflow on `master` | Scaffolding is in place (CODEOWNERS, PR template, CI). Needs the GitHub branch-protection setting enabled and future changes to land via PRs. |
| SYN-2 | low | Schema migrations | Currently `CREATE TABLE IF NOT EXISTS` only; add a `schema_version` + migration path if the schema evolves. |
| SYN-3 | low | Nightly live-integration CI job | Spin up the CE container in CI and run `SYNAPTIC_LIVE=1` tests on a schedule. |
| SYN-4 | low | Free-permutation ranking heuristics | `ordered=False` mode exists; tune ranking for the larger unordered candidate sets. |

## Recently closed (2026-07-29 hardening pass)

- SYN-C1 SQL label lookups centralized through `sql_literal`.
- SYN-C2 Orchestrator + rankers unit-tested (DB-free).
- SYN-C3 Secondary indexes added (with the CE indexed-projection workaround).
- SYN-C4 Retention/privacy control (`forget`), non-local-URL guard, batch embeddings.
- SYN-C5 Transactional run recording; removed `os.chdir` global mutation.
- SYN-C6 Packaging (pyproject), compose + runbook, governance + release workflows.
