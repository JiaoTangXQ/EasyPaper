import { test, expect } from "@playwright/test";

const title = "Efficient Learning with Limited Memory: Methods, Evidence, and Practical Evaluation";
const chineseTitle = "有限内存下的高效学习：方法、证据与实践评估";
const tasks = [
  {
    task_id: "sample",
    filename: "2401.00001.pdf",
    title,
    title_zh: chineseTitle,
    status: "completed",
    mode: "translate",
    created_at: "2026-09-10T08:00:00Z",
    can_read: true,
    reading: { block_id: "b1", page: 6, updated_at: "2026-09-10T09:00:00Z" },
  },
  {
    task_id: "pending",
    filename: "Understanding Multimodal Reasoning",
    status: "rewriting",
    mode: "simplify",
    created_at: "2026-09-10T07:00:00Z",
    percent: 52,
    can_read: true,
    message: "正在生成简化英文",
  },
];
const papers = [
  {
    id: "p1",
    task_id: "sample",
    title,
    year: 2026,
    venue: "Example Conference",
    doi: null,
    extraction_status: "completed",
  },
];
const cards = [
  {
    id: "c1",
    paper_id: "p1",
    front: "为什么需要同时评估运行时间？",
    back: "降低内存占用可能增加计算开销。",
    tags: ["示例"],
    difficulty: 2,
  },
];
const entities = [
  {
    id: "e1",
    name: "缓冲区复用",
    type: "method",
    definition: "在临时结果不再需要时，复用已有内存。",
    importance: 0.8,
    paper_id: "p1",
  },
  {
    id: "e2",
    name: "内存占用",
    type: "metric",
    definition: "运行方法所需的内存资源。",
    importance: 0.7,
    paper_id: "p1",
  },
];
const paper = {
  ...papers[0],
  metadata: {
    title,
    authors: [{ name: "Example Author" }],
    year: 2026,
    venue: "Example Conference",
    abstract: "用于界面回归的示例论文内容。",
    keywords: ["内存效率", "评估方法"],
  },
  entities,
  relationships: [],
  findings: [
    {
      id: "f1",
      type: "result",
      statement: "临时缓冲区复用能够降低内存占用。",
      evidence: "参见实验结果。",
      evidence_refs: [{ block_id: "b1", page: 6 }],
    },
  ],
  methods: [],
  datasets: [],
  flashcards: cards,
  annotations: [],
};

async function setup(page, overrides = {}) {
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    let data = {};
    if (path === "/api/auth/login") data = { access_token: "workspace-test-only" };
    else if (path === "/api/tasks") data = overrides.tasks ?? tasks;
    else if (path.endsWith("/title-translation") && overrides.translateTitle) return overrides.translateTitle(route);
    else if (path === "/api/knowledge/papers") data = overrides.papers ?? papers;
    else if (path === "/api/knowledge/papers/p1") data = paper;
    else if (path.includes("/flashcards/due")) data = cards;
    else if (path === "/api/knowledge/graph")
      data = overrides.graph ?? { nodes: entities, edges: [{ id: "r1", source: "e1", target: "e2", type: "reduces" }] };
    else if (path.endsWith("/vaults")) data = { vaults: [] };
    else if (path.endsWith("/settings/obsidian")) data = { vault_path: "", root_folder: "EasyPaper" };
    else if (path.startsWith("/api/knowledge/export/"))
      return route.fulfill({ body: "{}", contentType: "application/json" });
    await route.fulfill({ json: data });
  });
  await page.goto("/login");
  await page.getByLabel("邮箱").fill("workspace-test@example.com");
  await page.getByLabel("密码").fill("fixture");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL("**/dashboard");
}

