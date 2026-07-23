# Milestone 6 — Manual Test Checklist

Purpose: verify the Milestone 6 extensions against **real inputs** (especially
your own robots) and against a **live ROS 2 / Gazebo** stack, and hand the
results back so the code can be improved.

The Milestone 6 modules are deterministic *generators and validators*. There is
no live ROS node in this repo yet (that is Milestones 0–3), so:

- **Tiers 1–2** run fully offline and are the highest-value tests right now —
  they exercise the generator/validator logic on arbitrary URDFs.
- **Tiers 3–5** feed the generated artifacts into a real ROS 2 / Gazebo / RViz
  install. Skip them if you don't have that set up; note it in the report.

A helper script generates every artifact for you:

```bash
# from the repo root, on branch claude/milestone-6-extensions-chapter-67088x
python scripts/m6_demo.py                          # sample model
python scripts/m6_demo.py path/to/your_robot.urdf  # YOUR robot
python scripts/m6_demo.py your.urdf --namespace armA --out /tmp/m6_out
```

---

## 0. Environment capture (do this first)

Record once at the top of your report:

```bash
uname -a
python3 --version
echo "ROS_DISTRO=$ROS_DISTRO"                       # e.g. humble / jazzy (blank if no ROS)
ros2 --version 2>/dev/null || echo "no ROS 2"
ros2 pkg list 2>/dev/null | grep -E "ros2_control|controller_manager|gazebo_ros2_control|ros_gz" || echo "control/gazebo pkgs not found"
```

- [ ] **T0** — environment captured (paste the output).

---

## Tier 1 — Offline core (no ROS needed)

### T1.1 — Test suite is green
```bash
pip install -q pytest flake8 PyYAML
python -m pytest src -q
flake8 --max-line-length=99 --extend-ignore=E203,W503 src conftest.py
```
- [ ] **T1.1** — all tests pass, lint clean.
- **Capture:** the pytest summary line (`N passed`) and any failures **verbatim**.

### T1.2 — Generators on YOUR real URDF  ⭐ most useful
Run the helper on 2–3 of your own robots (arm, mobile base, gripper, anything).
```bash
python scripts/m6_demo.py /path/to/your_robot.urdf --out /tmp/m6_out
```
- [ ] **T1.2a** — the `<ros2_control>` block lists exactly your movable joints
      (no `fixed` joints), with sensible command/state interfaces.
- [ ] **T1.2b** — `controllers.yaml` joints match, controller type is reasonable
      (trajectory vs. velocity).
- [ ] **T1.2c** — `embed_ros2_control` output (`/tmp/m6_out/robot_with_control.urdf`)
      still parses (`check_urdf` if you have it, or just open it).
- **Capture:** the full console output **and** attach `/tmp/m6_out/*`. Flag
  anything that looks wrong for your robot (mimic joints, multi-DOF, continuous
  vs revolute choices, non-standard interfaces).

### T1.3 — Physical validation on real + intentionally-broken models
- [ ] **T1.3a** — run on a *good* real URDF → expect `ok`. If it flags something
      that is actually fine, that's a false positive I want to know about.
- [ ] **T1.3b** — hand-break a copy: set a `<mass value="0"/>`, or an inertia of
      `ixx=iyy=1 izz=5` (triangle-inequality), or a `<box size="-1 1 1"/>`.
      Confirm the matching finding appears (`mass_nonpositive`,
      `inertia_triangle_inequality`, `geometry_nonpositive`).
- **Capture:** both reports (paste), plus the broken snippet you used.

### T1.4 — Multi-model namespacing
```bash
python scripts/m6_demo.py your.urdf --namespace armA --out /tmp/armA
```
- [ ] **T1.4** — every link/joint (and any `mimic`) is prefixed and the URDF is
      internally consistent (parent/child references updated).
- **Capture:** the namespaced URDF (attach the file).

### T1.5 — Docs build
```bash
pip install -q -r docs/requirements.txt
mkdocs build --strict && mkdocs serve   # then open http://127.0.0.1:8000
```
- [ ] **T1.5** — build is clean; the **Extensions (Milestone 6)** page renders,
      code blocks and tables look right.
- **Capture:** a screenshot of the rendered Extensions page.

---

## Tier 2 — Web UI (offline mock backend)

