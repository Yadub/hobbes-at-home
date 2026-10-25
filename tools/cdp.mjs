// Scripted headless-Chrome session: node tools/cdp.mjs <outdir> <WxH[m]> <steps.json>
// steps: [{"go": url} | {"js": "expr"} | {"key": "o"} | {"wait": ms} | {"shot": "name"} | {"dark": true|false}]
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";

const [outdir, size, stepsFile] = process.argv.slice(2);
const steps = JSON.parse(readFileSync(stepsFile, "utf8"));
const mobile = size.endsWith("m");
const [W, H] = size.replace("m", "").split("x").map(Number);
mkdirSync(outdir, { recursive: true });
const port = 9400 + Math.floor(Math.random() * 500);
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", [
  "--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`, "--no-first-run",
  `--user-data-dir=${outdir}/.profile`, "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 50 && !wsUrl; i++) {
  try { wsUrl = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page")?.webSocketDebuggerUrl; }
  catch { await sleep(200); }
}
const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const pending = new Map(), events = [];
ws.addEventListener("message", (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); } else if (msg.method) events.push(msg);
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Runtime.enable"); await send("Log.enable"); await send("Page.enable"); await send("Network.enable");
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: mobile ? 2 : 1, mobile });
if (mobile) await send("Emulation.setTouchEmulationEnabled", { enabled: true });
const out = [];
for (const s of steps) {
  if (s.go) { await send("Page.navigate", { url: s.go }); await sleep(s.wait ?? 3500); }
  else if (s.js) { const r = await send("Runtime.evaluate", { expression: s.js, awaitPromise: true, returnByValue: true }); out.push({ js: s.js.slice(0, 60), value: r.result?.result?.value, err: r.result?.exceptionDetails?.text }); await sleep(s.wait ?? 800); }
  else if (s.key) {
    const vk = { Escape: 27, Enter: 13, Tab: 9, ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40 }[s.key] ?? (s.key.length === 1 ? s.key.toUpperCase().charCodeAt(0) : 0);
    for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key: s.key, text: type === "keyDown" ? (s.key === "Enter" ? "\r" : s.key.length === 1 ? s.key : undefined) : undefined, code: s.code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers: s.mod || 0 });
    await sleep(s.wait ?? 900);
  }
  else if ("dark" in s) await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: s.dark ? "dark" : "light" }] });
  else if (s.wait) await sleep(s.wait);
  else if (s.shot) {
    const m = await send("Page.getLayoutMetrics");
    const ch = s.full ? Math.min(4000, Math.ceil(m.result.cssContentSize.height)) : H;
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: !!s.full, clip: { x: 0, y: 0, width: W, height: ch, scale: 1 } });
    writeFileSync(`${outdir}/${s.shot}.png`, Buffer.from(shot.result.data, "base64"));
    const docW = Math.ceil(m.result.cssContentSize.width);
    out.push({ shot: s.shot, overflow: docW > W ? docW : null });
  }
}
const errs = events.filter((e) => e.method === "Runtime.exceptionThrown" || (e.method === "Log.entryAdded" && e.params.entry.level === "error")
  || (e.method === "Network.responseReceived" && e.params.response.status >= 400))
  .map((e) => e.method === "Runtime.exceptionThrown" ? "EXC " + (e.params.exceptionDetails.exception?.description || e.params.exceptionDetails.text).slice(0, 300)
    : e.method === "Log.entryAdded" ? "LOG " + e.params.entry.text.slice(0, 200) + " " + (e.params.entry.url || "") : `HTTP ${e.params.response.status} ${e.params.response.url}`);
console.log(JSON.stringify({ out, errors: errs }, null, 1));
ws.close(); chrome.kill(); process.exit(0);
