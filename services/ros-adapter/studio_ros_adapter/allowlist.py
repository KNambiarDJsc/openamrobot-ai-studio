"""The adapter's complete ROS surface. Anything not listed here cannot be subscribed or called.

Topics are subscribed (read). Services are called only if their type is a pure query. There is no
publisher, no action client and no parameter client anywhere in the adapter; tests/test_read_only.py
checks this file and the adapter's source.

Sources (docs/discovery.md):
  /joint_states, controller_manager    openamr-upperbody-sw  mock.launch.py / sim.launch.py
  /navigation/status, /diagnostics     openamr-platform-sw   navigation_status_node.py
  <nav2 node>/get_state                openamr-platform-sw   MANAGED_NAV_NODES
"""
from __future__ import annotations

import re

TOPICS: dict[str, tuple[str, str]] = {
    # topic: (message type, observation kind)
    "/joint_states": ("sensor_msgs/msg/JointState", "joint_state"),
    "/diagnostics": ("diagnostic_msgs/msg/DiagnosticArray", "diagnostics"),
    "/tf": ("tf2_msgs/msg/TFMessage", "tf"),
    "/tf_static": ("tf2_msgs/msg/TFMessage", "tf"),
    "/navigation/status": ("openamr_nav_msgs/msg/NavigationStatus", "navigation_status"),
}

NAV2_MANAGED_NODES = (
    "amcl", "planner_server", "controller_server", "smoother_server", "bt_navigator",
    "behavior_server", "waypoint_follower", "velocity_smoother", "map_server", "collision_monitor",
)

# Query-only service types. A service is callable only if its name matches and its type is listed.
READ_ONLY_SERVICE_TYPES = {
    "controller_manager_msgs/srv/ListControllers",
    "lifecycle_msgs/srv/GetState",
}
SERVICES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^/controller_manager/list_controllers$"), "controller_manager_msgs/srv/ListControllers"),
    (re.compile(r"^/(%s)/get_state$" % "|".join(NAV2_MANAGED_NODES)), "lifecycle_msgs/srv/GetState"),
]

# Never allowed, whatever the allowlist says (defence in depth for a future edit).
DENIED_TYPES = {
    "controller_manager_msgs/srv/SwitchController", "controller_manager_msgs/srv/LoadController",
    "controller_manager_msgs/srv/UnloadController", "controller_manager_msgs/srv/ConfigureController",
    "lifecycle_msgs/srv/ChangeState", "rcl_interfaces/srv/SetParameters",
    "rcl_interfaces/srv/SetParametersAtomically", "geometry_msgs/msg/Twist",
    "trajectory_msgs/msg/JointTrajectory", "control_msgs/action/FollowJointTrajectory",
    "nav2_msgs/action/NavigateToPose",
}


class NotAllowed(PermissionError):
    pass


def check_topic(topic: str, msg_type: str) -> str:
    if msg_type in DENIED_TYPES:
        raise NotAllowed(f"{msg_type} is denied")
    entry = TOPICS.get(topic)
    if entry is None or entry[0] != msg_type:
        raise NotAllowed(f"topic {topic} ({msg_type}) is not on the allowlist")
    return entry[1]


def check_service(service: str, srv_type: str) -> None:
    if srv_type in DENIED_TYPES or srv_type not in READ_ONLY_SERVICE_TYPES:
        raise NotAllowed(f"service type {srv_type} is not a read-only query")
    if not any(rx.match(service) and t == srv_type for rx, t in SERVICES):
        raise NotAllowed(f"service {service} ({srv_type}) is not on the allowlist")
