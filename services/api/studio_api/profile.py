"""What the readiness rules expect, taken from the OpenAMRobot repositories (see docs/discovery.md).

Every entry names the upstream file it comes from. If upstream changes, change it here and in the
discovery note; nothing in this file is invented.
"""
from __future__ import annotations

# openamr-upperbody-sw @ a3a93c6
#   ros2/src/openamrobot_upperbody_control/config/arm_controllers.yaml
UPPER_BODY_CONTROLLERS: dict[str, list[str]] = {
    "joint_state_broadcaster": [],
    "left_arm_controller": [f"openarm_left_joint{i}" for i in range(1, 8)],
    "right_arm_controller": [f"openarm_right_joint{i}" for i in range(1, 8)],
    "left_gripper_controller": ["openarm_left_finger_joint1"],
    "right_gripper_controller": ["openarm_right_finger_joint1"],
    "lift_controller": ["lift_joint"],
}
UPPER_BODY_JOINTS: list[str] = [j for joints in UPPER_BODY_CONTROLLERS.values() for j in joints]

# openamr-platform-sw @ 69847ab
#   ros2/src/openamrobot_nav2/openamrobot_nav2/navigation_status_node.py  MANAGED_NAV_NODES
NAV2_MANAGED_NODES: list[str] = [
    "amcl", "planner_server", "controller_server", "smoother_server", "bt_navigator",
    "behavior_server", "waypoint_follower", "velocity_smoother", "map_server", "collision_monitor",
]

# lifecycle_msgs/msg/State primary state ids
LIFECYCLE_LABELS = {0: "unknown", 1: "unconfigured", 2: "inactive", 3: "active", 4: "finalized"}
LIFECYCLE_ACTIVE = 3

# openamrobot-interfaces @ 50ed777  ros2/openamr_nav_msgs/msg/NavigationStatus.msg (CONTRACT_VERSION=2)
NAV_HEALTH = {0: "UNKNOWN", 1: "OK", 2: "DEGRADED", 3: "FAULT"}
NAV_READINESS = {0: "NOT_READY", 1: "READY"}
NAV_REASONS: dict[int, str] = {
    0: "NONE",
    1001: "NAV_STACK_NOT_STARTED", 1002: "NAV_STACK_STARTING", 1003: "NAV_STACK_RESETTING",
    1004: "NAV_NODE_INACTIVE", 1005: "NAV_CONFIG_FAULT",
    2001: "SENSOR_DATA_STALE", 2002: "SENSOR_NOT_CONFIGURED", 2003: "SENSOR_NO_DATA_YET",
    2004: "SENSOR_DATA_INVALID", 2005: "SENSOR_RATE_LOW",
    3001: "LOCALIZATION_NOT_INITIALIZED", 3002: "LOCALIZATION_UNCERTAIN",
    3003: "LOCALIZATION_STALE_WHILE_MOVING", 3004: "LOCALIZATION_PAUSED_FOR_DOCKING", 3005: "TF_UNAVAILABLE",
    4001: "GOAL_OUTSIDE_MAP", 4002: "GOAL_BLOCKED", 4003: "START_BLOCKED", 4004: "NO_VALID_PATH",
    4005: "PLANNER_TIMEOUT", 4006: "CONTROLLER_TIMEOUT", 4007: "STUCK", 4008: "LOCAL_BLOCKED",
    4009: "NAV_UNKNOWN_FAULT",
    5001: "RECOVERY_IN_PROGRESS", 5002: "RECOVERY_LIMIT_REACHED",
    6001: "COLLISION_LAYER_INACTIVE", 6002: "MOTION_SOURCE_UNPROTECTED", 6003: "REAR_COVERAGE_UNAVAILABLE",
    6004: "PROTECTION_STATE_UNKNOWN", 6005: "SPEED_LIMIT_ACTIVE", 6006: "REVERSE_SPEED_LIMITED",
    6007: "MOTION_SOURCE_PARTIALLY_PROTECTED", 6008: "COLLISION_APPROACH_ACTIVE",
    7001: "DOCK_ENGAGEMENT_UNKNOWN", 7002: "DOCK_TAGS_NOT_VISIBLE", 7003: "DOCK_ALIGNMENT_FAILED",
    7004: "DOCK_TIMEOUT", 7005: "DOCK_STAGING_FAILED", 7006: "UNDOCK_FAILED", 7007: "UNDOCKING_BEFORE_GOAL",
    7008: "DOCK_REASON_UNSPECIFIED",
    8001: "PARK_TARGET_UNREACHABLE", 8002: "PARK_POSE_MISSED", 8003: "PARKING_NOT_IMPLEMENTED",
    9001: "BASE_LINK_LOST", 9002: "BASE_NOT_READY", 9003: "ESTOP_ACTIVE", 9004: "BATTERY_LOW",
}

# diagnostic_msgs/DiagnosticStatus levels
DIAG_LEVELS = {0: "OK", 1: "WARN", 2: "ERROR", 3: "STALE"}

# Freshness budgets, seconds since the adapter received the fact. Policy, not upstream values:
# joint_state_broadcaster publishes at the controller_manager rate (100 Hz in arm_controllers.yaml),
# navigation_status_node publishes on change and on a heartbeat, the adapter polls services about every 1 s.
MAX_AGE_S: dict[str, float] = {
    "graph": 5.0,
    "joint_state": 1.0,
    "controllers": 3.0,
    "lifecycle": 5.0,
    "navigation_status": 5.0,
    "diagnostics": 10.0,
    "tf": 2.0,
}
# The WSL2 wall clock can step backwards by about a second; a fact received "in the future" by more
# than this is not trusted.
FUTURE_TOLERANCE_S = 1.5

POLICY_VERSION = "readiness-policy/1"
