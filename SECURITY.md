# Security policy

## Reporting a vulnerability

Do not include API keys, worker records, or other sensitive data in a public issue.
Use the repository's private
[security advisory form](https://github.com/DataElk/sunup/security/advisories/new)
when it is available. If private reporting is unavailable, open a public issue with
only a minimal, redacted description and ask the maintainer for a private channel.

## Browser security model

Sunup is a static browser application with no application backend or account system.
Roster data, weather history, exception acknowledgements, and the optional FortyGuard
API key are stored in that browser's local storage.

The API key:

- is never part of the repository or deployed assets;
- is not included in the JSON store export;
- is not changed by resetting demo data;
- is sent only to `https://api.fortyguard.com` in the `api-key` request header;
- can be removed from Settings at any time.

A browser application cannot make a client-side API key cryptographically secret from
code executing on the same origin. Sunup therefore limits script sources with a Content
Security Policy and pins the dynamically loaded Leaflet files with Subresource
Integrity. These controls reduce supply-chain risk but do not replace a backend secret
store. A production deployment should keep the FortyGuard key on a server and issue
short-lived, scoped requests to authenticated clients.

Anyone who pasted a key into a public issue, commit, screenshot, or shared browser
profile should revoke or rotate it with FortyGuard.

## Supported version

The current `main` deployment is the only supported prototype version. This project is
not validated for operational safety decisions.
