import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

async function open(page) {
  await page.goto('/login');
  await page.getByLabel('邮箱').fill('reader-test@example.com');
  await page.getByLabel('密码').fill('fixture');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/dashboard');
  await page.goto('/reader/reader-fixture');
  await rendered(page);
}
async function rendered(page) {
  await page.locator('embedpdf-container img').first().waitFor();
  await page.waitForFunction(() => [...document.querySelector('embedpdf-container').shadowRoot.querySelectorAll('img')].some(i => i.complete && i.naturalWidth > 0));
}
async function bundle(page) { return (await page.request.get('/api/reader/tasks/reader-fixture')).json(); }
async function exportedAnnotations(page, testInfo, name) {
  await rendered(page);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '带批注 PDF', exact: true }).click();
  const path = testInfo.outputPath(`${name}.pdf`);
  await (await download).saveAs(path);
  return JSON.parse(execFileSync('../backend/.venv/bin/python', ['-c',
    'import fitz,json,sys\np=fitz.open(sys.argv[1]);print(json.dumps([{"page":page.number,"type":a.type[1],"id":a.info.get("id"),"text":a.info.get("content"),"rect":list(a.rect)} for page in p for a in page.annots()]))', path], { encoding: 'utf8' }));
}
async function drawLine(page, tool, start, end) {
  await page.getByRole('button', { name: '批注', exact: true }).click();
  await page.getByRole('button', { name: tool, exact: true }).click();
  const image = await page.locator('embedpdf-container img').first().boundingBox();
  const scale = image.width / 595;
  await page.mouse.move(image.x + start[0] * scale, image.y + start[1] * scale);
  await page.mouse.down();
  await page.mouse.move(image.x + end[0] * scale, image.y + end[1] * scale, { steps: 30 });
  await page.mouse.up();
}

test('highlighting already marked text selects text instead of moving the old mark', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: '中文译文', exact: true }).click();
  await rendered(page);
  // Keep this regression isolated from the persistence scenario's real fixture records.
  await page.route('**/api/reader/documents/*/annotations/*', route => route.request().method() === 'GET' ? route.continue() : route.abort());
  await page.evaluate(async () => {
    const registry = await document.querySelector('embedpdf-container').registry;
    window.createdMarks = [];
    registry.getPlugin('annotation').provides().onAnnotationEvent(e => {
      if(e.type === 'create' && !e.committed) window.createdMarks.push(e.annotation);
    });
  });
  await drawLine(page, '高亮', [54, 103], [278, 103]);
  await expect.poll(() => page.evaluate(() => window.createdMarks.length)).toBe(1);
  // drawLine toggles the toolbar; select the existing highlighter directly this time.
  const image = await page.locator('embedpdf-container img').first().boundingBox();
  const scale = image.width / 595;
  await page.mouse.move(image.x + 65 * scale, image.y + 103 * scale);
  await page.mouse.down();
  await page.mouse.move(image.x + 145 * scale, image.y + 103 * scale, { steps: 20 });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => window.createdMarks.length)).toBe(2);
  await page.getByRole('button', { name: '墨迹荧光笔', exact: true }).click();
  await page.mouse.move(image.x + 65 * scale, image.y + 103 * scale);
  await page.mouse.down();
  await page.mouse.move(image.x + 145 * scale, image.y + 103 * scale, { steps: 20 });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => window.createdMarks.length)).toBe(3);
  expect(await page.evaluate(() => window.createdMarks.every(m => m.type === 9 && m.segmentRects.length === 1))).toBe(true);
});

