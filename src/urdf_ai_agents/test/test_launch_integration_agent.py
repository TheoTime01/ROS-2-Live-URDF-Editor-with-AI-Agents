"""Tests for the Launch/Integration Agent wrapper.

These exercise the agent's deterministic behavior: analysis, explanation, and
application with audit + logging side effects. No Claude API access is required.
"""

from __future__ import annotations

import pytest

from urdf_ai_agents.agents import LaunchIntegrationAgent
from urdf_live_editor.integration.launch_sync import extract_model_summary, plan_config_sync
from urdf_live_editor.observability import AuditTrail

URDF = """
<robot name="arm">
  <link name="base_link"/><link name="l1"/><link name="l2"/>
  <joint name="j1" type="revolute">
    <parent link="base_link"/><child link="l1"/>
    <axis xyz="0 0 1"/><limit lower="-1" upper="1"/>
  </joint>
  <joint name="j2" type="continuous">
    <parent link="l1"/><child link="l2"/><axis xyz="1 0 0"/>
  </joint>
</robot>
"""


@pytest.fixture()
def model():
    return extract_model_summary(URDF)


def test_analyze_reports_in_sync(model):
    agent = LaunchIntegrationAgent()
    configs = {"policy": {"joints": {"j1": {"type": "revolute"},
                                     "j2": {"type": "continuous"}}}}
    report = agent.analyze(model, configs)
    assert report.in_sync
    assert report.action_count() == 0
    assert "in sync" in agent.explain(report).lower()


def test_analyze_detects_drift_and_explains(model):
    agent = LaunchIntegrationAgent()
    configs = {"policy": {"joints": {"j1": {"type": "revolute"}}}}  # j2 missing
    report = agent.analyze(model, configs)
    assert not report.in_sync
    assert report.action_count() == 1
    text = agent.explain(report)
    assert "j2" in text
    assert "[policy]" in text


def test_analyze_urdf_convenience(model):
    agent = LaunchIntegrationAgent()
    report = agent.analyze_urdf(URDF, {"policy": {"joints": {}}})
    assert report.action_count() == 2  # j1, j2 both missing


def test_analyze_flags_missing_launch_reference(model, tmp_path):
    agent = LaunchIntegrationAgent()
    configs = {"policy": {"joints": {"j1": {"type": "revolute"},
                                     "j2": {"type": "continuous"}}}}
    report = agent.analyze(
        model, configs,
        launch_references={"rviz_config": "does_not_exist.rviz"},
        base_dir=str(tmp_path),
    )
    assert not report.in_sync
    assert report.reference_issues[0].key == "rviz_config"
    assert "rviz_config" in agent.explain(report)


def test_apply_plan_records_audit_and_returns_synced_config(model):
    trail = AuditTrail()
    agent = LaunchIntegrationAgent(audit_trail=trail)
    config = {"joints": {"j1": {"type": "revolute"}}}
    plan = plan_config_sync(model, config, config_name="policy")

    updated = agent.apply_plan(config, model, plan, model_version="v7")

    # config is now in sync
    assert plan_config_sync(model, updated).in_sync
    # audit entry was recorded
    assert len(trail) == 1
    entry = trail.head
    assert entry.actor == "agent:launch_integration"
    assert entry.action == "sync_config"
    assert entry.to_version == "v7"
    assert entry.metadata["config"] == "policy"
    assert trail.is_intact()


def test_report_to_dict_is_json_ready(model):
    agent = LaunchIntegrationAgent()
    report = agent.analyze(model, {"policy": {"joints": {}}})
    data = report.to_dict()
    assert data["in_sync"] is False
    assert data["action_count"] == 2
    assert data["plans"][0]["config_name"] == "policy"
