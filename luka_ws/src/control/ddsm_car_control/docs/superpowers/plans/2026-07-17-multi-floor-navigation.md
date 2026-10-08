# 半自动多层地图导航实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在现有单层 `auto_nav` 基础上新增半自动跨楼层导航：用户只发一个目的地 ID/名称，机器人自动去当前楼层默认电梯口，等待人工确认到达目标楼层后切换地图、发布目标楼层电梯出口初始位姿，再继续导航到目标点。

**架构：** 新增 `ddsm_multifloor_manager` 作为单层导航之上的任务编排层，读取多层 YAML 配置并通过现有 `/hotel/goal_destination`、`/hotel/mission/*` 控制单层导航。跨楼层切换采用脚本化重启：状态先持久化，再用 `restart_nav_reset.sh` 加载目标楼层地图，重启后管理器恢复任务并发布目标楼层固定电梯出口初始位姿。

**技术栈：** ROS 2 Jazzy、rclpy、std_msgs、geometry_msgs/PoseWithCovarianceStamped、YAML、现有 `ddsm_mission_control`、现有 `hotel_named_navigation_server`、现有 `restart_nav_reset.sh`。

---

## 文件结构

- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/ddsm_car_control/ddsm_multifloor_manager.py`
  - 职责：加载多层配置、解析跨楼层目标、编排状态机、发布状态、发起单层导航、处理人工到达目标楼层确认、执行地图切换恢复。
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/config/multifloor_building.yaml`
  - 职责：描述楼层、地图、语义地图、默认电梯、每层电梯入口目标点、每层电梯出口 initialpose、全楼目的地索引。
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_multifloor_manager.py`
  - 职责：覆盖配置解析、同楼层/跨楼层任务规划、状态持久化、状态 JSON、initialpose 生成。
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/setup.py`
  - 职责：安装 `ddsm_multifloor_manager` console script。
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/package.xml`
  - 职责：确认依赖 `geometry_msgs`、`std_msgs`、`PyYAML` 由当前包可用。
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/launch/ddsm_bringup.launch.py`
  - 职责：新增多层导航启动参数，并在 `nav/auto_nav` 下启动 `ddsm_multifloor_manager`。
- 修改：`/home/terry/ddsm_car_ws/restart_nav_reset.sh`
  - 职责：传入多层导航参数，停止旧 `ddsm_multifloor_manager` 进程，允许用 `MAP=` 切换楼层地图。
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_unified_launch_packaging.py`
  - 职责：验证 launch 暴露并启动多层导航管理器。
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_one_click_nav_startup.py`
  - 职责：验证一键脚本包含多层导航参数。

---

### 任务 1：多层配置模型和任务规划

**文件：**
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_multifloor_manager.py`
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/ddsm_car_control/ddsm_multifloor_manager.py`

- [ ] **步骤 1：编写失败的配置解析测试**

在 `test_multifloor_manager.py` 写入：

```python
from pathlib import Path

from ddsm_car_control.ddsm_multifloor_manager import (
    load_building_config,
    plan_floor_mission,
)


def test_load_building_config_resolves_destination_floor(tmp_path):
    config = tmp_path / "multifloor.yaml"
    config.write_text(
        """
building_id: hotel_a
current_floor_id: F1
default_elevator_id: elevator_A
floors:
  F1:
    map: maps/floor_1.yaml
    semantic_map: semantic/floor_1.yaml
    elevator_poses:
      elevator_A:
        entry_destination_id: f1_elevator_A_entry
        exit_initial_pose: {x: 1.0, y: 2.0, yaw: 1.57}
  F2:
    map: maps/floor_2.yaml
    semantic_map: semantic/floor_2.yaml
    elevator_poses:
      elevator_A:
        entry_destination_id: f2_elevator_A_entry
        exit_initial_pose: {x: 3.0, y: 4.0, yaw: 3.14}
destinations:
  room_203:
    floor_id: F2
    destination_id: f2_room_203
""",
        encoding="utf-8",
    )

    building = load_building_config(config)
    mission = plan_floor_mission(building, "room_203")

    assert mission.current_floor_id == "F1"
    assert mission.target_floor_id == "F2"
    assert mission.elevator_entry_destination_id == "f1_elevator_A_entry"
    assert mission.final_destination_id == "f2_room_203"
    assert Path(mission.target_map).as_posix() == "maps/floor_2.yaml"
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd /home/terry/ddsm_car_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
python3 -m pytest src/ddsm_car_control/test/test_multifloor_manager.py -q
```

