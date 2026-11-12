# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.x     | :white_check_mark: |
| 1.x     | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in Tool Compass, please report it responsibly.

### Preferred channel — GitHub Security Advisories

Open a private advisory through GitHub's confidential channel:
[github.com/mcp-tool-shop-org/tool-compass/security/advisories/new](https://github.com/mcp-tool-shop-org/tool-compass/security/advisories/new).
Reports through this path are end-to-end encrypted via GitHub and are
automatically routed to the maintainers — no PGP key handoff is required.

### Fallback — email

If GitHub Security Advisories are unavailable for any reason, email
**64996768+mcp-tool-shop@users.noreply.github.com**. PGP / sigstore keys
are not currently published; use the GitHub Advisories path above
whenever possible.

### How to Report

1. **Do NOT open a public GitHub issue** for security vulnerabilities.
2. Use the preferred channel above; fall back to email only if needed.
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Any suggested fixes (optional)

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 5 business days
- **Resolution Timeline** (tightened on the Critical lane per industry
  practice — see RFC 9116 + FIRST.org Vulnerability Coordination Maturity
  Model):
  - Critical: 72 hours to acknowledged remediation plan; 7 days to patch
  - High: 7 days
  - Medium: 30 days
  - Low: 90 days

### Disclosure Policy

- We follow [Coordinated Vulnerability Disclosure](https://vuls.cert.org/confluence/display/CVD)
- We will credit reporters in release notes (unless anonymity requested)
- Please allow us reasonable time to fix before public disclosure

## Security Considerations

### Known Security Boundaries

Tool Compass is designed as a **local development tool**. It has these security characteristics:

| Component | Security Model |
|-----------|----------------|
| Gradio UI | Loopback (`127.0.0.1` / `localhost` / `::1`) has no login by default unless `GRADIO_AUTH` / `--auth` is set; non-loopback binds (including Docker) and `--share` require `GRADIO_AUTH=user:pass` (or `TOOL_COMPASS_UI_ALLOW_NO_LOGIN=1` behind an authenticating proxy, which warns and hides execute controls) |
| MCP Gateway (stdio) | Local subprocess transport; trusts configured backend servers |
| MCP Gateway (HTTP) | Binds `127.0.0.1` by default; off loopback refuses to start without `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` (`gateway_auth_token`) or `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1` behind an authenticating proxy (`/health` and `/ready` remain unauthenticated for probes); trusts configured backend servers |
| Analytics DB | Local SQLite, no encryption |
| Embeddings | Sent to local Ollama |

### Production Deployment

If deploying Tool Compass in a shared environment:

1. **Configure UI login**:
   Set `GRADIO_AUTH=user:pass` (or pass `tool-compass ui --auth user:pass`). Non-loopback binds and the Docker UI image refuse to start without `GRADIO_AUTH` unless `TOOL_COMPASS_UI_ALLOW_NO_LOGIN=1` is explicitly set behind a reverse proxy that enforces its own login (which prints a startup warning and hides the UI execute controls).

2. **Use environment variables** for sensitive config (not `compass_config.json`)

3. **Network isolation and HTTP gateway auth**: Run behind an authenticating reverse proxy (`TOOL_COMPASS_UI_ALLOW_NO_LOGIN=1` if delegating UI login to the proxy). When the HTTP gateway binds off loopback (`HOST` not `127.0.0.1`, `localhost`, or `::1`), set `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` (or `gateway_auth_token` in config, or `fly secrets set TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<token>` on Fly.io); only set `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1` when a proxy in front enforces authentication and blocks direct access to the gateway port

4. **Rate limiting**: Add nginx/Cloudflare rate limiting for the UI

### Data Privacy

- **Search queries** are logged to `compass_analytics.db`
- **Tool call arguments** are hashed (not stored in plain text)
- **Embeddings** are generated locally via Ollama
- **No telemetry** is sent to external services

### Dependencies

We monitor dependencies for vulnerabilities using:
- GitHub Dependabot
- `pip-audit` in CI

To check locally:
```bash
pip install pip-audit
pip-audit
```

## Security Checklist for Contributors

- [ ] No hardcoded secrets or credentials
- [ ] Input validation on user-provided data
- [ ] SQL queries use parameterized statements
- [ ] File paths are validated before access
- [ ] Error messages don't leak sensitive info
- [ ] Dependencies are pinned to specific versions

## Contact

For security concerns: use the preferred channel described above
([GitHub Security Advisories](https://github.com/mcp-tool-shop-org/tool-compass/security/advisories/new)).

For general questions: Open a [GitHub Discussion](https://github.com/mcp-tool-shop-org/tool-compass/discussions).
