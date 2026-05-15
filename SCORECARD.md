# Scorecard

> Score a repo before remediation. Fill this out first, then use SHIP_GATE.md to fix.

**Repo:** tool-compass
**Date:** 2026-05-14
**Version:** 2.2.2
**Type tags:** [pypi] [mcp] [cli]

<!-- SHIPCHECK-AUTO-START -->
## Current Assessment

The auto-generated block below is rewritten by
`bash scripts/regenerate-scorecard.sh` from `npx @mcptoolshop/shipcheck audit
--format markdown`. Per-category scores are **regenerated post-swarm** —
the placeholders here reflect the most recent merge of the wave-7 hardening
pass (CT-B-001..CT-B-020); a follow-up `make scorecard` will replace them
with shipcheck's numeric output once the markdown emitter stabilizes.

| Category | Score | Notes |
|----------|-------|-------|
| A. Security | TBD — regenerate post-swarm via `make scorecard` | SHA-pinned actions (CT-B-001/002); digest-pinned base image (CT-B-003); Dependabot pip+github-actions+docker w/ daily security overlay (CT-B-005/006); SLSA provenance + SBOM on PyPI + GHCR (CT-B-009); secrets scan via pre-commit gitleaks (CT-B-018). pip-audit warn-only pending CVE baseline. |
| B. Error Handling | TBD — regenerate post-swarm via `make scorecard` | Structured results, graceful degradation, exit codes; circuit breaker on Ollama; loud-fail on PyPI propagation timeout (CT-B-014). |
| C. Operator Docs | TBD — regenerate post-swarm via `make scorecard` | README, CHANGELOG (Keep a Changelog), LICENSE, SECURITY, CODE_OF_CONDUCT, CONTRIBUTING (with `pre-commit install` quick-start, CT-B-018), Makefile `verify`, `make verify-metrics`, `make scorecard`. |
| D. Shipping Hygiene | TBD — regenerate post-swarm via `make scorecard` | CI consolidated to 2 workflows; timeout-minutes on every job (CT-B-011); retention-days on every upload-artifact (CT-B-012); actions/configure-pages wired (CT-B-016); pytest config consolidated into pyproject.toml. |
| E. Identity (soft) | TBD — regenerate post-swarm via `make scorecard` | Logo, landing page, GitHub metadata, OpenContainers labels via docker/metadata-action (no hand-sync, CT-B-015), maintainers field in pyproject.toml (CT-B-019); translations re-run on TranslateGemma 12B before publish (CT-B-013). |
| **Overall** | TBD | Regenerate after swarm merges via `bash scripts/regenerate-scorecard.sh`. |

<!-- SHIPCHECK-AUTO-END -->

## Known Gaps (as of 2026-05-14)

1. **Translation freshness** — non-English READMEs (`README.{es,fr,hi,it,ja,pt-BR,zh}.md`) re-run on TranslateGemma 12B locally as the last release-prep step BEFORE `npm publish` and `gh release create` per the user's global CLAUDE.md ordering rule (CT-B-013). Tag is immutable so a follow-up translation commit ships permanently stale translations.
2. **pip-audit baseline** — pip-audit runs with `continue-on-error: true` until the CVE baseline is reviewed; a follow-up issue will flip it to blocking. Daily Dependabot security overlay (CT-B-006) provides the always-on advisory feed in the meantime.
3. **Ollama pin** — CI pins Ollama to a specific release; the upstream release does not ship a per-file `.sha256` sibling, so the verification step falls back to a SHA-less pin with a `::warning::`. Switch to attestation verification once Ollama publishes SLSA provenance.
4. **Saturation metrics** (CT-B-008 / BE-B-002) — `/metrics` currently covers latency + traffic + errors. Inflight gauges (`tool_compass_inflight_requests`, `tool_compass_inflight_backend_calls`) wire to the backend domain and are tracked under BE-B-002. `make verify-metrics` already includes warn-only checks for these so the smoke test will flip green once the surface lands.

## Remediation History

| Date | Wave | Highlights |
|------|------|------------|
| 2026-02-27 | Initial polish | SECURITY.md email fix, README data scope, Makefile `verify`, h1 cleanup |
| 2026-04-23 | Dogfood Stage A | CI workflow consolidation (2-file limit), flat-layout entry points, Dockerfile version sync, pinned Ollama install, pytest config consolidated, Makefile lint unmasked |
| 2026-05-14 | Dogfood Stage B+C (ci-tooling) | SHA-pinned remaining actions (github-script, setup-qemu); digest-pinned python:3.11-slim base in both Dockerfile stages; narrowed production COPY to builder /build only; Dependabot docker ecosystem added with all-docker group + daily security overlay for pip+github-actions+docker; SLSA provenance + SBOM emitted on PyPI publish + GHCR push; timeout-minutes on every job + retention-days on every upload-artifact; actions/configure-pages wired into pages-build; pre-commit-config.yaml with ruff + gitleaks; scripts/regenerate-scorecard.sh preserves hand-curated sections via SHIPCHECK markers; verify-metrics smoke test (Four Golden Signals); pyproject maintainers field; Python 3.13 classifier dropped pending hnswlib cp313 wheel; redundant pip install loop hardened to loud-fail; LABEL version hand-sync dropped (docker/metadata-action is now sole source); SECURITY.md preferred-path consolidation. |
