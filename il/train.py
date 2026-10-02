"""모방학습 2단계: 시연 데이터로 정책 학습 (GPU 있으면 GPU).
실행: .venv\\Scripts\\python il\\train.py --epochs 40
"""
import argparse
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from policy import CHUNK, Policy

ROOT = Path(__file__).resolve().parent


def chunk_targets(act, ep, k):
    """각 프레임의 「앞으로 k스텝 명령」 — 에피소드 끝을 넘으면 마지막 명령을 반복"""
    n = len(act)
    idx = np.arange(n)[:, None] + np.arange(k)[None]
    last = np.zeros(n, int)
    for e in np.unique(ep):
        w = np.where(ep == e)[0]; last[w] = w[-1]
    idx = np.minimum(idx, last[:, None])
    return act[idx]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--data", default="data/demos.npz")
    ap.add_argument("--run", default="data")
    ap.add_argument("--arch", default="ssm", choices=["ssm", "flat"])
    ap.add_argument("--limit", type=int, default=0, help="앞에서부터 시연 N개만 사용")
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    d = np.load(ROOT / args.data)
    imgs, q, act, ep = d["imgs"], d["qpos"], d["act"], d["ep"]
    if args.limit:
        keep = ep < args.limit; imgs, q, act, ep = imgs[keep], q[keep], act[keep], ep[keep]
    tgt = chunk_targets(act, ep, CHUNK)
    # 에피소드 단위로 90% 학습 / 10% 검증
    eps = np.unique(ep); rng = np.random.default_rng(0); rng.shuffle(eps)
    val_eps = set(eps[: max(1, len(eps) // 10)].tolist())
    is_val = np.array([e in val_eps for e in ep])
    model = Policy(img=imgs.shape[1], arch=args.arch).to(dev)
    model.q_mean.copy_(torch.tensor(q.mean(0))); model.q_std.copy_(torch.tensor(q.std(0) + 1e-3))
    model.a_mean.copy_(torch.tensor(act.mean(0))); model.a_std.copy_(torch.tensor(act.std(0) + 1e-3))
    T = lambda a: torch.tensor(a).to(dev)
    I_tr, Q_tr, Y_tr = T(imgs[~is_val]), T(q[~is_val]), T(tgt[~is_val])
    I_va, Q_va, Y_va = T(imgs[is_val]), T(q[is_val]), T(tgt[is_val])
    norm = lambda y: (y - model.a_mean) / model.a_std
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
    print(f"장치 {dev} · 학습 프레임 {len(Q_tr)} · 검증 {len(Q_va)} (시연 {len(eps)}개 중 {len(val_eps)}개는 검증용)")
    t0 = time.time()
    for epoch in range(args.epochs):
        model.train(); perm = torch.randperm(len(Q_tr), device=dev); tot = 0
        for i in range(0, len(perm), args.batch):
            b = perm[i:i + args.batch]
            img = I_tr[b]
            # 데이터 늘리기: 밝기만 살짝 흔듦(위치 정보는 건드리지 않음)
            img = (img.float() * torch.empty(len(b), 1, 1, 1, device=dev).uniform_(0.85, 1.15)).clamp(0, 255).to(torch.uint8)
            loss = F.l1_loss(model(img, Q_tr[b]), norm(Y_tr[b]))
            opt.zero_grad(); loss.backward(); opt.step(); tot += loss.item() * len(b)
        sched.step()
        if (epoch + 1) % 5 == 0 or epoch == 0:
            model.eval()
            with torch.no_grad():
                vl = F.l1_loss(model(I_va, Q_va), norm(Y_va)).item()
            print(f"epoch {epoch + 1:3d} · 학습 오차 {tot / len(Q_tr):.4f} · 검증 오차 {vl:.4f} · {time.time() - t0:.0f}초", flush=True)
    out = ROOT / args.run; out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "policy.pt")
    import json; (out / "config.json").write_text(json.dumps({"img": int(imgs.shape[1]), "arch": args.arch, "data": args.data, "limit": args.limit, "epochs": args.epochs, "val_loss": vl}))
    print(f"저장: il/{args.run}/policy.pt")
