"""색깔별 분류 로봇 — 보기(카메라) → 판단(어느 칸으로) → 움직이기(집어 옮기기).

실행: ..\.venv\Scripts\python programs\sort_by_color.py [--view] [--trials 5]
  --view    실시간 3D 창에서 보기
  --trials  무작위 배치로 여러 번 돌려 정확도 측정

정답값(시뮬레이션이 아는 실제 큐브 위치)은 **채점에만** 쓰고, 로봇은 카메라 사진만 보고 움직인다.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "sim"))
sys.path.insert(0, str(HERE))
from robot import Arm  # noqa: E402
from perception import find_cubes  # noqa: E402

LOOK_POSE = [0, -3.32, 3.11, 1.18, 0]          # 팔을 받침 쪽으로 접어 카메라를 가리지 않는 자세
BINS = {"red": "bin_red", "blue": "bin_blue", "green": "bin_green"}  # 색 → 칸(장면의 site 이름)
HOVER, LIFT, PLACE = 0.08, 0.09, 0.03


def look(arm):
    arm.move_joints(LOOK_POSE, 1.0)
    return find_cubes(arm.camera_image("top"))


def pick_and_place(arm, src, dst):
    arm.grip(False)
    arm.move_to((src[0], src[1], HOVER))
    arm.move_to((src[0], src[1], src[2] + 0.005))
    arm.grip(True)
    arm.move_to((src[0], src[1], LIFT))
    arm.move_to((dst[0], dst[1], LIFT))
    arm.move_to((dst[0], dst[1], PLACE))
    arm.grip(False)
    arm.move_to((dst[0], dst[1], LIFT))


def run_once(arm, log=print):
    seen = look(arm)
    truth = {k.replace("cube_", ""): v for k, v in arm.objects().items()}
    for c in seen:  # 인식 오차 기록 (정답과 비교 — 채점용)
        err = np.linalg.norm(c["xyz"][:2] - truth[c["color"]][:2]) * 100
        log(f"  보기: {c['color']:5s} ({c['xyz'][0]*100:6.1f}, {c['xyz'][1]*100:6.1f})cm · 인식 오차 {err:.1f}cm")
    for c in sorted(seen, key=lambda c: c["color"]):
        pick_and_place(arm, c["xyz"], arm.site(BINS[c["color"]]))
    arm.move_joints(LOOK_POSE, 1.0)
    # 채점: 각 큐브가 자기 색 칸(3cm 반경) 안에 있나
    ok = 0
    for name, pos in arm.objects().items():
        color = name.replace("cube_", "")
        d = np.linalg.norm(pos[:2] - arm.site(BINS[color])[:2]) * 100
        good = d < 3.0
        ok += good
        log(f"  결과: {color:5s} 칸 중심까지 {d:.1f}cm {'✓' if good else '✗'}")
    return ok, len(seen)


def random_layout(rng):
    """큐브 3개를 팔이 닿고 서로 겹치지 않는 오른쪽 구역에 무작위 배치"""
    pts = []
    while len(pts) < 3:
        x, y = rng.uniform(0.06, 0.20), rng.uniform(-0.29, -0.13)
        if 0.15 <= np.hypot(x, y) <= 0.28 and all(np.hypot(x - a, y - b) > 0.06 for a, b in pts):
            pts.append((x, y))
    return {f"cube_{c}": p for c, p in zip(("red", "blue", "green"), pts)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", action="store_true")
    ap.add_argument("--trials", type=int, default=1)
    args = ap.parse_args()
    arm = Arm("scene_sort.xml", view=args.view)
    arm.render = arm.render if args.view or args.trials == 1 else arm.render
    rng = np.random.default_rng(3)
    total = seen_total = 0
    for t in range(args.trials):
        arm.reset(objects=None if t == 0 else random_layout(rng))
        print(f"--- 시도 {t + 1}")
        ok, n = run_once(arm)
        total += ok; seen_total += n
    print(f"=== 제자리에 놓은 큐브 {total}/{3 * args.trials} · 찾은 큐브 {seen_total}/{3 * args.trials}")