test('four versions, native export, offline recovery, conflicts, ink, undo and mobile', async ({ page, context }, testInfo) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await open(page);
  await page.getByRole('button', { name: '中文译文', exact: true }).click();
  await rendered(page);
  const retries = [];
  page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/align')) retries.push(r.url()); });
  // Hold only the fixture's model so a new mark stays pending during the switch.
  await page.request.post('http://127.0.0.1:18080/fixture/alignment?paused=true');
  await drawLine(page, '高亮', [54, 103], [278, 103]);
  await expect.poll(async () => (await bundle(page)).annotations.filter(a => !a.deleted).length).toBe(1);
  await expect(page.getByRole('status').first()).toContainText('正在自动同步 1 条批注');
  await page.getByRole('button', { name: '原文', exact: true }).click();
  await rendered(page);
  expect((await exportedAnnotations(page, testInfo, 'original-pending')).filter(a => a.type === 'Highlight')).toHaveLength(0);
  await page.request.post('http://127.0.0.1:18080/fixture/alignment?paused=false');
  await expect.poll(async () => (await bundle(page)).annotations[0].alignment_status).toBe('matched');
  // The existing viewer must receive the new projection without a reload or retry.
  await expect.poll(async () => (await exportedAnnotations(page, testInfo, 'original-auto-synced')).filter(a => a.type === 'Highlight').length).toBe(1);
  await expect(page.getByRole('status').first()).toContainText('当前版本批注已同步');
  expect(retries).toEqual([]);
  await expect(page.getByRole('button', { name: '批注 1', exact: true })).toBeVisible();
  for (const [name, count] of [['中文译文', 1], ['原文', 1], ['简化英语', 1], ['双语对照', 2]]) {
    await page.getByRole('button', { name, exact: true }).click();
    await rendered(page);
    await expect.poll(async () => (await exportedAnnotations(page, testInfo, name)).filter(a => a.type === 'Highlight').length).toBe(count);
  }
  await page.getByRole('button', { name: '批注 1', exact: true }).click();
  await page.getByRole('textbox', { name: '批注笔记' }).fill('Shared note');
  await expect.poll(async () => (await bundle(page)).annotations[0].data.contents).toBe('Shared note');
  // A completed but incorrect automatic match must still be retryable from the UI.
  const beforeRetry = (await bundle(page)).annotations[0];
  const retried = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/annotations/${beforeRetry.id}/align`));
  await page.getByRole('button', { name: '重试匹配', exact: true }).click();
  expect((await retried).status()).toBe(202);
  await expect.poll(async () => {
    const mark = (await bundle(page)).annotations.find(a => a.id === beforeRetry.id);
    return mark.alignment_status === 'matched' && mark.updated_at > beforeRetry.updated_at;
  }).toBe(true);
  const afterRetry = await bundle(page);
  expect(afterRetry.annotations.filter(a => !a.deleted)).toHaveLength(1);
  expect(afterRetry.annotations[0].data).toEqual(beforeRetry.data);
  const saved = await bundle(page);
  const prefix = `/api/reader/documents/${saved.document_id}`;
  const savedId = saved.annotations[0].id;

  // API outage: keep the durable outbox across a full app reload, then reconnect.
  await page.route('**/api/**', route => route.abort());
  await page.getByRole('textbox', { name: '批注笔记' }).fill('Offline note survives reload');
  await expect(page.getByRole('status').first()).toContainText('本地已保存');
  await page.reload(); await rendered(page);
  await page.getByRole('button', { name: '批注 1', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '批注笔记' })).toHaveValue('Offline note survives reload');
  await page.unroute('**/api/**');
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect.poll(async () => (await bundle(page)).annotations[0].data.contents).toBe('Offline note survives reload');

  // A separate client saves while this page has an offline edit. Neither edit disappears.
  await page.route('**/api/**', route => route.abort());
  await page.getByRole('textbox', { name: '批注笔记' }).fill('My concurrent edit');
  await expect(page.getByRole('status').first()).toContainText('本地已保存');
  const current = (await bundle(page)).annotations.find(a => a.id === savedId);
  const response = await page.request.put(`${prefix}/annotations/${savedId}`, { data: {
    operation_id: 'other-window', base_revision: current.revision, version_id: current.source_version_id,
    data: { ...current.data, contents: 'Another window edit' }, geometry_changed: false,
  } });
  expect(response.status()).toBe(200);
  await page.unroute('**/api/**'); await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.getByRole('button', { name: '将本地修改另存一份' })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: '将本地修改另存一份' }).click();
  await expect.poll(async () => (await bundle(page)).annotations.filter(a => !a.deleted).length).toBe(2);
  const notes = (await bundle(page)).annotations.map(a => a.data.contents);
  expect(notes).toContain('My concurrent edit'); expect(notes).toContain('Another window edit');

  await page.getByRole('button', { name: '关闭批注', exact: true }).click();
  await page.getByRole('button', { name: '中文译文', exact: true }).click(); await rendered(page);
  await drawLine(page, '自由绘制', [350, 210], [480, 260]);
  await expect.poll(async () => (await bundle(page)).annotations.filter(a => !a.deleted && a.data.type === 15).length).toBe(1);
  await page.getByRole('button', { name: '撤销', exact: true }).click();
  await expect.poll(async () => (await bundle(page)).annotations.filter(a => !a.deleted && a.data.type === 15).length).toBe(0);
  await page.getByRole('button', { name: '恢复', exact: true }).click();
  await expect.poll(async () => (await bundle(page)).annotations.filter(a => !a.deleted && a.data.type === 15).length).toBe(1);
  const inkBefore = (await bundle(page)).annotations.find(a => !a.deleted && a.data.type === 15);
  await page.getByRole('button', { name: '光标模式', exact: true }).click();
  const image = await page.locator('embedpdf-container img').first().boundingBox();
  const scale = image.width / 595;
  const x = image.x + 415 * scale, y = image.y + 235 * scale;
  await page.mouse.click(x, y);
  await page.mouse.move(x, y); await page.mouse.down();
  await page.mouse.move(x + 20 * scale, y + 15 * scale, { steps: 20 }); await page.mouse.up();
  await expect.poll(async () => (await bundle(page)).annotations.find(a => a.id === inkBefore.id).data.rect.origin.x).toBeGreaterThan(inkBefore.data.rect.origin.x + 10);
  await page.reload(); await rendered(page);
  expect((await exportedAnnotations(page, testInfo, 'ink-restored')).some(a => a.type === 'Ink')).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('desktop.png') });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: '中文译文', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '带批注 PDF', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: '批注 3', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '共享批注' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('mobile.png') });
  const backup = page.waitForEvent('download');
  await page.getByRole('button', { name: '备份论文与批注', exact: true }).click();
  const archivePath = testInfo.outputPath('backup.zip');
  await (await backup).saveAs(archivePath);
  await page.getByLabel('导入论文备份').setInputFiles(archivePath);
  await expect(page.getByText('已恢复 0 条批注；3 条已有批注保留当前修改', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('new multiline highlights and underlines follow compact rows at different zooms and pointer offsets', async ({ page }) => {
  await open(page);
  await page.getByRole('button', { name: '中文译文', exact: true }).click();
  await rendered(page);
  await page.route('**/api/reader/documents/*/annotations/*', route => route.request().method() === 'GET' ? route.continue() : route.abort());
  await page.evaluate(async () => {
    const registry = await document.querySelector('embedpdf-container').registry;
    window.createdMarks = [];
    registry.getPlugin('annotation').provides().onAnnotationEvent(e => {
      if (e.type === 'create' && !e.committed) window.createdMarks.push(e.annotation);
    });
  });
  await page.getByRole('button', { name: '批注', exact: true }).click();
  let count = 0;
  let previousTool;
  const selections = [];
  for (const zoom of [1.25, 1.6]) for (const offset of [-4, 0, 4]) {
    await page.evaluate(async z => (await document.querySelector('embedpdf-container').registry)
      .getPlugin('zoom').provides().requestZoom(z), zoom);
    await expect.poll(async () => (await page.locator('embedpdf-container img').first().boundingBox()).width)
      .toBeCloseTo(595 * zoom, 0);
    for (const tool of ['高亮', '下划线']) {
      if (tool !== previousTool) await page.getByRole('button', { name: tool, exact: true }).click();
      previousTool = tool;
      const b = await page.locator('embedpdf-container img').first().boundingBox();
      const scale = b.width / 595;
      await page.mouse.move(b.x + 56 * scale, b.y + (406 + offset) * scale);
      await page.mouse.down();
      await page.mouse.move(b.x + 150 * scale, b.y + (448 + offset) * scale, { steps: 20 });
      await page.mouse.up();
      await expect.poll(() => page.evaluate(() => window.createdMarks.length)).toBe(++count);
      const mark = await page.evaluate(() => window.createdMarks.at(-1));
      expect(mark.type).toBe(tool === '高亮' ? 9 : 10);
      expect(mark.segmentRects).toHaveLength(4);
      expect(mark.segmentRects.every(r => r.size.height < 14)).toBe(true);
      selections.push(mark.segmentRects);
    }
  }
  for (const selection of selections) expect(selection).toEqual(selections[0]);
});

test('export waits for annotation writes already in progress', async ({ page }, testInfo) => {
  await open(page);
  await page.evaluate(async () => {
    const registry = await document.querySelector('embedpdf-container').registry;
    const engine = registry.getEngine();
    const dm = registry.getPlugin('document-manager').provides();
    const doc = dm.getDocumentState(dm.getActiveDocumentId()).document;
    const Task = engine.getPageGeometry(doc, doc.pages[0]).constructor;
    const create = engine.createPageAnnotation.bind(engine);
    engine.createPageAnnotation = (...args) => {
      const delayed = new Task();
      setTimeout(() => create(...args).wait(result => delayed.resolve(result), error => delayed.fail(error)), 1000);
      return delayed;
    };
    registry.getPlugin('annotation').provides().importAnnotations([0, 1].map(i => {
      const rect = { origin: { x: 50, y: 300 + i * 30 }, size: { width: 120, height: 12 } };
      return { annotation: { id: `export-pending-${i}`, type: 9, pageIndex: 0, rect, segmentRects: [rect], strokeColor: '#ffff00', opacity: 0.5 } };
    }));
  });
  const exported = await exportedAnnotations(page, testInfo, 'pending-writes');
  expect(exported.map(a => a.id)).toEqual(expect.arrayContaining(['export-pending-0', 'export-pending-1']));
});

test('cross-version marks are drawn from target text even when stored coordinates are stale', async ({ page }) => {
  await page.route(/\/api\/reader\/(?:tasks\/reader-fixture|documents\/[^/]+)$/, async route => {
    const response = await route.fetch();
    const data = await response.json();
    const source = data.versions.find(v => v.kind === 'chinese');
    const target = data.versions.find(v => v.kind === 'original');
    const stale = {origin:{x:480,y:700},size:{width:90,height:20}};
    data.annotations = [{id:'text-location-fixture',document_id:data.document_id,source_version_id:source.id,
      quote:'内存占用降低30%',revision:1,deleted:false,alignment_status:'matched',alignment_message:'已匹配',
      updated_at:'2026-09-10T00:00:00',anchors:[],
      data:{id:'source-text-location',type:9,pageIndex:0,rect:stale,segmentRects:[stale],strokeColor:'#ffff00',opacity:0.5},
      projections:{[target.id]:[{page:0,unit_id:'target',quote:'30% less memory',rects:[stale],method:'semantic'}]}}];
    await route.fulfill({response,json:data});
  });
  await open(page);
  await page.getByRole('button',{name:'原文',exact:true}).click();
  await rendered(page);
  await expect.poll(async () => page.evaluate(async () => {
    const r=await document.querySelector('embedpdf-container').registry;
    return r.getPlugin('annotation').provides().getAnnotations().find(a=>a.object.custom?.easyPaperId==='text-location-fixture')?.object.rect.origin.y;
  })).toBeLessThan(150);
});