预期：失败，提示 `ModuleNotFoundError: No module named 'ddsm_car_control.ddsm_multifloor_manager'`。

- [ ] **步骤 3：实现配置 dataclass 和规划函数**

在 `ddsm_multifloor_manager.py` 添加：

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import yaml


@dataclass(frozen=True)
class InitialPose:
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class ElevatorPose:
    entry_destination_id: str
    exit_initial_pose: InitialPose


@dataclass(frozen=True)
class FloorConfig:
    floor_id: str
    map: str
    semantic_map: str
    elevator_poses: Dict[str, ElevatorPose]


@dataclass(frozen=True)
class DestinationConfig:
    floor_id: str
    destination_id: str
    display_name: str = ""


@dataclass(frozen=True)
class BuildingConfig:
    building_id: str
    current_floor_id: str
    default_elevator_id: str
    floors: Dict[str, FloorConfig]
    destinations: Dict[str, DestinationConfig]


@dataclass(frozen=True)
class FloorMissionPlan:
    requested_destination_id: str
    current_floor_id: str
    target_floor_id: str
    final_destination_id: str
    elevator_id: str
    elevator_entry_destination_id: str
    target_map: str
    target_exit_initial_pose: InitialPose


def load_building_config(path: str | Path) -> BuildingConfig:
    data = yaml.safe_load(Path(path).expanduser().read_text(encoding="utf-8")) or {}
    floors = {}
    for floor_id, floor_data in data.get("floors", {}).items():
        elevators = {}
        for elevator_id, elevator_data in floor_data.get("elevator_poses", {}).items():
            pose = elevator_data["exit_initial_pose"]
            elevators[elevator_id] = ElevatorPose(
                entry_destination_id=str(elevator_data["entry_destination_id"]),
                exit_initial_pose=InitialPose(
                    x=float(pose["x"]),
                    y=float(pose["y"]),
                    yaw=float(pose["yaw"]),
                ),
            )
        floors[floor_id] = FloorConfig(
            floor_id=floor_id,
            map=str(floor_data["map"]),
            semantic_map=str(floor_data.get("semantic_map", "")),
            elevator_poses=elevators,
        )
    destinations = {
        key: DestinationConfig(
            floor_id=str(value["floor_id"]),
            destination_id=str(value["destination_id"]),
            display_name=str(value.get("display_name", "")),
        )
        for key, value in data.get("destinations", {}).items()
    }
    return BuildingConfig(
        building_id=str(data["building_id"]),
        current_floor_id=str(data["current_floor_id"]),
        default_elevator_id=str(data["default_elevator_id"]),
        floors=floors,
        destinations=destinations,
    )


