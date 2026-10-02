"""로봇 바리스타 컨트롤러 — AI 없이 정해진 순서(상태 기계)와 복구 절차로 움직이는 프로그램.

주문 대기열 → 레시피(정해진 단계) → 단계마다 센서 확인 → 실패하면 정해진 복구 → 그래도 안 되면 알림.
Claude는 이 프로그램을 같이 만든 개발자일 뿐, 실행 중에는 쓰지 않는다.
"""
import time
from dataclasses import dataclass, field

HOVER, CARRY = 0.09, 0.09     # 컵 위에서 내려가기 전 높이, 들고 옮기는 높이
GRASP_Z, PLACE_Z = 0.025, 0.036
SEARCH = [(0, 0), (0.006, 0), (-0.006, 0), (0, 0.006), (0, -0.006)]  # 못 잡으면 6mm씩 옮겨 다시
# 머신 작동 시간(초, 로봇 시간). 실제 카페에 가깝게 바꿀 수 있다: run.py --brew espresso=20,milk=12
BREW = {"espresso": 3.0, "milk": 2.0}
RECIPES = {
    "아메리카노": [("espresso", "espresso")],
    "라떼": [("espresso", "espresso"), ("milk", "latte")],
}


@dataclass
class Order:
    no: int
    drink: str
    status: str = "대기"
    log: list = field(default_factory=list)
    seconds: float = 0.0


