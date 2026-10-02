"""README용 결과 그림(result_chart.png)과 같은 위치에서 A·C 비교 영상(compare.gif) 만들기.
eval 결과(data/result.json)와 학습된 모델(data/run)이 있어야 한다."""
import json
import numpy as np, torch, mujoco
from PIL import Image, ImageDraw, ImageFont
import cup_pick as P
from driver import SimDriver
from policy import Policy

r = json.load(open('data/result.json', encoding='utf-8'))
dist, res = r['dist_mm'], r['res']
F = lambda s: ImageFont.truetype('C:/Windows/Fonts/malgunbd.ttf', s)
W, H = 1000, 520; im = Image.new('RGB', (W, H), '#0f1315'); g = ImageDraw.Draw(im)
g.text((40, 28), '컵 집기 성공률 · 컵이 보관대에서 어긋난 거리별 (같은 50개 위치)', font=F(24), fill='#e6ebed')
bins = [(0, 10, '0~10mm'), (10, 20, '10~20mm'), (20, 36, '20mm 이상')]
cols = {'A': ('#6d7880', 'A 고정 좌표'), 'B': ('#3cc07e', 'B 카메라 규칙'), 'C': ('#ffc21a', 'C 피지컬 AI')}
x0, y0, ch = 90, 440, 300
for bi, (lo, hi, lab) in enumerate(bins):
    idx = [i for i, d in enumerate(dist) if lo <= d < hi]
    for k, name in enumerate('ABC'):
        rate = sum(res[name][i] for i in idx) / len(idx)
        x = x0 + bi * 300 + k * 80; h = max(2, int(ch * rate))
        g.rectangle([x, y0 - h, x + 62, y0], fill=cols[name][0])
        g.text((x + 31, y0 - h - 26), f'{round(rate * 100)}%', font=F(18), fill='#e6ebed', anchor='mt')
    g.text((x0 + bi * 300 + 111, y0 + 14), f'{lab} ({len(idx)}번)', font=F(18), fill='#98a4aa', anchor='mt')
lx = 40
for name in 'ABC':
    g.rectangle([lx, 76, lx + 18, 94], fill=cols[name][0]); t = f"{cols[name][1]} {sum(res[name])}/50"
    g.text((lx + 26, 74), t, font=F(18), fill='#e6ebed'); lx += 26 + g.textlength(t, font=F(18)) + 30
im.save('result_chart.png'); print('chart ok')

pick = [i for i, d in enumerate(dist) if not res['A'][i] and res['C'][i] and d > 15]
rng = np.random.default_rng(1234); offs = [P.random_off(rng) for _ in range(50)]
off = offs[pick[0]]; print('offset mm', round(dist[pick[0]], 1))
dev = 'cuda' if torch.cuda.is_available() else 'cpu'
cfg = json.load(open('data/run/config.json')); m = Policy(img=cfg['img'], arch=cfg['arch']).to(dev)
m.load_state_dict(torch.load('data/run/policy.pt', map_location=dev)); m.eval()
drv = SimDriver(); ren = mujoco.Renderer(drv.m, 240, 320)
def shot():
    ren.update_scene(drv.d, camera='cafe'); return ren.render()
frames = {'A': [], 'C': []}
class Sink:
    def append(self, f): frames['A'].append(shot())
P.setup(drv, off); P.quiet(drv); drv.arm.render = lambda *a, **k: 1; drv.arm.frames = Sink()
P.run_fixed(drv); drv.arm.hold(0.5); okA = P.lifted(drv)
P.setup(drv, off)
orig = mujoco.mj_step; cnt = [0]
def step(mm, dd):
    orig(mm, dd); cnt[0] += 1
    if cnt[0] % 25 == 0: frames['C'].append(shot())
P.mujoco.mj_step = step
P.run_ai(drv, m, dev); okC = P.lifted(drv); P.mujoco.mj_step = orig
print('A', okA, 'C', okC, len(frames['A']), len(frames['C']))
n = max(len(frames['A']), len(frames['C'])); out = []
for i in range(0, n, 2):
    cv = Image.new('RGB', (660, 290), '#0f1315'); d = ImageDraw.Draw(cv)
    for j, (k, lab, col) in enumerate((('A', 'A 고정 좌표 (프로그램)', '#98a4aa'), ('C', 'C 피지컬 AI (모방학습)', '#ffc21a'))):
        fr = frames[k][min(i, len(frames[k]) - 1)]; cv.paste(Image.fromarray(fr), (10 + j * 330, 40)); d.text((10 + j * 330, 10), lab, font=F(17), fill=col)
    out.append(cv)
end = out[-1].copy(); d = ImageDraw.Draw(end)
for j, ok in enumerate((okA, okC)):
    d.rounded_rectangle([20 + j * 330, 236, 150 + j * 330, 272], 8, fill='#3cc07e' if ok else '#ef6a64'); d.text((85 + j * 330, 254), 'O  집었음' if ok else 'X  못 집음', font=F(18), fill='#0f1315', anchor='mm')
out += [end] * 15
out[0].save('compare.gif', save_all=True, append_images=out[1:], duration=100, loop=0, optimize=True)
import os; print('gif', os.path.getsize('compare.gif') // 1024, 'KB')
