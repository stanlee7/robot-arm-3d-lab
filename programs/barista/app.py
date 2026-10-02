"""로봇 바리스타 조종 프로그램 (데스크톱 창).

주문을 넣고 「시작」을 누르면 controller.py(AI 없는 상태 기계)가 SimDriver로 로봇팔을 움직인다.
화면 왼쪽은 카페 카메라, 오른쪽 아래는 로봇이 컵을 찾을 때 보는 위 카메라.
실물 로봇팔이 생기면 driver.py 자리에 RealDriver만 바꿔 끼우면 이 화면은 그대로 쓴다.

  .venv\\Scripts\\python programs\\barista\\app.py      (또는 로봇바리스타_조종.bat 더블클릭)
"""
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import controller as C  # noqa: E402
from driver import SimDriver  # noqa: E402

BG, PANEL, INK, MUTED, ACCENT, GOOD, BAD = "#0f1315", "#161b1e", "#e6ebed", "#98a4aa", "#ffc21a", "#3cc07e", "#ef6a64"
FONT = ("Malgun Gothic", 10)
MAX_CUPS = 3   # 컵 보관대 3칸


class Stop(Exception):
    """「정지」를 누르면 로봇 동작 중간에 이 예외로 빠져나온다"""


class FrameSink:
    """Arm이 0.05초(로봇 시간)마다 넣는 영상 프레임을 화면으로 보내고, 재생 속도에 맞춰 기다린다.
    Arm.frames 대신 끼워서 메모리에 쌓지 않는다."""

    def __init__(self, app):
        self.app, self.wall0, self.sim0 = app, None, None

    def start(self, sim_t):
        self.wall0, self.sim0 = time.perf_counter(), sim_t

    def append(self, frame):
        if self.app.stop_flag.is_set():
            raise Stop()
        self.app.frames.put(("cafe", frame))
        sim_t = self.app.drv.d.time
        ahead = (sim_t - self.sim0) / self.app.speed - (time.perf_counter() - self.wall0)
        if ahead > 0:
            time.sleep(ahead)
        elif ahead < -0.5:      # 렌더링이 느려 밀리면 기준을 다시 잡음(따라잡으려 빨리 감지 않게)
            self.start(sim_t)


