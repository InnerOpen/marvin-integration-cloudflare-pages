"""Cloudflare Pages provider — API calls through a stub http helper, no network."""

import json
import logging

import pytest
from marvin_integration_sdk import IntegrationContext, Response

from marvin_integration_cloudflare_pages import CloudflarePagesProvider

API = "https://api.cloudflare.com/client/v4"
ACCOUNT = "acct1"
PROJECT = "my-site"
_LOG = logging.getLogger("test")

PROJECT_INFO = {"result": {"id": "proj-uuid", "name": PROJECT, "production_branch": "main"}, "success": True}
DEPLOYMENTS = {
    "result": [
        {
            "id": "dep2",
            "environment": "production",
            "url": "https://dep2.my-site.pages.dev",
            "created_on": "2026-10-03T16:48:22Z",
            "latest_stage": {"name": "deploy", "status": "success"},
            "deployment_trigger": {"metadata": {"branch": "main", "commit_hash": "abc", "commit_message": "Update"}},
        }
    ],
    "success": True,
}
LOGS = {
    "result": {
        "data": [
            {"line": "Installing dependencies"},
            {"line": "npm ERR! missing script: build"},
            {"line": "Failed: build command exited with code: 1"},
        ]
    },
    "success": True,
}


class _Http:
    def __init__(self, routes):
        self.routes = routes
        self.calls: list[dict] = []

    def _answer(self, method, url, body=None, data=None, headers=None):
        self.calls.append({"method": method, "url": url, "json": body, "data": data, "headers": headers})
        for route_method, needle, status, payload in self.routes:
            if route_method == method and needle in url:
                return Response(status_code=status, content=json.dumps(payload).encode())
        return Response(status_code=599, content=b'{"errors":[{"code":0,"message":"no stub route"}]}')

    def get(self, url, *, headers=None, timeout=15):
        return self._answer("GET", url, headers=headers)

    def post(self, url, *, json=None, data=None, headers=None, timeout=15):
        return self._answer("POST", url, json, data, headers)

    def put(self, url, *, json=None, data=None, headers=None, timeout=15):
        return self._answer("PUT", url, json, data, headers)

    def delete(self, url, *, headers=None, timeout=15):
        return self._answer("DELETE", url, headers=headers)


def _ctx(http, secret="tok", **config):
    cfg = {"account_id": ACCOUNT, "project_name": PROJECT, **config}
    return IntegrationContext(config=cfg, secret=secret, logger=_LOG, http=http)


def _run(http, key, **args):
    return CloudflarePagesProvider().run_action(key, args, _ctx(http))


def test_check_is_ok_when_the_project_is_readable():
    assert CloudflarePagesProvider().check(_ctx(_Http([("GET", f"/pages/projects/{PROJECT}", 200, PROJECT_INFO)]))) == ("ok", None)


def test_check_reports_a_rejected_token():
    http = _Http([("GET", "/pages/projects/", 403, {"errors": [{"code": 10000, "message": "Authentication error"}]})])
    state, detail = CloudflarePagesProvider().check(_ctx(http))
    assert state == "error" and "Authentication error" in detail


def test_check_without_config_or_token():
    assert CloudflarePagesProvider().check(_ctx(_Http([]), secret=None))[0] == "unconfigured"
    assert CloudflarePagesProvider().check(_ctx(_Http([]), account_id=""))[0] == "error"


def test_list_deployments_returns_status_url_and_commit():
    out = _run(_Http([("GET", "/deployments?per_page=3", 200, DEPLOYMENTS)]), "list_deployments", limit=3)
    (d,) = out["deployments"]
    assert (d["status"], d["url"], d["commit_hash"]) == ("success", "https://dep2.my-site.pages.dev", "abc")


def test_build_log_quotes_the_failing_line_with_a_link():
    out = _run(_Http([("GET", "/deployments/dep9/history/logs", 200, LOGS)]), "build_log", deployment_id="dep9")
    assert out["reason"].startswith("Failed: build command exited with code: 1")
    assert out["link"] == f"https://dash.cloudflare.com/{ACCOUNT}/pages/view/{PROJECT}/dep9" and out["link"] in out["reason"]


def test_build_log_never_fails_without_log_access():
    out = _run(_Http([("GET", "/history/logs", 403, {"errors": [{"code": 10000, "message": "no"}]})]), "build_log", deployment_id="dep9")
    assert out["reason"].startswith("See the build log: https://dash.cloudflare.com/") and out["lines"] == []


def _alerting(destinations=None, policies=None):
    return _Http(
        [
            ("GET", "/alerting/v3/destinations/webhooks", 200, {"result": destinations or [], "success": True}),
            ("POST", "/alerting/v3/destinations/webhooks", 200, {"result": {"id": "dest1"}, "success": True}),
            ("PUT", "/alerting/v3/destinations/webhooks/", 200, {"result": {"id": "dest1"}, "success": True}),
            ("GET", f"/pages/projects/{PROJECT}", 200, PROJECT_INFO),
            ("GET", "/alerting/v3/policies", 200, {"result": policies or [], "success": True}),
            ("POST", "/alerting/v3/policies", 200, {"result": {"id": "pol1"}, "success": True}),
            ("PUT", "/alerting/v3/policies/", 200, {"result": {"id": "pol1"}, "success": True}),
        ]
    )


