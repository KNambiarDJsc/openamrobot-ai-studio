# studio_ros_adapter

Read-only bridge from a ROS 2 Jazzy graph to AI Studio. Runs in the ROS environment, using the stdlib and `rclpy` only.

```bash
source /opt/ros/jazzy/setup.bash && source <overlay>/install/setup.bash
PYTHONPATH=services/ros-adapter python3 -m studio_ros_adapter.server --host 127.0.0.1 --port 8765
```

| Module | Role |
|---|---|
| `allowlist.py` | the complete ROS surface: 5 topics, 2 query service types, a deny list |
| `snapshot.py` | message conversion and snapshot assembly; no ROS import, unit-tested anywhere |
| `node.py` | `ReadOnlyNode` (subscribe and query only, both checked) and the polling of `list_controllers` and Nav2 `get_state` with 1 s deadlines |
| `server.py` | `GET /snapshot`, `/health`, `/allowlist`; 405 for any other method |

The output follows `oar_contracts.Snapshot`. Freshness is judged by the API on `received_at`; `stamp` is the header stamp, which is sim time under Gazebo. NaN and inf become `null`.
