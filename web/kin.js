// 로봇팔 계산 코어 — 브라우저와 node에서 같이 쓴다 (화면·three.js 없음).
// 관절각 → 몸체 위치·자세(순기구학), 손끝 위치, 손끝 목표 → 관절각(역기구학).
// 계산 방식은 sim/robot.py(MuJoCo)와 같다: 몸체 = 부모 × 이동(pos) × 회전(quat) × 관절 회전.
(function (root) {
  "use strict";
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
  const norm = (a) => Math.hypot(a[0], a[1], a[2]);
  const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
  // 쿼터니언 [w, x, y, z] (MuJoCo 순서)
  const qmul = (a, b) => [
    a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
    a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
    a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
    a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0],
  ];
  const qrot = (q, v) => {
    const [w, x, y, z] = q;
    const tx = 2 * (y * v[2] - z * v[1]), ty = 2 * (z * v[0] - x * v[2]), tz = 2 * (x * v[1] - y * v[0]);
    return [v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx)];
  };
  const qaxis = (axis, ang) => {
    const s = Math.sin(ang / 2);
    return [Math.cos(ang / 2), axis[0] * s, axis[1] * s, axis[2] * s];
  };

  function makeKin(D) {
    const order = D.joint_order; // Rotation, Pitch, Elbow, Wrist_Pitch, Wrist_Roll, Jaw
    const jointOf = {};
    D.joints.forEach((j) => { jointOf[j.body] = Object.assign({}, j, { idx: order.indexOf(j.name) }); });
    const ranges = order.map((n) => D.joints.find((j) => j.name === n).range);
    const HOME = D.home.slice();

    // 순기구학: 관절각 6개 → {몸체이름: {p: 위치, r: 자세}}
    function fk(q) {
      const F = { world: { p: [0, 0, 0], r: [1, 0, 0, 0] } };
      for (const b of D.bodies) { // 부모가 먼저 나오는 순서(MuJoCo 순서)
        const par = F[b.parent];
        let p = add(par.p, qrot(par.r, b.pos));
        let r = qmul(par.r, b.quat);
        const j = jointOf[b.name];
        if (j) { // 경첩 관절: 축(몸체 좌표) 둘레로 회전, 기준점 j.pos는 제자리
          const jr = qaxis(j.axis, q[j.idx]);
          p = add(p, qrot(r, sub(j.pos, qrot(jr, j.pos))));
          r = qmul(r, jr);
        }
        F[b.name] = { p, r };
      }
      return F;
    }
    const point = (F, body, local) => add(F[body].p, qrot(F[body].r, local));
    // 손끝 = 두 집게 패드(pad_2)의 가운데 (sim/robot.py의 tip과 같음)
    function tipOf(F) {
      const a = D.pads.fixed_jaw_pad_2, b = D.pads.moving_jaw_pad_2;
      return mid(point(F, a.body, a.pos), point(F, b.body, b.pos));
    }
    const tip = (q) => tipOf(fk(q));

    // 역기구학: 여러 시작 자세에서 풀어 가장 가까운 답 (접힌 자세에서 갇히는 문제 방지)
    const SEEDS = [null, HOME.slice(0, 5), [0, -1.2, 1.2, 1.57, -1.57], [0, -1.8, 2.0, 1.2, -1.57]];
    function ikFrom(goal, q0, seed) {
      const q = q0.slice();
      if (seed) {
        for (let k = 0; k < 5; k++) q[k] = seed[k];
        q[0] = Math.atan2(goal[0], -goal[1]);
      }
      const h = 1e-6;
      for (let it = 0; it < 300; it++) {
        const p = tip(q);
        const e = sub(goal, p);
        if (norm(e) < 1e-3) break;
        const J = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
        for (let k = 0; k < 3; k++) {
          const qq = q.slice(); qq[k] += h;
          const pk = tip(qq);
          for (let i = 0; i < 3; i++) J[i][k] = (pk[i] - p[i]) / h;
        }
        // dq = Jᵀ (J Jᵀ + λI)⁻¹ e
        const A = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
        for (let i = 0; i < 3; i++) for (let k = 0; k < 3; k++) {
          A[i][k] = J[i][0] * J[k][0] + J[i][1] * J[k][1] + J[i][2] * J[k][2] + (i === k ? 1e-4 : 0);
        }
        const s = solve3(A, e);
        for (let k = 0; k < 3; k++) {
          const dq = J[0][k] * s[0] + J[1][k] * s[1] + J[2][k] * s[2];
          q[k] = clamp(q[k] + 0.5 * dq, ranges[k][0], ranges[k][1]);
        }
        // 손목: 어깨·팔꿈치 각도의 합을 상쇄해 집게가 바닥을 보게
        q[3] = clamp(-(q[1] + q[2]) + 1.57, -1.66, 1.66);
      }
      return { q: q.slice(0, 5), err: norm(sub(goal, tip(q))) };
    }
    function ik(goal, qNow) {
      let best = null;
      for (const sd of SEEDS) {
        const r = ikFrom(goal, qNow, sd);
        if (!best || r.err < best.err) best = r;
        if (r.err < 1.5e-3) break;
      }
      return best;
    }
    return { fk, tip, tipOf, point, ik, ranges, HOME, order };
  }

  function solve3(A, b) { // 3x3 연립방정식 (가우스 소거)
    const M = A.map((row, i) => row.concat([b[i]]));
    for (let c = 0; c < 3; c++) {
      let piv = c;
      for (let r = c + 1; r < 3; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
      [M[c], M[piv]] = [M[piv], M[c]];
      for (let r = 0; r < 3; r++) {
        if (r === c) continue;
        const f = M[r][c] / M[c][c];
        for (let k = c; k < 4; k++) M[r][k] -= f * M[c][k];
      }
    }
    return [M[0][3] / M[0][0], M[1][3] / M[1][1], M[2][3] / M[2][2]];
  }

  const api = { makeKin, qmul, qrot, qaxis, add, sub, norm };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RobotKin = api;
})(typeof window !== "undefined" ? window : globalThis);
