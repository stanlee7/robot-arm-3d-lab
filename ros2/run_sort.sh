#!/usr/bin/env bash
# ROS 2 노드 3개를 따로 띄워 색깔별 분류를 한 번 돌린다.
# 사용: bash ros2/run_sort.sh [--view]      (ROS_PY로 ROS 2 환경의 python 지정 가능)
set -e
cd "$(dirname "$0")"
PY="${ROS_PY:-$HOME/ros/env/bin/python}"
export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
"$PY" arm_sim_node.py "$@" & A=$!
"$PY" perception_node.py & P=$!
sleep 5
set +e
"$PY" sorter_node.py; R=$?
kill $A $P 2>/dev/null; wait 2>/dev/null
exit $R
