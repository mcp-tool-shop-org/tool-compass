# tool-compass: how it works

Mapped at 2026-11-12 from commit 03a2cf4 by Atlas 1.26.0.

## What this is

8 parts, mostly Python (46 files), JavaScript (4), shell (4), CSS (2), TypeScript (2) and Astro (1). Work enters through 7 doors; the busiest is CI, which reaches 5 parts. It publishes to PyPI, @mcptoolshop/tool-compass to npm, and a container image. It deploys a site to GitHub Pages. People run tool-compass and tool-compass-ui.

## What changed since 2026-11-11 (b8a7f76)

- Dockerfile is now also read by tests/test_gateway_handlers.py and tests/test_ui.py.
- docker-entrypoint.sh is now read by tests/test_gateway_handlers.py.
- gateway.py is now also read by tests/test_gateway_handlers.py.
- And 1 more new writer or reader of a place.
- 20 files changed content, across 5 parts.

## What comes in

1. **CI.** On a pull request to main; on a push to main touching 16 paths; on a schedule (`0 9 * * 1,3,5`); or by hand. Runs cli.py, docker-entrypoint.sh, gateway.py and 37 more; checks requirements.txt; packs LICENSE, README.md, _version.py and 13 more into an image. Except on a schedule or when run by hand, it also runs site/astro.config.mjs and site/src/.
2. **Publish.** When a release is published; when the workflow Release completes; or by hand. Runs cli.py, docker-entrypoint.sh, gateway.py and 1 more; packs LICENSE, README.md, _version.py and 14 more into an image.
3. **Release.** When a tag matching `v*` is pushed; or by hand. Runs ui.py.
4. **Release Binaries.** When a release is published; on a `workflow_call` event; or by hand. Runs ui.py; builds cli.py.
5. **tool-compass** (a command people run, from npm/package.json). Runs npm/bin/tool-compass.js.
6. **tool-compass** (a command people run, from pyproject.toml). Runs cli.py.
7. **tool-compass-ui** (a command people run). Runs ui.py.

## What happens through CI

1. The workflow runs npm/test/ in npm, 4 files in the repository root, scripts/check-org-urls.sh, scripts/regenerate-scorecard.sh and scripts/verify-metrics.sh in scripts, and tests/ in tests; it checks requirements.txt in the repository root; it packs 16 files in the repository root into an image.
   1. Inside gateway.py, `main` does, in order: `config.py` (6 steps), `backend_client_simple.py` (3 steps), `ToolDefinition`, `Embedder`, `indexer.py` (3 steps), `disconnect_all` (SimpleBackendManager) and `indexer.py` (3 steps).
   2. Or, when `isinstance(explicit, str) and explicit.strip()`, `main` does `redact_url_credentials` instead.
   3. Or, when `_is_ollama_embedding_provider(cfg)`, `main` does `redact_url_credentials` instead.
   4. Or, when `not tools`, `main` does `disconnect_all` (SimpleBackendManager) instead.
   5. `main` returns early 1 more way.
   6. Inside ui.py, `main` does, in order: `load_config`, `embedder.py` (3 steps), `load_config` and `embedder.py` (3 steps).
2. Except on a schedule or when run by hand, it also runs site/astro.config.mjs and site/src/.
3. It uploads coverage to Codecov.
4. It runs the pre-commit hooks.
5. It deploys the site on a push to main.

## Who reads the results

CI writes nothing this map can see.

## The other doors

**Publish** runs cli.py, docker-entrypoint.sh, gateway.py and 1 more, packs LICENSE, README.md, _version.py and 14 more into an image, and publishes to PyPI and a container image.

**Release** runs ui.py, publishes @mcptoolshop/tool-compass to npm, creates a GitHub release, and uploads artifacts/* to the release.

**Release Binaries** runs ui.py, creates a GitHub release, and builds cli.py into binaries for darwin-arm64, linux-x64 and win-x64 and uploads them to the release.

**tool-compass** (a command people run, from npm/package.json) runs npm/bin/tool-compass.js.

**tool-compass** (a command people run, from pyproject.toml) runs cli.py.

**tool-compass-ui** (a command people run) runs ui.py.

## What breaks what

- **the repository root** is imported only from tests, by 1 part (tests), and sits on the path of 6 doors.
- **npm** is imported by no other part and sits on the path of 2 doors.

## What tends to change together

No two source files changed together often enough to name.

Window: 180 days; a pair counts from 3 shared commits, since 0 source files reach 10 revisions; the floor rises to 10 when 25 do.

## What no test touches

- **scripts** is imported by no test.

npm is tested only by its package's own test script, which a workflow runs.

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

.github/workflows/ci.yml → cli.py → gateway.py → config.py → tool_manifest.py

Read those in order to follow one pull request end to end.

Beside the path, cli.py also calls indexer.py, backend_client_simple.py, sync_manager.py and ui.py. Beside the path, gateway.py also calls backend_client_simple.py, embedder.py and indexer.py.

## What this map cannot see

- 11 writes and 4 reads use paths built at run time and are not named here.
- 5 writes and 35 reads go to a path their caller passes, not to this repository.
- There are a docker-compose.yml and a fly.toml that no workflow runs; what deploys from them does so from outside this repository, and is not on this page.
- Statistics confidence is low: fewer than 25 source files reach 10 revisions in the window.

Regenerate with `npx --yes @dogfood-lab/atlas map`.
