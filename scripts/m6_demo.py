#!/usr/bin/env python3
"""Milestone 6 manual-test helper.

Generates every Milestone 6 artifact from a URDF and prints all validation
reports, so you can eyeball the output and feed your own real robots in.

Usage:
    # from the repo root, on the milestone-6 branch:
    python scripts/m6_demo.py                                  # uses the sim sample
    python scripts/m6_demo.py path/to/your_robot.urdf          # your model
    python scripts/m6_demo.py your.urdf --namespace armA       # namespacing demo
    python scripts/m6_demo.py your.urdf --out out_dir          # write artifacts to files

Nothing here needs ROS, Gazebo, or an API key.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Make the package importable when run from the repo root without colcon.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src", "urdf_live_editor"))

from urdf_live_editor.extensions import (  # noqa: E402
    build_spawn_plan,
    check_gazebo_readiness,
    embed_ros2_control,
    generate_controller_manager_yaml,
    generate_gazebo_ros2_control_block,
    generate_ros2_control_xml,
    namespace_urdf,
    validate_controllers_config,
    validate_physical,
)

SAMPLE = os.path.join(_ROOT, "models", "sample_arm", "sample_arm_sim.urdf")


def banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def dump_report(report) -> None:
    print(report.summary())
    for issue in report.issues:
        print(f"  [{issue.severity.label:7}] {issue.code}: {issue.message}")
    if not report.issues:
        print("  (no findings)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urdf", nargs="?", default=SAMPLE)
    ap.add_argument("--namespace", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.urdf, encoding="utf-8") as fh:
        urdf = fh.read()
    print(f"Loaded URDF: {args.urdf}")

    banner("1. ros2_control block")
    block = generate_ros2_control_xml(urdf, name="RobotSystem")
    print(block)

    banner("2. controller_manager YAML")
    cm = generate_controller_manager_yaml(urdf)
    print(json.dumps(cm, indent=2))

    banner("3. validate controllers config against the model")
    dump_report(validate_controllers_config(urdf, cm))

    banner("4. gazebo_ros2_control block")
    print(generate_gazebo_ros2_control_block(controllers_path="config/controllers.yaml"))

    banner("5. Gazebo spawn plan")
    plan = build_spawn_plan(entity_name="robot", controllers=["robot_controller"],
                            namespace=args.namespace)
    for step in plan.steps:
        print(f"  {step.order}. [{step.kind}] {step.description}")

    banner("6. Gazebo readiness")
    dump_report(check_gazebo_readiness(urdf))

    banner("7. Physical validation (require_collision=True)")
    dump_report(validate_physical(urdf, require_collision=True))

    if args.namespace:
        banner(f"8. Namespaced URDF (prefix '{args.namespace}')")
        print(namespace_urdf(urdf, args.namespace)[:600] + " ...")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "robot_with_control.urdf"), "w") as fh:
            fh.write(embed_ros2_control(urdf, block))
        try:
            import yaml
            with open(os.path.join(args.out, "controllers.yaml"), "w") as fh:
                yaml.safe_dump(cm, fh, sort_keys=False)
        except ImportError:
            with open(os.path.join(args.out, "controllers.json"), "w") as fh:
                json.dump(cm, fh, indent=2)
        print(f"\nWrote artifacts to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
