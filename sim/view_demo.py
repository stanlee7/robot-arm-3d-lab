"""실시간 3D 창에서 로봇팔이 큐브를 여러 위치에서 집어 목표 원에 옮기는 것을 반복해서 보여 준다.
실행: .venv\Scripts\python sim\view_demo.py   (창을 닫으면 끝)"""
import numpy as np
from robot import Arm
from experiment import pick_place

a = Arm(view=True)
a.render = lambda *k, **kw: None   # 녹화는 끔
rng = np.random.default_rng()
while a.viewer.is_running():
    r, ang = rng.uniform(0.15, 0.28), rng.uniform(-0.9, 0.9)
    a.reset((r * np.sin(ang), -r * np.cos(ang))); a.viewer.sync()
    held, dist = pick_place(a)
    print(f"큐브 ({r*np.sin(ang):+.2f}, {-r*np.cos(ang):+.2f}) → 목표 오차 {dist*100:.1f}cm {'성공' if held and dist < 0.02 else '실패'}", flush=True)
    a.home()
