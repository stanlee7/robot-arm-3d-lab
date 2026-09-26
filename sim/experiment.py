"""여러 위치에서 집어 옮기기 성공률 측정. 결과: out/experiment.json"""
import json, sys, numpy as np
from pathlib import Path
from robot import Arm

def pick_place(a, lift=0.09):
    c, t = a.cube(), a.target()
    a.grip(False); a.move_to((c[0], c[1], 0.08)); a.move_to((c[0], c[1], c[2] + 0.005))
    a.grip(True); a.move_to((c[0], c[1], lift))
    held = a.cube()[2] > 0.04                       # 들어 올렸나
    a.move_to((t[0], t[1], lift)); a.move_to((t[0], t[1], 0.03)); a.grip(False); a.move_to((t[0], t[1], lift))
    end = a.cube(); dist = float(np.linalg.norm(end[:2] - t[:2]))
    return held, dist

if __name__ == "__main__":
    rng = np.random.default_rng(7)
    a = Arm(); a.renderer = None
    rows = []
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    for i in range(n):
        r, ang = rng.uniform(0.15, 0.28), rng.uniform(-0.9, 0.9)   # 로봇 앞쪽(-y) 부채꼴
        x, y = r * np.sin(ang), -r * np.cos(ang)
        a.reset((x, y)); a.render = lambda *k, **kw: None; a.frames = []
        held, dist = pick_place(a)
        ok = held and dist < 0.02
        rows.append({"x": round(x, 3), "y": round(y, 3), "거리_m": round(r, 3), "들어올림": bool(held), "목표오차_m": round(dist, 3), "성공": bool(ok)})
        print(i, rows[-1], flush=True)
    OUT = Path(__file__).parent / "out"  # 어디서 실행해도 sim/out/에 저장
    OUT.mkdir(exist_ok=True)
    s = sum(r["성공"] for r in rows)
    json.dump({"시도": n, "성공": s, "성공률": round(s / n, 2), "기록": rows}, open(OUT / "experiment.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"성공 {s}/{n}")
