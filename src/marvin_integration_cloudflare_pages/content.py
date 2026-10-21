"""What a workspace needs to see its Cloudflare Pages site build — declared for the core to offer.

Applying (from the integration's card) creates only what is missing: the incoming webhook Cloudflare
posts deploy notifications to, and three workflows that turn those notifications into Marvin's own
site deployment events — which show as activity toasts (failures stay until dismissed), land in the
event log, and can trigger further workflows or notifications. Webhooks and workflows arrive switched
off; turning them on after a review is the deliberate last step.

The loop: published content changes → Marvin queues one (coalesced) site rebuild → the deploy hook
builds the site → Cloudflare posts "started" / "succeeded" / "failed" here → the toast. A failure
carries the end of the build log (the `build_log` action), not just a link.

Each of the three also settles the build under Settings > Automation > Results (0.3.0): the Deploy action (a site rebuild runs it)
records the build as in flight with its deployment id, and the notification's `automation_result` step finishes it by that id, in
Cloudflare's own words (`EVENT_DEPLOYMENT_SUCCESS` ...; the provider maps them). The step names no connection: Marvin reads the words
through the connection that installed this webhook. A build Marvin did not start (a git push) is listed too, from its first notification.
A failed build's result carries the same build log tail as the toast; a build that went live carries a summary of it (environment, branch and the
commit message's first line), and the deployment's `pages_dev_url` as the link to it when the result has none.

One parameter: `integration` (this integration's slug in the workspace, default `cloudflare_pages`).
"""

from marvin_integration_sdk import ContentBlueprint

CATEGORY = "Cloudflare Pages"
WEBHOOK_SLUG = "cloudflare-pages"
SECRET_REF = "CLOUDFLARE_NOTIFY_TOKEN"

INTEGRATION_PARAM = {
    "key": "integration",
    "label": "Which Cloudflare Pages connection",
    "kind": "integration",
    "default": "cloudflare_pages",
    "help": "The success and failure workflows read that connection's deployment and build log.",
}

_DATA = "${event.payload.data."
_COMMON = {"site_url": f"{_DATA}pages_dev_url}}", "deployment_id": f"{_DATA}deployment_id}}"}

DEPLOY_WEBHOOK = ContentBlueprint(
    kind="incoming_webhook",
    slug=WEBHOOK_SLUG,
    name="Cloudflare Pages deploys",
    description=(
        "Where Cloudflare posts Pages deploy notifications. Mint its token, generate a key under Signing (stored as "
        f"{SECRET_REF}), then run the connection's Connect notifications action with this webhook's URL."
    ),
    required=True,
    category=CATEGORY,
    payload={
        "name": "Cloudflare Pages deploys",
        "description": "Cloudflare notification: Pages → Project updates (deployment started / success / failed).",
        "signature_scheme": "cloudflare",
        "signing_secret_ref": SECRET_REF,
    },
)


def _result(message: str | None = None) -> dict:
    """Report the notification to Results: the build's status in Cloudflare's words, found by its deployment id, with the build's summary
    and its page. No `integration`: Marvin reads the words through the connection that installed this webhook."""
    step = {
        "kind": "automation_result",
        "status": f"{_DATA}event}}",
        "remote_id": f"{_DATA}deployment_id}}",
        "target": f"{_DATA}project_name}}",
        "remote_url": f"{_DATA}pages_dev_url}}",
    }
    return {**step, "message": message} if message else step


def _on(event: str) -> dict:
    return {"type": "incoming_webhook", "webhook": WEBHOOK_SLUG}, [{"field": "event.payload.data.event", "op": "eq", "value": event}]


def _workflow(slug: str, name: str, description: str, cf_event: str, actions: list[dict], parameters: tuple = ()) -> ContentBlueprint:
    trigger, conditions = _on(cf_event)
    return ContentBlueprint(
        kind="workflow",
        slug=slug,
        name=name,
        description=description,
        required=True,
        category=CATEGORY,
        parameters=parameters,
        payload={"definition": {"trigger": trigger, "conditions": conditions, "actions": actions}},
    )


DEPLOY_STARTED = _workflow(
    "cloudflare-pages-deploy-started",
    "Cloudflare Pages: deploy started",
    "When Cloudflare starts building the site, emit Marvin's site deploy started event (an activity toast) and note the build under Results.",
    "EVENT_DEPLOYMENT_STARTED",
    [
        {"kind": "emit_event", "event": "site_deployment_started", "message": f"Building {_DATA}project_name}} on Cloudflare Pages", **_COMMON},
        _result(),
    ],
)

DEPLOY_SUCCEEDED = _workflow(
    "cloudflare-pages-deploy-succeeded",
    "Cloudflare Pages: deployed",
    "When the site is live, emit Marvin's site deployed event (an activity toast) and mark the build succeeded under Results.",
    "EVENT_DEPLOYMENT_SUCCESS",
    [
        # deployment_summary never fails the step: without access it says "Deployed".
        {
            "kind": "integration",
            "id": "deployment",
            "integration": "{{integration}}",
            "action": "deployment_summary",
            "args": {"deployment_id": f"{_DATA}deployment_id}}"},
        },
        {"kind": "emit_event", "event": "site_deployment_completed", "message": f"Site is live — {_DATA}pages_dev_url}}", **_COMMON},
        _result("${steps.deployment.output.summary}"),  # e.g. "Preview on develop: Fix the feed"
    ],
    parameters=(INTEGRATION_PARAM,),
)

DEPLOY_FAILED = _workflow(
    "cloudflare-pages-deploy-failed",
    "Cloudflare Pages: deploy failed",
    "When a deploy fails, read the end of its build log, emit Marvin's site deploy failed event with the reason and mark the build failed under Results.",
    "EVENT_DEPLOYMENT_FAILED",
    [
        # build_log never fails the step: without access to logs it returns a link instead of a reason.
        {
            "kind": "integration",
            "id": "log",
            "integration": "{{integration}}",
            "action": "build_log",
            "args": {"deployment_id": f"{_DATA}deployment_id}}"},
        },
        {
            "kind": "emit_event",
            "event": "site_deployment_failed",
            "message": f"{_DATA}project_name}} failed to build or deploy",
            "error": "${steps.log.output.reason}",
            **_COMMON,
        },
        _result("${steps.log.output.reason}"),  # the build log tail, as the toast shows it
    ],
    parameters=(INTEGRATION_PARAM,),
)

CONTENT = (DEPLOY_WEBHOOK, DEPLOY_STARTED, DEPLOY_SUCCEEDED, DEPLOY_FAILED)
