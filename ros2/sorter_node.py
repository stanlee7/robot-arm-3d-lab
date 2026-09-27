"""분류 작업 노드 — 판단 담당. 로봇 내부를 모르고 ROS 2 메시지로만 일을 시킨다.
보는 자세 → 촬영 → /cubes 받기 → 큐브마다 이동·집기·놓기 → 결과를 정답과 비교해 채점.
"""
import json
import threading
import time

import numpy as np
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from geometry_msgs.msg import Point
from std_msgs.msg import String
from std_srvs.srv import SetBool, Trigger

HOVER, LIFT, PLACE = 0.08, 0.09, 0.03


class SorterNode(Node):
    def __init__(self):
        super().__init__("sorter")
        self.goal = self.create_publisher(Point, "/arm/goal_point", 10)
        self.grip_cli = self.create_client(SetBool, "/gripper/close")
        self.look_cli = self.create_client(Trigger, "/arm/look_pose")
        self.cap_cli = self.create_client(Trigger, "/camera/capture")
        self.result, self.cubes, self.truth = None, None, None
        self.ev_res, self.ev_cubes = threading.Event(), threading.Event()
        self.create_subscription(String, "/arm/result", self._on_res, 10)
        self.create_subscription(String, "/cubes", self._on_cubes, 10)
        self.create_subscription(String, "/sim/ground_truth", self._on_truth, 1)

    def _on_res(self, m):
        self.result = json.loads(m.data)
        self.ev_res.set()

    def _on_cubes(self, m):
        self.cubes = json.loads(m.data)
        self.ev_cubes.set()

    def _on_truth(self, m):
        self.truth = json.loads(m.data)

    def call(self, cli, req):
        if not cli.wait_for_service(timeout_sec=15):
            raise TimeoutError(f"서비스 없음: {cli.srv_name}")
        return cli.call(req)

    def move(self, x, y, z):
        self.ev_res.clear()
        self.goal.publish(Point(x=float(x), y=float(y), z=float(z)))
        if not self.ev_res.wait(90):
            raise TimeoutError("이동 결과 없음")
        return self.result

    def grip(self, close):
        return json.loads(self.call(self.grip_cli, SetBool.Request(data=close)).message)

    def run(self):
        t0 = time.time()
        while self.truth is None and time.time() - t0 < 20:
            time.sleep(0.1)
        bins = self.truth["bins"]
        self.call(self.look_cli, Trigger.Request())
        self.ev_cubes.clear()
        self.call(self.cap_cli, Trigger.Request())
        if not self.ev_cubes.wait(20):
            raise TimeoutError("인식 결과 없음")
        self.get_logger().info(f"받은 큐브 {len(self.cubes)}개")
        for c in sorted(self.cubes, key=lambda c: c["color"]):
            b = bins[c["color"]]
            self.grip(False)
            self.move(c["x"], c["y"], HOVER)
            self.move(c["x"], c["y"], c["z"] + 0.005)
            held = self.grip(True)
            self.move(c["x"], c["y"], LIFT)
            self.move(b[0], b[1], LIFT)
            self.move(b[0], b[1], PLACE)
            self.grip(False)
            r = self.move(b[0], b[1], LIFT)
            self.get_logger().info(f"{c['color']} → 칸 (집게 {held.get('집게')}, 마지막 도달 오차 {r['도달오차_m'] * 100:.1f}cm)")
        self.call(self.look_cli, Trigger.Request())
        time.sleep(0.5)
        ok = 0
        for color in ("red", "blue", "green"):
            d = np.hypot(self.truth[color][0] - bins[color][0], self.truth[color][1] - bins[color][1]) * 100
            ok += d < 3
            self.get_logger().info(f"채점 {color}: 칸 중심까지 {d:.1f}cm {'✓' if d < 3 else '✗'}")
        self.get_logger().info(f"=== 제자리 {ok}/3")
        return ok


def main():
    rclpy.init()
    node = SorterNode()
    ex = MultiThreadedExecutor()
    ex.add_node(node)
    threading.Thread(target=ex.spin, daemon=True).start()
    try:
        node.run()
    finally:
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
