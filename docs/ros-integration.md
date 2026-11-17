# Running against a real ROS 2 graph

The adapter runs where ROS 2 Jazzy is installed (Linux or WSL2). The API and web app can run on another
machine and poll it over HTTP.

## 1. Start the robot stack (unchanged upstream launch files)

```bash
source /opt/ros/jazzy/setup.bash
source ~/oar_ws/install/setup.bash          # overlay with openamr-upperbody-sw built
ros2 launch openamrobot_upperbody_bringup mock.launch.py      # or openamrobot_upperbody_gazebo sim.launch.py
```

For navigation readiness, also run platform-sw bringup, which provides `navigation_status_node`, and build `openamr_nav_msgs` into the overlay. Without them, navigation reads UNKNOWN. That is correct, because the Studio has no evidence.

## 2. Start the read-only adapter

```bash
cd /path/to/openamrobot-ai-studio
ROBOT_STACK_REVISION="upperbody-sw $(git -C ~/oar_ws/src/openamr-upperbody-sw rev-parse --short HEAD)" \
PYTHONPATH=services/ros-adapter python3 -m studio_ros_adapter.server --host 127.0.0.1 --port 8765
curl -s localhost:8765/health; curl -s localhost:8765/allowlist
```

The adapter uses only the stdlib and `rclpy`; nothing is pip-installed into the ROS environment. Under WSL2, a port bound to `127.0.0.1` in WSL is reachable from Windows as `localhost`.

## 3. Point the API at it

```powershell
$env:STUDIO_MODE="live"; $env:ADAPTER_URL="http://127.0.0.1:8765"; $env:STUDIO_SUBSYSTEMS="upper_body"
.\scripts\dev.ps1
```

Set `STUDIO_SUBSYSTEMS=upper_body` when only the upper body is running. Otherwise the overall status is UNKNOWN, because there is no navigation evidence.

## 4. Automated live check

```bash
OVERLAY=~/oar_ws/install bash tests/ros/run_mock_integration.sh    # on the ROS machine
ADAPTER_URL=http://127.0.0.1:8765 pytest -m ros tests/ros            # from the Studio venv
```

The script:
- launches `mock.launch.py` on an isolated `ROS_DOMAIN_ID` (73);
- waits for all six controllers to be active and for all 17 joints on `/joint_states`;
- writes the adapter snapshot to `fixtures/recorded/`.

`python scripts/make_fixtures.py --base fixtures/recorded/<file>.json` then rebuilds the demo fixtures on that recording, and their provenance says so.

## Status of this integration

**Not yet executed.** The adapter's ROS-independent code is unit-tested (conversion, snapshot shape, allowlist, HTTP read-only). The `rclpy` part (`node.py`) has not run against a live graph from this repository yet: the WSL2 distro on the development machine did not respond while this slice was built. Until `run_mock_integration.sh` passes, treat live mode as unverified.
