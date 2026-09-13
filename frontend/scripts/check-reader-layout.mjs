// Run against a disposable Chrome profile with remote debugging and an authenticated
// reader tab: node scripts/check-reader-layout.mjs. No login secrets are read or saved.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';

const browser = process.env.READER_BROWSER_URL || 'http://127.0.0.1:9223';
const targets = await (await fetch(`${browser}/json`)).json();
const source = targets.find(t => t.type === 'page' && new URL(t.url).pathname.startsWith('/reader/'));
assert(source, 'Open an authenticated /reader/ page in the test browser first.');
const target = source;
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener('open', resolve, {once:true}));
let nextId = 0;
const pending = new Map();
ws.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  const request = pending.get(message.id);
  if (!request) return;
  pending.delete(message.id);
  clearTimeout(request.timer);
  if (message.error) request.reject(new Error(message.error.message));
  else request.resolve(message.result);
});
const call = (method, params = {}) => new Promise((resolve,reject) => {
  const id = ++nextId;
  const timer = setTimeout(() => {pending.delete(id); reject(new Error(`Timed out: ${method}`));}, 15000);
  pending.set(id, {resolve,reject,timer});
  ws.send(JSON.stringify({id,method,params}));
});
const evaluate = async expression => {
  const result = await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
};
const rects = `(() => {
  const rect = s => { const e = document.querySelector(s); if (!e) return null;
    const {x,y,width,height,right,bottom} = e.getBoundingClientRect(); return {x,y,width,height,right,bottom}; };
  return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,
    layout:rect('.reader-layout'),pdf:rect('.pdf-reading'),frame:rect('.pdf-viewer-container'),panel:rect('.assistant-panel')};
})()`;
const pause = () => new Promise(resolve => setTimeout(resolve, 250));
try {
  for (let i=0;i<60 && !await evaluate(`Boolean(document.querySelector('.pdfViewer .page'))`);i++) await pause();
  assert(await evaluate(`Boolean(document.querySelector('.pdfViewer .page'))`), 'The real PDF must load.');
  for (const width of [1600,1100,768,390]) {
    await call('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
    // Reproduces the former directory-close bug before the directory is removed.
    await evaluate(`[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='目录')?.click()`);
    await pause();
    const closed = await evaluate(rects);
    assert(closed.pdf.width >= width * .95, `Reading area must fill ${width}px viewport: ${JSON.stringify(closed)}`);
    assert(closed.frame.width >= width * .9, 'PDF must not occupy an empty sidebar column.');
    assert(closed.scrollWidth <= width + 1, 'No horizontal page overflow.');
    assert(!await evaluate(`Boolean(document.querySelector('.outline-rail'))`), 'No outer directory rail.');
    assert(!await evaluate(`[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='目录')`), 'No outer directory toggle.');
    await evaluate(`window.__layoutFrame = document.querySelector('.pdfViewer .page'); document.querySelector('[aria-label="全文提问"]').click()`);
    await pause();
    const opened = await evaluate(rects);
    assert(opened.panel && opened.panel.right <= width + 1 && opened.panel.width >= 280, 'Question panel must be visible.');
    assert(opened.panel.y >= opened.layout.y - 1 && opened.panel.bottom <= 1001, 'Panel must fit below the toolbar.');
    if (width > 760) assert(Math.abs(opened.pdf.width + opened.panel.width - opened.layout.width) <= 2, 'Only paper and active panel occupy desktop width.');
    assert(await evaluate(`window.__layoutFrame === document.querySelector('.pdfViewer .page')`), 'Opening a panel must not reload the PDF.');
    if (process.env.READER_SCREENSHOT_PREFIX && width === 1600) {
      const shot = await call('Page.captureScreenshot',{format:'png'});
      await writeFile(`${process.env.READER_SCREENSHOT_PREFIX}-ask.png`,Buffer.from(shot.data,'base64'));
    }
    await evaluate(`document.querySelector('[aria-label="关闭提问"]').click()`);
    await pause();
    assert(await evaluate(`window.__layoutFrame === document.querySelector('.pdfViewer .page')`), 'Closing a panel must not reload the PDF.');
    const restored = await evaluate(rects);
    assert(restored.pdf.width >= width*.95, 'Closing the panel must restore full width.');
    if (process.env.READER_SCREENSHOT_PREFIX && [1600,390].includes(width)) {
      const shot = await call('Page.captureScreenshot',{format:'png'});
      await writeFile(`${process.env.READER_SCREENSHOT_PREFIX}-${width}.png`,Buffer.from(shot.data,'base64'));
    }
    console.log(`PASS ${width}px: PDF ${Math.round(closed.frame.width)}px; open/close retains PDF, no empty rail`);
  }
} finally {
  ws.close();
  await call('Emulation.clearDeviceMetricsOverride').catch(() => undefined);
}
