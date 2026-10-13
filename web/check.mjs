// 한 번 점검: docs/index.html을 헤드리스 크롬으로 열어 콘솔 오류·좌표 이동·집어 옮기기를 확인하고
// 공유 미리보기(docs/preview.png)와 휴대폰 화면 캡처를 남긴다.
// 필요: playwright-core + chromium_headless_shell (PLAYWRIGHT_CORE 환경변수로 경로 지정 가능)
import http from "node:http"; import fs from "node:fs"; import path from "node:path"; import os from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const pwPath = process.env.PLAYWRIGHT_CORE || "playwright-core";
const { chromium } = await import(pwPath.endsWith(".mjs") ? pathToFileURL(pwPath).href : pwPath);
const html = fs.readFileSync(path.join(here, "..", "docs", "index.html"));
const PORT = +(process.env.CHECK_PORT || 8765);
const bhtml = fs.readFileSync(path.join(here, "..", "docs", "barista.html"));
const srv = http.createServer((q, s) => { s.writeHead(200, { "content-type": "text/html; charset=utf-8" }); s.end(q.url.startsWith("/barista") ? bhtml : html); }).listen(PORT);
let exe;
try {
  const base = path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), ".cache"), "ms-playwright");
  const dir = fs.readdirSync(base).filter((d) => /^chromium_headless_shell-\d+$/.test(d)).sort().reverse()[0];
  const sub = fs.readdirSync(path.join(base, dir))[0];
  exe = path.join(base, dir, sub, process.platform === "win32" ? "chrome-headless-shell.exe" : "chrome-headless-shell");
} catch { exe = undefined; }
const b = await chromium.launch({ executablePath: exe, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errs = [];
for (const [w, h, name] of [[1280, 720, "desktop"], [400, 860, "phone"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  p.on("console", (m) => { if (m.type() === "error") errs.push(`${name}: ${m.text()}`); });
  p.on("pageerror", (e) => errs.push(`${name}: ${e.message}`));
  await p.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
  await p.waitForFunction(() => window.__lab?.ready, null, { timeout: 60000 });
  await p.waitForTimeout(1200);
  if (name === "desktop") {
    const g = await p.evaluate(async () => { const r = await window.__lab.go(5, -22, 10); return r[0]; });
    console.log(`좌표 이동 (5, -22, 10)cm → 도달 오차 ${(g.reach * 100).toFixed(2)}cm`);
    await p.evaluate(() => window.__lab.pickPlaceOnce());
    const st = await p.evaluate(() => window.__lab.state());
    console.log(`집어 옮기기 → 목표 중심까지 ${(st.dist * 100).toFixed(2)}cm`);
    await p.evaluate(async () => { const c = window.__lab.state().cube; await window.__lab.go(c[0] * 100 - 6, c[1] * 100 - 4, 9); });
    await p.waitForTimeout(400);
    await p.screenshot({ path: path.join(here, "..", "docs", "preview.png") });
  } else {
    await p.screenshot({ path: path.join(os.tmpdir(), "robotlab_phone.png") });
  }
  await p.close();
}
// 로봇 바리스타: 3잔을 두 방식으로 끝까지 돌려 번호 칸 1, 2, 3에 모두 놓이는지 확인
for (const [w, h, name] of [[1280, 720, "barista-desktop"], [400, 860, "barista-phone"]]) {
  const p = await b.newPage({ viewport: { width: w, height: h } });
  p.on("console", (m) => { if (m.type() === "error") errs.push(`${name}: ${m.text()}`); });
  p.on("pageerror", (e) => errs.push(`${name}: ${e.message}`));
  await p.goto(`http://localhost:${PORT}/barista.html`, { waitUntil: "networkidle" });
  await p.waitForFunction(() => window.__barista, null, { timeout: 60000 });
  await p.evaluate(() => { window.__barista.manual(true); window.__barista.speed(1); });
  const runAll = async (m) => {
    await p.evaluate((m) => window.__barista.run3(m), m);
    for (let i = 0; i < 400; i++) { const st = await p.evaluate(() => window.__barista.state()); if (!st.busy && st.orders.length && st.orders.every((o) => o.s === "완료")) return st; await p.evaluate(() => window.__barista.advance(1)); }
    throw new Error(`바리스타 ${m}: 400초 안에 끝나지 않음`);
  };
  if (name === "barista-desktop") {
    for (const m of ["seq", "pipe"]) {
      const st = await runAll(m);
      const cub = st.orders.map((o) => o.cubby).sort().join(",");
      console.log(`바리스타 ${m === "seq" ? "한 잔씩" : "동시 진행"} → ${st.clock.toFixed(1)}초, 칸 ${cub}, 화면 「${st.board}」`);
      if (cub !== "1,2,3") errs.push(`${name}: 3잔이 칸 1, 2, 3에 나뉘어 놓이지 않음 (${cub})`);
    }
    // 미리보기: 3잔 중 첫 잔을 칸으로 뻗어 놓는 장면 근처
    await p.evaluate(() => window.__barista.run3("seq"));
    for (let i = 0; i < 300; i++) { const st = await p.evaluate(() => window.__barista.state()); if (st.cubbies.some(Boolean)) break; await p.evaluate(() => window.__barista.advance(0.2)); }
    await p.evaluate(() => window.__barista.advance(0.6));
    await p.screenshot({ path: path.join(here, "..", "docs", "barista.png") });
  } else {
    await runAll("seq");
    await p.screenshot({ path: path.join(os.tmpdir(), "barista_phone.png"), fullPage: true });
  }
  await p.close();
}
await b.close(); srv.close();
console.log(errs.length ? "오류:\n" + errs.join("\n") : "콘솔 오류 없음");
