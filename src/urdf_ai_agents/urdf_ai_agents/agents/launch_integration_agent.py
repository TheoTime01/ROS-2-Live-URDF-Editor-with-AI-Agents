"""Launch/Integration Agent — keeps launch/config in sync after model changes.

This is the Milestone 5 agent from the README's AI-agent list. It is a *thin,
auditable wrapper* over the deterministic planner in
``urdf_live_editor.integration.launch_sync``: the planner decides what must
change, and the agent only

1. presents the plan (optionally as natural-language prose via the Claude Agent
   SDK, with a deterministic fallback when the SDK/key is unavailable), and
2. applies an already-computed, deterministic plan on request — recording a
   structured log event and an audit-trail entry for every applied change.

The agent can never invent a change the deterministic planner did not authorize.
That keeps it consistent with the project's core guarantee that the AI layer
cannot bypass deterministic validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

# The deterministic core is imported directly. In a built colcon workspace both
# packages are on the path; for offline unit tests the src/ tree is importable.
from urdf_live_editor.integration.launch_sync import (
    ChangeKind,
    ModelSummary,
    ReferenceIssue,
    SyncPlan,
    apply_config_sync,
    check_launch_references,
    extract_model_summary,
    plan_config_sync,
)

try:  # optional: only needed for LLM-generated prose
    from urdf_live_editor.observability import AuditTrail, get_logger
except Exception:  # pragma: no cover - observability is part of the same pkg
    AuditTrail = None  # type: ignore[assignment]

    def get_logger(name: str, **_ctx: Any):  # type: ignore[no-redef]
        class _Null:
            def __getattr__(self, _n):
                return lambda *a, **k: None

        return _Null()


__all__ = ["IntegrationReport", "LaunchIntegrationAgent"]


@dataclass(frozen=True)
class IntegrationReport:
    """The result of analyzing model-vs-config/launch drift."""

    plans: List[SyncPlan]
    reference_issues: List[ReferenceIssue]

    @property
    def in_sync(self) -> bool:
        return all(p.in_sync for p in self.plans) and not self.reference_issues

    def action_count(self) -> int:
        return sum(len(p.actions) for p in self.plans)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "in_sync": self.in_sync,
            "action_count": self.action_count(),
            "plans": [p.to_dict() for p in self.plans],
            "reference_issues": [i.to_dict() for i in self.reference_issues],
        }


class LaunchIntegrationAgent:
    """Analyze and (on request) repair launch/config drift after model edits."""

    #: The agent's focused system prompt when run as a Claude Agent SDK subagent.
    SYSTEM_PROMPT = (
        "You are the Launch/Integration Agent for a ROS 2 URDF live editor. "
        "A deterministic planner has already computed exactly which launch and "
        "config changes are required to match the current robot model. Your job "
        "is to explain that plan clearly to a robotics engineer and, only when "
        "asked, to apply it. Never propose changes the deterministic planner did "
        "not list. Be concise and precise about joint names and types."
    )

    def __init__(
        self,
        *,
        audit_trail: "Optional[AuditTrail]" = None,
        actor: str = "agent:launch_integration",
        logger=None,
    ) -> None:
        self._audit = audit_trail
        self._actor = actor
        self._log = logger or get_logger("launch_integration_agent")

    # -- analysis ---------------------------------------------------------
    def analyze(
        self,
        model: ModelSummary,
        configs: Mapping[str, Mapping[str, Any]],
        *,
        launch_references: Optional[Mapping[str, str]] = None,
        base_dir: str = ".",
        joints_key: str = "joints",
        movable_only: bool = True,
    ) -> IntegrationReport:
        """Analyze one or more configs and the launch references against ``model``.

        ``configs`` maps a config name (used in the plan) to its parsed dict.
        """
        plans = [
            plan_config_sync(
                model,
                cfg,
                config_name=name,
                joints_key=joints_key,
                movable_only=movable_only,
            )
            for name, cfg in configs.items()
        ]
        ref_issues: List[ReferenceIssue] = []
        if launch_references:
            ref_issues = check_launch_references(launch_references, base_dir=base_dir)

        report = IntegrationReport(plans=plans, reference_issues=ref_issues)
        self._log.info(
            "integration_analyzed",
            in_sync=report.in_sync,
            actions=report.action_count(),
            missing_refs=len(ref_issues),
        )
        return report

    def analyze_urdf(
        self,
        urdf_xml: str,
        configs: Mapping[str, Mapping[str, Any]],
        **kwargs: Any,
    ) -> IntegrationReport:
        """Convenience wrapper that extracts a :class:`ModelSummary` from URDF."""
        return self.analyze(extract_model_summary(urdf_xml), configs, **kwargs)

    # -- explanation ------------------------------------------------------
    def explain(self, report: IntegrationReport) -> str:
        """Return a human-readable explanation of ``report``.

        Uses a deterministic, dependency-free renderer. A future enhancement can
        route this through the Claude Agent SDK for richer prose using
        :attr:`SYSTEM_PROMPT`; the deterministic text below is always the
        ground truth and the fallback when no API key is configured.
        """
        if report.in_sync:
            return "Launch and config are in sync with the model. No changes required."

        lines: List[str] = []
        for plan in report.plans:
            if plan.in_sync:
                continue
            lines.append(f"[{plan.config_name}]")
            for action in plan.actions:
                verb = {
                    ChangeKind.ADD: "add",
                    ChangeKind.REMOVE: "remove",
                    ChangeKind.RETYPE: "update",
                }[action.kind]
                lines.append(f"  - {verb} '{action.joint}': {action.detail}")
        if report.reference_issues:
            lines.append("[launch references]")
            for issue in report.reference_issues:
                lines.append(f"  - {issue.key}: {issue.message}")
        return "\n".join(lines)

    # -- application ------------------------------------------------------
    def apply_plan(
        self,
        config: Mapping[str, Any],
        model: ModelSummary,
        plan: SyncPlan,
        *,
        joints_key: str = "joints",
        default_entry: Optional[Mapping[str, Any]] = None,
        model_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply ``plan`` to ``config`` and record log + audit entries.

        Returns the updated config dict (the input is never mutated).
        """
        updated = apply_config_sync(
            config, model, plan, joints_key=joints_key, default_entry=default_entry
        )
        self._log.info(
            "integration_applied",
            config=plan.config_name,
            actions=len(plan.actions),
            summary=plan.summary(),
        )
        if self._audit is not None:
            self._audit.record(
                actor=self._actor,
                action="sync_config",
                summary=plan.summary(),
                to_version=model_version,
                operation=plan.to_dict(),
                metadata={"config": plan.config_name},
            )
        return updated
