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

// Bare -h / --help / help (no subcommand) must print usage locally. Requiring
// npm-launcher here would download a GitHub Release binary before argparse
// can speak, which is what `npx @mcptoolshop/tool-compass --help` advertises.
const args = process.argv.slice(2);
const HELP_TOKENS = new Set(["-h", "--help", "help"]);
const hasHelp = args.some((a) => HELP_TOKENS.has(a));
const hasSubcommand = args.some(
  (a) => a !== "" && !a.startsWith("-") && !HELP_TOKENS.has(a)
);

if (hasHelp && !hasSubcommand) {
  process.stdout.write(`Usage: tool-compass <command> [options]

Commands:
  doctor      Diagnose config, backends, and Ollama
  search      One-shot semantic search by intent
  sync        Rebuild the index from backends
  ui          Launch the Gradio web UI
  serve       Run the MCP gateway (default with no command)
  describe, execute, init, status, categories, audit, analytics, chains

This npx wrapper fetches a SHA256-verified GitHub Release binary on the
first real command. Bare --help / -h / help print this usage locally and
do not download anything.

Python fallback:  pip install tool-compass
Docker fallback:  docker run ghcr.io/mcp-tool-shop-org/tool-compass:latest
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
        "  docker run ghcr.io/mcp-tool-shop-org/tool-compass:latest\n"
    );
    process.exit(1);
  }
  throw err;
}
