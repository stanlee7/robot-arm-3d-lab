"""프로그램 로봇 vs 피지컬 AI 로봇 — 같은 장면, 같은 과제(보관대의 컵 하나 집어 들기)로 비교.

컵은 매번 보관대 자리에서 최대 ±25mm 어긋나 있다(사람이 대충 채워 넣은 상황).
  A 고정 좌표   : 사람이 정한 보관대 좌표로만 간다(카메라 없음)
  B 카메라 규칙 : 사람이 짠 인식 규칙(흰 테두리 원 찾기)으로 컵 위치를 구해 간다 = 지금 바리스타 방식
  C 피지컬 AI   : 시연을 보고 배운 신경망이 카메라 사진+관절 각도만 보고 0.1초마다 관절 명령을 낸다.
                  좌표·역기구학·순서 규칙을 쓰지 않는다.

  python programs/compare/cup_pick.py collect --episodes 300      시연 모으기(정답 위치를 아는 전문가)
  python il/train.py --data ../programs/compare/data/demos.npz --run ../programs/compare/data/run --epochs 60
  python programs/compare/cup_pick.py eval --trials 50             세 방식 성공률
"""
import argparse
import json
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "programs" / "barista"))
sys.path.insert(0, str(ROOT / "il"))
from driver import SimDriver, CUP_OPEN  # noqa: E402

CAM, IMG = "rack_cam", 96
HOVER, GRASP, LIFT = 0.09, 0.025, 0.10
MAX_OFF = 0.025
START = [0.25, -1.57, 1.57, 1.57, -1.57]   # 준비 자세(보관대 쪽으로 살짝 돌림)


def setup(drv, off, rng=None):
    """컵1만 보관대2 자리 + 어긋남, 나머지 컵은 치움. 팔은 준비 자세, 집게는 컵 폭으로 벌림"""
    drv.arm.reset(objects={})
    m, d = drv.m, drv.d
    base = drv.spot("rack2")
    for i, c in enumerate(drv.cups):
        a = m.joint(c).qposadr[0]
        d.qpos[a:a + 7] = ([base[0] + off[0], base[1] + off[1], 0.02] if i == 0 else [0.6 + i * 0.1, 0.6, 0.02]) + [1, 0, 0, 0]
        drv.machine_fill(c, "empty")
    for k, a in enumerate(drv.arm.qadr):
        d.qpos[a] = START[k] + (rng.uniform(-0.08, 0.08) if rng is not None else 0)
    ja = m.joint("Jaw").qposadr[0]
    d.qpos[ja] = CUP_OPEN
    d.ctrl[:5] = [d.qpos[a] for a in drv.arm.qadr]
    d.ctrl[5] = CUP_OPEN
    mujoco.mj_forward(m, d)
    drv.folded = False


def quiet(drv):
    """기록용 영상 렌더링은 끄고(느림·메모리), 인식 카메라(camera_image)만 남긴다"""
    arm, render = drv.arm, drv.arm.render
    arm.camera_image = lambda camera="top": render(camera)
    arm.render = lambda *a, **k: None


def cup_z(drv):
    return float(drv.d.xpos[drv.m.body("cup1").id][2])


def lifted(drv):
    return cup_z(drv) > 0.06 and drv.holding()


def grasp_at(drv, xy):
    """좌표가 주어지면 집어서 들어 올리는 정해진 동작(A·B 공통, 전문가 시연에도 사용)"""
    drv.move_open_to((xy[0], xy[1], HOVER), 1.0)
    drv.move_open_to((xy[0], xy[1], GRASP), 0.8)
    drv.grip(True)
    drv.move_to((xy[0], xy[1], LIFT), 0.8)


def random_off(rng):
    return rng.uniform(-MAX_OFF, MAX_OFF, 2)


