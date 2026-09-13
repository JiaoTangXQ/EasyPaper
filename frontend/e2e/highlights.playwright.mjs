import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

test('AI highlights keep their positions and sync, export and delete across all versions', async ({ page }, testInfo) => {
  await page.goto('/login');
  await page.getByLabel('邮箱').fill('reader-test@example.com');
  await page.getByLabel('密码').fill('fixture');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/dashboard');
  await page.goto('/reader/ai-highlight-fixture');
  await page.getByRole('button', { name: '中文译文', exact: true }).click();
  await page.locator('embedpdf-container img').first().waitFor();
  await expect.poll(() => page.evaluate(async () => {
    const registry = await document.querySelector('embedpdf-container').registry;
    return registry.getPlugin('annotation').provides().getAnnotations().filter(a => a.object.type === 9).length;
  })).toBe(2);

  const marks = await page.evaluate(async () => {
    const registry = await document.querySelector('embedpdf-container').registry;
    const manager = registry.getPlugin('document-manager').provides();
    const doc = manager.getDocumentState(manager.getActiveDocumentId()).document;
    const api = registry.getPlugin('annotation').provides();
    const native = (await Promise.all(doc.pages.map(p => registry.getEngine().getPageAnnotations(doc, p).toPromise())))
      .flat().filter(a => a.type === 9);
    return native.map(a => {
      const displayed = api.getAnnotations().find(item => item.object.id === a.id).object;
      return { native: { page: a.pageIndex, text: a.contents, rect: a.rect },
        displayed: { page: displayed.pageIndex, text: displayed.contents, rect: displayed.rect } };
    });
  });
  expect(marks).toHaveLength(2);
  for (const mark of marks) expect(mark.displayed).toEqual(mark.native);
  expect(marks[0].displayed.page).toBe(0);
  expect(marks[0].displayed.text).toContain('30%');
  expect(marks[1].displayed.page).toBe(1);
  expect(marks[1].displayed.text).toContain('92%');

  const bundle = await (await page.request.get('/api/reader/tasks/ai-highlight-fixture')).json();
  await expect.poll(async () => {
    const latest = await (await page.request.get(`/api/reader/documents/${bundle.document_id}`)).json();
    return latest.annotations.every(a => a.alignment_status === 'matched');
  }).toBe(true);
  for (const [name, count] of [['原文', 2], ['简化英语', 2], ['双语对照', 4], ['中文译文', 2]]) {
    await page.getByRole('button', { name, exact: true }).click();
    await page.locator('embedpdf-container img').first().waitFor();
    await expect.poll(() => page.evaluate(async () => {
      const registry = await document.querySelector('embedpdf-container').registry;
      return registry.getPlugin('annotation').provides().getAnnotations()
        .filter(a => a.object.type === 9 && a.commitState !== 'deleted').length;
    })).toBe(count);
    // Export can preserve the deprecated `color` field even when the on-screen
    // renderer ignores it and paints yellow. Check the actual rendered fill.
    await expect.poll(() => page.evaluate(() => [...document.querySelector('embedpdf-container').shadowRoot.querySelectorAll('div')]
      .some(el => el.style.backgroundColor === 'rgb(178, 217, 255)' && Math.abs(Number(el.style.opacity) - 0.4) < 0.001)
    )).toBe(true);
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: '带批注 PDF', exact: true }).click();
    const path = testInfo.outputPath(`${name}.pdf`);
    await (await download).saveAs(path);
    const exported = JSON.parse(execFileSync('../backend/.venv/bin/python', ['-c',
      'import fitz,json,sys\np=fitz.open(sys.argv[1]);print(json.dumps([{ "id":a.info["id"],"page":page.number,"opacity":a.opacity,"color":a.colors["stroke"],"quad":a.vertices[0]} for page in p for a in page.annots() if a.type[0]==8]))', path], { encoding: 'utf8' }));
    expect(exported).toHaveLength(count);
    expect(new Set(exported.map(a => a.id)).size).toBe(count);
    for (const a of exported) {
      expect(a.opacity).toBeCloseTo(0.4);
      expect(a.color[2]).toBeCloseTo(1);
      const sourcePage = name === '双语对照' ? Math.floor(a.page / 2) : a.page;
      expect(Math.abs(a.quad[1] - (200 + sourcePage * 180))).toBeLessThan(20);
    }
  }
  const first = bundle.annotations.find(a => a.data.pageIndex === 0);
  const response = await page.request.put(`/api/reader/documents/${bundle.document_id}/annotations/${first.id}`, {
    data: { operation_id: 'delete-ai-browser', base_revision: first.revision, version_id: first.source_version_id,
      data: first.data, deleted: true },
  });
  expect(response.ok()).toBe(true);
  await page.reload();
  for (const [name, count] of [['中文译文', 1], ['原文', 1], ['双语对照', 2], ['简化英语', 1]]) {
    await page.getByRole('button', { name, exact: true }).click();
    await page.locator('embedpdf-container img').first().waitFor();
    await expect.poll(() => page.evaluate(async () => {
      const registry = await document.querySelector('embedpdf-container').registry;
      return registry.getPlugin('annotation').provides().getAnnotations()
        .filter(a => a.object.type === 9 && a.commitState !== 'deleted').length;
    })).toBe(count);
  }
});
