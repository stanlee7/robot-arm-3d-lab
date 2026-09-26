"""MuJoCo 모델 → 웹용 데이터 (web/robot_data.json).

MuJoCo가 컴파일한 그대로(부품 좌표계, 관절 축, 색)를 꺼내므로 웹에서도 같은 모양·같은 움직임이 나온다.
꼭짓점은 부품마다 16비트 정수로 압축(오차 약 0.003mm 이하), 면은 16비트 번호.
검증용으로 무작위 관절각 몇 개에 대한 MuJoCo 정답(손끝·몸체 위치)도 함께 넣는다.
실행: .venv\\Scripts\\python web\\export_model.py
"""
import base64
import json
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sim"))
from robot import Arm, ARM, HOME, JAW_OPEN, JAW_CLOSED  # noqa: E402

a = Arm()
m, d = a.m, a.d
b64 = lambda arr: base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode()
r = lambda v, n=6: [round(float(x), n) for x in v]

bodies = []
for b in range(1, m.nbody):
    if m.body(b).name == "cube":
        continue
    bodies.append({"name": m.body(b).name, "parent": m.body(m.body_parentid[b]).name,
                   "pos": r(m.body_pos[b]), "quat": r(m.body_quat[b])})

joints = []
for j in range(m.njnt):
    if m.jnt_type[j] != mujoco.mjtJoint.mjJNT_HINGE:
        continue
    joints.append({"name": m.joint(j).name, "body": m.body(m.jnt_bodyid[j]).name,
                   "axis": r(m.jnt_axis[j]), "pos": r(m.jnt_pos[j]), "range": r(m.jnt_range[j], 4)})

meshes, mesh_index, geoms = [], {}, []
for g in range(m.ngeom):
    if m.geom_type[g] != mujoco.mjtGeom.mjGEOM_MESH or m.geom_group[g] == 3:  # 3 = 충돌용(안 보임)
        continue
    mid = int(m.geom_dataid[g])
    if mid not in mesh_index:
        va, vn = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        fa, fn = m.mesh_faceadr[mid], m.mesh_facenum[mid]
        v = m.mesh_vert[va:va + vn].astype(np.float64)
        f = m.mesh_face[fa:fa + fn].astype(np.int64)
        assert vn < 65536
        lo, hi = v.min(0), v.max(0)
        scale = np.where(hi - lo > 0, (hi - lo) / 65535.0, 1.0)
        q = np.round((v - lo) / scale).astype(np.uint16)
        mesh_index[mid] = len(meshes)
        meshes.append({"name": m.mesh(mid).name, "min": r(lo, 7), "scale": [float(s) for s in scale],
                       "v": b64(q), "f": b64(f.astype(np.uint16))})
    mat = m.geom_matid[g]
    rgba = m.mat_rgba[mat] if mat >= 0 else m.geom_rgba[g]
    geoms.append({"body": m.body(m.geom_bodyid[g]).name, "mesh": mesh_index[mid],
                  "pos": r(m.geom_pos[g]), "quat": r(m.geom_quat[g]), "rgba": r(rgba, 3)})

pads = {n: {"body": m.body(m.geom_bodyid[m.geom(n).id]).name, "pos": r(m.geom_pos[m.geom(n).id])}
        for n in ["fixed_jaw_pad_1", "fixed_jaw_pad_2", "moving_jaw_pad_1", "moving_jaw_pad_2"]}

# 큐브(한 변 3cm)를 잡을 때 집게 각도: 두 pad_2 사이가 3.2cm가 되는 각
names = ARM + ["Jaw"]
adr = [m.joint(n).qposadr[0] for n in names]
def set_q(q):
    for k, aa in enumerate(adr):
        d.qpos[aa] = q[k]
    mujoco.mj_forward(m, d)
def pad_gap(jaw):
    set_q(HOME[:5] + [jaw])
    return float(np.linalg.norm(d.geom_xpos[m.geom("fixed_jaw_pad_2").id] - d.geom_xpos[m.geom("moving_jaw_pad_2").id]))
grid = np.linspace(-0.174, 1.75, 2000)
gaps = np.array([pad_gap(x) for x in grid])
jaw_grip = float(grid[np.argmin(np.abs(gaps - 0.032))])

# 검증용 정답: 무작위 관절각 → 손끝(pad_2 가운데)·몸체 위치
rng = np.random.default_rng(1)
checks = []
for _ in range(6):
    q = [float(rng.uniform(*m.jnt_range[m.joint(n).id])) for n in names]
    set_q(q)
    tip = (d.geom_xpos[m.geom("fixed_jaw_pad_2").id] + d.geom_xpos[m.geom("moving_jaw_pad_2").id]) / 2
    checks.append({"q": r(q), "tip": r(tip), "bodies": {m.body(b).name: r(d.xpos[b]) for b in range(1, 8)}})

out = {
    "source": "MuJoCo Menagerie trs_so_arm100 (SO-ARM100, Apache-2.0), exported by web/export_model.py",
    "joint_order": names, "home": HOME, "jaw": {"open": JAW_OPEN, "closed": JAW_CLOSED, "grip": round(jaw_grip, 4)},
    "bodies": bodies, "joints": joints, "meshes": meshes, "geoms": geoms, "pads": pads,
    "cube": {"size": 0.03, "start": [0.0, -0.25]}, "target": {"pos": [0.12, -0.2], "radius": 0.03},
    "checks": checks,
}
p = ROOT / "web" / "robot_data.json"
p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"{p.name}: {p.stat().st_size/1024:.0f} KB, 부품 {len(geoms)}개, 메시 {len(meshes)}개, 집게(큐브 잡기) {jaw_grip:.3f} rad")
