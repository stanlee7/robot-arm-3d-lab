"""로봇 바리스타 실행.

  ..\..\.venv\Scripts\python programs\barista\run.py                      주문 3개 한 번 (영상 저장)
  ..\..\.venv\Scripts\python programs\barista\run.py --view               실시간 3D 창
  ..\..\.venv\Scripts\python programs\barista\run.py --trials 10 --mess 8 컵을 최대 8mm 어긋나게 놓고 10번 → 성공률
  --orders 아메리카노,라떼,아메리카노
"""
import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from driver import SimDriver  # noqa: E402
from controller import Barista  # noqa: E402

OUT = HERE.parents[1] / "sim" / "out"


def save_mp4(frames, path, fps=20, speed=3):
    """프레임(0.05초 간격) → mp4, speed배 빠르게. ffmpeg 필요(WinGet 설치 위치도 찾음)"""
    import shutil, subprocess, os, glob
    ff = shutil.which("ffmpeg") or next(iter(glob.glob(os.path.expandvars(
        "%LOCALAPPDATA%/Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"))), None)
    if not ff:
        return "ffmpeg 없음"
    h, w = frames[0].shape[:2]
    proc = subprocess.Popen([ff, "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                             "-r", str(fps * speed), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(path)],
                            stdin=subprocess.PIPE)
    for f in frames:
        proc.stdin.write(np.ascontiguousarray(f).tobytes())
    proc.stdin.close(); proc.wait()
    return str(path)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", default="아메리카노,라떼,아메리카노")
    ap.add_argument("--view", action="store_true")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--mess", type=float, default=0.0, help="컵 보관대 자리 어긋남 최대값(mm)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--mode", default="seq", choices=["seq", "pipe"], help="seq: 한 잔씩 끝까지 / pipe: 머신이 도는 동안 다음 일")
    ap.add_argument("--brew", default="", help="머신 시간 바꾸기, 예: espresso=20,milk=12")
    a = ap.parse_args()
    drinks = a.orders.split(",")
    import controller as C
    for kv in filter(None, a.brew.split(",")):
        k, v = kv.split("="); C.BREW[k.strip()] = float(v)
    rng = np.random.default_rng(7)
    drv = SimDriver(view=a.view)
    drv.arm.video_camera = "cafe"   # 로봇 어깨 너머 시점(정면 카메라는 머신에 가림)
    done = total = 0
    times, alarms, totals = [], [], []
    for t in range(a.trials):
        off = rng.uniform(-a.mess, a.mess, size=(3, 2)) / 1000 if a.mess else np.zeros((3, 2))
        drv.place_cups(off)
        if a.trials > 1:
            print(f"--- 시도 {t + 1} (어긋남 {', '.join(f'{np.hypot(*o)*1000:.0f}mm' for o in off)})")
        bar = Barista(drv, say=(lambda *_: None) if a.quiet else print)
        orders = bar.run_pipelined(drinks) if a.mode == "pipe" else bar.run(drinks)
        totals.append(getattr(bar, "total", None) or sum(o.seconds for o in orders))
        done += sum(o.status == "완료" for o in orders)
        total += len(orders)
        times += [o.seconds for o in orders if o.status == "완료"]
        alarms += bar.alarms
        if a.trials == 1 and not a.view:
            OUT.mkdir(exist_ok=True)
            print("영상:", save_mp4(drv.arm.frames, OUT / f"barista_{a.mode}.mp4", speed=3))
    print(f"=== 방식 {a.mode} · 머신 {C.BREW} · 주문 {len(drinks)}잔 전체 걸린 시간 평균 {np.mean(totals):.1f}초(로봇 시간)")
    print(f"=== 완료 {done}/{total}잔 · 한 잔 평균 {np.mean(times) if times else 0:.1f}초(로봇 시간) · 직원 호출 {len(alarms)}건")
    for x in alarms:
        print("  알림:", x)