class Barista:
    def __init__(self, drv, say=print):
        self.drv, self.say = drv, say
        self.rack = ["rack1", "rack2", "rack3"]
        self.pickup = ["pickup1", "pickup2"]
        self.alarms = []
        self.placed = {}   # 자리 → 로봇이 컵을 놓은 손끝 위치(xy). 머신 자리는 노즐이 카메라를 가려서 이 기억으로 다시 집는다

    # ---- 기본 동작 ----
    def _pick(self, spot):
        """컵 집기. 직접 놓은 자리면 놓은 위치를 기억해 그대로, 아니면 카메라로 위치 확인.
        못 잡으면 6mm씩 옮겨 다시(최대 5번)"""
        for i, (dx, dy) in enumerate(SEARCH):
            self.drv.look()                # 집기 전 항상 카메라로 확인 (놓은 위치 기억은 집게 속 컵 쏠림 때문에 최대 9mm 틀림)
            p = self.drv.find_cup(spot)
            if p is None:
                self.say(f"    ⚠ {spot}에 컵이 안 보임")
                return False, i
            self.drv.grip(False)
            self.drv.move_open_to((p[0] + dx, p[1] + dy, HOVER))
            self.drv.move_open_to((p[0] + dx, p[1] + dy, GRASP_Z))
            self.drv.grip(True)
            self.drv.move_to((p[0] + dx, p[1] + dy, HOVER))
            if self.drv.holding():
                return True, i
            self.say(f"    ⚠ {spot}에서 못 잡음 → 다시 시도 ({i + 1}/{len(SEARCH)})")
        self.drv.grip(False)
        return False, len(SEARCH)

    def _place(self, spot):
        p = self.drv.spot(spot)
        self.drv.move_to((p[0], p[1], CARRY))
        self.drv.move_to((p[0], p[1], PLACE_Z))
        self.placed[spot] = self.drv.tip()[:2].copy()   # 턱을 열기 전(컵을 쥔 채) 집는 점 = 컵 중심
        self.drv.grip(False)
        self.drv.move_to((p[0], p[1], HOVER))
        return self.drv.cup_at(spot) is not None

    def _move_cup(self, src, dst):
        ok, tries = self._pick(src)
        if not ok:
            return False, f"{src}에서 컵을 잡지 못함"
        self.placed.pop(src, None)
        if not self._place(dst):
            return False, f"{dst}에 컵이 제대로 놓이지 않음"
        return True, f"{src} → {dst}" + (f" (다시 잡기 {tries}번)" if tries else "")

    # ---- 주문 하나 ----
    def make(self, order):
        t0 = time.perf_counter()
        sim0 = self.drv.d.time
        order.status = "만드는 중"
        self.say(f"[주문 {order.no}] {order.drink}")
        # 1) 빈 픽업 자리 확보 (가득 차 있으면 손님이 가져가길 기다리는 대신, 시뮬레이션에선 손님이 가져감)
        slot = next((s for s in self.pickup if self.drv.cup_at(s) is None), None)
        if slot is None:
            old = self.drv.cup_at(self.pickup[0])
            self.drv.take_away(old)
            self.say(f"    손님이 {self.pickup[0]}의 음료를 가져감")
            slot = self.pickup[0]
        # 2) 컵 고르기: 보관대에서 컵이 있는 첫 자리
        src = None
        while self.rack:
            cand = self.rack.pop(0)
            if self.drv.cup_at(cand, radius=0.025):
                src = cand
                break
        if src is None:
            return self._fail(order, "컵 보관대가 비었음 — 컵 채워 넣기 필요", t0, sim0)
        # 3) 레시피 단계
        here = src
        for station, kind in RECIPES[order.drink]:
            brew = BREW[station]
            if self.drv.cup_at(station):
                return self._fail(order, f"{station} 자리에 이미 컵이 있음", t0, sim0)
            ok, msg = self._move_cup(here, station)
            order.log.append(msg)
            if not ok:
                return self._fail(order, msg, t0, sim0)
            self.say(f"    {msg} · {station} 작동 {brew:.0f}초")
            self.drv.look()                       # 머신이 도는 동안 물러나 기다림
            self.drv.wait(max(0.0, brew - 0.8))
            cup = self.drv.cup_at(station)
            self.drv.machine_fill(cup, kind)
            here = station
        # 4) 픽업대로
        ok, msg = self._move_cup(here, slot)
        order.log.append(msg)
        if not ok:
            return self._fail(order, msg, t0, sim0)
        order.status = "완료"
        order.seconds = self.drv.d.time - sim0
        self.say(f"    ✓ {slot}에 {order.drink} 준비 완료 · 로봇 시간 {order.seconds:.1f}초")
        return order

    def _fail(self, order, why, t0, sim0):
        order.status = "실패"
        order.seconds = self.drv.d.time - sim0
        self.alarms.append(f"주문 {order.no} {order.drink}: {why}")
        self.say(f"    ✗ 실패 — {why} → 직원 호출")
        self.drv.grip(False)
        self.drv.home()
        return order

    def run(self, drinks):
        orders = [Order(i + 1, d) for i, d in enumerate(drinks)]
        for o in orders:
            self.make(o)
        self.drv.home()
        return orders

    # ---- 2단계: 머신이 도는 동안 다음 일 (파이프라인) ----
    def run_pipelined(self, drinks):
        """한 잔을 끝까지 기다리지 않는다. 매번 「지금 할 수 있는 일」 중 가장 앞선 주문의 일을 고르고,
        할 일이 없을 때만 가장 먼저 끝나는 머신을 기다린다(이벤트 기반 스케줄러). 실제 카페 로봇의 사이클 타임 단축 원리."""
        orders = [Order(i + 1, d) for i, d in enumerate(drinks)]
        t0 = self.drv.d.time
        st = {o.no: {"step": -1, "at": None, "ready": None, "done": False, "start": None} for o in orders}
        busy = {}          # 머신 자리 → 주문 번호
        while True:
            now = self.drv.d.time
            live = [o for o in orders if not st[o.no]["done"] and o.status != "실패"]
            if not live:
                break
            # 다 된 머신의 컵 색 바꾸기(추출 완료)
            for o in live:
                s = st[o.no]
                if s["at"] in BREW and s["ready"] is not None and now >= s["ready"] and not s.get("filled"):
                    self.drv.machine_fill(self.drv.cup_at(s["at"]), RECIPES[o.drink][s["step"]][1]); s["filled"] = True
            action = None
            # ① 추출이 끝난 컵을 다음 자리로 (앞선 주문부터)
            for o in sorted(live, key=lambda o: -st[o.no]["step"]):
                s = st[o.no]
                if s["step"] < 0 or now < s["ready"]:
                    continue
                steps = RECIPES[o.drink]
                if s["step"] + 1 < len(steps):
                    nxt = steps[s["step"] + 1][0]
                    if nxt in busy:
                        continue
                else:
                    nxt = next((p for p in self.pickup if self.drv.cup_at(p) is None), None)
                    if nxt is None:
                        old = self.drv.cup_at(self.pickup[0]); self.drv.take_away(old)
                        self.say(f"    손님이 {self.pickup[0]}의 음료를 가져감"); nxt = self.pickup[0]
                action = (o, nxt); break
            # ② 없으면 새 주문 시작(에스프레소 자리가 비었을 때)
            if action is None and "espresso" not in busy:
                o = next((o for o in live if st[o.no]["step"] < 0), None)
                if o is not None:
                    action = (o, "espresso")
            if action is None:
                waits = [st[o.no]["ready"] for o in live if st[o.no]["ready"] is not None and st[o.no]["ready"] > now]
                if not waits:
                    self.alarms.append("스케줄러가 할 일을 못 찾음"); break
                self.drv.look(); self.drv.wait(max(0.0, min(waits) - self.drv.d.time))
                continue
            o, dst = action; s = st[o.no]
            if s["step"] < 0:   # 보관대에서 시작
                src = None
                while self.rack:
                    cand = self.rack.pop(0)
                    if self.drv.cup_at(cand, radius=0.025):
                        src = cand; break
                if src is None:
                    o.status = "실패"; self.alarms.append(f"주문 {o.no}: 컵 보관대가 비었음"); continue
                s["start"] = self.drv.d.time
                self.say(f"[주문 {o.no}] {o.drink} 시작")
            else:
                src = s["at"]
            ok, msg = self._move_cup(src, dst)
            if not ok:
                o.status = "실패"; self.alarms.append(f"주문 {o.no} {o.drink}: {msg}"); self.say(f"    ✗ {msg}")
                busy.pop(src, None); continue
            busy.pop(src, None)
            if dst in BREW:
                busy[dst] = o.no; s["step"] += 1; s["at"] = dst; s["ready"] = self.drv.d.time + BREW[dst]; s["filled"] = False
                self.say(f"    주문 {o.no}: {msg} · {dst} {BREW[dst]:.0f}초")
            else:
                s["done"] = True; o.status = "완료"; o.seconds = self.drv.d.time - s["start"]
                self.say(f"    ✓ 주문 {o.no} {o.drink} → {dst} · 이 잔 {o.seconds:.1f}초")
        self.drv.home()
        self.total = self.drv.d.time - t0
        return orders
