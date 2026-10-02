"""모방학습 정책 — 사진(64×64) + 관절 6개 → 앞으로 1초(10스텝)의 관절 명령 묶음.
ACT의 핵심 아이디어인 「동작 묶음 예측(action chunking)」을 작은 CNN으로 단순하게 구현했다.
사진에 좌표 채널 2개를 붙여(CoordConv) 큐브가 「어디에」 있는지 배우기 쉽게 했다.
"""
import torch
import torch.nn as nn

CHUNK = 10  # 0.1초 × 10 = 1초 앞까지 예측


class Policy(nn.Module):
    def __init__(self, img=96, chunk=CHUNK, arch="ssm"):
        super().__init__()
        self.chunk, self.arch = chunk, arch
        ys, xs = torch.meshgrid(torch.linspace(-1, 1, img), torch.linspace(-1, 1, img), indexing="ij")
        self.register_buffer("coords", torch.stack([xs, ys])[None])
        c = lambda i, o: nn.Sequential(nn.Conv2d(i, o, 3, 2, 1), nn.GroupNorm(8, o), nn.GELU())
        if arch == "flat":  # 2차 방식: 특징 지도를 펴서 전결합
            self.cnn = nn.Sequential(c(5, 32), c(32, 64), c(64, 128), c(128, 128))
            self.flat_fc = nn.Sequential(nn.Flatten(), nn.Linear(128 * (img // 16) ** 2, 256), nn.GELU())
        else:               # 3차 방식: spatial softmax 특징점
            self.cnn = nn.Sequential(c(5, 32), c(32, 64), c(64, 64), nn.Conv2d(64, 32, 3, 1, 1))
        s = img // 8
        yy, xx = torch.meshgrid(torch.linspace(-1, 1, s), torch.linspace(-1, 1, s), indexing="ij")
        self.register_buffer("kx", xx.reshape(-1)); self.register_buffer("ky", yy.reshape(-1))
        self.img_fc = nn.Sequential(nn.Linear(32 * 2, 256), nn.GELU())
        self.q_fc = nn.Sequential(nn.Linear(6, 64), nn.GELU())
        self.head = nn.Sequential(nn.Linear(256 + 64, 512), nn.GELU(), nn.Linear(512, 512), nn.GELU(), nn.Linear(512, chunk * 6))
        # 정규화 값 (학습 데이터에서 채움)
        for n in ("q_mean", "q_std", "a_mean", "a_std"):
            self.register_buffer(n, torch.zeros(6) if "mean" in n else torch.ones(6))

    def forward(self, img_u8, q):
        x = img_u8.float().permute(0, 3, 1, 2) / 255.0
        x = torch.cat([x, self.coords.expand(x.shape[0], -1, -1, -1)], 1)
        h = self.cnn(x)
        if self.arch == "flat":
            f = torch.cat([self.flat_fc(h), self.q_fc((q - self.q_mean) / self.q_std)], 1)
            return self.head(f).view(-1, self.chunk, 6)
        p = torch.softmax(h.flatten(2), -1)               # spatial softmax: 특징마다 「어디가 가장 센가」
        kp = torch.cat([(p * self.kx).sum(-1), (p * self.ky).sum(-1)], 1)  # 특징점 32개의 (x, y)
        f = torch.cat([self.img_fc(kp), self.q_fc((q - self.q_mean) / self.q_std)], 1)
        return self.head(f).view(-1, self.chunk, 6)  # 정규화된 동작

    def act(self, img_u8, q):
        """정규화를 풀어 실제 관절 명령(라디안) 묶음으로"""
        return self.forward(img_u8, q) * self.a_std + self.a_mean
