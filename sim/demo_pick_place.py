"""큐브를 집어 동그라미(목표) 위에 놓는 데모. 결과: sim/out/demo.gif, demo_end.png"""
from pathlib import Path
from robot import Arm
OUT = Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
a = Arm()
c, t = a.cube(), a.target()
log = []
log.append(a.grip(close=False))
log.append(a.move_to((c[0], c[1], 0.08)))
log.append(a.move_to((c[0], c[1], c[2] + 0.005)))
log.append(a.grip(close=True))
log.append(a.move_to((c[0], c[1], 0.09)))
log.append(a.move_to((t[0], t[1], 0.09)))
log.append(a.move_to((t[0], t[1], 0.03)))
log.append(a.grip(close=False))
log.append(a.move_to((t[0], t[1], 0.09)))
for l in log: print(l)
end = a.cube(); import numpy as np
print("큐브 최종", end.round(3), "목표까지 거리", round(float(np.linalg.norm(end[:2] - t[:2])), 3))
a.save_gif(OUT / "demo.gif")
a.snapshot(OUT / "demo_end.png")
