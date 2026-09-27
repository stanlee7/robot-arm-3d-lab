# ROS 2 버전 — 노드 3개가 메시지로 협업

`programs/sort_by_color.py`와 같은 일을 로봇 업계 표준 방식(ROS 2)으로 나눴습니다. 각 노드는 따로 도는 프로그램이고 **표준 메시지로만** 대화합니다.

```
[perception_node] ←─ /camera/top/image_raw (Image) ─ [arm_sim_node] ←─ /arm/goal_point (Point) · /gripper/close (SetBool) ─ [sorter_node]
        └──────────── /cubes (String JSON) ──────────────────────────────────────────────────────────────→┘
```

| 노드 | 역할 | 실물 로봇이면 |
|---|---|---|
| `arm_sim_node.py` | MuJoCo 로봇팔. `/joint_states` 발행, 이동·집게·보는 자세·촬영 명령 받음 | **이 노드만** 실물 드라이버로 교체 |
| `perception_node.py` | 사진 → 큐브 위치 `/cubes` | 그대로 (카메라만 실물) |
| `sorter_node.py` | 로봇 내부를 모르고 메시지로만 작업 지시, 끝나고 채점 | 그대로 |

결과(2026-09-27, WSL Ubuntu + ROS 2 Jazzy): **3/3** 제자리, 칸 중심까지 0.3~0.8cm.

## 설치 (관리자 권한 없이 — RoboStack)
Windows라면 WSL의 Ubuntu에서:
```bash
mkdir -p ~/ros/bin && cd ~/ros
curl -Lsf -o bin/micromamba https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64 && chmod +x bin/micromamba
MAMBA_ROOT_PREFIX=~/ros/mamba ./bin/micromamba create -y -p ~/ros/env -c conda-forge -c robostack-jazzy \
  python=3.12 ros-jazzy-ros-base ros-jazzy-sensor-msgs ros-jazzy-std-srvs ros-jazzy-geometry-msgs numpy pillow
~/ros/env/bin/python -m pip install mujoco==3.14.0 glfw
```

## 실행
```bash
bash ros2/run_sort.sh          # 노드 3개를 띄워 한 번 분류
```
노드를 따로 띄워 두고 다른 터미널에서 `~/ros/env/bin/ros2 topic list`, `ros2 topic echo /joint_states`로 오가는 메시지를 볼 수 있습니다.

## 고전 방식에서 피지컬 AI로
지금은 사람이 정한 규칙(색 판정, 동작 순서)으로 움직이는 **고전적 로봇 시스템**입니다. 피지컬 AI로 가려면 `perception_node`를 학습된 시각 모델로, `sorter_node`를 카메라 영상 → 관절 명령을 내는 학습된 정책(모방학습·VLA)으로 바꿉니다. ROS 2 구조는 그대로 씁니다.
