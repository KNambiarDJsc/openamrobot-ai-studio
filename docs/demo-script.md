# Demo script for Alex (about 6 minutes, demo mode, no ROS or model needed)

**Setup:** run `.\scripts\dev.ps1` (or `./scripts/dev.sh`) and open http://localhost:3000.

**1. The point (30 s).** "This is RFC milestone M1: a read-only diagnostics sidecar. It answers 'why is the robot not ready?' from observed ROS state. It says UNKNOWN when it can't know. It can't move anything."

**2. Overview, healthy (45 s).**
- Show the DEMO FIXTURE flag, the three READY cards and the source freshness table.
- "Every row is a real interface from upperbody-sw or platform-sw: controller_manager, /joint_states, /navigation/status, Nav2 get_state and /diagnostics. Ages are judged on receive time, because Gazebo stamps are sim time."

**3. Switch fixtures (90 s).**
- **Inactive controller:** BLOCKED, named as `lift_controller is inactive`, with the next human check.
- **Stale telemetry:** UNKNOWN, not BLOCKED. "Stale isn't a failure we observed; it's missing evidence."
- **Missing ROS graph:** ERROR. The query itself could not complete.
- **Conflicting state:** UNKNOWN. `/navigation/status` says READY but `controller_server` is inactive, and the Studio refuses to pick a side.
- **Diagnostic warning:** READY with warnings, and the rear scan shown as WARN.

**4. Copilot (90 s).**
- Ask the RFC example: "Is the simulated robot ready for a navigation task? Which subsystem is blocking it?"
- Point at the source, receive time, age, freshness budget and trace id on each line.
- Click "Raise the lift to the top stop". It is refused, with one `refuse` record and no tool call.
- "Ollama and Strands are optional. If enabled, they can only rephrase. Any new number, a changed status or a dropped trace id discards their text."

**5. Evidence Explorer (60 s).**
- Filter Status = BLOCKED and open an evaluation. Show the full trace and the recorded snapshot JSON.
- On the Tool calls tab, show the copilot's calls by trace id.
- "This is what makes an answer reproducible: the same snapshot and time always give the same result."

**6. Simulation Monitor (30 s).**
- "A telemetry view of lift_joint over its 0.35 m stroke, the joint table, TF frames and controllers."
- "It says on screen that it is not a Gazebo render."

**7. The ask (30 s).**
- Approve M0: the contract review. Which read-only interfaces are stable, who owns them, and the freshness budgets.
- Then run the live check against mock.launch.py (`tests/ros/run_mock_integration.sh`).
- No action-capable tool until M2 review.

**Say clearly:**
- The live ROS path is written and unit-tested but has not yet run against a graph.
- Nothing here is safety evidence or physical acceptance.