```bash
cd web && python server.py   # then open the printed URL
node --test                  # pure-module unit tests
```
- [ ] **T2.1** — page loads; kinematic tree renders for the sample model.
- [ ] **T2.2** — an edit → validate → apply → rollback round-trip works.
- [ ] **T2.3** — the audit-trail viewer shows the applied change.
- **Capture:** screenshots of (a) the tree view, (b) a validation result,
  (c) the audit trail. Plus the browser **DevTools console** (screenshot or
  copied text) if anything errors.

---

## Tier 3 — Live `ros2_control` (needs ROS 2 + ros2_control)

Use the generated `robot_with_control.urdf` + `controllers.yaml` from T1.2 with
your own (or a demo) launch that starts `ros2_control_node` /
`controller_manager`.
- [ ] **T3.1** — controller_manager loads the URDF without error.
- [ ] **T3.2** — `ros2 control list_hardware_interfaces` shows a command +
      state interface per movable joint.
- [ ] **T3.3** — `ros2 control list_controllers` shows the broadcaster and the
      generated controller reaching `active`.
- [ ] **T3.4** — commanding the controller moves the expected joint (echo
      `/joint_states`).
- **Capture (logs, as text):** the full `controller_manager` stdout/stderr,
  and the output of the three `ros2 control ...` commands. Save long logs as
  `.txt`/`.log` files named by test ID (e.g. `T3.1-cm.log`).

---

## Tier 4 — Gazebo simulation (needs Gazebo + gazebo_ros2_control)

Embed the gazebo block (helper step 4) + `gazebo_ros2_control`, then spawn the
model **in the order the spawn plan prints** (helper step 5).
- [ ] **T4.1** — model spawns and is visible; it rests on the ground (collision
      present) rather than falling through.
- [ ] **T4.2** — controllers activate and joints are drivable in sim.
- [ ] **T4.3** — negative test: spawn a model with a **massless** link (matches
      our `gazebo_inertial_missing` warning) and confirm Gazebo drops/warns on
      that link — i.e. our readiness check predicted reality.
- **Capture:** screenshots of the Gazebo viewport (T4.1 resting, T4.2 mid-move),
  plus the spawn/gzserver terminal logs as text. Note ROS distro + Gazebo
  version (Classic vs. Ignition/gz-sim).

---

## Tier 5 — Multi-model in RViz2 (needs ROS 2 + RViz2)

Publish two namespaced robots (from T1.4) via two `robot_state_publisher`
instances with matching `frame_prefix`.
- [ ] **T5.1** — both robots appear in RViz2 with no overlapping/duplicate TF
      frames; `ros2 run tf2_tools view_frames` produces a clean two-tree graph.
- [ ] **T5.2** — `SessionRegistry.check_scene()` (helper) reports `scene_ok`
      and the frame list matches what RViz shows.
- **Capture:** RViz2 screenshot (both robots + TF display), the generated
  `frames.pdf`/`frames.gv` from `view_frames`, and the helper's frame list.

---

## What to send back — report format

Please return **one Markdown file** named `m6-manual-report.md`, plus a
`screenshots/` folder, bundled as a `.zip` (or paste the Markdown inline and
attach images/logs separately).

**Conventions**
- **Logs:** short ones inline in triple-backtick code blocks; long ones as
  attached `.txt`/`.log` files named by test ID (`T3.1-cm.log`).
- **Screenshots:** PNG, named by test ID (`T4.1-gazebo-rest.png`), referenced
  from the report. Full window including relevant panels (RViz displays list,
  Gazebo left panel, DevTools console), not just the viewport.
- **Every failure:** paste the **exact** error text — don't paraphrase.

**Template** (copy this, fill one block per test you ran):

````markdown
# Milestone 6 — Manual Test Report
Date:
Tester:

## Environment (T0)
<paste uname / python / ROS_DISTRO / pkg check output>

## Results
### T1.1 — Test suite
Status: PASS | FAIL | SKIPPED
Observed: <e.g. "120 passed">
Logs:
```
<paste>
```
Notes / suspected bug:

### T1.2 — Generators on my URDF
Robot(s) tested: <name + link count>
Status:
Observed:
Attachments: m6_out_myrobot/ (robot_with_control.urdf, controllers.yaml)
Anything wrong for my robot: <mimic? multi-DOF? interface choice?>

<...one block per test...>

## Summary
- Bugs found:
- False positives/negatives in validation:
- Generated artifacts that didn't work in ROS/Gazebo:
- Suggestions / missing features:
````

Send the zip (or paste + attachments) back in this chat and I'll triage each
finding, reproduce where I can, and push fixes to the Milestone 6 branch.
