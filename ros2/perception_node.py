"""인식 노드 — 사진을 받아 큐브 위치를 발행한다 (programs/perception.py를 그대로 씀).
  구독 /camera/top/image_raw  sensor_msgs/Image
  발행 /cubes                 std_msgs/String(JSON)  [{"color", "x", "y", "z"}]
"""
import json
import sys
from pathlib import Path

import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "programs"))
from perception import find_cubes  # noqa: E402


class PerceptionNode(Node):
    def __init__(self):
        super().__init__("perception")
        self.pub = self.create_publisher(String, "/cubes", 10)
        self.create_subscription(Image, "/camera/top/image_raw", self.on_image, 1)
        self.get_logger().info("인식 노드 준비")

    def on_image(self, msg):
        img = np.frombuffer(bytes(msg.data), dtype=np.uint8).reshape(msg.height, msg.width, 3)
        cubes = [{"color": c["color"], "x": float(c["xyz"][0]), "y": float(c["xyz"][1]), "z": float(c["xyz"][2])}
                 for c in find_cubes(img)]
        self.pub.publish(String(data=json.dumps(cubes)))
        self.get_logger().info(f"큐브 {len(cubes)}개: " + ", ".join(
            f"{c['color']}({c['x'] * 100:.1f},{c['y'] * 100:.1f})cm" for c in cubes))


def main():
    rclpy.init()
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
