"use strict";

// Smoke test: verify the launch config JSON is well-formed and includes the
// fields npm-launcher requires. Does NOT exercise the download path (that
// would hit GitHub Releases and is reserved for the release-time smoke).

const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

test("bin/tool-compass.js sets a valid MCPTOOLSHOP_LAUNCH_CONFIG", () => {
  const binPath = path.join(__dirname, "..", "bin", "tool-compass.js");
  const source = fs.readFileSync(binPath, "utf8");

  // Extract the JSON payload from the source.
  const match = source.match(/JSON\.stringify\((\{[\s\S]*?\})\)/);
  assert.ok(match, "bin/tool-compass.js must use JSON.stringify({...})");

  // eval is acceptable here: the source is repo-controlled, not user input.
  const config = eval(`(${match[1]})`);

  for (const key of ["toolName", "owner", "repo", "version", "tag"]) {
    assert.ok(config[key], `config.${key} must be set`);
  }

  assert.equal(config.toolName, "tool-compass");
  assert.equal(config.owner, "mcp-tool-shop-org");
  assert.equal(config.repo, "tool-compass");
  assert.match(config.version, /^\d+\.\d+\.\d+/, "version must be semver");
  assert.equal(config.tag, `v${config.version}`, "tag must be v<version>");
});

test("package.json bin points at bin/tool-compass.js", () => {
  const pkg = require(path.join(__dirname, "..", "package.json"));
  assert.equal(pkg.bin["tool-compass"], "bin/tool-compass.js");
  assert.ok(
    pkg.dependencies["@mcptoolshop/npm-launcher"],
    "must depend on @mcptoolshop/npm-launcher"
  );
});

test("package.json version matches bin shim version", () => {
  const pkg = require(path.join(__dirname, "..", "package.json"));
  const binPath = path.join(__dirname, "..", "bin", "tool-compass.js");
  const source = fs.readFileSync(binPath, "utf8");
  const match = source.match(/version:\s*"([^"]+)"/);
  assert.ok(match, "bin shim must declare a version");
  assert.equal(
    match[1],
    pkg.version,
    "bin shim version must equal package.json version"
  );
});

test("bin intercepts bare help before requiring npm-launcher", () => {
  const binPath = path.join(__dirname, "..", "bin", "tool-compass.js");
  const source = fs.readFileSync(binPath, "utf8");
  const requireIdx = source.indexOf(
    'require("@mcptoolshop/npm-launcher/bin/mcptoolshop-launch.js")'
  );
  const helpIdx = source.indexOf("HELP_TOKENS");
  assert.ok(requireIdx > 0, "bin must still require npm-launcher for real commands");
  assert.ok(helpIdx > 0, "bin must define HELP_TOKENS");
  assert.ok(helpIdx < requireIdx, "help intercept must run before require()");
  assert.match(source, /try\s*\{/);
  assert.match(source, /MODULE_NOT_FOUND/);
  assert.match(source, /pip install tool-compass/);
});

const { spawnSync } = require("node:child_process");

function runBin(...cliArgs) {
  const binPath = path.join(__dirname, "..", "bin", "tool-compass.js");
  return spawnSync(process.execPath, [binPath, ...cliArgs], {
    encoding: "utf8",
    timeout: 5000,
    windowsHide: true,
  });
}

for (const flag of ["--help", "-h", "help"]) {
  test(`bin ${flag} prints local usage and exits 0 without launching`, () => {
    const r = runBin(flag);
    assert.equal(r.status, 0, r.stderr || r.stdout);
    for (const cmd of ["doctor", "search", "sync", "ui", "serve"]) {
      assert.match(r.stdout, new RegExp(`\\b${cmd}\\b`));
    }
    assert.match(r.stdout, /GitHub Release/i);
    assert.doesNotMatch(r.stdout, /Downloading|checksum/i);
  });
}
