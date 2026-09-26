"""Claude가 시뮬레이션 로봇팔을 조종하는 MCP 서버.
도구: 상태보기, 이동, 집게, 처음자세, 카메라, 초기화, 녹화저장

ROBOT_VIEW=1 이면 3D 창이 뜨고 조종 과정이 실시간으로 보인다.
이때 창(그리기·마우스)은 주 스레드, Claude와의 통신은 별도 스레드에서 돌린다.
그래야 Claude가 생각하는 동안에도 창이 멈추지 않고 마우스로 시점을 바꿀 수 있다.
"""
import io
import os
import queue
import sys
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image as McpImage

sys.path.insert(0, str(Path(__file__).parent))
from robot import Arm  # noqa: E402

VIEW = os.environ.get("ROBOT_VIEW") == "1"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
mcp = FastMCP("robot-arm-sim")
arm = Arm(view=VIEW)  # 창은 주 스레드에서 만들어야 함
_jobs: "queue.Queue" = queue.Queue()


def _call(fn, *a, **kw):
    """창이 있으면 주 스레드에 일을 넘기고 끝날 때까지 기다린다."""
    if not VIEW:
        return fn(*a, **kw)
    done, box = threading.Event(), {}
    _jobs.put((fn, a, kw, done, box))
    done.wait()
    if "err" in box:
        raise box["err"]
    return box["val"]


@mcp.tool()
def state() -> dict:
    """손끝·큐브·목표 위치(미터, x·y·z)와 관절각. 작업대 윗면 z=0, 로봇 받침이 원점. 팔은 -y 쪽을 향함."""
    return _call(arm.state)


@mcp.tool()
def move_to(x: float, y: float, z: float, seconds: float = 1.2) -> dict:
    """손끝(집게 가운데)을 (x, y, z)로 옮김. 닿는 범위 대략 반경 0.1~0.3m, z 0.02~0.15m.
    결과의 IK오차는 계산상 닿는지, 도달오차는 실제로 멈춘 위치와의 거리(큐브·바닥에 닿으면 커짐)."""
    return _call(arm.move_to, (x, y, z), seconds)


@mcp.tool()
def grip(close: bool) -> dict:
    """집게 닫기(True) / 열기(False)."""
    return _call(arm.grip, close)


@mcp.tool()
def home() -> dict:
    """처음 자세로 돌아감."""
    return _call(lambda: (arm.home(), arm.state())[1])


@mcp.tool()
def look(camera: str = "front") -> McpImage:
    """카메라 화면. camera: front 또는 top."""
    from PIL import Image
    frame = _call(arm.render, camera)
    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, format="PNG")
    return McpImage(data=buf.getvalue(), format="png")


@mcp.tool()
def reset(cube_x: float = 0.0, cube_y: float = -0.25) -> dict:
    """장면 초기화. 큐브를 (cube_x, cube_y) 작업대 위에 놓음. 녹화도 지움."""
    return _call(lambda: (arm.reset((cube_x, cube_y)), arm.state())[1])


@mcp.tool()
def save_recording(name: str = "run") -> str:
    """reset 이후 움직임을 GIF로 저장하고 경로를 돌려줌."""
    return _call(arm.save_gif, OUT / f"{name}.gif")


def _main_loop():
    while arm.viewer.is_running():
        try:
            fn, a, kw, done, box = _jobs.get(timeout=1 / 60)
        except queue.Empty:
            arm.viewer.sync()  # 쉬는 동안에도 그리기·마우스 처리
            continue
        try:
            box["val"] = fn(*a, **kw)
        except BaseException as e:  # 창을 닫으면 SystemExit — Claude에게는 오류로 알림
            box["err"] = e if isinstance(e, Exception) else RuntimeError(f"로봇 창이 닫혔습니다: {e}")
        finally:
            done.set()
    arm.viewer.close()
    os._exit(0)


if __name__ == "__main__":
    if VIEW:
        threading.Thread(target=mcp.run, daemon=True).start()
        _main_loop()
    else:
        mcp.run()
