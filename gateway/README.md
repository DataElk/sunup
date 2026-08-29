# Sunup weather gateway

This Cloudflare Worker keeps the shared FortyGuard credential out of the public
GitHub Pages bundle. It is not a general API proxy. It accepts only Sunup's daily
Arizona heatmap request and activity status polling.

The Worker validates the request origin, payload shape, date, granularity, Arizona
geometry, polygon size, and request rate before forwarding anything. The browser
never sends or receives the upstream key.

## Deploy

1. Authenticate Wrangler with `npx wrangler login`.
2. Store `FORTYGUARD_API_KEY` with `npx wrangler secret put FORTYGUARD_API_KEY --config gateway/wrangler.jsonc`.
3. Deploy with `npx wrangler deploy --config gateway/wrangler.jsonc`.
4. Put the returned Worker origin in `app/data/config.js` and allow that exact origin
   in the Content Security Policy in `app/index.html`.

The secret must never be added to `wrangler.jsonc`, source code, a commit, or a shell
history entry. Without a local or deployed gateway, the browser keeps using cached
demo weather.
