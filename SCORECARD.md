# Scorecard

> Score a repo before remediation. Fill this out first, then use SHIP_GATE.md to fix.

**Repo:** tool-compass
**Date:** 2026-02-27
**Type tags:** [pypi] [mcp] [cli]

## Pre-Remediation Assessment

| Category | Score | Notes |
|----------|-------|-------|
| A. Security | 9/10 | Extensive SECURITY.md but non-standard email, no inline data scope in README |
| B. Error Handling | 10/10 | Structured results, graceful degradation, exit codes, SQLite auto-recreate |
| C. Operator Docs | 9/10 | README, CHANGELOG, LICENSE, --help all present but no verify script |
| D. Shipping Hygiene | 8/10 | CI has coverage + pip-audit + Docker, but no Makefile verify target |
| E. Identity (soft) | 10/10 | Logo, translations, landing page, GitHub metadata |
| **Overall** | **46/50** | |

## Key Gaps

1. SECURITY.md uses non-standard email address
2. README missing inline Security & Data Scope section
3. No Makefile with verify target
4. Redundant h1 tag when logo already contains product name

## Remediation Priority

| Priority | Item | Estimated effort |
|----------|------|-----------------|
| 1 | Update SECURITY.md email + add data scope to README | 3 min |
| 2 | Add Makefile with verify target | 2 min |
| 3 | Remove redundant h1, add scorecard to README | 2 min |

## Post-Remediation

| Category | Before | After |
|----------|--------|-------|
| A. Security | 9/10 | 10/10 |
| B. Error Handling | 10/10 | 10/10 |
| C. Operator Docs | 9/10 | 10/10 |
| D. Shipping Hygiene | 8/10 | 10/10 |
| E. Identity (soft) | 10/10 | 10/10 |
| **Overall** | 46/50 | 50/50 |
