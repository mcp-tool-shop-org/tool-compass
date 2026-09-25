# tool-compass: how it works

Mapped at 2026-09-25 from commit 6f5a233.

## What this is

8 parts, mostly Python (46 files), JavaScript (4) and TypeScript (2). Work enters through 6 doors; the busiest is CI, which reaches 5 parts. It publishes to PyPI, @mcptoolshop/tool-compass (npm) to npm, and a container image. People run tool-compass and tool-compass-ui.

## What changed since the last map

This is the first map.

## What comes in

1. **CI.** On a pull request touching 15 paths; on a push to main touching 15 paths; on a schedule (`0 9 * * 1,3,5`); or by hand. Runs docker-entrypoint.sh, gateway.py, scripts/check-org-urls.sh and 35 more; checks LICENSE, README.md, _version.py and 16 more. On a push to main, it also runs site/astro.config.mjs and site/src/.
2. **Publish.** When a release is published; when the workflow Release completes; or by hand. Runs cli.py, docker-entrypoint.sh and gateway.py; checks LICENSE, README.md, _version.py and 15 more.
3. **Release Binaries.** When a release is published; on a `workflow_call` event; or by hand. Builds cli.py.
4. **Release.** When a tag matching `v*` is pushed; or by hand. Runs no file this map can see.
5. **tool-compass** (a command people run). Runs cli.py.
6. **tool-compass-ui** (a command people run). Runs ui.py.

## What happens through CI

1. The workflow runs npm/test/ in npm, docker-entrypoint.sh and gateway.py in the repository root, scripts/check-org-urls.sh, scripts/regenerate-scorecard.sh and scripts/verify-metrics.sh in scripts, and tests/ in tests; it checks 19 files in the repository root.
   1. Inside gateway.py, main does, in order:
      1. config (6 steps)
      2. backend client simple (3 steps)
      3. tool definition
      4. resolved embedding base url
      5. embedder
      6. indexer (3 steps)
      7. disconnect all (SimpleBackendManager)
      8. indexer (3 steps)
   2. Or, when `isinstance(explicit, str) and explicit.strip()`, main does redact url credentials instead.
   3. Or, when `_is_ollama_embedding_provider(cfg)`, main does redact url credentials instead.
   4. Or, when `not tools`, main does disconnect all (SimpleBackendManager) instead.
   5. Main returns early 1 more way.
2. On a push to main, it also runs site/astro.config.mjs and site/src/.
3. It deploys the site on a push to main.

## Who reads the results

CI writes nothing this map can see.

## The other doors

**Publish** runs cli.py, docker-entrypoint.sh and gateway.py, checks LICENSE, README.md, _version.py and 15 more, and publishes to PyPI and a container image.

**Release Binaries** creates a GitHub release and builds cli.py into binaries for darwin-arm64, linux-x64 and win-x64 and uploads them to the release.

**Release** runs no file this map can see, publishes @mcptoolshop/tool-compass (npm) to npm, and creates a GitHub release.

**tool-compass** (a command people run) runs cli.py.

**tool-compass-ui** (a command people run) runs ui.py.

## What breaks what

- **the repository root** is imported only from tests, by 1 part (tests), and sits on the path of 5 doors.

## What tends to change together

No two source files changed together often enough to name.

Window: 180 days; a pair counts from 3 shared commits, since 0 source files reach 10 revisions; the floor rises to 10 when 25 do.

## What no test touches

- **scripts** is imported by no test.

npm is touched by tests only through a spawn: a test runs its files as a child process.

## Written but never read

Every written place has a reader.

## Helpers that look duplicated

No two parts export a helper that looks alike.

## Generated, never hand-edited

- **npm/bin/tool-compass.js** has a block written by scripts/sync-version.mjs.
- **npm/package.json** has a block written by scripts/sync-version.mjs.

## Hand-authored

People write .github/, assets/, docs/ and site/; 11 writes with paths built at run time may land here.

## Where to start

.github/workflows/ci.yml → gateway.py

Read those in order to follow one pull request end to end.

## What this map cannot see

- 3 import sites could not be resolved.
- 11 writes and 6 reads use paths built at run time and are not named here.
- 1 read goes to a path its caller passes, not to this repository.
- There is a docker-compose.yml and a fly.toml that no workflow runs; what deploys from them does so from outside this repository, and is not on this page.
- Statistics confidence is low: fewer than 20 source files reach 10 revisions in the window.

Regenerate with `npx --yes @dogfood-lab/atlas map`.
