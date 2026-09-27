"""SO-ARM100 시뮬레이션 제어 — Claude가 부르는 간단한 로봇 API.

실제 로봇팔 SO-ARM100/101과 같은 관절 구조(MuJoCo Menagerie 모델)를 물리 엔진으로 돌린다.
"""
from pathlib import Path
import time
import mujoco
import numpy as np
from PIL import Image

HERE = Path(__file__).parent
ARM = ["Rotation", "Pitch", "Elbow", "Wrist_Pitch", "Wrist_Roll"]
HOME = [0, -1.57, 1.57, 1.57, -1.57, 0]
JAW_OPEN, JAW_CLOSED = 1.2, -0.15
MAX_JOINT_SPEED = 0.8  # rad/s — 들고 있는 큐브가 빠지지 않는 관절 속도 상한


class Arm:
    def __init__(self, scene="scene.xml", view=False):
        # MuJoCo는 한글 경로 파일을 못 열어서 파일을 메모리로 읽어 넘긴다
        assets = {p.relative_to(HERE).as_posix(): p.read_bytes()
                  for p in HERE.rglob("*") if p.is_file() and p.suffix.lower() in (".xml", ".stl", ".obj", ".png")}
        self.m = mujoco.MjModel.from_xml_string((HERE / scene).read_text(encoding="utf-8"), assets)
        self.d = mujoco.MjData(self.m)
        self.pads = [self.m.geom("fixed_jaw_pad_2").id, self.m.geom("moving_jaw_pad_2").id]
        self.qadr = [self.m.joint(j).qposadr[0] for j in ARM]
        self.dadr = [self.m.joint(j).dofadr[0] for j in ARM]
        self.renderer = None
        self.frames = []
        self.viewer = None
        self.reset()
        if view:  # 실시간 3D 창 — 휠 앞뒤 확대·축소, 휠 누르고 드래그 이동 (viewer.py)
            from viewer import Viewer
            self.viewer = Viewer(self.m, self.d)

    # ---- 상태 ----
    def reset(self, cube=(0.0, -0.25), objects=None):
        """objects: {"cube_red": (x, y), ...} — 여러 물체 장면(scene_sort.xml)에서 자리 지정. 안 주면 장면 파일 자리 그대로"""
        mujoco.mj_resetData(self.m, self.d)
        for i, j in enumerate(ARM + ["Jaw"]):
            self.d.qpos[self.m.joint(j).qposadr[0]] = HOME[i]
        self.d.ctrl[:] = HOME
        if self._has("joint", "cube"):
            objects = dict(objects or {}, cube=cube)
        for name, (x, y) in (objects or {}).items():
            a = self.m.joint(name).qposadr[0]
            self.d.qpos[a:a + 7] = [x, y, 0.015, 1, 0, 0, 0]
        mujoco.mj_forward(self.m, self.d)
        self.frames = []

    def _has(self, kind, name):
        try:
            getattr(self.m, kind)(name); return True
        except KeyError:
            return False

    def objects(self):
        """자유롭게 움직이는 물체(큐브)들의 이름과 위치 — 시뮬레이션의 정답값(프로그램 채점용)"""
        out = {}
        for j in range(self.m.njnt):
            if self.m.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE:
                b = self.m.jnt_bodyid[j]
                out[self.m.body(b).name] = self.d.xpos[b].copy()
        return out

    def site(self, name):
        return self.d.site_xpos[self.m.site(name).id].copy()

    def move_joints(self, q5, seconds=1.0):
        """관절 5개를 직접 지정해 움직이기(라디안). 카메라를 가리지 않는 자세 등에 씀"""
        c = self.d.ctrl.copy(); c[:5] = q5
        self._run(c, seconds)

    def tip(self):
        return (self.d.geom_xpos[self.pads[0]] + self.d.geom_xpos[self.pads[1]]) / 2

    def cube(self, name="cube"):
        return self.d.xpos[self.m.body(name).id].copy()

    def target(self, name="target"):
        return self.d.site_xpos[self.m.site(name).id].copy()

    def state(self):
        if not self._has("body", "cube"):
            return {"tip": self.tip().round(3).tolist(), "objects": {k: v.round(3).tolist() for k, v in self.objects().items()},
                    "joints": {j: round(float(self.d.qpos[self.m.joint(j).qposadr[0]]), 3) for j in ARM + ["Jaw"]}}
        return {"tip": self.tip().round(3).tolist(), "cube": self.cube().round(3).tolist(),
                "target": self.target().round(3).tolist(),
                "joints": {j: round(float(self.d.qpos[self.m.joint(j).qposadr[0]]), 3) for j in ARM + ["Jaw"]}}

    # ---- 계산 ----
    def ik(self, goal, iters=300):
        """여러 시작 자세에서 풀어 가장 가까운 답을 고른다(접힌 자세에서 갇히는 문제 방지)."""
        seeds = [None, HOME[:5], [0, -1.2, 1.2, 1.57, -1.57], [0, -1.8, 2.0, 1.2, -1.57]]
        best = None
        for sd in seeds:
            q, err = self._ik_from(goal, sd, iters)
            if best is None or err < best[1]:
                best = (q, err)
            if err < 1.5e-3:
                break
        return best

    def _ik_from(self, goal, seed, iters):
        """손끝(두 집게 패드의 가운데)을 goal로 보내는 관절각. 실제 상태는 바꾸지 않는다.
        Wrist_Pitch 는 손끝이 아래를 보도록 Pitch·Elbow에 맞춰 둔다."""
        q0 = self.d.qpos.copy()
        d = mujoco.MjData(self.m); d.qpos[:] = q0
        if seed is not None:
            ang = np.arctan2(goal[0], -goal[1]) if seed is not HOME[:5] else 0.0
            for k, a in enumerate(self.qadr):
                d.qpos[a] = seed[k]
            d.qpos[self.qadr[0]] = ang
        goal = np.asarray(goal, float)
        jac = np.zeros((3, self.m.nv)); jr = np.zeros((3, self.m.nv))
        use = self.dadr[:3]
        for _ in range(iters):
            mujoco.mj_forward(self.m, d)
            p = (d.geom_xpos[self.pads[0]] + d.geom_xpos[self.pads[1]]) / 2
            err = goal - p
            if np.linalg.norm(err) < 1e-3:
                break
            J = np.zeros((3, self.m.nv))
            for g in self.pads:
                mujoco.mj_jacGeom(self.m, d, jac, jr, g); J += jac / 2
            Jr = J[:, use]
            dq = Jr.T @ np.linalg.solve(Jr @ Jr.T + 1e-4 * np.eye(3), err)
            for k, a in enumerate(self.qadr[:3]):
                lo, hi = self.m.jnt_range[self.m.joint(ARM[k]).id]
                d.qpos[a] = np.clip(d.qpos[a] + 0.5 * dq[k], lo, hi)
            # 손목: 위팔·아래팔 각도의 합을 상쇄해 집게가 바닥을 보게
            d.qpos[self.qadr[3]] = np.clip(-(d.qpos[self.qadr[1]] + d.qpos[self.qadr[2]]) + 1.57 + 0.0, -1.66, 1.66)
        mujoco.mj_forward(self.m, d)
        p = (d.geom_xpos[self.pads[0]] + d.geom_xpos[self.pads[1]]) / 2
        return [float(d.qpos[a]) for a in self.qadr], float(np.linalg.norm(goal - p))

    # ---- 움직임 ----
    def _run(self, ctrl_to, seconds, record=True):
        start = self.d.ctrl.copy(); n = int(seconds / self.m.opt.timestep)
        for i in range(n):
            a = min(1.0, (i + 1) / (0.8 * n))
            self.d.ctrl[:] = start + (np.asarray(ctrl_to) - start) * a
            mujoco.mj_step(self.m, self.d)
            if self.viewer is not None and i % 8 == 0:  # 실제 시간 속도로 화면 갱신
                if not self.viewer.is_running():
                    raise SystemExit("창이 닫혔습니다")
                self.viewer.sync(); time.sleep(self.m.opt.timestep * 8)
            if record and i % 25 == 0:
                self.frames.append(self.render())

    def move_to(self, xyz, seconds=1.2):
        """IK오차 = 계산상 닿을 수 있는지, 도달오차 = 실제로 움직인 뒤 손끝과 요청의 거리.
        둘이 크게 다르면 무언가(큐브·바닥)에 닿아 멈춘 것 — 2026-09-27 Claude 조종 시험에서 발견"""
        q, err = self.ik(xyz)
        c = self.d.ctrl.copy(); c[:5] = q
        # 속도 제한: 관절이 많이 돌수록 천천히 (2026-09-27 색 분류 실험에서 큰 회전 중 큐브가 빠져나감)
        seconds = max(seconds, float(np.max(np.abs(np.asarray(q) - self.d.qpos[self.qadr]))) / MAX_JOINT_SPEED)
        self._run(c, seconds)
        tip = self.tip()
        reach = float(np.linalg.norm(np.asarray(xyz, float) - tip))
        out = {"요청": [round(float(v), 3) for v in xyz], "도달": tip.round(3).tolist(),
               "IK오차_m": round(err, 4), "도달오차_m": round(reach, 4)}
        if err > 0.01:
            out["비고"] = "팔이 닿지 않는 위치 — 더 가까운 곳으로"
        elif reach > 0.01:
            out["비고"] = "무언가에 닿아 멈춤(큐브·바닥 등). 집을 때는 정상일 수 있음"
        return out

    def grip(self, close=True, seconds=0.6):
        c = self.d.ctrl.copy(); c[5] = JAW_CLOSED if close else JAW_OPEN
        self._run(c, seconds)
        return {"집게": "닫힘" if close else "열림"}

    def home(self, seconds=1.0):
        c = self.d.ctrl.copy(); c[:5] = HOME[:5]
        self._run(c, seconds)

    # ---- 보기 ----
    def render(self, camera="front"):
        if self.renderer is None:
            self.renderer = mujoco.Renderer(self.m, 480, 640)
        self.renderer.update_scene(self.d, camera=camera)
        return self.renderer.render()

    def camera_image(self, camera="top"):
        """카메라 한 장(RGB, 480x640) — 인식 프로그램의 입력. 실물 로봇이면 USB 카메라 사진이 이 자리에 들어감"""
        return self.render(camera)

    def snapshot(self, path, camera="front"):
        Image.fromarray(self.render(camera)).save(path); return str(path)

    def save_gif(self, path, fps=20):
        imgs = [Image.fromarray(f) for f in self.frames]
        imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=int(1000 / fps), loop=0)
        return str(path)
