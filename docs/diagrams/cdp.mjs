// 최소한의 Chrome DevTools 프로토콜 드라이버입니다 (Node 22 이상: 내장 WebSocket, fetch).
//
//   node docs/diagrams/cdp.mjs <jobs.json>
//
// jobs.json: {"width":1600,"height":900,"scale":1.5,"shots":[
//   {"url": "...", "out": "/abs/path.png", "height": 900, "wait": 8000,
//    "eval": ["js", ...], "after": 2000}]}
// "eval" 조각은 "wait" ms 뒤 페이지에서 실행됩니다(UI 버튼 클릭용). 결과를 출력하므로
// DOM 확인 용도로도 쓸 수 있습니다.
// 스크린샷 파일은 이 프로세스가 쓰므로, snap으로 제한된 Chromium은 저장소에 접근하지
// 않습니다.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const port = 9333;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// $HOME 아래의 숨김이 아닌 폴더를 씁니다: snap으로 설치한 Chromium은 다른 위치를 쓸 수 없습니다
const profile = mkdtempSync(join(homedir(), "cdp-profile-"));
const chrome = spawn(
  process.env.CHROMIUM || "chromium",
  [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--hide-scrollbars",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    `--window-size=${jobs.width},${jobs.height}`,
    `--force-device-scale-factor=${jobs.scale ?? 1}`,
    "about:blank",
  ],
  { stdio: "ignore" },
);

try {
  let target;
  for (let i = 0; i < 150 && !target; i++) {
    await sleep(200);
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      target = list.find((t) => t.type === "page");
    } catch {}
  }
  if (!target) throw new Error("chromium did not start");

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r, j) => ((ws.onopen = r), (ws.onerror = j)));
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, (msg) => (msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)));
      ws.send(JSON.stringify({ id, method, params }));
    });

  await send("Page.enable");
  for (const shot of jobs.shots) {
    // 화면별 뷰포트 높이입니다(지정하지 않으면 창 크기를 씁니다)
    await send("Emulation.setDeviceMetricsOverride", {
      width: jobs.width,
      height: shot.height ?? jobs.height,
      deviceScaleFactor: jobs.scale ?? 1,
      mobile: false,
    });
    await send("Page.navigate", { url: shot.url });
    await sleep(shot.wait ?? 8000);
    for (const js of shot.eval ?? []) {
      const r = await send("Runtime.evaluate", { expression: js, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) console.log("eval error:", r.exceptionDetails.text);
      else if (r.result.value !== undefined) console.log(typeof r.result.value === "string" ? r.result.value : JSON.stringify(r.result.value));
      await sleep(400);
    }
    await sleep(shot.after ?? 0);
    if (shot.out) {
      const { data } = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(shot.out, Buffer.from(data, "base64"));
      console.log(`wrote ${shot.out}`);
    }
  }
  ws.close();
} finally {
  chrome.kill();
  await sleep(500);
  rmSync(profile, { recursive: true, force: true });
}