# ---------- 시연 모으기 ----------
def collect(n, seed, noise, out):
    rng = np.random.default_rng(seed)
    drv = SimDriver(view=False)
    arm = drv.arm
    quiet(drv)
    imgs, qpos, act, ep = [], [], [], []
    kept, t0 = 0, time.time()

    def rec(a):
        imgs.append(a.small_image(IMG, camera=CAM)); qpos.append(a.qpos6())
        act.append((a.ctrl_clean if a.ctrl_clean is not None else a.d.ctrl).copy()); ep.append(kept)
        a.ctrl_noise = rng.normal(0, noise, 5) if noise > 0 else None

    for e in range(n):
        n0 = len(act)
        off = random_off(rng)
        setup(drv, off, rng)
        arm.recorder = rec
        arm.hold(0.3)
        p = drv.d.xpos[drv.m.body("cup1").id][:2]      # 전문가는 정답 위치를 안다
        grasp_at(drv, p)
        arm.hold(0.6)
        arm.recorder = None; arm.ctrl_noise = None
        if not lifted(drv):
            del imgs[n0:], qpos[n0:], act[n0:], ep[n0:]
            continue
        kept += 1
        if (e + 1) % 25 == 0:
            print(f"{e + 1}/{n} · 성공 시연 {kept} · 프레임 {len(act)} · {time.time() - t0:.0f}초", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, imgs=np.array(imgs, np.uint8), qpos=np.array(qpos, np.float32),
                        act=np.array(act, np.float32), ep=np.array(ep, np.int32))
    print(f"저장: 시연 {kept}개 · 프레임 {len(act)} → {out} · {time.time() - t0:.0f}초")


# ---------- 세 방식 ----------
def run_fixed(drv):
    grasp_at(drv, drv.spot("rack2")[:2])


def run_rule(drv):
    drv.look()
    p = drv.find_cup("rack2")
    if p is None:
        return
    grasp_at(drv, p)


def run_ai(drv, model, dev, steps=45, k=0.2):
    import torch
    from policy import CHUNK
    buf = []
    for t in range(steps):
        img = torch.tensor(drv.arm.small_image(IMG, camera=CAM)[None], device=dev)
        q = torch.tensor(drv.arm.qpos6()[None], dtype=torch.float32, device=dev)
        with torch.no_grad():
            buf.append((t, model.act(img, q)[0].cpu().numpy()))
        buf = [(s, c) for s, c in buf if t - s < CHUNK]
        preds = np.array([c[t - s] for s, c in buf]); w = np.exp(-k * np.arange(len(preds))[::-1])
        drv.d.ctrl[:] = (preds * w[:, None]).sum(0) / w.sum()
        for _ in range(50):
            mujoco.mj_step(drv.m, drv.d)


def evaluate(trials, seed, run, out_json, only="ABC"):
    import torch
    from policy import Policy
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    cfg = json.loads((run / "config.json").read_text())
    model = Policy(img=cfg["img"], arch=cfg["arch"]).to(dev)
    model.load_state_dict(torch.load(run / "policy.pt", map_location=dev)); model.eval()
    drv = SimDriver(view=False); quiet(drv)
    rng = np.random.default_rng(seed)               # 학습(seed 0)과 다른 위치
    offs = [random_off(rng) for _ in range(trials)]
    methods = [m for m in (("A", run_fixed), ("B", run_rule), ("C", lambda d: run_ai(d, model, dev))) if m[0] in only]
    res = {m[0]: [] for m in methods}
    for i, off in enumerate(offs):
        for name, fn in methods:
            setup(drv, off)
            fn(drv)
            res[name].append(bool(lifted(drv)))
        print(f"{i + 1:2d}. 어긋남 {np.hypot(*off) * 1000:4.1f}mm  " + "  ".join(f"{k} {'✓' if v[-1] else '✗'}" for k, v in res.items()), flush=True)
    dist = [float(np.hypot(*o) * 1000) for o in offs]
    bins = [(0, 10), (10, 20), (20, 36)]
    summary = {k: {"all": f"{sum(v)}/{len(v)}", "bins": {f"{lo}-{hi}mm": f"{sum(x for x, dd in zip(v, dist) if lo <= dd < hi)}/{sum(1 for dd in dist if lo <= dd < hi)}" for lo, hi in bins}} for k, v in res.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    out_json.write_text(json.dumps({"dist_mm": dist, "res": res, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "eval", "peek"])
    ap.add_argument("--episodes", type=int, default=300)
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--noise", type=float, default=0.02)
    ap.add_argument("--run", default="data/run")
    ap.add_argument("--only", default="ABC", help="평가할 방식만, 예: C")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.episodes, a.seed, a.noise, HERE / "data" / "demos.npz")
    elif a.cmd == "peek":       # 카메라 사진 한 장 확인
        from PIL import Image
        drv = SimDriver(view=False); setup(drv, (0.02, -0.02))
        Image.fromarray(drv.arm.small_image(240, camera=CAM)).save(HERE / "data" / "peek.png")
        print("peek.png", cup_z(drv))
    else:
        evaluate(a.trials, 1234 if a.seed == 0 else a.seed, HERE / a.run, HERE / "data" / ("result.json" if a.only == "ABC" else f"result_{a.only}_{Path(a.run).name}.json"), a.only)