def plan_floor_mission(building: BuildingConfig, destination_key: str) -> FloorMissionPlan:
    destination = building.destinations[destination_key]
    elevator_id = building.default_elevator_id
    current_floor = building.floors[building.current_floor_id]
    target_floor = building.floors[destination.floor_id]
    return FloorMissionPlan(
        requested_destination_id=destination_key,
        current_floor_id=building.current_floor_id,
        target_floor_id=destination.floor_id,
        final_destination_id=destination.destination_id,
        elevator_id=elevator_id,
        elevator_entry_destination_id=current_floor.elevator_poses[elevator_id].entry_destination_id,
        target_map=target_floor.map,
        target_exit_initial_pose=target_floor.elevator_poses[elevator_id].exit_initial_pose,
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
cd /home/terry/ddsm_car_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
python3 -m pytest src/ddsm_car_control/test/test_multifloor_manager.py -q
```

预期：`1 passed`。

- [ ] **步骤 5：Commit**

```bash
cd /home/terry/ddsm_car_ws
git add src/ddsm_car_control/ddsm_car_control/ddsm_multifloor_manager.py src/ddsm_car_control/test/test_multifloor_manager.py
git commit -m "feat: add multifloor mission config model"
```

---

### 任务 2：状态持久化和 Foxglove 状态输出

**文件：**
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/ddsm_car_control/ddsm_multifloor_manager.py`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_multifloor_manager.py`

- [ ] **步骤 1：编写失败的状态测试**

在 `test_multifloor_manager.py` 追加：

```python
from ddsm_car_control.ddsm_multifloor_manager import (
    FloorMissionState,
    dump_floor_state,
    load_floor_state,
    make_status_json,
)


def test_floor_state_round_trip_and_status_json(tmp_path):
    state_file = tmp_path / "floor_state.yaml"
    state = FloorMissionState(
        state="waiting_floor_transfer",
        current_floor_id="F1",
        target_floor_id="F2",
        requested_destination_id="room_203",
        final_destination_id="f2_room_203",
        target_map="maps/floor_2.yaml",
        instruction="请将机器人移动到 F2 电梯出口后点击继续",
    )

    dump_floor_state(state_file, state)
    loaded = load_floor_state(state_file)
    status = make_status_json(loaded)

    assert loaded == state
    assert '"state":"waiting_floor_transfer"' in status
    assert '"target_floor":"F2"' in status
    assert "请将机器人移动到 F2 电梯出口后点击继续" in status
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest src/ddsm_car_control/test/test_multifloor_manager.py::test_floor_state_round_trip_and_status_json -q
```

预期：失败，提示缺少 `FloorMissionState` 或相关函数。

- [ ] **步骤 3：实现状态模型**

在 `ddsm_multifloor_manager.py` 添加：

```python
import json


@dataclass(frozen=True)
class FloorMissionState:
    state: str = "idle"
    current_floor_id: str = ""
    target_floor_id: str = ""
    requested_destination_id: str = ""
    final_destination_id: str = ""
    elevator_id: str = ""
    target_map: str = ""
    instruction: str = ""


def dump_floor_state(path: str | Path, state: FloorMissionState) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(state.__dict__, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_floor_state(path: str | Path) -> FloorMissionState:
    source = Path(path).expanduser()
    if not source.exists():
        return FloorMissionState()
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    return FloorMissionState(**{key: str(value) for key, value in data.items()})


def make_status_json(state: FloorMissionState) -> str:
    return json.dumps(
        {
            "state": state.state,
            "current_floor": state.current_floor_id,
            "target_floor": state.target_floor_id,
            "destination_id": state.requested_destination_id,
            "final_destination_id": state.final_destination_id,
            "instruction": state.instruction,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：

```bash
python3 -m pytest src/ddsm_car_control/test/test_multifloor_manager.py -q
```

预期：全部通过。

- [ ] **步骤 5：Commit**

```bash
git add src/ddsm_car_control/ddsm_car_control/ddsm_multifloor_manager.py src/ddsm_car_control/test/test_multifloor_manager.py
git commit -m "feat: persist multifloor mission state"
```

---

### 任务 3：实现半自动跨楼层管理节点

**文件：**
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/ddsm_car_control/ddsm_multifloor_manager.py`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_multifloor_manager.py`

- [ ] **步骤 1：编写 initialpose 生成测试**

在测试文件追加：

```python
import math

from ddsm_car_control.ddsm_multifloor_manager import InitialPose, make_initialpose_msg


def test_make_initialpose_msg_uses_map_frame_and_yaw():
    msg = make_initialpose_msg(InitialPose(x=1.0, y=2.0, yaw=math.pi))

    assert msg.header.frame_id == "map"
    assert msg.pose.pose.position.x == 1.0
    assert msg.pose.pose.position.y == 2.0
    assert abs(msg.pose.pose.orientation.z - 1.0) < 1e-6
    assert abs(msg.pose.pose.orientation.w) < 1e-6
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest src/ddsm_car_control/test/test_multifloor_manager.py::test_make_initialpose_msg_uses_map_frame_and_yaw -q
```

预期：失败，提示缺少 `make_initialpose_msg`。

- [ ] **步骤 3：实现 initialpose 消息生成**

在 `ddsm_multifloor_manager.py` 添加：

```python
import math

from geometry_msgs.msg import PoseWithCovarianceStamped


def make_initialpose_msg(pose: InitialPose) -> PoseWithCovarianceStamped:
    message = PoseWithCovarianceStamped()
    message.header.frame_id = "map"
    message.pose.pose.position.x = pose.x
    message.pose.pose.position.y = pose.y
    message.pose.pose.orientation.z = math.sin(pose.yaw * 0.5)
    message.pose.pose.orientation.w = math.cos(pose.yaw * 0.5)
    message.pose.covariance[0] = 0.05
    message.pose.covariance[7] = 0.05
    message.pose.covariance[35] = 0.10
    return message
```

- [ ] **步骤 4：实现 ROS 节点接口**

在同文件添加 `DDSMFloorMissionManager`：

```python
import os
import subprocess

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Empty, String


class DDSMFloorMissionManager(Node):
    def __init__(self) -> None:
        super().__init__("ddsm_multifloor_manager")
        self.declare_parameter("building_config_file", "/home/terry/ddsm_car_ws/src/ddsm_car_control/config/multifloor_building.yaml")
        self.declare_parameter("state_file", "/home/terry/ddsm_car_ws/config/floor_mission_state.yaml")
        self.declare_parameter("goal_topic", "/hotel/floor_goal")
        self.declare_parameter("arrived_topic", "/hotel/floor_transfer/arrived")
        self.declare_parameter("cancel_topic", "/hotel/floor_mission/cancel")
        self.declare_parameter("status_topic", "/hotel/floor_mission/status")
        self.declare_parameter("single_floor_goal_topic", "/hotel/goal_destination")
        self.declare_parameter("mission_cancel_service", "/hotel/mission/cancel_now")
        self.declare_parameter("restart_script", "/home/terry/ddsm_car_ws/restart_nav_reset.sh")

        self.config_file = Path(str(self.get_parameter("building_config_file").value)).expanduser()
        self.state_file = Path(str(self.get_parameter("state_file").value)).expanduser()
        self.restart_script = str(self.get_parameter("restart_script").value)
        self.status_pub = self.create_publisher(String, str(self.get_parameter("status_topic").value), 10)
        self.single_floor_goal_pub = self.create_publisher(String, str(self.get_parameter("single_floor_goal_topic").value), 10)
        self.initialpose_pub = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
        self.goal_sub = self.create_subscription(String, str(self.get_parameter("goal_topic").value), self.on_floor_goal, 10)
        self.arrived_sub = self.create_subscription(Empty, str(self.get_parameter("arrived_topic").value), self.on_transfer_arrived, 10)
        self.cancel_sub = self.create_subscription(Empty, str(self.get_parameter("cancel_topic").value), self.on_cancel, 10)
        self.cancel_client = self.create_client(EmptySrv, str(self.get_parameter("mission_cancel_service").value))
        self.recover_after_restart()
```

- [ ] **步骤 5：实现目标入口**

在类中添加：

```python
    def publish_status(self, state: FloorMissionState) -> None:
        msg = String()
        msg.data = make_status_json(state)
        self.status_pub.publish(msg)
        self.get_logger().info(msg.data)

    def publish_single_floor_goal(self, destination_id: str) -> None:
        msg = String()
        msg.data = destination_id
        self.single_floor_goal_pub.publish(msg)

    def on_floor_goal(self, message: String) -> None:
        destination_key = message.data.strip()
        if not destination_key:
            self.publish_status(FloorMissionState(state="failed", instruction="destination is empty"))
            return
        building = load_building_config(self.config_file)
        plan = plan_floor_mission(building, destination_key)
        if plan.current_floor_id == plan.target_floor_id:
            state = FloorMissionState(
                state="single_floor_navigating",
                current_floor_id=plan.current_floor_id,
                target_floor_id=plan.target_floor_id,
                requested_destination_id=destination_key,
                final_destination_id=plan.final_destination_id,
            )
            dump_floor_state(self.state_file, state)
            self.publish_status(state)
            self.publish_single_floor_goal(plan.final_destination_id)
            return
        state = FloorMissionState(
            state="going_to_elevator",
            current_floor_id=plan.current_floor_id,
            target_floor_id=plan.target_floor_id,
            requested_destination_id=destination_key,
            final_destination_id=plan.final_destination_id,
            elevator_id=plan.elevator_id,
            target_map=plan.target_map,
            instruction=f"正在前往 {plan.current_floor_id} 默认电梯入口",
        )
        dump_floor_state(self.state_file, state)
        self.publish_status(state)
        self.publish_single_floor_goal(plan.elevator_entry_destination_id)
```

- [ ] **步骤 6：实现人工确认后的地图切换**

在类中添加：

```python
    def on_transfer_arrived(self, _message: Empty) -> None:
        state = load_floor_state(self.state_file)
        if state.state not in {"waiting_floor_transfer", "going_to_elevator"}:
            self.publish_status(state)
            return
        switching = FloorMissionState(
            state="switching_map",
            current_floor_id=state.target_floor_id,
            target_floor_id=state.target_floor_id,
            requested_destination_id=state.requested_destination_id,
            final_destination_id=state.final_destination_id,
            elevator_id=state.elevator_id,
            target_map=state.target_map,
            instruction="正在切换目标楼层地图",
        )
        dump_floor_state(self.state_file, switching)
        self.publish_status(switching)
        env = os.environ.copy()
        env["RESTART_FOXGLOVE"] = "0"
        env["MODE"] = "auto_nav"
        env["MAP"] = state.target_map
        subprocess.Popen([self.restart_script], env=env, start_new_session=True)
```

- [ ] **步骤 7：实现重启后的恢复**

在类中添加：

```python
    def recover_after_restart(self) -> None:
        state = load_floor_state(self.state_file)
        if state.state != "switching_map":
            return
        building = load_building_config(self.config_file)
        floor = building.floors[state.current_floor_id]
        pose = floor.elevator_poses[state.elevator_id].exit_initial_pose
        initialpose = make_initialpose_msg(pose)
        initialpose.header.stamp = self.get_clock().now().to_msg()
        for _ in range(5):
            self.initialpose_pub.publish(initialpose)
            time.sleep(0.2)
        resumed = FloorMissionState(
            state="going_to_destination",
            current_floor_id=state.current_floor_id,
            target_floor_id=state.target_floor_id,
            requested_destination_id=state.requested_destination_id,
            final_destination_id=state.final_destination_id,
            elevator_id=state.elevator_id,
            target_map=state.target_map,
            instruction="目标楼层定位已设置，正在前往目的地",
        )
        dump_floor_state(self.state_file, resumed)
        self.publish_status(resumed)
        self.publish_single_floor_goal(resumed.final_destination_id)
```

- [ ] **步骤 8：实现取消和 main**

在文件末尾添加：

```python
    def on_cancel(self, _message: Empty) -> None:
        if self.cancel_client.service_is_ready():
            self.cancel_client.call_async(EmptySrv.Request())
        state = FloorMissionState(state="canceled", instruction="跨楼层任务已取消")
        dump_floor_state(self.state_file, state)
        self.publish_status(state)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DDSMFloorMissionManager()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        node.get_logger().info("multifloor manager stopped")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
```

- [ ] **步骤 9：运行测试验证通过**

运行：

```bash
python3 -m pytest src/ddsm_car_control/test/test_multifloor_manager.py -q
```

预期：全部通过。

- [ ] **步骤 10：Commit**

```bash
git add src/ddsm_car_control/ddsm_car_control/ddsm_multifloor_manager.py src/ddsm_car_control/test/test_multifloor_manager.py
git commit -m "feat: add semi automatic multifloor manager"
```

---

### 任务 4：新增默认多层配置

**文件：**
- 创建：`/home/terry/ddsm_car_ws/src/ddsm_car_control/config/multifloor_building.yaml`

- [ ] **步骤 1：创建配置文件**

写入：

```yaml
building_id: hotel_demo
current_floor_id: F1
default_elevator_id: elevator_A

floors:
  F1:
    map: /home/terry/ddsm_car_ws/maps/floor_1.yaml
    semantic_map: /home/terry/ddsm_car_ws/config/semantic_floor_1.yaml
    elevator_poses:
      elevator_A:
        entry_destination_id: f1_elevator_A_entry
        exit_initial_pose:
          x: 0.0
          y: 0.0
          yaw: 0.0
  F2:
    map: /home/terry/ddsm_car_ws/maps/floor_2.yaml
    semantic_map: /home/terry/ddsm_car_ws/config/semantic_floor_2.yaml
    elevator_poses:
      elevator_A:
        entry_destination_id: f2_elevator_A_entry
        exit_initial_pose:
          x: 0.0
          y: 0.0
          yaw: 0.0

destinations:
  room_203:
    floor_id: F2
    destination_id: f2_room_203
    display_name: 房间203
```

- [ ] **步骤 2：写入现场真实值**

把 `floor_1.yaml`、`floor_2.yaml`、`f1_elevator_A_entry`、`f2_room_203` 替换为现场真实地图和语义点位 ID。第一版不允许缺失默认电梯入口，否则节点应发布 `failed` 状态。

- [ ] **步骤 3：Commit**

```bash
git add src/ddsm_car_control/config/multifloor_building.yaml
git commit -m "config: add multifloor building map"
```

---

### 任务 5：打包和统一启动集成

**文件：**
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/setup.py`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/launch/ddsm_bringup.launch.py`
- 修改：`/home/terry/ddsm_car_ws/restart_nav_reset.sh`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_unified_launch_packaging.py`
- 修改：`/home/terry/ddsm_car_ws/src/ddsm_car_control/test/test_one_click_nav_startup.py`

- [ ] **步骤 1：编写失败的打包测试**

在 `test_unified_launch_packaging.py` 追加断言：

```python
def test_unified_launch_starts_multifloor_manager_for_navigation_modes():
    launch_text = (PACKAGE_ROOT / "launch" / "ddsm_bringup.launch.py").read_text(encoding="utf-8")
    setup_text = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert '"enable_multifloor_manager"' in launch_text
    assert '"multifloor_building_config_file"' in launch_text
    assert 'executable="ddsm_multifloor_manager"' in launch_text
    assert 'enabled_for_mode("enable_multifloor_manager", ["nav", "auto_nav"])' in launch_text
    assert "ddsm_multifloor_manager = ddsm_car_control.ddsm_multifloor_manager:main" in setup_text
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest src/ddsm_car_control/test/test_unified_launch_packaging.py::test_unified_launch_starts_multifloor_manager_for_navigation_modes -q
```

预期：失败，提示缺少 launch 参数或 console script。

- [ ] **步骤 3：修改 setup.py**

在 `entry_points["console_scripts"]` 添加：

```python
"ddsm_multifloor_manager = ddsm_car_control.ddsm_multifloor_manager:main",
```

- [ ] **步骤 4：修改 ddsm_bringup.launch.py**

新增 launch 参数：

```python
enable_multifloor_manager_arg = DeclareLaunchArgument(
    "enable_multifloor_manager",
    default_value="false",
    description="Start semi-automatic multi-floor mission manager",
)
multifloor_building_config_file_arg = DeclareLaunchArgument(
    "multifloor_building_config_file",
    default_value="/home/terry/ddsm_car_ws/src/ddsm_car_control/config/multifloor_building.yaml",
    description="Multi-floor building YAML file",
)
multifloor_state_file_arg = DeclareLaunchArgument(
    "multifloor_state_file",
    default_value="/home/terry/ddsm_car_ws/config/floor_mission_state.yaml",
    description="Persistent multi-floor mission state file",
)
```

新增 Node：

```python
multifloor_manager = Node(
    package="ddsm_car_control",
    executable="ddsm_multifloor_manager",
    name="ddsm_multifloor_manager",
    output="screen",
    parameters=[
        {
            "building_config_file": LaunchConfiguration("multifloor_building_config_file"),
            "state_file": LaunchConfiguration("multifloor_state_file"),
            "goal_topic": "/hotel/floor_goal",
            "arrived_topic": "/hotel/floor_transfer/arrived",
            "cancel_topic": "/hotel/floor_mission/cancel",
            "status_topic": "/hotel/floor_mission/status",
            "single_floor_goal_topic": "/hotel/goal_destination",
            "mission_cancel_service": "/hotel/mission/cancel_now",
            "restart_script": "/home/terry/ddsm_car_ws/restart_nav_reset.sh",
        }
    ],
    condition=enabled_for_mode("enable_multifloor_manager", ["nav", "auto_nav"]),
)
```

把 `multifloor_manager` 加入 `delayed_nav_mission_services` 的启动列表。

- [ ] **步骤 5：修改 restart_nav_reset.sh**

新增环境变量：

```bash
ENABLE_MULTIFLOOR_MANAGER="${ENABLE_MULTIFLOOR_MANAGER:-false}"
MULTIFLOOR_BUILDING_CONFIG_FILE="${MULTIFLOOR_BUILDING_CONFIG_FILE:-$WS/src/ddsm_car_control/config/multifloor_building.yaml}"
MULTIFLOOR_STATE_FILE="${MULTIFLOOR_STATE_FILE:-$WS/config/floor_mission_state.yaml}"
```

停止进程 patterns 增加：

```python
'/home/terry/ddsm_car_ws/install/ddsm_car_control/lib/ddsm_car_control/ddsm_multifloor_manager',
'ddsm_multifloor_manager',
```

launch 命令追加：

```bash
enable_multifloor_manager:='$ENABLE_MULTIFLOOR_MANAGER' multifloor_building_config_file:='$MULTIFLOOR_BUILDING_CONFIG_FILE' multifloor_state_file:='$MULTIFLOOR_STATE_FILE'
```

- [ ] **步骤 6：运行测试验证通过**

运行：

```bash
python3 -m pytest src/ddsm_car_control/test/test_unified_launch_packaging.py src/ddsm_car_control/test/test_one_click_nav_startup.py -q
```

预期：全部通过。

- [ ] **步骤 7：Commit**

```bash
git add src/ddsm_car_control/setup.py src/ddsm_car_control/launch/ddsm_bringup.launch.py restart_nav_reset.sh src/ddsm_car_control/test/test_unified_launch_packaging.py src/ddsm_car_control/test/test_one_click_nav_startup.py
git commit -m "feat: launch multifloor mission manager"
```

---

### 任务 6：非运动验证和启动命令

**文件：**
- 不新增文件。

- [ ] **步骤 1：构建**

运行：

```bash
cd /home/terry/ddsm_car_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select ddsm_car_control
```

预期：`Summary: 1 package finished`。

- [ ] **步骤 2：运行测试**

运行：

```bash
cd /home/terry/ddsm_car_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
python3 -m pytest \
  src/ddsm_car_control/test/test_multifloor_manager.py \
  src/ddsm_car_control/test/test_unified_launch_packaging.py \
  src/ddsm_car_control/test/test_one_click_nav_startup.py \
  -q
```

预期：全部通过。

- [ ] **步骤 3：启动半自动多层模式**

运行：

```bash
RESTART_FOXGLOVE=0 MODE=auto_nav ENABLE_MULTIFLOOR_MANAGER=true /home/terry/ddsm_car_ws/restart_nav_reset.sh
```

预期：Foxglove 不重启，`/ddsm_multifloor_manager` 出现在节点列表中。

- [ ] **步骤 4：检查 topic**

运行：

```bash
source /opt/ros/jazzy/setup.bash
source /home/terry/ddsm_car_ws/install/setup.bash
ros2 topic list | grep -E '/hotel/floor_goal|/hotel/floor_transfer/arrived|/hotel/floor_mission/status'
```

预期输出包含：

```text
/hotel/floor_goal
/hotel/floor_transfer/arrived
/hotel/floor_mission/status
```

- [ ] **步骤 5：Foxglove 操作方式**

发布跨楼层目的地：

```bash
ros2 topic pub --once -w 0 /hotel/floor_goal std_msgs/msg/String "{data: room_203}"
```

人工到达目标楼层电梯出口后确认：

```bash
ros2 topic pub --once -w 0 /hotel/floor_transfer/arrived std_msgs/msg/Empty "{}"
```

取消跨楼层任务：

```bash
ros2 topic pub --once -w 0 /hotel/floor_mission/cancel std_msgs/msg/Empty "{}"
```

观察状态：

```bash
ros2 topic echo /hotel/floor_mission/status
```

- [ ] **步骤 6：Commit 验证文档或参数修正**

如果验证过程中只修改了 `multifloor_building.yaml` 的现场点位，提交：

```bash
git add src/ddsm_car_control/config/multifloor_building.yaml
git commit -m "config: tune multifloor hotel points"
```

---

## 自检结果

- 规格覆盖：已覆盖每层独立地图、默认电梯、目标只发一个 ID、到电梯口暂停、人工确认、固定电梯出口 initialpose、脚本化切图、单点优先且预留多点。
- 范围控制：第一版不接入真实电梯控制、不做多电梯选择、不做动态 `load_map`，避免一次性扩大到全自动。
- 可验证性：每个核心行为都有测试入口；现场运动前可以先完成构建、topic、状态 JSON、launch 参数验证。