def test_connect_notifications_creates_destination_and_pages_alert():
    http = _alerting()
    out = _run(http, "connect_notifications", webhook_url="https://marvin.example/api/hooks/t", webhook_secret="s3cret")

    assert out == {"destination_id": "dest1", "policy_id": "pol1", "created": True}
    dest = next(c["json"] for c in http.calls if c["method"] == "POST" and c["url"].endswith("/destinations/webhooks"))
    assert dest == {"name": f"Marvin ({PROJECT})", "url": "https://marvin.example/api/hooks/t", "secret": "s3cret"}
    policy = next(c["json"] for c in http.calls if c["method"] == "POST" and c["url"].endswith("/policies"))
    assert policy["alert_type"] == "pages_event_alert" and policy["mechanisms"] == {"webhooks": [{"id": "dest1"}]}
    assert policy["filters"] == {
        "project_id": ["proj-uuid"],
        "environment": ["ENVIRONMENT_PRODUCTION"],
        "event": ["EVENT_DEPLOYMENT_STARTED", "EVENT_DEPLOYMENT_SUCCESS", "EVENT_DEPLOYMENT_FAILED"],
    }


def test_connect_notifications_updates_instead_of_duplicating():
    http = _alerting(
        destinations=[{"id": "dest1", "name": f"Marvin ({PROJECT})"}], policies=[{"id": "pol1", "name": f"Site builds → Marvin ({PROJECT})"}]
    )
    out = _run(http, "connect_notifications", webhook_url="https://marvin.example/api/hooks/t", webhook_secret="s3cret")

    assert out["created"] is False
    assert not any(c["method"] == "POST" for c in http.calls)


@pytest.mark.parametrize(
    "args",
    [
        {"webhook_url": "http://insecure", "webhook_secret": "x"},
        {"webhook_url": "https://ok", "webhook_secret": ""},
        {"webhook_url": "https://ok", "webhook_secret": "{{CLOUDFLARE_NOTIFY_TOKEN}}"},  # an unresolved reference
    ],
)
def test_connect_notifications_refuses_bad_input(args):
    with pytest.raises(ValueError):
        _run(_alerting(), "connect_notifications", **args)


def test_deploy_posts_the_production_branch_as_multipart():
    http = _Http(
        [
            ("GET", f"/pages/projects/{PROJECT}", 200, PROJECT_INFO),
            ("POST", "/deployments", 200, {"result": {"id": "dep3", "url": "https://dep3.my-site.pages.dev"}, "success": True}),
        ]
    )
    out = _run(http, "deploy")
    post = next(c for c in http.calls if c["method"] == "POST")
    assert out["deployment_id"] == "dep3" and b'name="branch"\r\n\r\nmain' in post["data"]
    assert post["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")


def test_unknown_action_and_missing_token():
    with pytest.raises(NotImplementedError):
        _run(_Http([]), "nope")
    with pytest.raises(ValueError, match="token"):
        CloudflarePagesProvider().run_action("list_deployments", {}, _ctx(_Http([]), secret=None))


# --- declared content -----------------------------------------------------------------------------


def test_contributes_the_cloudflare_token_scheme():
    scheme = CloudflarePagesProvider.signature_schemes["cloudflare"]
    assert scheme["mode"] == "token" and scheme["header"] == "cf-webhook-auth"


def test_declares_the_webhook_and_three_workflows():
    from marvin_integration_cloudflare_pages.content import CONTENT

    assert [(b.kind, b.slug) for b in CONTENT] == [
        ("incoming_webhook", "cloudflare-pages"),
        ("workflow", "cloudflare-pages-deploy-started"),
        ("workflow", "cloudflare-pages-deploy-succeeded"),
        ("workflow", "cloudflare-pages-deploy-failed"),
    ]
    assert CONTENT[0].payload["signature_scheme"] == "cloudflare"


def test_each_workflow_maps_one_cloudflare_event_to_one_marvin_event():
    from marvin_integration_cloudflare_pages.content import CONTENT

    mapping = {}
    for b in CONTENT[1:]:
        d = b.payload["definition"]
        assert d["trigger"] == {"type": "incoming_webhook", "webhook": "cloudflare-pages"}
        emit = next(a for a in d["actions"] if a["kind"] == "emit_event")
        mapping[d["conditions"][0]["value"]] = emit["event"]
    assert mapping == {
        "EVENT_DEPLOYMENT_STARTED": "site_deployment_started",
        "EVENT_DEPLOYMENT_SUCCESS": "site_deployment_completed",
        "EVENT_DEPLOYMENT_FAILED": "site_deployment_failed",
    }


def test_the_failure_workflow_reads_the_build_log_through_this_provider():
    from marvin_integration_cloudflare_pages.content import DEPLOY_FAILED

    actions = DEPLOY_FAILED.payload["definition"]["actions"]
    assert actions[0]["action"] == "build_log" and actions[0]["id"] == "log"
    assert actions[1]["error"] == "${steps.log.output.reason}"
    assert {a.key for a in CloudflarePagesProvider.actions} >= {"build_log"}
