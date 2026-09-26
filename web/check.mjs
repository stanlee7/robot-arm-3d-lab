// 한 번 점검: docs/index.html을 헤드리스 크롬으로 열어 콘솔 오류·좌표 이동·집어 옮기기를 확인하고
// 공유 미리보기(docs/preview.png)와 휴대폰 화면 캡처를 남긴다.
// 필요: playwright-core + chromium_headless_shell (PLAYWRIGHT_CORE 환경변수로 경로 지정 가능)
import http from "node:http"; import fs from "node:fs"; import path from "node:path"; import os from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const pwPath = process.env.PLAYWRIGHT_CORE || "playwright-core";
const { chromium } = await import(pwPath.endsWith(".mjs") ? pathToFileURL(pwPath).href : pwPath);
const html = fs.readFileSync(path.join(here, "..", "docs", "index.html"));
const srv = http.createServer((q, s) => { s.writeHead(200, { "content-type": "text/html; charset=utf-8" }); s.end(html); }).listen(8765);
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
  await p.goto("http://localhost:8765/", { waitUntil: "networkidle" });
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
await b.close(); srv.close();
console.log(errs.length ? "오류:\n" + errs.join("\n") : "콘솔 오류 없음");
