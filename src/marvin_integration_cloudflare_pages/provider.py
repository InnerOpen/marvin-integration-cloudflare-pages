"""Cloudflare Pages provider: a site's deployments, build logs and deploy notifications.

The provider is pure with respect to Marvin: it gets ``config`` (account and project), the resolved
``secret`` (an account API token), a ``logger`` and a safe ``http`` client via ``ctx``, and returns
dicts. Receiving Cloudflare's notifications (and verifying their token) is the core's job — this
provider contributes the `cloudflare` signature scheme and declares the webhook + workflows.

API token permissions: Cloudflare Pages Read (deployments, logs), Notifications Edit (Connect
notifications), Cloudflare Pages Edit only for the `deploy` action.
"""

from __future__ import annotations

import uuid
from typing import ClassVar
from urllib.parse import quote

from marvin_integration_sdk import (
    CATEGORY_DESTINATION,
    RESULT_FAILED,
    RESULT_IN_FLIGHT,
    RESULT_SUCCEEDED,
    CredentialField,
    HandsOff,
    IntegrationContext,
    IntegrationProvider,
    ProviderAction,
    Response,
    register_provider,
)

from .content import CONTENT

API = "https://api.cloudflare.com/client/v4"
DASH = "https://dash.cloudflare.com"
ENVIRONMENTS = {"production": "ENVIRONMENT_PRODUCTION", "preview": "ENVIRONMENT_PREVIEW"}
DEPLOY_EVENTS = ("EVENT_DEPLOYMENT_STARTED", "EVENT_DEPLOYMENT_SUCCESS", "EVENT_DEPLOYMENT_FAILED")
# How a build is going, in Cloudflare's words, to Marvin's (Settings > Automation > Results). The notification's own `event` words come
# first (what the three notification workflows report); then the stage statuses the Pages API gives a deployment (list_deployments'
# `status`): idle and active are waiting or building, success and failure are the end, canceled is a build that never finished. A stage
# `skipped` (a build Cloudflare chose not to run) is left out on purpose: it is neither, so it stays in flight with the word shown.
BUILD_STATUSES = {
    "EVENT_DEPLOYMENT_STARTED": RESULT_IN_FLIGHT,
    "EVENT_DEPLOYMENT_SUCCESS": RESULT_SUCCEEDED,
    "EVENT_DEPLOYMENT_FAILED": RESULT_FAILED,
    "idle": RESULT_IN_FLIGHT,
    "active": RESULT_IN_FLIGHT,
    "success": RESULT_SUCCEEDED,
    "failure": RESULT_FAILED,
    "canceled": RESULT_FAILED,
}
DEFAULT_LIMIT = 5
MAX_LIMIT = 25
DEFAULT_LOG_LINES = 30
MAX_LOG_LINES = 200
ERROR_TEXT_LIMIT = 300
REASON_LIMIT = 500
# Lines worth quoting as the reason a build failed; otherwise the last lines are the reason.
FAILURE_MARKERS = ("error", "failed", "cannot", "not found", "exited with", "exception", "✘")

_ID = {"type": "string"}


def _errors(resp: Response) -> str:
    try:
        errors = (resp.json() or {}).get("errors") or []
    except ValueError:
        errors = []
    text = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors if isinstance(e, dict))
    return text or resp.text[:ERROR_TEXT_LIMIT]


