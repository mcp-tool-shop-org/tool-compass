# Scorecard

> Score a repo before remediation. Fill this out first, then use SHIP_GATE.md to fix.

**Repo:** tool-compass
**Date:** 2026-04-23
**Version:** 2.0.7
**Type tags:** [pypi] [mcp] [cli]

## Current Assessment

Per-category scores below are placeholders — regenerate after the current
dogfood swarm lands by running `npx @mcptoolshop/shipcheck audit` and copying
the hard-gate totals verbatim. Do NOT fabricate numbers.

| Category | Score | Notes |
|----------|-------|-------|
| A. Security | TBD — regenerate post-swarm via `npx @mcptoolshop/shipcheck audit` | SECURITY.md present; pip-audit runs warn-only pending CVE baseline |
| B. Error Handling | TBD — regenerate post-swarm via `npx @mcptoolshop/shipcheck audit` | Structured results, graceful degradation, exit codes |
| C. Operator Docs | TBD — regenerate post-swarm via `npx @mcptoolshop/shipcheck audit` | README, CHANGELOG, LICENSE, Makefile `verify` present |
| D. Shipping Hygiene | TBD — regenerate post-swarm via `npx @mcptoolshop/shipcheck audit` | CI consolidated to 2 workflows; pytest config consolidated into pyproject.toml |
| E. Identity (soft) | TBD — regenerate post-swarm via `npx @mcptoolshop/shipcheck audit` | Logo, landing page, GitHub metadata present; translations lag main by one version (see below) |
| **Overall** | TBD | Regenerate after swarm merges |

## Known Gaps (as of 2026-04-23)

1. **Translation freshness** — non-English READMEs (`README.{es,fr,hi,it,ja,pt-BR,zh}.md`) are behind the current English README by at least one version; user regenerates locally via polyglot-mcp as part of the release hand-off.
2. **pip-audit baseline** — pip-audit runs with `continue-on-error: true` until the CVE baseline is reviewed; a follow-up issue will flip it to blocking.
3. **Ollama pin** — CI pins Ollama to a specific release but the SHA-256 field is a placeholder; fill in the real hash from the upstream `.sha256` file and drop the fallback `|| true` in the verification step.

## Remediation History

| Date | Wave | Highlights |
|------|------|------------|
| 2026-02-27 | Initial polish | SECURITY.md email fix, README data scope, Makefile `verify`, h1 cleanup |
| 2026-04-23 | Dogfood Stage A | CI workflow consolidation (2-file limit), flat-layout entry points, Dockerfile version sync, pinned Ollama install, pytest config consolidated, Makefile lint unmasked |
