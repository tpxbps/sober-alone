import { expect, test, type Page } from "@playwright/test";

async function openCalibrationLobby(page: Page) {
  await page.route("**/alignment-cover.svg", route => route.fulfill({
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="768"><path fill="#f00" d="M0 0h1280v768H0z"/></svg>',
  }));
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    const data = path.endsWith("/game/scripts")
      ? { success: true, scripts: Array.from({ length: 8 }, (_, i) => ({
        script_id: "align-" + i, title: "对齐样本 " + (i + 1), difficulty: 1,
        player_count: 4, estimated_duration: 30, overview: "测试封面实际像素边界。",
        cover_image_url: "/alignment-cover.svg",
      })) }
      : { success: true, models: [], features: {} };
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
  });
  await page.goto("/");
  await expect(page.locator(".dream-lobby")).toHaveAttribute("data-renderer", "webgl");
  await expect(page.locator(".card-cover-media").first()).toHaveAttribute("data-gpu", "ready");
  await expect(page.locator(".card-cover-media").first()).toHaveCSS("opacity", "0");
}

/** Check rendered pixels, not just the DOM boxes that the WebGL overlay copies. */
async function expectCoverPixelsAligned(page: Page) {
  await expect.poll(() => page.locator(".lobby-atmosphere").evaluate((node: HTMLCanvasElement) => {
    const box = node.getBoundingClientRect();
    const ratio = Math.min(devicePixelRatio, box.width < 900 ? 1 : 1.25);
    return Math.abs(node.width - box.width * ratio);
  })).toBeLessThan(1);
  await expect(page.locator(".dream-lobby")).toHaveAttribute("data-renderer", "webgl");
  const boxes = await page.locator(".card-cover-media").evaluateAll(images =>
    images.map(image => image.getBoundingClientRect().toJSON())
      .filter(box => box.top > 85 && box.bottom < innerHeight),
  );
  expect(boxes.length).toBeGreaterThan(0);
  const y = Math.floor(boxes[0].top + boxes[0].height / 2);
  const row = boxes.filter(box => box.top < y && box.bottom > y);
  const png = await page.screenshot({ scale: "css" });
  const spans = await page.evaluate(async ({ data, y }) => {
    const image = new Image();
    image.src = "data:image/png;base64," + data;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.width; canvas.height = 1;
    const context = canvas.getContext("2d")!;
    context.drawImage(image, 0, y, image.width, 1, 0, 0, image.width, 1);
    const pixels = context.getImageData(0, 0, image.width, 1).data;
    const spans: Array<{ left: number; right: number }> = [];
    let start = -1;
    for (let x = 0; x <= image.width; x++) {
      const red = x < image.width && pixels[x * 4] > 65
        && pixels[x * 4] > pixels[x * 4 + 1] * 2.5
        && pixels[x * 4] > pixels[x * 4 + 2] * 2.5;
      if (red && start === -1) start = x;
      if (!red && start !== -1) { spans.push({ left: start, right: x }); start = -1; }
    }
    return spans;
  }, { data: png.toString("base64"), y });
  expect(spans).toHaveLength(row.length);
  for (let i = 0; i < row.length; i++) {
    expect(Math.abs(spans[i].left - row[i].left), "GPU left edge").toBeLessThanOrEqual(1.5);
    expect(Math.abs(spans[i].right - row[i].right), "GPU right edge").toBeLessThanOrEqual(1.5);
  }
}

for (const deviceScaleFactor of [1, 1.25, 2]) {
  test.describe("动态封面像素对齐 DPR " + deviceScaleFactor, () => {
    test.use({ viewport: { width: 1280, height: 850 }, deviceScaleFactor, reducedMotion: "no-preference" });
    test("滚动条、双侧留槽、弹层和滚动后的封面边界与 DOM 一致", async ({ page }, info) => {
      await openCalibrationLobby(page);
      // Stable gutters reproduce classic Windows scrollbars even on headless CI.
      const gutter = await page.addStyleTag({ content: "html { scrollbar-gutter:stable; } ::-webkit-scrollbar { width:18px; }" });
      await expectCoverPixelsAligned(page);
      await page.screenshot({ path: info.outputPath("aligned-classic-scrollbar.png"), scale: "css" });
      await gutter.evaluate(node => { node.textContent = "html { scrollbar-gutter:stable both-edges; } ::-webkit-scrollbar { width:22px; }"; });
      await expectCoverPixelsAligned(page);
      await page.setViewportSize({ width: 1024, height: 850 });
      await expectCoverPixelsAligned(page);
      await page.getByRole("button", { name: "设置", exact: true }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expectCoverPixelsAligned(page);
      await page.evaluate(() => window.scrollTo(0, 390));
      await expectCoverPixelsAligned(page);
    });
  });
}
