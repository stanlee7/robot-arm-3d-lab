// app.html + robot_data.json + kin.js → 두 가지 결과물
//  - web/dist/robot-arm-lab.html : claude.ai 아티팩트용(본문만)
//  - docs/index.html              : GitHub Pages용(완전한 HTML 문서)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const read = (f) => fs.readFileSync(path.join(here, f), "utf8");
const data = read("robot_data.json"), kin = read("kin.js");
if (/<\/script/i.test(data + kin)) throw new Error("데이터에 </script가 있으면 안 됨");
const app = read("app.html").replace("<!--ROBOT_DATA-->", () => data).replace("/*KIN_JS*/", () => kin);
const [head, body] = app.split("<!--BODY-->");
if (!body) throw new Error("app.html에 <!--BODY--> 표시가 없음");

fs.mkdirSync(path.join(here, "dist"), { recursive: true });
fs.writeFileSync(path.join(here, "dist", "robot-arm-lab.html"), head + body);

const PAGES = "https://stanlee7.github.io/robot-arm-3d-lab/";
const desc = "하드웨어 없이 배우는 피지컬AI — 실제 저가 로봇팔 SO-ARM100과 같은 모델을 브라우저 3D에서 좌표·관절로 움직여 보는 실습실";
const standalone = `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="${desc}">
<meta property="og:type" content="website">
<meta property="og:title" content="로봇팔 3D 실습실">
<meta property="og:description" content="${desc}">
<meta property="og:url" content="${PAGES}">
<meta property="og:image" content="${PAGES}preview.png">
<meta name="twitter:card" content="summary_large_image">
<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
${head.trim()}
</head>
<body>
${body.trim()}
</body>
</html>
`;
const docs = path.join(here, "..", "docs");
fs.mkdirSync(docs, { recursive: true });
fs.writeFileSync(path.join(docs, "index.html"), standalone);
const kb = (f) => (fs.statSync(f).size / 1024).toFixed(0) + " KB";
console.log(`web/dist/robot-arm-lab.html ${kb(path.join(here, "dist", "robot-arm-lab.html"))} · docs/index.html ${kb(path.join(docs, "index.html"))}`);

// ---- 로봇 바리스타 (2026-10-02): barista.html → docs/barista.html ----
{
  const app2 = read("barista.html").replace("<!--ROBOT_DATA-->", () => data).replace("/*KIN_JS*/", () => kin);
  const [h2, b2] = app2.split("<!--BODY-->");
  const d2 = "SO-ARM100 로봇팔이 정해진 프로그램으로 커피를 만드는 3D 실습실 — 한 잔씩 vs 머신이 도는 동안 다음 일, 사이클 타임 비교";
  const page = `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="${d2}">
<meta property="og:type" content="website">
<meta property="og:title" content="로봇 바리스타 3D 실습실">
<meta property="og:description" content="${d2}">
<meta property="og:url" content="${PAGES}barista.html">
<meta property="og:image" content="${PAGES}barista.png">
<style>[hidden]{display:none!important}</style>
${h2.trim()}
</head>
<body>
${b2.trim()}
</body>
</html>
`;
  fs.writeFileSync(path.join(docs, "barista.html"), page);
  console.log(`docs/barista.html ${kb(path.join(docs, "barista.html"))}`);
}
