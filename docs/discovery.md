# Discovery: what OpenAMRobot already provides

Read from shallow clones of the official repositories on 17 Nov 2026. Nothing here is from memory. Each
interface the Studio uses names the file it comes from.

| Repository | Commit | Date |
|---|---|---|
| openamr-upperbody-sw | `a3a93c6` | 2026-11-16 |
| openamr-platform-sw | `69847ab` | 2026-11-15 |
| openamrobot-interfaces | `50ed777` | 2026-11-15 |
| openamrobot-ui | `51b4af3` | 2026-11-10 |
| openamrobot-docs (roadmap) | `852c32c` | 2026-11-13 |

Roadmap snapshot, 9 Nov (`openamrobot-docs/docs/assets/roadmap/index.html`):
- **Target:** v2.0.0-rc.1 on 20 Nov 2026. No 2.0 hardware has been delivered.
- **Safety chain:** designed, not built.
- **Odometry:** the Gazebo physics fault (upperbody-sw #49) means simulation results that rely on odometry alone are not evidence. The Studio therefore does not read `/odom` at all.

## What exists

### Upper body: `openamr-upperbody-sw`

- **Controllers:** `ros2/src/openamrobot_upperbody_control/config/arm_controllers.yaml` configures `controller_manager` at 100 Hz with six controllers:

  | Controller | Type | Joints |
  |---|---|---|
  | `joint_state_broadcaster` | `joint_state_broadcaster/JointStateBroadcaster` | |
  | `left_arm_controller` | `joint_trajectory_controller/JointTrajectoryController` | `openarm_left_joint1..7` |
  | `right_arm_controller` | `joint_trajectory_controller/JointTrajectoryController` | `openarm_right_joint1..7` |
  | `left_gripper_controller` | `position_controllers/GripperActionController` | `openarm_left_finger_joint1` |
  | `right_gripper_controller` | `position_controllers/GripperActionController` | `openarm_right_finger_joint1` |
  | `lift_controller` | `joint_trajectory_controller/JointTrajectoryController` | `lift_joint` |

  `lift_joint` has a command interface only in the simulated profiles. On real hardware the CTL-017 firmware owns the lift.
- **Launch files** (`openamrobot_upperbody_bringup/launch/`): `mock.launch.py` (mock_components, all six controllers active, headless), `moveit.launch.py` and `view.launch.py`. `openamrobot_upperbody_gazebo/launch/sim.launch.py` runs Gazebo. `openamrobot_openarm_emulator/launch/sil.launch.py` runs the SIL emulator.
- **Topics and services:**
  - `/joint_states` (`sensor_msgs/JointState`), published by `joint_state_broadcaster`.
  - `/tf` and `/tf_static`, published by `robot_state_publisher`.
  - `/controller_manager/list_controllers` (`controller_manager_msgs/srv/ListControllers`).
- **TF chain**, from `openamrobot_upperbody_description` (`combined_robot.xacro` and `openamrobot_upperbody.xacro`): `world → base_footprint → lift_column_base_link → lift_carriage_link`, where `lift_joint` is prismatic with a 0.35 m stroke for `dold_v4_350`. The arm bases (`openarm_{left,right}_base_link`) and `adapter_plate_link` hang off `lift_carriage_link`.

### Navigation: `openamr-platform-sw` and `openamrobot-interfaces`

- **`navigation_status_node`** (`openamrobot_nav2/openamrobot_nav2/navigation_status_node.py`):
  - Publishes `/navigation/status` (`openamr_nav_msgs/msg/NavigationStatus`, `CONTRACT_VERSION = 2`).
  - Mirrors health and per-sensor entries on `/diagnostics` (`diagnostic_msgs/DiagnosticArray`). Entry names are `navigation_status_node: health` and `navigation_status_node: sensor <id>`.
  - Its own docstring: "It never sends goals or velocity commands." It is a functional status, not a safety function.
- **`NavigationStatus.msg`** (`openamrobot-interfaces/ros2/openamr_nav_msgs/msg/`) carries:
  - `health` (UNKNOWN, OK, DEGRADED or FAULT) and `navigation_readiness` (NOT_READY or READY).
  - `not_ready_reasons` and `active_reasons`, as reason codes 1001–9004: stack, sensors, localization, task, recovery, protection, docking, parking, base/I8.
  - Note: the base/I8 adapter does not exist yet, so the real node stays NOT_READY with `BASE_LINK_LOST`.
- **Nav2 lifecycle:** `MANAGED_NAV_NODES` lists `amcl`, `planner_server`, `controller_server`, `smoother_server`, `bt_navigator`, `behavior_server`, `waypoint_follower`, `velocity_smoother`, `map_server` and `collision_monitor`. Each serves `/<node>/get_state` (`lifecycle_msgs/srv/GetState`), and `lifecycle_manager_navigation` manages them.
- **Launch files:** `openamrobot_bringup/launch/bringup.launch.py` and `real_bringup.launch.py`; `openamrobot_gazebo/launch/gz_simulator.launch.py`; `openamrobot_sil/launch/sil.launch.py`. The SIL topics `/sil/*` (lift permit, emulator states, BMS) exist but are emulator internals.

### Operator UI: `openamrobot-ui`

Talks to ROS through rosbridge and roslib. It is a separate product that owns the operator command path; the Studio does not overlap with it and does not command anything.

## What the Studio reuses directly

| Need | Reused interface |
|---|---|
| Arm, gripper and lift controller readiness | `ListControllers` on `/controller_manager` (query only) |
| Joint freshness and completeness | `/joint_states` |
| Frames | `/tf`, `/tf_static` |
| Navigation readiness and reason codes | `/navigation/status` (the existing roll-up, not recomputed) |
| Nav2 stack state | `/<node>/get_state` for `MANAGED_NAV_NODES` |
| Generic health | `/diagnostics` |

The Studio's expectations (controller and joint names, Nav2 nodes, reason-code names) are in `services/api/studio_api/profile.py`, with these file references.

## What needs an adapter

- **A ROS-to-HTTP bridge.** The web platform must run without ROS 2, so a separate `rclpy` process (`services/ros-adapter`) subscribes and queries under an allowlist and serves `/snapshot` over HTTP using the stdlib only.
- **Custom message types.** `openamr_nav_msgs` must be built in the ROS environment for `/navigation/status`. Without it, the adapter records a note and navigation reads UNKNOWN.
- **Freshness on receive time.** Header stamps are in the publisher's clock, which is sim time under Gazebo. Freshness is therefore judged on the adapter's receive time, and the stamp is kept as evidence.

## Deliberately not used

- `/odom` and odometry-derived motion, because of the Gazebo fault (#49).
- Any publisher or action, including `/cmd_vel`, `JointTrajectory`, `FollowJointTrajectory` and `NavigateToPose`.
- Mutating services: `switch_controller`, lifecycle `change_state`, `set_parameters`.
- `/lift_guard/status`. The simulated lift guard (upperbody-sw #53) is not on main.
