import { expect, test } from "@playwright/test";

test.beforeEach(async ({ context }) => {
  const result = await context.request.post("/api/v1/auth/login", {
    data: { username: "browser-test", password: "browser-test-password" },
  });
  expect(result.ok()).toBe(true);
});

test("create project, deep-route refresh, validation and navigation", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "我的工程" })).toBeVisible();
  await page.screenshot({
    path: "test-results/projects-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "新建工程", exact: true }).click();
  await page.getByLabel("工程名称").fill(`E2E 导航验证 ${Date.now()}`);
  await page.getByRole("button", { name: "创建工程", exact: true }).click();
  await expect(page).toHaveURL(/\/analysis$/);
  await expect(
    page.getByRole("heading", { name: "让一段原片，成为创作的起点" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "开始拆解", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: /E2E 导航验证/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "再创作", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "保存并确认创作要求" }),
  ).toBeDisabled();
  await page.getByRole("link", { name: "资产库", exact: true }).click();
  await expect(
    page.getByText("上传原片或导入剧本后，这里将出现提取的资产"),
  ).toBeVisible();
  await page.getByRole("link", { name: "导出创作包", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "生成当前版本创作包" }),
  ).toBeDisabled();
  await page.screenshot({
    path: "test-results/export-desktop.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("script import and character assets work on desktop and mobile", async ({
  page,
}) => {
  const response = await page.request.post("/api/v1/projects", {
    data: { name: "剧本资产验证" },
  });
  const project = await response.json();
  await page.goto(`/projects/${project.id}/script`);
  await page
    .getByLabel("剧本正文")
    .fill(
      "第一场，旧书店，夜。小林穿蓝色衬衫，将一张旧照片放到柜台上。小林：你认识照片上的人吗？",
    );
  await expect(
    page.getByRole("button", { name: "解析剧本", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "保存剧本", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "解析剧本", exact: true }),
  ).toBeEnabled();
  await page.reload();
  await expect(page.getByLabel("剧本正文")).toContainText("旧书店");
  await page.getByRole("link", { name: "资产库", exact: true }).click();
  await page.getByRole("button", { name: "创建资产", exact: true }).click();
  await page.getByLabel("资产名称").fill("小林");
  await page.getByLabel("形象描述").fill("蓝色衬衫的青年，书店访客。");
  await page
    .getByRole("button", { name: "创建资产", exact: true })
    .last()
    .click();
  await expect(page.locator(".asset-card")).toContainText("小林");
  await page.locator(".asset-card").click();
  await page.getByRole("tab", { name: "完整人物设定" }).click();
  await page.getByLabel("目标与动机").fill("寻找照片中失散的亲人");
  await page.getByLabel("服装与配饰").fill("蓝色衬衫、旧手表");
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.locator(".asset-card").click();
  await page.getByRole("tab", { name: "完整人物设定" }).click();
  await expect(page.getByLabel("目标与动机")).toHaveValue(
    "寻找照片中失散的亲人",
  );
  await page.getByRole("tab", { name: "基本信息" }).click();
  await page.screenshot({
    path: "test-results/character-library-editor.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.screenshot({
    path: "test-results/character-library.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/character-library-mobile.png",
    fullPage: true,
  });
});

test("mobile layout has no page overflow and exposes connection status", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "我的工程" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "查看环境" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("已配置（未展示）")).toHaveCount(0);
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.screenshot({
    path: "test-results/projects-mobile.png",
    fullPage: true,
  });
});

test("asset editor retains a user's draft after a version conflict", async ({
  page,
}) => {
  // UI-only fixture: this route exists only in the test and makes no model requests.
  const project = {
    id: "browser-fixture",
    name: "UI 测试工程",
    created_at: new Date().toISOString(),
    media: [],
    jobs: [],
    entities: [
      {
        id: "fixture_asset",
        project_id: "browser-fixture",
        kind: "asset",
        scope: "adaptation",
        version: 1,
        status: "pending",
        content: {
          id: "NEW_CHAR_001",
          name: "测试角色",
          type: "character",
          description: "原始描述",
          prompt: "测试提示词",
          evidence: [],
          image_ids: [],
        },
      },
    ],
  };
  let conflict = true;
  await page.route("**/api/v1/projects/browser-fixture**", async (route) => {
    if (route.request().method() === "PATCH") {
      if (conflict)
        return route.fulfill({
          status: 409,
          json: { message: "版本已变化，请保留草稿" },
        });
      project.entities[0].content = route.request().postDataJSON().content;
      project.entities[0].version = 2;
      return route.fulfill({ json: project.entities[0] });
    }
    return route.fulfill({ json: project });
  });
  await page.goto("/projects/browser-fixture/assets?scope=adaptation");
  await page.locator(".asset-card").click();
  await page.getByLabel("形象描述").fill("人工修订后必须保留的草稿");
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  await expect(page.getByText("版本已变化，请保留草稿")).toBeVisible();
  await expect(page.getByLabel("形象描述")).toHaveValue(
    "人工修订后必须保留的草稿",
  );
  await page.screenshot({
    path: "test-results/asset-editor-desktop.png",
    fullPage: true,
  });
  conflict = false;
  await page.getByRole("button", { name: "保存新版本", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".asset-card")).toContainText(
    "人工修订后必须保留的草稿",
  );
});
