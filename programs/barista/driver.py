"""연결 계층 — 컨트롤러는 이 클래스의 함수만 부른다.

지금은 시뮬레이션(SimDriver). 실물 로봇팔을 쓰면 같은 함수 이름으로 RealDriver를 만들어 바꿔 끼운다.
  move_to / grip / move_joints / home  → 실물: LeRobot 서보 드라이버 (미확인 — 하드웨어 시험 전)
  holding()                           → 실물: 집게 서보 위치 또는 전류값
  cup_at(자리)                        → 실물: 자리별 무게 센서(로드셀)나 카메라
  machine_start(…)                    → 실물: 커피머신 통신(시리얼·HTTP). 시뮬레이션은 컵 윗면 색을 바꿔 흉내
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robot import Arm  # noqa: E402
from perception import find_cup_near  # noqa: E402

LOOK_POSE = [1.9, -3.32, 3.11, 1.18, 0]  # 팔을 접고 옆(빈 쪽)으로 돌려 위 카메라를 가리지 않는 자세. 회전 0이면 접힌 팔이 에스프레소 자리를 가림(2026-10-02)

CUP_OPEN = 0.35   # 컵(지름 3cm)에 맞춘 벌림 — 턱 사이 약 4.4cm. 0.45(5cm)는 어긋난 옆 컵을 쳐서 넘어뜨림(2026-10-02 실패 분석)
GRIP_HOLD = 0.05  # 집게 각도가 이보다 크면 무언가 쥐고 있음 (빈 손 -0.11, 컵 0.18 — 2026-10-02 측정)
FILL = {"empty": (0.98, 0.98, 0.97, 1), "espresso": (0.24, 0.13, 0.06, 1), "latte": (0.78, 0.6, 0.42, 1)}


class SimDriver:
    def __init__(self, view=False):
        self.arm = Arm("scene_barista.xml", view=view)
        self.m, self.d = self.arm.m, self.arm.d
        self.cups = [f"cup{i}" for i in (1, 2, 3)]
        self.folded = False

    # ---- 움직이기 ----
    def move_to(self, xyz, seconds=1.0):
        if self.folded:  # 접힌 자세에서 바로 뻗으면 팔이 낮게 휘둘러 컵을 칠 수 있음 → 먼저 준비 자세로 세움(2026-10-02)
            self.arm.home(0.8)
            self.folded = False
        return self.arm.move_to(xyz, seconds)

    def move_open_to(self, xyz, seconds=1.0):
        """집게를 연 채로, 「닫았을 때의 집는 점」이 xyz에 오도록 이동.
        이 집게는 한쪽 턱이 경첩으로 벌어져서, 열린 상태의 두 턱 가운데는 위·옆으로 4cm 넘게 벗어난다(2026-10-02 발견).
        그래서 역기구학은 턱을 닫은 모양으로 풀고, 실제로는 연 채로 그 관절각으로 간다."""
        if self.folded:
            self.arm.home(0.8)
            self.folded = False
        import mujoco
        ja = self.m.joint("Jaw").qposadr[0]
        keep = self.d.qpos[ja]
        self.d.qpos[ja] = -0.1          # 계산할 때만 닫힌 모양 (컵을 쥐었을 때 각도에 가깝게)
        q, err = self.arm.ik(xyz)
        self.d.qpos[ja] = keep
        mujoco.mj_forward(self.m, self.d)
        self.arm.move_joints(q, seconds)
        return err

    def grip(self, close):
        """컵용 집게: 끝까지(1.2, 약 9.5cm) 벌리면 옆 칸 컵을 쳐서 끌고 감(2026-10-02) → CUP_OPEN만 벌림"""
        c = self.d.ctrl.copy(); c[5] = -0.15 if close else CUP_OPEN
        self.arm._run(c, 0.6)

    def home(self):
        self.arm.home()
        self.folded = False

    def wait(self, seconds):
        """기다리는 동안에도 시뮬레이션 시간은 흐른다(머신 추출 등)"""
        self.arm._run(self.d.ctrl.copy(), seconds)

    def look(self):
        """보는 자세로 접기 — 머신이 도는 동안 여기서 기다린다(사람·머신과 거리 두기)"""
        if not self.folded:
            self.arm.home(0.6)        # 접을 때도 세운 다음 접기
        self.arm.move_joints(LOOK_POSE, 0.8)
        self.folded = True

    # ---- 센서 ----
    def find_cup(self, spot):
        """위 카메라 사진으로 spot 근처 컵 중심(m). 팔이 보는 자세여야 함. 실물: USB 카메라"""
        return find_cup_near(self.arm.camera_image("top"), self.spot(spot)[:2])

    def tip(self):
        """손끝 위치 (실물: 관절 각도로 순기구학 계산)"""
        return self.arm.tip()

    def holding(self):
        return float(self.d.qpos[self.m.joint("Jaw").qposadr[0]]) > GRIP_HOLD

    def spot(self, name):
        return self.arm.site(name)

    def cup_at(self, name, radius=0.015):
        """그 자리에 컵이 있나 (실물: 무게 센서). 시뮬레이션은 정답 위치로 흉내"""
        p = self.spot(name)[:2]
        for c in self.cups:
            q = self.d.xpos[self.m.body(c).id]
            if np.linalg.norm(q[:2] - p) < radius and q[2] < 0.035:
                return c
        return None

    # ---- 장비 ----
    def machine_fill(self, cup, kind):
        """머신이 다 내렸을 때 컵 윗면 색 (실물에서는 머신이 알아서 함)"""
        self.m.geom_rgba[self.m.geom(f"{cup}_fill").id] = FILL[kind]

    # ---- 시험용(시뮬레이션에만) ----
    def place_cups(self, offsets):
        """컵 보관대 자리를 조금씩 어긋나게(현장에서 사람이 대충 채워 넣은 상황)"""
        self.arm.reset(objects={})
        for c, (dx, dy) in zip(self.cups, offsets):
            a = self.m.joint(c).qposadr[0]
            base = self.arm.site("rack" + c[-1])
            self.d.qpos[a:a + 7] = [base[0] + dx, base[1] + dy, 0.02, 1, 0, 0, 0]
            self.machine_fill(c, "empty")
        import mujoco
        mujoco.mj_forward(self.m, self.d)

    def take_away(self, cup):
        """손님이 픽업대에서 컵을 가져감 → 작업대 밖으로"""
        a = self.m.joint(cup).qposadr[0]
        self.d.qpos[a:a + 7] = [0.6, 0.6, 0.02, 1, 0, 0, 0]
        self.d.qvel[self.m.joint(cup).dofadr[0]:self.m.joint(cup).dofadr[0] + 6] = 0
