#!/usr/bin/env node
"use strict";

// version/tag refer to the source repo binary release, not the npm wrapper version.
// Both lines are kept in sync at release time by scripts/sync-version.mjs.
process.env.MCPTOOLSHOP_LAUNCH_CONFIG = JSON.stringify({
  toolName: "tool-compass",
  owner: "mcp-tool-shop-org",
  repo: "tool-compass",
  version: "2.5.0",
  tag: "v2.5.0",
});

// Bare identity flags (no subcommand) must print locally. Requiring
// npm-launcher here would download a GitHub Release binary before argparse
// can speak, which is what `npx @mcptoolshop/tool-compass --help` / `--version`
// advertise.
const args = process.argv.slice(2);
const HELP_TOKENS = new Set(["-h", "--help", "help", "--version", "-V"]);
const VERSION_TOKENS = new Set(["--version", "-V"]);
const hasHelp = args.some((a) => a === "-h" || a === "--help" || a === "help");
const hasVersion = args.some((a) => VERSION_TOKENS.has(a));
const hasSubcommand = args.some(
  (a) => a !== "" && !a.startsWith("-") && !HELP_TOKENS.has(a)
);

function embeddedVersion() {
  try {
    return JSON.parse(process.env.MCPTOOLSHOP_LAUNCH_CONFIG).version;
  } catch {
    return "0.0.0";
  }
}

if (hasVersion && !hasSubcommand) {
  process.stdout.write(`${embeddedVersion()}\n`);
  process.exit(0);
}

if (hasHelp && !hasSubcommand) {
  const version = embeddedVersion();
  process.stdout.write(`tool-compass ${version}
Usage: npx @mcptoolshop/tool-compass <command> [options]

Commands:
  doctor      Diagnose config, backends, and the embedding provider
  search      One-shot semantic search by intent
  sync        Rebuild the index from backends
  ui          Launch the Gradio web UI
  serve       Run the MCP gateway (default with no command)
  describe    Print a tool's schema and metadata
  execute     Run a named tool on its backend
  init        Scaffold compass_config.json and MCP client setup
  status      Show backend, index, and sync health
  categories  List available tool categories with counts
  audit       Audit the index, backends, chains, and analytics
  analytics   Show usage statistics, hot tools, and top chains
  chains      List or detect tool-chain workflow patterns

This npx wrapper fetches a SHA256-verified GitHub Release binary on the
first real command. Bare --help / -h / help / --version / -V print locally
and do not download anything.

Python fallback:  pip install tool-compass
Docker fallback:
  Gateway:  docker run --rm -p 8080:8080 ghcr.io/mcp-tool-shop-org/tool-compass:latest
  UI:       docker run --rm -p 7860:7860 ghcr.io/mcp-tool-shop-org/tool-compass:ui
  Compose:  docker compose up
            docker compose --profile gateway up
            docker build --target production -t tool-compass:ui .
`);
  process.exit(0);
}

try {
  require("@mcptoolshop/npm-launcher/bin/mcptoolshop-launch.js");
} catch (err) {
  const msg = err && err.message ? String(err.message) : String(err);
  const missingLauncher =
    err &&
    (err.code === "MODULE_NOT_FOUND" || err.code === "ERR_MODULE_NOT_FOUND") &&
    /@mcptoolshop\/npm-launcher/.test(msg);
  if (missingLauncher) {
    process.stderr.write(
      "tool-compass: this wrapper fetches GitHub Release binaries; " +
        "@mcptoolshop/npm-launcher is missing (MODULE_NOT_FOUND).\n" +
        "  npm install @mcptoolshop/tool-compass\n" +
        "  pip install tool-compass\n" +
        "  docker run --rm -p 8080:8080 ghcr.io/mcp-tool-shop-org/tool-compass:latest\n" +
        "  docker run --rm -p 7860:7860 ghcr.io/mcp-tool-shop-org/tool-compass:ui\n"
    );
    process.exit(1);
  }
  throw err;
}