@register_provider
class CloudflarePagesProvider(IntegrationProvider):
    slug = "cloudflare_pages"
    name = "Cloudflare Pages"
    description = "See your Cloudflare Pages site build: deploy started / live / failed as Marvin events (with the build log's reason), deployments, and one-click notification setup."
    category = CATEGORY_DESTINATION
    icon = "☁️"
    logo = "logo.svg"  # the Cloudflare Pages mark, shown instead of the emoji

    content = CONTENT

    # Cloudflare notifications don't sign: they send the destination's shared secret in cf-webhook-auth.
    signature_schemes: ClassVar[dict[str, dict]] = {
        "cloudflare": {"mode": "token", "header": "cf-webhook-auth", "notes": "Cloudflare notifications: the shared secret in cf-webhook-auth"},
    }

    credentials = (
        CredentialField(
            key="api_token",
            label="API token",
            help="An account API token: Cloudflare Pages Read + Notifications Edit (add Cloudflare Pages Edit to use Deploy).",
        ),
    )
    config_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "account_id": {"type": "string", "title": "Account ID", "description": "The Cloudflare account that owns the Pages project."},
            "project_name": {
                "type": "string",
                "title": "Pages project",
                "description": "The project's name, e.g. my-site (as in my-site.pages.dev).",
            },
        },
        "required": ["account_id", "project_name"],
        "additionalProperties": False,
    }

    actions = (
        ProviderAction(
            key="list_deployments",
            label="List deployments",
            description="The project's latest deployments: when, which environment, status, URL and commit.",
            input_schema={
                "type": "object",
                "properties": {
                    "environment": {"type": "string", "enum": list(ENVIRONMENTS), "description": "Blank = both."},
                    "limit": {"type": "integer", "description": f"Default {DEFAULT_LIMIT}, max {MAX_LIMIT}."},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {"deployments": {"type": "array"}}},
            cost_hint="free",
        ),
        ProviderAction(
            key="build_log",
            label="Build log",
            description="The end of a deployment's build log and the likely failure reason. Never fails: without log access it returns a link instead.",
            input_schema={
                "type": "object",
                "properties": {
                    "deployment_id": _ID,
                    "lines": {"type": "integer", "description": f"Default {DEFAULT_LOG_LINES}, max {MAX_LOG_LINES}."},
                },
                "required": ["deployment_id"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {"reason": _ID, "lines": {"type": "array"}, "link": _ID}},
            cost_hint="free",
        ),
        ProviderAction(
            key="connect_notifications",
            label="Connect notifications",
            description=(
                "Create (or update) the Cloudflare notification that posts this project's deploys to Marvin: a webhook destination "
                "with the given URL and secret, and a Pages 'Project updates' alert for started / succeeded / failed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "webhook_url": {"type": "string", "description": "The cloudflare-pages incoming webhook's URL in this workspace."},
                    "webhook_secret": {"type": "string", "description": "The webhook's signing secret — pass {{CLOUDFLARE_NOTIFY_TOKEN}}."},
                    "environments": {"type": "array", "items": {"type": "string", "enum": list(ENVIRONMENTS)}, "description": "Default production. Add preview when Marvin's rebuild deploys a non-production branch (e.g. develop): Cloudflare counts that as a preview deployment."},
                },
                "required": ["webhook_url", "webhook_secret"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {"destination_id": _ID, "policy_id": _ID, "created": {"type": "boolean"}}},
        ),
        ProviderAction(
            key="deploy",
            label="Deploy",
            description=(
                "Start a new production deployment of the project's branch (needs Cloudflare Pages Edit). It only starts the build: "
                "Marvin keeps it under Results as in flight until Cloudflare's notification says how it ended."
            ),
            input_schema={
                "type": "object",
                "properties": {"branch": {"type": "string", "description": "Default: the project's production branch."}},
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "deployment_id": _ID,
                    "url": _ID,
                    "link": {"type": "string", "description": "The deployment's page in the Cloudflare dashboard (its build log)."},
                },
            },
            # The build runs on Cloudflare's side; its started / success / failed notifications settle the result by the deployment id.
            hands_off=HandsOff(remote_id="deployment_id", remote_url="link", statuses=BUILD_STATUSES),
        ),
    )

    # ---- plumbing ---------------------------------------------------------------------------

    @staticmethod
    def _cfg(ctx: IntegrationContext) -> tuple[str, str]:
        cfg = ctx.config or {}
        account, project = str(cfg.get("account_id") or "").strip(), str(cfg.get("project_name") or "").strip()
        if not account or not project:
            raise ValueError("Set the Cloudflare account ID and Pages project name in the connection's config.")
        return account, project

    @staticmethod
    def _headers(ctx: IntegrationContext, content_type: str = "application/json") -> dict[str, str]:
        return {"Authorization": f"Bearer {ctx.secret}", "Content-Type": content_type}

    def _get(self, ctx: IntegrationContext, path: str) -> Response:
        return ctx.http.get(f"{API}{path}", headers=self._headers(ctx))

    @staticmethod
    def _ok(resp: Response, what: str):
        if not resp.ok:
            raise ValueError(f"Cloudflare {what} failed: HTTP {resp.status_code}: {_errors(resp)}")
        return (resp.json() or {}).get("result")

    def _project_path(self, ctx: IntegrationContext) -> tuple[str, str]:
        account, project = self._cfg(ctx)
        return account, f"/accounts/{quote(account, safe='')}/pages/projects/{quote(project, safe='')}"

    @staticmethod
    def _deployment(d: dict) -> dict:
        stage = d.get("latest_stage") or {}
        meta = (d.get("deployment_trigger") or {}).get("metadata") or {}
        return {
            "id": d.get("id"),
            "environment": d.get("environment"),
            "status": stage.get("status"),
            "stage": stage.get("name"),
            "created_on": d.get("created_on"),
            "url": d.get("url"),
            "branch": meta.get("branch"),
            "commit_hash": meta.get("commit_hash"),
            "commit_message": (meta.get("commit_message") or "")[:200] or None,
        }

    # ---- lifecycle --------------------------------------------------------------------------

    def check(self, ctx: IntegrationContext) -> tuple[str, str | None]:
        if not ctx.secret:
            return ("unconfigured", "Missing API token.")
        try:
            _, path = self._project_path(ctx)
            self._ok(self._get(ctx, path), "project lookup")
        except Exception as e:  # noqa: BLE001 — reported on the card, never raised
            return ("error", str(e))
        return ("ok", None)

    def run_action(self, key: str, args: dict, ctx: IntegrationContext) -> dict:
        handler = {
            "list_deployments": self._list_deployments,
            "build_log": self._build_log,
            "connect_notifications": self._connect_notifications,
            "deploy": self._deploy,
        }.get(key)
        if handler is None:
            raise NotImplementedError(f"cloudflare_pages has no action '{key}'")
        if not ctx.secret:
            raise ValueError("No Cloudflare API token configured.")
        return handler(args or {}, ctx)

    # ---- actions ----------------------------------------------------------------------------

    def _list_deployments(self, args: dict, ctx: IntegrationContext) -> dict:
        _, path = self._project_path(ctx)
        limit = max(1, min(int(args.get("limit") or DEFAULT_LIMIT), MAX_LIMIT))
        env = str(args.get("environment") or "").strip()
        query = f"?per_page={limit}" + (f"&env={quote(env)}" if env in ENVIRONMENTS else "")
        rows = self._ok(self._get(ctx, f"{path}/deployments{query}"), "list deployments") or []
        return {"deployments": [self._deployment(d) for d in rows[:limit]]}

    def _build_log(self, args: dict, ctx: IntegrationContext) -> dict:
        account, path = self._project_path(ctx)
        deployment_id = str(args.get("deployment_id") or "").strip()
        _, project = self._cfg(ctx)
        link = f"{DASH}/{account}/pages/view/{project}/{deployment_id}"
        if not deployment_id:
            return {"reason": "No deployment id in the notification.", "lines": [], "link": link}
        count = max(1, min(int(args.get("lines") or DEFAULT_LOG_LINES), MAX_LOG_LINES))
        try:
            data = self._ok(self._get(ctx, f"{path}/deployments/{quote(deployment_id, safe='')}/history/logs"), "build log") or {}
        except Exception as e:  # noqa: BLE001 — a failure toast with a link beats a failed workflow
            ctx.logger.warning("cloudflare_pages: build log unavailable for %s: %s", deployment_id, e)
            return {"reason": f"See the build log: {link}", "lines": [], "link": link}
        lines = [str(entry.get("line", "")).rstrip() for entry in (data.get("data") or []) if entry.get("line")]
        tail = lines[-count:]
        flagged = [line for line in tail if any(marker in line.lower() for marker in FAILURE_MARKERS)]
        reason = (flagged[-1] if flagged else (tail[-1] if tail else "The build log is empty."))[:REASON_LIMIT]
        return {"reason": f"{reason} — {link}", "lines": tail, "link": link}

    def _connect_notifications(self, args: dict, ctx: IntegrationContext) -> dict:
        account, project = self._cfg(ctx)
        url, secret = str(args.get("webhook_url") or "").strip(), str(args.get("webhook_secret") or "").strip()
        if not url.startswith("https://"):
            raise ValueError("webhook_url must be the https URL of this workspace's cloudflare-pages webhook.")
        if not secret or secret.startswith("{{"):
            raise ValueError("webhook_secret is required — pass {{CLOUDFLARE_NOTIFY_TOKEN}} (the webhook's signing secret).")
        envs = [ENVIRONMENTS[e] for e in (args.get("environments") or ["production"]) if e in ENVIRONMENTS] or [ENVIRONMENTS["production"]]
        base = f"{API}/accounts/{quote(account, safe='')}/alerting/v3"
        name = f"Marvin ({project})"

        destinations = self._ok(ctx.http.get(f"{base}/destinations/webhooks", headers=self._headers(ctx)), "list webhook destinations") or []
        destination = next((d for d in destinations if d.get("name") == name), None)
        body = {"name": name, "url": url, "secret": secret}
        if destination:
            self._ok(
                ctx.http.put(f"{base}/destinations/webhooks/{destination['id']}", json=body, headers=self._headers(ctx)), "update webhook destination"
            )
            destination_id = destination["id"]
        else:
            created = self._ok(ctx.http.post(f"{base}/destinations/webhooks", json=body, headers=self._headers(ctx)), "create webhook destination")
            destination_id = (created or {}).get("id")
        if not destination_id:
            raise ValueError("Cloudflare returned no webhook destination id.")

        project_info = (
            self._ok(self._get(ctx, f"/accounts/{quote(account, safe='')}/pages/projects/{quote(project, safe='')}"), "project lookup") or {}
        )
        policy_name = f"Site builds → Marvin ({project})"
        policy = {
            "name": policy_name,
            "description": f"Pages deployments of {project}, reported to Marvin.",
            "alert_type": "pages_event_alert",
            "enabled": True,
            "mechanisms": {"webhooks": [{"id": destination_id}]},
            "filters": {"project_id": [project_info.get("id") or project], "environment": envs, "event": list(DEPLOY_EVENTS)},
        }
        policies = self._ok(ctx.http.get(f"{base}/policies", headers=self._headers(ctx)), "list notification policies") or []
        existing = next((p for p in policies if p.get("name") == policy_name), None)
        if existing:
            self._ok(ctx.http.put(f"{base}/policies/{existing['id']}", json=policy, headers=self._headers(ctx)), "update notification policy")
            return {"destination_id": destination_id, "policy_id": existing["id"], "created": False}
        created = self._ok(ctx.http.post(f"{base}/policies", json=policy, headers=self._headers(ctx)), "create notification policy") or {}
        return {"destination_id": destination_id, "policy_id": created.get("id"), "created": True}

    def _deploy(self, args: dict, ctx: IntegrationContext) -> dict:
        account, path = self._project_path(ctx)
        branch = str(args.get("branch") or "").strip()
        if not branch:
            branch = (self._ok(self._get(ctx, path), "project lookup") or {}).get("production_branch") or "main"
        # Create deployment takes multipart form data; for a Git-connected project a branch is enough.
        boundary = uuid.uuid4().hex
        form = f'--{boundary}\r\nContent-Disposition: form-data; name="branch"\r\n\r\n{branch}\r\n--{boundary}--\r\n'.encode()
        resp = ctx.http.post(f"{API}{path}/deployments", data=form, headers=self._headers(ctx, f"multipart/form-data; boundary={boundary}"))
        d = self._ok(resp, "create deployment") or {}
        deployment_id = d.get("id")
        _, project = self._cfg(ctx)
        link = f"{DASH}/{account}/pages/view/{project}/{deployment_id}" if deployment_id else None
        return {"deployment_id": deployment_id, "url": d.get("url"), "link": link}
