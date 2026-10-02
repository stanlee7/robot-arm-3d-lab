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


# ---- 컵 찾기 (로봇 바리스타, 2026-10-02) ----
# 컵은 흰색이고 윗면 가운데는 음료 색으로 바뀐다 → 흰 테두리(밝고 색 차이 작은 픽셀)의 중심 = 컵 중심.
# 흰 로봇팔과 헷갈리지 않게, 찾을 자리 주변(반경 3.5cm)만 본다. 팔은 「보는 자세」로 접혀 있어야 한다.
CUP_TOP = 0.04


def to_pixel(camera, x, y, z=CUP_TOP):
    d = camera.pos[2] - z
    return camera.w / 2 + (x - camera.pos[0]) * camera.f / d, camera.h / 2 - (y - camera.pos[1]) * camera.f / d


def _label(mask):
    """연결 영역 번호 매기기 (4-이웃). blobs()와 같은 방식이지만 픽셀 소속을 돌려준다"""
    lab = np.zeros(mask.shape, int)
    n = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if lab[y0, x0]:
            continue
        n += 1
        stack = [(y0, x0)]; lab[y0, x0] = n
        while stack:
            y, x = stack.pop()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = n; stack.append((ny, nx))
    return lab, n


def find_cup_near(image, xy, radius=0.035, camera=None, cup_r=0.015):
    """자리 xy 근처 컵의 중심 좌표(m). 없으면 None.
    흰 테두리의 바깥 경계에 반지름을 아는 원을 맞춘다 → 노즐이 컵 일부를 가려도 남은 호로 중심을 찾는다(2026-10-02:
    단순 평균은 노즐 그늘 때문에 4~6mm 치우침)."""
    camera = camera or TopCamera(width=image.shape[1], height=image.shape[0])
    u0, v0 = to_pixel(camera, xy[0], xy[1])
    k = camera.f / (camera.pos[2] - CUP_TOP)
    rpx, R = radius * k, cup_r * k
    hgt, wid = image.shape[:2]
    yy, xx = np.mgrid[0:hgt, 0:wid]
    near = (xx - u0) ** 2 + (yy - v0) ** 2 < rpx ** 2
    im = image.astype(int)
    hi, lo = im.max(axis=2), im.min(axis=2)
    white = near & (lo > 215) & (hi - lo < 25)
    if white.sum() < 40:
        return None
    # 흰 덩어리가 여럿이면(접힌 로봇팔 끝 등) 자리 중심에 가장 가까운 큰 덩어리만 (2026-10-02)
    lab, n = _label(white)
    if n > 1:
        best, bd = 0, 1e9
        for i in range(1, n + 1):
            vv, uu = np.nonzero(lab == i)
            if len(vv) < 40:
                continue
            dist = np.hypot(uu.mean() - u0, vv.mean() - v0)
            if dist < bd:
                best, bd = i, dist
        if best == 0:
            return None
        white = lab == best
    # 경계 픽셀: 흰데 이웃 중 하나라도 흰색이 아님
    pad = np.pad(white, 1)
    inner = pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
    edge = white & ~inner
    v, u = np.nonzero(edge)
    pts = np.stack([u, v], 1).astype(float)
    c = pts.mean(0)
    for _ in range(30):  # 반지름 R인 원을 바깥 경계에 맞추기(안쪽 음료 경계는 제외)
        d = np.linalg.norm(pts - c, axis=1) + 1e-9
        outer = d > 0.85 * R
        if outer.sum() < 15:
            return None
        q = pts[outer]; dq = d[outer][:, None]
        c = (q - R * (q - c) / dq).mean(0)
    resid = np.abs(np.linalg.norm(pts[outer] - c, axis=1) - R).mean()
    if resid > 2.5:  # 원 모양이 아니면(반사·다른 물체) 컵이 아님
        return None
    return camera.to_world(c[0], c[1], z=CUP_TOP)[:2]
