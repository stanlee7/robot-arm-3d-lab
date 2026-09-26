"""로봇팔 실시간 3D 창 (MuJoCo 기본 창 대신 마우스 조작을 직접 정함).

마우스
- 휠 앞으로: 확대 / 휠 뒤로: 축소
- 휠 누르고 드래그: 화면 이동 (Shift를 누르면 바닥을 따라 앞뒤·좌우로 이동)
- 왼쪽 드래그: 회전 (Shift: 수평으로만 회전)
- 오른쪽 드래그: 바닥을 따라 이동
- 왼쪽 더블클릭: 누른 물체를 화면 가운데로
키보드
- R: 처음 시점 / Esc: 닫기
"""
import time
import glfw
import mujoco
import numpy as np

TITLE = ("로봇팔 3D  |  휠: 확대·축소   휠 누르고 드래그: 이동   왼쪽 드래그: 회전   "
         "오른쪽 드래그: 바닥 따라 이동   더블클릭: 가운데로   R: 처음 시점")
HOME_VIEW = dict(azimuth=125.0, elevation=-28.0, distance=1.0, lookat=(0.03, -0.14, 0.06))
M = mujoco.mjtMouse


class Viewer:
    def __init__(self, m, d, width=1280, height=800, view=None):
        if not glfw.init():
            raise RuntimeError("3D 창을 만들 수 없습니다 (glfw 초기화 실패)")
        glfw.window_hint(glfw.SAMPLES, 4)
        self.win = glfw.create_window(width, height, TITLE, None, None)
        if not self.win:
            glfw.terminate()
            raise RuntimeError("3D 창을 만들 수 없습니다")
        glfw.make_context_current(self.win)
        glfw.swap_interval(0)  # 속도 조절은 시뮬레이션 쪽에서 (vsync로 두 번 기다리지 않게)
        self.m, self.d = m, d
        self.scn = mujoco.MjvScene(m, maxgeom=10000)
        self.cam = mujoco.MjvCamera()
        self.opt = mujoco.MjvOption()
        self.pert = mujoco.MjvPerturb()
        self.ctx = mujoco.MjrContext(m, mujoco.mjtFontScale.mjFONTSCALE_150)
        self.home = dict(HOME_VIEW, **(view or {}))
        self.reset_view()
        self._btn = None
        self._last = (0.0, 0.0)
        self._last_click = 0.0
        glfw.set_cursor_pos_callback(self.win, self._on_move)
        glfw.set_mouse_button_callback(self.win, self._on_button)
        glfw.set_scroll_callback(self.win, self._on_scroll)
        glfw.set_key_callback(self.win, self._on_key)

    # ---- 시점 ----
    def reset_view(self):
        self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.cam.azimuth = self.home["azimuth"]
        self.cam.elevation = self.home["elevation"]
        self.cam.distance = self.home["distance"]
        self.cam.lookat[:] = self.home["lookat"]

    def _shift(self):
        return (glfw.get_key(self.win, glfw.KEY_LEFT_SHIFT) == glfw.PRESS or
                glfw.get_key(self.win, glfw.KEY_RIGHT_SHIFT) == glfw.PRESS)

    def _action(self):
        """누른 버튼 → 카메라 동작. 가운데(휠) 버튼이 화면 이동."""
        if self._btn == glfw.MOUSE_BUTTON_MIDDLE:
            return M.mjMOUSE_MOVE_H if self._shift() else M.mjMOUSE_MOVE_V
        if self._btn == glfw.MOUSE_BUTTON_RIGHT:
            return M.mjMOUSE_MOVE_H
        if self._btn == glfw.MOUSE_BUTTON_LEFT:
            return M.mjMOUSE_ROTATE_H if self._shift() else M.mjMOUSE_ROTATE_V
        return None

    def drag(self, button, dx, dy, height, shift=False):
        """마우스 드래그 한 번을 카메라에 반영 (테스트에서도 직접 부름)."""
        self._btn = button
        if shift:
            act = {glfw.MOUSE_BUTTON_MIDDLE: M.mjMOUSE_MOVE_H, glfw.MOUSE_BUTTON_RIGHT: M.mjMOUSE_MOVE_H,
                   glfw.MOUSE_BUTTON_LEFT: M.mjMOUSE_ROTATE_H}[button]
        else:
            act = self._action()
        if act is not None:
            mujoco.mjv_moveCamera(self.m, act, dx / height, dy / height, self.cam)

    def zoom(self, wheel_steps):
        """휠 앞(+) = 확대, 뒤(-) = 축소."""
        mujoco.mjv_moveCamera(self.m, M.mjMOUSE_ZOOM, 0.0, 0.05 * wheel_steps, self.cam)  # 이 버전은 +가 가까워짐(2026-09-27 실측)

    # ---- 입력 ----
    def _on_button(self, win, button, action, mods):
        x, y = glfw.get_cursor_pos(win)
        self._last = (x, y)
        if action == glfw.PRESS:
            self._btn = button
            if button == glfw.MOUSE_BUTTON_LEFT:
                now = time.time()
                if now - self._last_click < 0.3:
                    self._focus(x, y)
                self._last_click = now
        elif action == glfw.RELEASE and button == self._btn:
            self._btn = None

    def _on_move(self, win, x, y):
        if self._btn is None:
            return
        dx, dy = x - self._last[0], y - self._last[1]
        self._last = (x, y)
        _, h = glfw.get_window_size(win)
        act = self._action()
        if act is not None and h > 0:
            mujoco.mjv_moveCamera(self.m, act, dx / h, dy / h, self.cam)

    def _on_scroll(self, win, xoff, yoff):
        self.zoom(yoff)

    def _on_key(self, win, key, sc, action, mods):
        if action != glfw.PRESS:
            return
        if key == glfw.KEY_R:
            self.reset_view()
        elif key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(win, True)

    def _focus(self, x, y):
        """더블클릭한 물체를 화면 가운데로."""
        w, h = glfw.get_window_size(self.win)
        if w == 0 or h == 0:
            return
        selpnt = np.zeros(3); geomid = np.zeros(1, np.int32); flexid = np.zeros(1, np.int32); skinid = np.zeros(1, np.int32)
        try:
            body = mujoco.mjv_select(self.m, self.d, self.opt, w / h, x / w, (h - y) / h, self.scn,
                                     selpnt, geomid, flexid, skinid)
        except TypeError:  # 버전에 따라 인자 수가 다름
            return
        if body >= 0:
            self.cam.lookat[:] = selpnt

    # ---- 그리기 ----
    def is_running(self):
        return not glfw.window_should_close(self.win)

    def sync(self):
        """입력을 처리하고 현재 상태를 한 장 그린다."""
        if not self.is_running():
            return
        glfw.make_context_current(self.win)  # 화면 밖 캡처(Renderer)가 문맥을 바꿔 놓았을 수 있음
        glfw.poll_events()
        fw, fh = glfw.get_framebuffer_size(self.win)
        if fw == 0 or fh == 0:  # 최소화
            return
        vp = mujoco.MjrRect(0, 0, fw, fh)
        mujoco.mjv_updateScene(self.m, self.d, self.opt, self.pert, self.cam, mujoco.mjtCatBit.mjCAT_ALL, self.scn)
        mujoco.mjr_render(vp, self.scn, self.ctx)
        glfw.swap_buffers(self.win)

    def close(self):
        # terminate는 하지 않음 — 녹화용 화면 밖 렌더러가 종료 때 glfw를 쓰기 때문
        if self.win:
            glfw.destroy_window(self.win)
            self.win = None
