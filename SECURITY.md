# Security Policy

This repository is public and must never contain personal data. The
complainant identity, the PDF password, the recipient email and the SMTP
credentials live only in GitHub Secrets.

## Reporting a Vulnerability

Please report vulnerabilities through **GitHub private vulnerability
reporting** (the repository's Security tab -> "Report a vulnerability").
Do not open a public issue for a security problem.

## Hardening in place

- Secret scanning and push protection are enabled.
- Dependabot alerts and security updates are enabled.
- CodeQL runs on every push/PR and weekly.
- All GitHub Actions are pinned to full commit SHAs.
- The workflow never prints secret values; missing configuration is
  reported by variable name only.
