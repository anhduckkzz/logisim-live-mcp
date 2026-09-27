# Security

## Model

- The server only reads and writes `.circ` projects and test-vector files beneath the
  `--root` folder; paths are resolved and checked against it (no `..`, symlink or junction
  escapes). There is no arbitrary file or raw XML write tool.
- Every save is validated, backed up and written atomically.
- The live plugin listens on `127.0.0.1` only. Each request must carry a random token that
  the bridge stores in `~/.logisim-mcp/live.json` and passes to Logisim through an
  environment variable (never on the command line).
- The plugin runs no AI model and contacts no online service.
- The optional HTTP transport has no authentication: keep it on loopback or behind an
  authenticated tunnel/gateway.

## Reporting a vulnerability

Please report security issues privately through GitHub's "Report a vulnerability"
(Security Advisories) on this repository rather than in a public issue.
