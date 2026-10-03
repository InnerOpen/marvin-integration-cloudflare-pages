# marvin-integration-cloudflare-pages

Cloudflare Pages integration for [Marvin](https://github.com/InnerOpen/marvin): see your site build.

When published content changes, Marvin queues one (coalesced) site rebuild and your deploy hook builds
the site. With this integration, Cloudflare reports back: **deploy started**, **site is live**, or
**deploy failed — with the reason from the build log** — as Marvin's own site deployment events. They
show as activity toasts under the bell (failures stay until dismissed), land in the event log, and can
trigger further workflows or notifications.

## Connection

| | |
|---|---|
| **API token** | An *account* API token: **Cloudflare Pages: Read** + **Notifications: Edit**. Add **Cloudflare Pages: Edit** only to use *Deploy*. Store it as a workspace secret and reference it as `{{SLUG}}`. |
| **Account ID** | The account that owns the Pages project (dashboard URL, or Workers & Pages → Account details). |
| **Pages project** | The project's name, e.g. `my-site` for `my-site.pages.dev`. |

## Actions

| Action | What it does |
|---|---|
| `list_deployments` | Latest deployments: environment, status, URL, branch and commit. |
| `build_log` | The end of a deployment's build log and the likely failure line, with a link. Never fails — without log access it returns the link. |
| `connect_notifications` | Creates (or updates) the Cloudflare side in one go: a webhook destination pointed at Marvin and a Pages *Project updates* alert for started / succeeded / failed. Args: `webhook_url` (this workspace's `cloudflare-pages` webhook URL) and `webhook_secret: {{CLOUDFLARE_NOTIFY_TOKEN}}`. |
| `deploy` | Starts a production deployment of the project's branch (needs Pages Edit). |

It also contributes the **`cloudflare`** webhook signature scheme: Cloudflare notifications don't sign,
they send the destination's shared secret in `cf-webhook-auth`, which Marvin compares in constant time.

## What a workspace gets — declared, applied from the integration's card

Nothing is created on install. **Apply** creates only what is missing; the webhook and workflows
arrive switched off.

| Kind | Slug | What it does |
|---|---|---|
| incoming webhook | `cloudflare-pages` | Where Cloudflare posts deploy notifications (scheme `cloudflare`, secret `CLOUDFLARE_NOTIFY_TOKEN`). |
| workflow | `cloudflare-pages-deploy-started` | `EVENT_DEPLOYMENT_STARTED` → `site_deployment_started`. |
| workflow | `cloudflare-pages-deploy-succeeded` | `EVENT_DEPLOYMENT_SUCCESS` → `site_deployment_completed` ("Site is live — <url>"). |
| workflow | `cloudflare-pages-deploy-failed` | `EVENT_DEPLOYMENT_FAILED` → `build_log` → `site_deployment_failed` with the reason. |

## Setting it up

1. Connect the integration (token, account ID, project) and **Apply** its content.
2. Open the `cloudflare-pages` incoming webhook: **Mint token**, then under **Signing** click **Generate key** (stored as `CLOUDFLARE_NOTIFY_TOKEN`). Copy the webhook URL.
3. Run **Connect notifications** on the card with `webhook_url` = that URL and `webhook_secret` = `{{CLOUDFLARE_NOTIFY_TOKEN}}`.
4. Switch the webhook and the three workflows on.

The next deploy shows up under the bell.

## Develop

```
uv run --extra dev pytest -q
uv run --extra dev ruff check .
```

Resolves the SDK from a sibling checkout (`../MarvinIntegrationSDK`).
