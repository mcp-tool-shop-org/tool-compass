# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.x     | :white_check_mark: |
| 1.x     | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in Tool Compass, please report it responsibly.

### How to Report

1. **Do NOT open a public GitHub issue** for security vulnerabilities
2. Use [GitHub Security Advisories](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) to report privately
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Any suggested fixes (optional)

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 5 business days
- **Resolution Timeline**: Depends on severity
  - Critical: 24-48 hours
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
| Gradio UI | No authentication by default |
| MCP Gateway | Trusts backend servers |
| Analytics DB | Local SQLite, no encryption |
| Embeddings | Sent to local Ollama |

### Production Deployment

If deploying Tool Compass in a shared environment:

1. **Enable Gradio authentication**:
   ```python
   demo.launch(auth=("user", "password"))
   ```

2. **Use environment variables** for sensitive config (not `compass_config.json`)

3. **Network isolation**: Run behind a reverse proxy with auth

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

For security concerns: Use [GitHub Security Advisories](https://github.com/mcp-tool-shop-org/tool-compass/security/advisories/new) (private)

For general questions: Open a [GitHub Discussion](https://github.com/mcp-tool-shop-org/tool-compass/discussions)
