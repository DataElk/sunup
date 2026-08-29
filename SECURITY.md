# Security policy

## Reporting a vulnerability

Do not include API keys, worker records, or other sensitive data in a public issue.
Use the repository's private
[security advisory form](https://github.com/DataElk/sunup/security/advisories/new)
when it is available. If private reporting is unavailable, open a public issue with
only a minimal, redacted description and ask the maintainer for a private channel.

## Browser and gateway security model

Sunup stores roster data, weather history, and exception acknowledgements in the
browser's local storage. It does not store the shared weather credential in the
browser, public configuration, repository, or data export.

The public app calls a Cloudflare Worker that holds the credential as an encrypted
secret binding. The Worker is deliberately not a general proxy. It accepts only a
daily FortyGuard heatmap submission and activity status polling. Before forwarding a
submission it checks the requesting origin, JSON size and shape, filter type,
granularity, date, Arizona geometry, area, and request rate.

The browser limits script and network destinations with a Content Security Policy and
pins the dynamically loaded Leaflet files with Subresource Integrity. The gateway does
not make an unauthenticated public demo abuse-proof, so the upstream credential should
still be rotated if traffic or logs indicate misuse.

Anyone who pasted a key into a public issue, commit, screenshot, or shared browser
profile should revoke or rotate it with FortyGuard.

## Supported version

The current `main` deployment is the only supported prototype version. This project is
not validated for operational safety decisions.
