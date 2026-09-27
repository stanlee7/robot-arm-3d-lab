"""보기: 카메라 사진 한 장에서 색깔 큐브를 찾아 작업대 좌표(m)로 바꾼다.

시뮬레이션 정답값을 쓰지 않고 **사진만** 쓴다. 실물 로봇에서는 USB 카메라 사진을 넣으면 된다
(그때는 카메라 위치·화각을 실제 값으로 바꾸거나, 작업대 네 모서리를 찍어 보정).
의존성: numpy만 (OpenCV 없이 색 범위 + 연결 영역).
"""
import numpy as np

# 색 판정: 절대값 대신 「한 채널이 다른 채널보다 얼마나 센가」 — 조명이 밝아져도 버틴다.
# (2026-09-27: 초록 큐브가 조명 때문에 (81,255,147)로 찍혀 절대 기준 b<140에서 놓침 → 이 방식으로 바꿈)
# 회색 작업대·흰 로봇(세 채널 비슷)과 노란 안전선(R·G 둘 다 높음)은 자동으로 빠진다
COLORS = {
    "red":   lambda r, g, b: (r > 170) & (r - g > 80) & (r - b > 80),
    "blue":  lambda r, g, b: (b > 170) & (b - r > 80) & (b - g > 40),
    "green": lambda r, g, b: (g > 170) & (g - r > 80) & (g - b > 50),
}


def blobs(mask, min_px=60):
    """연결된 픽셀 덩어리들 → [(픽셀 수, 중심 u, 중심 v)]. 큐브 여러 개도 구분"""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    out = []
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack, pts = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop(); pts.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True; stack.append((ny, nx))
        if len(pts) >= min_px:
            p = np.array(pts)
            out.append((len(pts), float(p[:, 1].mean()), float(p[:, 0].mean())))
    return out


class TopCamera:
    """위에서 아래로 보는 카메라의 픽셀 ↔ 작업대 좌표 변환 (핀홀 모델)"""

    def __init__(self, pos=(0.0, -0.2, 0.7), fovy_deg=45.0, width=640, height=480):
        self.pos, self.w, self.h = np.array(pos), width, height
        self.f = (height / 2) / np.tan(np.radians(fovy_deg) / 2)

    def to_world(self, u, v, z=0.015):
        d = self.pos[2] - z  # 카메라에서 큐브 윗면이 아니라 중심 높이까지
        x = self.pos[0] + (u - self.w / 2) / self.f * d
        y = self.pos[1] - (v - self.h / 2) / self.f * d
        return np.array([x, y, z])


def find_cubes(image, camera=None):
    """사진 → [{"color", "xyz", "px"}]"""
    camera = camera or TopCamera(width=image.shape[1], height=image.shape[0])
    r, g, b = (image[..., i].astype(int) for i in range(3))
    found = []
    for color, rule in COLORS.items():
        for n, u, v in blobs(rule(r, g, b)):
            # 위에서 본 큐브는 윗면 중심 → 윗면 높이(0.03)로 변환해야 원근 오차가 적다
            xyz = camera.to_world(u, v, z=0.03)
            xyz[2] = 0.015
            found.append({"color": color, "xyz": xyz, "px": n})
    return found
