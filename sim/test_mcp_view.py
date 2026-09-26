"""MCP 서버를 3D 창 모드로 띄워 Claude 대신 도구를 불러 보는 점검 스크립트.
실행: .venv\Scripts\python sim\test_mcp_view.py"""
import asyncio, json, os, subprocess, sys, time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))

def responding():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process python* | Where-Object {$_.MainWindowTitle -like '로봇팔 3D*'} | ForEach-Object { \"$($_.Id) $($_.Responding)\" }"],
        capture_output=True, text=True, encoding="utf-8").stdout.strip()
    return out or "창 없음"

async def main():
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(HERE, "mcp_server.py")],
                                   env={**os.environ, "ROBOT_VIEW": "1", "PYTHONUTF8": "1"})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("도구:", [t.name for t in (await s.list_tools()).tools])
            await s.call_tool("reset", {"cube_x": 0.1, "cube_y": -0.22})
            await asyncio.sleep(3)
            print("쉬는 중 창 응답:", responding())
            st = json.loads((await s.call_tool("state", {})).content[0].text)
            c, t = st["cube"], st["target"]
            for name, args in [("grip", {"close": False}), ("move_to", {"x": c[0], "y": c[1], "z": 0.08}),
                               ("move_to", {"x": c[0], "y": c[1], "z": c[2] + 0.005}), ("grip", {"close": True}),
                               ("move_to", {"x": c[0], "y": c[1], "z": 0.09}), ("move_to", {"x": t[0], "y": t[1], "z": 0.09}),
                               ("move_to", {"x": t[0], "y": t[1], "z": 0.03}), ("grip", {"close": False}),
                               ("move_to", {"x": t[0], "y": t[1], "z": 0.09})]:
                res = await s.call_tool(name, args)
                print(name, res.content[0].text.replace("\n", " ")[:160])
            await asyncio.sleep(2)
            print("끝난 뒤 창 응답:", responding())
            st = json.loads((await s.call_tool("state", {})).content[0].text)
            dx = ((st["cube"][0] - st["target"][0]) ** 2 + (st["cube"][1] - st["target"][1]) ** 2) ** 0.5
            print(f"큐브-목표 거리 {dx*100:.1f}cm")
            img = await s.call_tool("look", {"camera": "front"})
            print("look:", img.content[0].type)

asyncio.run(main())
