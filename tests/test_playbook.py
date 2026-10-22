"""The Playbook this integration ships (0.5.0, SDK 0.15.0), and the SDK's conformance kit over the whole provider."""

from importlib import resources

import pytest
from marvin_integration_sdk import check_playbook
from marvin_integration_sdk.testing import IntegrationContract

from marvin_integration_cloudflare_pages import CloudflarePagesProvider
from marvin_integration_cloudflare_pages.content import DEPLOY_FAILED


class TestCloudflarePagesContract(IntegrationContract):
    @pytest.fixture
    def provider(self):
        return CloudflarePagesProvider()


def _playbook():
    (blueprint,) = [c for c in CloudflarePagesProvider.content if c.kind == "playbook"]
    return blueprint


def test_the_provider_ships_the_failed_build_playbook():
    blueprint = _playbook()
    assert (blueprint.slug, blueprint.required) == ("cloudflare-pages-failed-build", False)
    assert list(blueprint.payload["files"]) == ["references/causes.md"]
    assert check_playbook(blueprint, CloudflarePagesProvider()) == []


def test_it_names_the_workflow_by_its_slug_and_the_workflow_exists():
    assert DEPLOY_FAILED.slug == "cloudflare-pages-deploy-failed"
    assert "`cloudflare-pages-deploy-failed`" in _playbook().payload["skill_md"]


def test_it_narrows_the_agent_to_reading_tools_only():
    tools = _playbook().payload["skill_md"].split("allowed-tools:")[1].splitlines()[0].split()
    assert tools == ["list_events", "describe_event", "get_workflow", "find_entries", "get_entry"]
    assert not {"run_workflow", "compose_entry", "revise_entry", "create_draft", "update_draft"} & set(tools)


def test_it_says_never_to_guess_past_the_log():
    assert "Never guess past the log" in _playbook().payload["skill_md"]


def test_the_playbook_files_are_package_data():
    root = resources.files("marvin_integration_cloudflare_pages").joinpath("playbooks", "cloudflare-pages-failed-build")
    assert root.joinpath("SKILL.md").is_file() and root.joinpath("references", "causes.md").is_file()
