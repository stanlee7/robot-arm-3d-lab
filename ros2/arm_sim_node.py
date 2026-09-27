"""로봇팔 노드 — 시뮬레이션 로봇(MuJoCo)을 ROS 2 인터페이스로 감싼다.
실물 로봇이면 이 노드만 실물 드라이버 노드로 바뀌고, 나머지 노드는 그대로다.

주고받는 것 (모두 ROS 2 표준 메시지)
  발행   /joint_states              sensor_msgs/JointState   관절 각도 (10Hz + 동작 뒤)
  발행   /camera/top/image_raw      sensor_msgs/Image        위 카메라 사진 (촬영 요청 때)
  발행   /arm/result                std_msgs/String(JSON)    이동 결과 (요청·도달·도달 오차)
  발행   /sim/ground_truth          std_msgs/String(JSON)    시뮬레이션 정답 위치 — 채점용, 로봇은 쓰지 않음
  구독   /arm/goal_point            geometry_msgs/Point      손끝 목표 (m)
  서비스 /gripper/close             std_srvs/SetBool         true=닫기, false=열기
  서비스 /arm/look_pose             std_srvs/Trigger         카메라를 가리지 않는 자세
  서비스 /camera/capture            std_srvs/Trigger         사진 한 장 찍어 발행
"""
import json
import sys
from pathlib import Path

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from geometry_msgs.msg import Point
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import String
from std_srvs.srv import SetBool, Trigger

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sim"))
from robot import Arm, ARM  # noqa: E402

LOOK_POSE = [0, -3.32, 3.11, 1.18, 0]


class ArmSimNode(Node):
    def __init__(self, view=False):
        super().__init__("arm_sim")
        self.arm = Arm("scene_sort.xml", view=view)
        self.pub_js = self.create_publisher(JointState, "/joint_states", 10)
        self.pub_img = self.create_publisher(Image, "/camera/top/image_raw", 1)
        self.pub_res = self.create_publisher(String, "/arm/result", 10)
        self.pub_gt = self.create_publisher(String, "/sim/ground_truth", 1)
        self.create_subscription(Point, "/arm/goal_point", self.on_goal, 10)
        self.create_service(SetBool, "/gripper/close", self.on_grip)
        self.create_service(Trigger, "/arm/look_pose", self.on_look)
        self.create_service(Trigger, "/camera/capture", self.on_capture)
        self.create_timer(0.1, self.publish_state)
        self.get_logger().info("로봇팔 노드 준비")

    def publish_state(self):
        m = JointState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.name = ARM + ["Jaw"]
        m.position = [float(self.arm.d.qpos[self.arm.m.joint(j).qposadr[0]]) for j in m.name]
        self.pub_js.publish(m)
        gt = {k.replace("cube_", ""): [round(float(v), 4) for v in p] for k, p in self.arm.objects().items()}
        gt["bins"] = {c: [round(float(v), 4) for v in self.arm.site(f"bin_{c}")] for c in ("red", "blue", "green")}
        self.pub_gt.publish(String(data=json.dumps(gt)))
        if self.arm.viewer is not None:
            self.arm.viewer.sync()

    def on_goal(self, msg):
        r = self.arm.move_to((msg.x, msg.y, msg.z))
        self.publish_state()
        self.pub_res.publish(String(data=json.dumps(r, ensure_ascii=False)))

    def on_grip(self, req, res):
        r = self.arm.grip(req.data)
        self.publish_state()
        res.success, res.message = True, json.dumps(r, ensure_ascii=False)
        return res

    def on_look(self, req, res):
        self.arm.move_joints(LOOK_POSE, 1.0)
        self.publish_state()
        res.success, res.message = True, "look pose"
        return res

    def on_capture(self, req, res):
        img = self.arm.camera_image("top")
        m = Image()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = "top_camera"
        m.height, m.width = int(img.shape[0]), int(img.shape[1])
        m.encoding, m.step = "rgb8", int(img.shape[1] * 3)
        m.data = img.tobytes()
        self.pub_img.publish(m)
        res.success, res.message = True, f"{m.width}x{m.height}"
        return res


def main():
    rclpy.init()
    node = ArmSimNode(view="--view" in sys.argv)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    rclpy.try_shutdown()


if __name__ == "__main__":
    main()