test("returning readers can continue above the fold and imports preserve selected options", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  const resume = page.locator(".continue-paper").getByRole("button", { name: "继续阅读" });
  await expect(resume).toBeVisible();
  const bounds = await resume.boundingBox();
  expect(bounds.y + bounds.height).toBeLessThan(844);
  await page.getByRole("button", { name: "导入论文", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("简化英文", { exact: true }).check();
  await dialog.getByText("可选设置", { exact: true }).click();
  await dialog.getByRole("checkbox").check();
  let uploaded;
  await page.route("**/api/upload", async (route) => {
    uploaded = route.request().postData();
    await route.fulfill({ json: { task_id: "new" } });
  });
  await dialog
    .locator("input[type=file]")
    .setInputFiles({ name: "sample.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await expect(dialog).not.toBeVisible();
  expect(uploaded).toContain("simplify");
  expect(uploaded).toContain("true");
});

test("paper titles appear in the library and resume card while filenames remain searchable", async ({ page }) => {
  await setup(page);
  await expect(page.locator(".continue-paper h3")).toHaveText(title);
  await expect(page.locator(".paper-title").first()).toHaveText(title);
  await expect(page.locator(".continue-paper .paper-title-zh")).toHaveText(chineseTitle);
  await expect(page.locator(".paper-row").first().locator(".paper-title-zh")).toHaveText(chineseTitle);
  await expect(page.locator(".paper-title").last()).toHaveText(tasks[1].filename);
  const search = page.getByLabel("按标题搜索论文");
  for (const query of ["limited memory", "实践评估", "2401.00001.pdf"]) {
    await search.fill(query);
    await expect(page.locator(".paper-row")).toHaveCount(1);
    await expect(page.locator(".paper-title")).toHaveText(title);
  }
});

test("Chinese title subtitles translate once, retry without blocking reading, and fit narrow screens", async ({ page }, testInfo) => {
  let calls = 0, finishFirst;
  const pending = new Promise(resolve => { finishFirst = resolve; });
  await setup(page, {
    tasks: [{ ...tasks[0], title_zh: null }],
    translateTitle: async route => {
      calls++;
      if (calls === 1) {
        await pending;
        return route.fulfill({status:503,json:{detail:"标题暂未翻译成功，请稍后重试。"}});
      }
      return route.fulfill({json:{title,title_zh:chineseTitle}});
    },
  });
  await expect(page.locator(".continue-paper h3")).toHaveText(title);
  await expect(page.locator(".continue-paper").getByRole("button",{name:"继续阅读"})).toBeEnabled();
  await expect(page.getByText("正在翻译标题…",{exact:true})).toHaveCount(2);
  expect(calls).toBe(1);
  finishFirst();
  await page.getByRole("button",{name:"重试标题翻译",exact:true}).first().click();
  await expect(page.locator(".continue-paper .paper-title-zh")).toHaveText(chineseTitle);
  await expect(page.locator(".paper-row .paper-title-zh")).toHaveText(chineseTitle);
  expect(calls).toBe(2);
  for (const width of [1440,320]) {
    await page.setViewportSize({width,height:1000});
    const metrics=await page.locator(".continue-paper .paper-title-zh").evaluate(el=>({
      title:el.previousElementSibling.getBoundingClientRect().bottom,
      subtitle:el.getBoundingClientRect().top,
      font:getComputedStyle(el).fontSize,
      page:document.documentElement.scrollWidth,
    }));
    expect(metrics.subtitle).toBeGreaterThanOrEqual(metrics.title);
    expect(metrics.font).toBe("14px");
    expect(metrics.page).toBeLessThanOrEqual(width);
    await page.screenshot({path:testInfo.outputPath(`bilingual-titles-${width}.png`)});
  }
  // A cached subtitle on reload must not start another model request.
  await page.route("**/api/tasks", route=>route.fulfill({json:[{...tasks[0],title_zh:chineseTitle}]}));
  await page.reload();
  await expect(page.locator(".paper-row .paper-title-zh")).toHaveText(chineseTitle);
  expect(calls).toBe(2);
});

test("search empty state does not replace the library with onboarding", async ({ page }) => {
  await setup(page);
  await page.getByLabel("按标题搜索论文").fill("nonexistent");
  await expect(page.getByText("没有符合条件的论文")).toBeVisible();
  await expect(page.getByText("导入第一篇论文")).toHaveCount(0);
  await page.getByRole("button", { name: "清除筛选" }).click();
  await expect(page.locator(".paper-row")).toHaveCount(2);
  await page.getByRole("button", { name: "处理中", exact: true }).click();
  await expect(page.locator(".paper-row")).toHaveCount(1);
  await page.getByLabel("按标题搜索论文").fill("Multimodal");
  await page.getByRole("navigation", { name: "主要导航" }).getByRole("link", { name: "知识笔记", exact: true }).click();
  await page.getByRole("navigation", { name: "主要导航" }).getByRole("link", { name: "我的论文", exact: true }).click();
  await expect(page.getByLabel("按标题搜索论文")).toHaveValue("Multimodal");
  await expect(page.getByRole("button", { name: "处理中", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".paper-row")).toHaveCount(1);
});

test("knowledge defaults to evidence and keeps all export formats and personal notes reachable", async ({ page }) => {
  await setup(page);
  await page.getByRole("link", { name: "知识笔记", exact: true }).click();
  await page.getByRole("button", { name: "导出", exact: true }).click();
  for (const name of [
    "知识备份 · JSON",
    "Obsidian 笔记 · ZIP",
    "文献引用 · BibTeX",
    "文献引用 · CSL-JSON",
    "论文表格 · CSV ZIP",
  ])
    await expect(page.getByRole("menuitem", { name })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "文献引用 · BibTeX" }).click();
  expect((await download).suggestedFilename()).toBe("easypaper_references.bib");
  await page.getByRole("button", { name: "查看笔记", exact: true }).click();
  await expect(page.getByRole("tab", { name: /发现与证据/ })).toHaveAttribute("data-state", "active");
  await expect(page.getByRole("button", { name: "查看第 6 页原文" })).toBeVisible();
  await page.getByRole("tab", { name: /我的笔记/ }).click();
  await page.getByLabel("添加个人笔记").fill("需要检查实验的适用条件");
  const request = page.waitForRequest(
    (req) => req.method() === "POST" && req.url().endsWith("/api/knowledge/papers/p1/annotations"),
  );
  await page.getByRole("button", { name: "添加", exact: true }).click();
  expect((await request).postDataJSON()).toEqual({ type: "note", content: "需要检查实验的适用条件" });
});

test("review keeps the answer and card when rating fails, then saves the original rating value", async ({ page }) => {
  await setup(page);
  await page.goto("/knowledge/review");
  await page.getByRole("button", { name: "显示答案" }).click();
  await expect(page.getByText(cards[0].back)).toBeVisible();
  let attempt = 0,
    quality;
  await page.route("**/api/knowledge/flashcards/c1/review", async (route) => {
    quality = route.request().postDataJSON().quality;
    await route.fulfill(
      attempt++ === 0 ? { status: 500, json: { detail: "测试中的提交失败" } } : { json: { ok: true } },
    );
  });
  await page.getByRole("button", { name: "一般 费力答对" }).click();
  await expect(page.getByText(cards[0].back)).toBeVisible();
  await expect(page.getByRole("button", { name: "一般 费力答对" })).toBeEnabled();
  await page.getByRole("button", { name: "一般 费力答对" }).click();
  await expect(page.getByText("本轮复习完成", { exact: true })).toBeVisible();
  expect(quality).toBe(3);
});

test("graph offers keyboard-accessible concepts and source navigation on small screens", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await page.goto("/knowledge/graph");
  await expect(page.getByRole("button", { name: "列表", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "缓冲区复用 方法" }).click();
  await expect(page.getByRole("complementary", { name: "选中的概念" })).toContainText("在临时结果不再需要时");
  await page.getByRole("button", { name: "查看来源论文" }).click();
  await page.waitForURL("**/knowledge/paper/p1");
});

test("graph groups dense relationships, preserves the full view, and supports search and keyboard selection", async ({ page }) => {
  const neighbors = Array.from({ length: 17 }, (_, index) => ({ ...entities[1], id: `related-${index}`, name: `关联概念 ${index}` }));
  await setup(page, { graph: { nodes: [entities[0], ...neighbors, { ...entities[1], id: "isolated", name: "独立概念" }],
    edges: neighbors.map(node => ({ id: `edge-${node.id}`, source: "e1", target: node.id, type: "uses" })) } });
  await page.goto("/knowledge/graph");
  const selected = page.locator(".concept-map-node[data-selected]");
  const nodes = page.locator(".concept-map-node");
  await expect(nodes).toHaveCount(9);
  await expect(selected).toHaveAttribute("data-graph-node", "e1");
  const first = await nodes.evaluateAll(elements => elements.map(element => element.getAttribute("data-graph-node")));
  await page.getByRole("button", { name: "下一组关联概念" }).click();
  const second = await nodes.evaluateAll(elements => elements.map(element => element.getAttribute("data-graph-node")));
  expect(second.filter(id => first.includes(id))).toEqual(["e1"]);
  await page.getByRole("button", { name: "下一组关联概念" }).click();
  await expect(nodes).toHaveCount(2);
  await expect(page.getByRole("button", { name: "下一组关联概念" })).toBeDisabled();
  await page.getByRole("button", { name: "全局图谱", exact: true }).click();
  await expect(nodes).toHaveCount(19);
  await page.getByRole("button", { name: "放大图谱" }).click();
  await expect(page.getByLabel("图谱缩放比例")).toHaveText("120%");
  await page.getByRole("button", { name: "适应画布" }).click();
  await expect(page.getByLabel("图谱缩放比例")).toHaveText("100%");
  const inspector = page.getByRole("complementary", { name: "选中的概念" });
  await inspector.evaluate(element => { element.scrollTop = 250; });
  await inspector.locator(".concept-relations > button").nth(8).click();
  await expect.poll(() => inspector.evaluate(element => element.scrollTop)).toBe(0);
  const search = page.getByLabel("查找概念名称");
  await search.fill("独立概念");
  await page.getByRole("button", { name: "独立概念 指标" }).focus();
  await page.keyboard.press("Enter");
  await expect(nodes).toHaveCount(1);
  await expect(page.getByText("暂未整理出关联关系。", { exact: true })).toBeVisible();
  await search.fill("没有这个概念");
  await expect(page.getByText("没有匹配的概念", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "清除筛选" }).click();
  await page.getByRole("button", { name: "查看来源论文" }).click();
  await page.waitForURL("**/knowledge/paper/p1");
});

test("graph tablet selection reveals the new definition and selected keyboard focus stays visible", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 850 });
  await setup(page);
  await page.goto("/knowledge/graph");
  const other = page.locator('.concept-map-node[data-graph-node="e2"]');
  await other.focus();
  await page.keyboard.press("Enter");
  const inspector = page.getByRole("complementary", { name: "选中的概念" });
  await expect(inspector).toBeFocused();
  await expect(inspector.locator("h2")).toHaveText("内存占用");
  const bounds = await inspector.locator("h2").boundingBox();
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.y + bounds.height).toBeLessThan(850);
  const sourceBounds = await inspector.getByRole("button", { name: "查看来源论文" }).boundingBox();
  expect(sourceBounds.y + sourceBounds.height).toBeLessThan(850);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await other.focus();
  const style = await other.locator("rect").evaluate(element => ({ stroke: getComputedStyle(element).stroke, fill: getComputedStyle(element).fill }));
  expect(style.stroke).not.toBe(style.fill);
});

test("all workspace pages fit mobile and tablet widths, including long titles and review ratings", async ({ page }) => {
  await setup(page);
  for (const width of [320, 390, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of [
      "/dashboard",
      "/knowledge",
      "/knowledge/paper/p1",
      "/knowledge/graph",
      "/knowledge/review",
      "/settings",
    ]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      if (path.endsWith("/review")) await page.getByRole("button", { name: "显示答案" }).click();
      const measured = await page.evaluate(() => ({
        viewport: innerWidth,
        scroll: document.documentElement.scrollWidth,
      }));
      expect(measured.scroll, `${path} at ${width}px`).toBeLessThanOrEqual(measured.viewport);
    }
  }
});
