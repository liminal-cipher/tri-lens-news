// Build-time only: Node 22+ and a Chromium browser, no npm packages.
// Usage: node scripts/export_email_icons.mjs "path/to/chrome-or-msedge"
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const executable = process.argv[2];
if (!executable) throw new Error('Pass the path to a Chromium browser executable.');
const assets = resolve(dirname(fileURLToPath(import.meta.url)), '../assets/email-icons');
const profile = await mkdtemp(join(tmpdir(), 'tri-lens-icons-'));
const browser = spawn(executable, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
let socket;
try {
  const endpoint = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Browser startup timed out')), 20000);
    const fail = error => { clearTimeout(timeout); reject(error); };
    browser.once('error', fail);
    browser.once('exit', code => fail(new Error(`Browser exited: ${code}`)));
    browser.stderr.on('data', data => {
      const match = data.toString().match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) { clearTimeout(timeout); resolve(match[1]); }
    });
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let next = 0;
  const pending = new Map();
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id);
    clearTimeout(task.timeout);
    message.error ? task.reject(new Error(JSON.stringify(message.error))) : task.resolve(message.result);
  };
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++next;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)); }, 10000);
    pending.set(id, { resolve, reject, timeout });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  const cdp = (method, params) => send(method, params, sessionId);
  await cdp('Page.enable');
  await cdp('Emulation.setDeviceMetricsOverride', { width: 64, height: 64, deviceScaleFactor: 1, mobile: false });
  await cdp('Emulation.setDefaultBackgroundColorOverride', { color: { r: 0, g: 0, b: 0, a: 0 } });
  const { frameTree } = await cdp('Page.getFrameTree');
  for (const name of ['everyone', 'developers', 'researchers']) {
    const svg = await readFile(join(assets, `${name}.svg`), 'utf8');
    await cdp('Page.setDocumentContent', {
      frameId: frameTree.frame.id,
      html: `<!doctype html><style>html,body{margin:0;background:transparent}svg{display:block;width:64px;height:64px}</style>${svg}`,
    });
    const { data } = await cdp('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 64, height: 64, scale: 1 } });
    await writeFile(join(assets, `${name}.png`), Buffer.from(data, 'base64'));
    console.log(`${name}.svg -> ${name}.png (64px, transparent)`);
  }
  await send('Browser.close');
} finally {
  if (socket) socket.close();
  browser.kill();
  // Only remove the unique temporary profile created by this invocation.
  const target = resolve(profile);
  if (dirname(target) === resolve(tmpdir()) && basename(target).startsWith('tri-lens-icons-')) {
    await rm(target, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
      .catch(error => console.warn(`Temporary profile retained: ${error.message}`));
  }
}
