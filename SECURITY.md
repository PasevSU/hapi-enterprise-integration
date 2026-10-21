# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.50.x  | :white_check_mark: |
| < 0.50  | :x:                |

## Security Model

hAPI Enterprise runs one shared Node.js backend (`hapi_enterprise/server.js`) on the
edge between Home Assistant and Windows. Security is enforced by design:

- **Fail-open token bootstrap** — the add-on no longer hard-fails on a placeholder
  admin token. On first start it auto-generates a cryptographically random 256-bit
  token and persists it to `/data/admin-token` (mode `0600`) unless an initial `token` option (24+ characters) is provided. The Windows
  standalone runtime does the same in its local data directory.
- **Role-based access control** — three independent bearer tokens (`ADMIN_TOKEN`,
  `OPERATOR_TOKEN`, `VIEWER_TOKEN`) resolve admin/operator/viewer roles; every
  administrative route is tagged with a capability.
- **Ingress SSO (Home Assistant)** — identity comes from the ingress headers
  `X-Remote-User-Id`, `X-Remote-User-Name` and `X-Remote-User-Display-Name`
  (`X-Remote-User` / `X-Remote-Groups` are kept only as legacy fallbacks) and is
  trusted **only** on the ingress/admin listener, which accepts packets **only** from the
  Supervisor proxy (`172.30.32.2`) and loopback. The public listener never trusts SSO
  headers and never serves `/admin`.
- **Loopback isolation (Windows)** — the standalone runtime binds the admin listener
  to `127.0.0.1` only.
- **No secret leakage** — the diagnostics API requires administrative authentication
  and never returns secret keys or absolute storage paths.
- **Timing-safe token comparison** and per-peer authentication rate limiting on
  administrative routes (`AUTH_MAX_FAILURES` within a 60-second window).

## Reporting a Vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report privately to the maintainer identified in `repository.yaml`. Include:

1. Affected version(s).
2. A clear description of the issue and its impact.
3. Steps to reproduce, and any proof-of-concept you can share.

The maintainer will acknowledge receipt within 5 business days and work to validate,
fix, and coordinate disclosure. Please avoid public disclosure until a fix has been
released.

## Security Best Practices for Operators

- Treat the generated admin token as a secret. Rotate it by deleting the stored token
  file and restarting: `/data/.portal-admin-token` (add-on) or `admin-token` in the
  local data directory (Windows).
- Expose the add-on only through Home Assistant ingress, not directly to the internet.
- Keep Node.js 22.13+ and Home Assistant Supervisor up to date.