class App:
    def __init__(self, root):
        self.root = root
        self.cart = []
        self.speed = 2.0
        self.running = False
        self.stop_flag = threading.Event()
        self.frames = queue.Queue(maxsize=4)
        self.msgs = queue.Queue()
        self.results = {}
        self.drv = None
        self.cur = None
        self._build()
        self.root.after(30, self._pump)
        self._log("프로그램 준비 중… (3D 장면 불러오는 중)")
        self.jobs = queue.Queue()
        # 3D 렌더링(OpenGL)은 만든 스레드에서만 써야 해서, 로봇 일은 전부 이 스레드 하나가 한다
        threading.Thread(target=self._robot_thread, daemon=True).start()

    # ---------- 화면 ----------
    def _build(self):
        r = self.root
        r.title("로봇 바리스타 조종 프로그램 · SO-ARM100 시뮬레이션")
        r.configure(bg=BG)
        r.geometry("1240x760")
        st = ttk.Style(r)
        st.theme_use("clam")
        st.configure(".", background=PANEL, foreground=INK, font=FONT)
        st.configure("TFrame", background=PANEL)
        st.configure("TLabel", background=PANEL, foreground=INK)
        st.configure("Muted.TLabel", foreground=MUTED)
        st.configure("H.TLabel", font=("Malgun Gothic", 12, "bold"))
        st.configure("Big.TLabel", font=("Consolas", 20), foreground=ACCENT)
        st.configure("TButton", background="#1d2327", foreground=INK, bordercolor="#293237", padding=6)
        st.map("TButton", background=[("active", "#273036"), ("disabled", "#14181b")], foreground=[("disabled", "#55606a")])
        st.configure("Accent.TButton", background=ACCENT, foreground="#182024", font=("Malgun Gothic", 10, "bold"))
        st.map("Accent.TButton", background=[("active", "#ffd451"), ("disabled", "#5c4f22")])
        st.configure("TRadiobutton", background=PANEL, foreground=INK)
        st.configure("Horizontal.TScale", background=PANEL)
        st.configure("Treeview", background="#1d2327", fieldbackground="#1d2327", foreground=INK, rowheight=24, bordercolor="#293237")
        st.configure("Treeview.Heading", background=PANEL, foreground=MUTED)

        r.columnconfigure(0, weight=1)
        r.rowconfigure(0, weight=1)
        left = tk.Frame(r, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.video = tk.Label(left, bg="#1b2126", fg=MUTED, text="3D 장면 불러오는 중…", font=FONT)
        self.video.grid(row=0, column=0, sticky="nsew")
        bottom = tk.Frame(left, bg=BG)
        bottom.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        self.logbox = tk.Text(bottom, height=9, bg=PANEL, fg=MUTED, bd=0, font=("Consolas", 9), wrap="word")
        self.logbox.grid(row=0, column=0, sticky="nsew")
        camf = tk.Frame(bottom, bg=BG)
        camf.grid(row=0, column=1, padx=(8, 0))
        tk.Label(camf, text="로봇이 보는 위 카메라", bg=BG, fg=MUTED, font=FONT).pack(anchor="w")
        self.cam = tk.Label(camf, bg="#1b2126", width=26, height=9)
        self.cam.pack()

        side = ttk.Frame(r, padding=12)
        side.grid(row=0, column=1, sticky="ns", padx=(6, 12), pady=12)
        ttk.Label(side, text="로봇 바리스타", style="H.TLabel").pack(anchor="w")
        ttk.Label(side, text="정해진 프로그램으로 움직입니다. 실행 중 AI는 쓰지 않습니다.", style="Muted.TLabel", wraplength=300).pack(anchor="w", pady=(0, 10))

        ttk.Label(side, text="1. 주문 담기 (최대 3잔)", style="Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(side)
        row.pack(anchor="w", pady=4)
        for d in C.RECIPES:
            ttk.Button(row, text=d, command=lambda d=d: self._add(d)).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="비우기", command=self._clear).pack(side="left")
        self.cart_lbl = ttk.Label(side, text="담은 주문 없음", wraplength=300)
        self.cart_lbl.pack(anchor="w", pady=(0, 10))

        ttk.Label(side, text="2. 로봇이 일하는 방식", style="Muted.TLabel").pack(anchor="w")
        self.mode = tk.StringVar(value="pipe")
        ttk.Radiobutton(side, text="한 잔씩 끝까지", value="seq", variable=self.mode).pack(anchor="w")
        ttk.Radiobutton(side, text="머신 도는 동안 다음 일", value="pipe", variable=self.mode).pack(anchor="w")
        self.sliders = {}
        for key, label, lo, hi, val in [("espresso", "에스프레소(초)", 2, 30, 10), ("milk", "우유(초)", 2, 20, 6), ("speed", "재생 속도(배)", 1, 4, 2)]:
            f = ttk.Frame(side)
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=label, width=13).pack(side="left")
            v = tk.DoubleVar(value=val)
            out = ttk.Label(f, text=str(val), width=3)
            ttk.Scale(f, from_=lo, to=hi, variable=v, command=lambda x, o=out, v=v: o.config(text=str(round(v.get())))).pack(side="left", fill="x", expand=True)
            out.pack(side="left")
            self.sliders[key] = v

        f = ttk.Frame(side)
        f.pack(fill="x", pady=(12, 4))
        self.start_btn = ttk.Button(f, text="▶ 시작", style="Accent.TButton", command=self._start, state="disabled")
        self.start_btn.pack(side="left", fill="x", expand=True)
        self.stop_btn = ttk.Button(f, text="■ 정지", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))

        ttk.Label(side, text="3. 주문 현황", style="Muted.TLabel").pack(anchor="w", pady=(10, 2))
        self.tree = ttk.Treeview(side, columns=("drink", "status", "sec"), show="headings", height=4)
        for c, t, w in [("drink", "음료", 90), ("status", "상태", 110), ("sec", "걸린 시간", 80)]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="x")

        ttk.Label(side, text="4. 결과 비교 (같은 주문·같은 머신 시간)", style="Muted.TLabel").pack(anchor="w", pady=(10, 2))
        g = ttk.Frame(side)
        g.pack(fill="x")
        self.res = {}
        for i, (k, t) in enumerate([("seq", "한 잔씩"), ("pipe", "동시 진행")]):
            ttk.Label(g, text=t, style="Muted.TLabel").grid(row=0, column=i, sticky="w", padx=(0, 30))
            self.res[k] = ttk.Label(g, text="-", style="Big.TLabel")
            self.res[k].grid(row=1, column=i, sticky="w", padx=(0, 30))
        self.note = ttk.Label(side, text="두 방식으로 같은 주문을 한 번씩 돌려 보세요.", style="Muted.TLabel", wraplength=300)
        self.note.pack(anchor="w", pady=(4, 0))
        self.alarm = ttk.Label(side, text="", foreground=BAD, wraplength=300)
        self.alarm.pack(anchor="w", pady=(8, 0))

    # ---------- 주문 ----------
    def _add(self, d):
        if len(self.cart) >= MAX_CUPS or self.running:
            return
        self.cart.append(d)
        self._show_cart()

    def _clear(self):
        if not self.running:
            self.cart = []
            self._show_cart()

    def _show_cart(self):
        self.cart_lbl.config(text=" → ".join(f"#{i + 1} {d}" for i, d in enumerate(self.cart)) or "담은 주문 없음")
        self.start_btn.config(state="normal" if self.cart and self.drv and not self.running else "disabled")

    def _start(self):
        if self.running or not self.cart:
            return
        C.BREW["espresso"] = round(self.sliders["espresso"].get())
        C.BREW["milk"] = round(self.sliders["milk"].get())
        self.speed = round(self.sliders["speed"].get())
        self.running = True
        self.stop_flag.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.alarm.config(text="")
        self.tree.delete(*self.tree.get_children())
        for i, d in enumerate(self.cart):
            self.tree.insert("", "end", iid=str(i + 1), values=(f"#{i + 1} {d}", "대기", ""))
        self.cur = None
        self.jobs.put((list(self.cart), self.mode.get()))

    def _stop(self):
        self.stop_flag.set()
        self._log("정지 요청 — 지금 동작에서 멈춥니다")

    # ---------- 로봇 (작업 스레드) ----------
    def _robot_thread(self):
        if self._load():
            while True:
                self._work(*self.jobs.get())

    def _load(self):
        try:
            self.drv = SimDriver(view=False)
            self.drv.arm.video_camera = "cafe"
            self.sink = FrameSink(self)
            self.drv.arm.frames = self.sink
            find = self.drv.find_cup

            def find_and_show(spot):     # 로봇이 컵을 찾을 때마다 위 카메라 사진을 화면에 보냄
                p = find(spot)
                self._put_cam(self.drv.arm.camera_image("top"), spot, p)
                return p
            self.drv.find_cup = find_and_show
            self.drv.place_cups(np.zeros((3, 2)))
            self.frames.put(("cafe", self.drv.arm.render("cafe")))
            self.msgs.put(("ready", None))
            return True
        except Exception as e:  # noqa: BLE001
            self.msgs.put(("log", f"3D 장면을 불러오지 못했습니다: {e}"))
            return False

    def _put_cam(self, img, spot, p):
        im = Image.fromarray(img).resize((240, 180))
        if p is not None:   # 찾은 컵 중심을 위 카메라 그림 위에 표시 (위 카메라는 x→오른쪽, y→위)
            m, cam = self.drv.m, self.drv.m.camera("top")
            h = self.drv.d.cam_xpos[cam.id][2] if hasattr(self.drv.d, "cam_xpos") else 0.7
            f = 0.5 * 180 / np.tan(np.radians(m.cam_fovy[cam.id]) / 2)
            cx, cy = self.drv.d.cam_xpos[cam.id][:2]
            u = 120 + (p[0] - cx) * f / h
            v = 90 - (p[1] - cy) * f / h
            ImageDraw.Draw(im).ellipse([u - 9, v - 9, u + 9, v + 9], outline=ACCENT, width=2)
        try:
            self.frames.put_nowait(("top", im))
        except queue.Full:
            pass

    def _work(self, drinks, mode):
        say = lambda s: self.msgs.put(("say", s))  # noqa: E731
        try:
            self.drv.place_cups(np.zeros((3, 2)))     # 컵 보관대 채우고 처음 자세로
            self.sink.start(self.drv.d.time)
            bar = C.Barista(self.drv, say=say)
            t0 = self.drv.d.time
            orders = bar.run_pipelined(drinks) if mode == "pipe" else bar.run(drinks)
            total = self.drv.d.time - t0
            self.msgs.put(("done", (mode, drinks, orders, total, bar.alarms)))
        except Stop:
            self.msgs.put(("stopped", None))
        except Exception as e:  # noqa: BLE001
            self.msgs.put(("log", f"오류: {e}"))
            self.msgs.put(("stopped", None))

    # ---------- 화면 갱신 (주 스레드) ----------
    def _pump(self):
        last = {}
        try:
            while True:
                kind, f = self.frames.get_nowait()
                last[kind] = f
        except queue.Empty:
            pass
        if "cafe" in last:
            w, h = max(320, self.video.winfo_width()), max(240, self.video.winfo_height())
            im = Image.fromarray(last["cafe"])
            s = min(w / im.width, h / im.height)
            self._vimg = ImageTk.PhotoImage(im.resize((int(im.width * s), int(im.height * s))))
            self.video.config(image=self._vimg, text="")
        if "top" in last:
            self._cimg = ImageTk.PhotoImage(last["top"])
            self.cam.config(image=self._cimg, width=240, height=180)
        while not self.msgs.empty():
            kind, v = self.msgs.get()
            if kind == "say":
                self._on_say(v)
            elif kind == "log":
                self._log(v)
            elif kind == "ready":
                self._log("준비 완료 — 주문을 담고 「시작」을 누르세요")
                self._show_cart()
            elif kind == "done":
                self._on_done(*v)
            elif kind == "stopped":
                self._log("멈췄습니다. 다시 시작하면 컵을 채우고 처음부터 합니다")
                self._finish()
        self.root.after(30, self._pump)

    def _on_say(self, s):
        self._log(s.strip())
        # 컨트롤러 안내 문장에서 주문 상태만 뽑아 표에 반영 (컨트롤러는 화면을 모름)
        for iid in self.tree.get_children():
            no = int(iid)
            vals = list(self.tree.item(iid, "values"))
            if f"[주문 {no}]" in s:
                vals[1] = "만드는 중"
                self.cur = no
            elif "✓" in s and (f"주문 {no} " in s or ("주문" not in s and self.cur == no)):
                vals[1] = "✓ 완료"
            elif "작동" in s and self.cur == no:      # 한 잔씩 방식: 「rack1 → espresso · espresso 작동 3초」
                vals[1] = "에스프레소 추출" if s.rstrip().split("·")[-1].strip().startswith("espresso") else "우유 스팀"
            elif f"주문 {no}:" in s and "espresso" in s.split("·")[-1]:
                vals[1] = "에스프레소 추출"
            elif f"주문 {no}:" in s and "milk" in s.split("·")[-1]:
                vals[1] = "우유 스팀"
            else:
                continue
            self.tree.item(iid, values=vals)

    def _on_done(self, mode, drinks, orders, total, alarms):
        for o in orders:
            st = {"완료": "✓ 완료", "실패": "✗ 직원 호출"}.get(o.status, o.status)
            self.tree.item(str(o.no), values=(f"#{o.no} {o.drink}", st, f"{o.seconds:.1f}초" if o.seconds else ""))
        key = (tuple(drinks), C.BREW["espresso"], C.BREW["milk"])
        self.results.setdefault(key, {})[mode] = total
        self.res[mode].config(text=f"{total:.1f}초")
        other = "seq" if mode == "pipe" else "pipe"
        r = self.results[key]
        if other in r:
            a, b = r["seq"], r["pipe"]
            self.note.config(text=f"동시 진행이 {a - b:.1f}초({(a - b) / a * 100:.0f}%) 빠릅니다." if a > b else "이 주문에서는 차이가 거의 없습니다(머신 시간을 늘려 보세요).")
        else:
            self.res[other].config(text="-")
            self.note.config(text="같은 주문으로 다른 방식도 돌려 보세요.")
        self.alarm.config(text="\n".join("직원 호출: " + a for a in alarms))
        self._log(f"=== 전체 {total:.1f}초(로봇 시간) · 완료 {sum(o.status == '완료' for o in orders)}/{len(orders)}잔")
        self._finish()

    def _finish(self):
        self.running = False
        self.stop_btn.config(state="disabled")
        self._show_cart()

    def _log(self, s):
        t = f"{self.drv.d.time:6.1f}s  " if self.drv else ""
        self.logbox.insert("1.0", t + s + "\n")


def selftest(root, app, mode, shot):
    """--selftest seq|pipe 화면.png: 라떼·아메리카노를 자동으로 돌리고 창을 캡처한 뒤 닫는다(점검용)"""
    state = {"started": False}

    def tick():
        if app.drv and not state["started"]:
            app._add("라떼"); app._add("아메리카노")
            app.mode.set(mode); app.sliders["speed"].set(4); app._start(); state["started"] = True
        elif state["started"] and not app.running:
            from PIL import ImageGrab
            root.attributes("-topmost", True); root.lift(); root.update(); time.sleep(0.5); root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(shot)
            print("결과:", [app.tree.item(i, "values") for i in app.tree.get_children()], app.res[mode].cget("text"))
            root.destroy(); return
        root.after(500, tick)
    root.after(500, tick)


if __name__ == "__main__":
    try:   # 윈도우 화면 배율(125%·150%)에서 글자가 흐리지 않게
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 3 and sys.argv[1] == "--selftest":
        selftest(root, app, sys.argv[2], sys.argv[3])
    root.mainloop()
