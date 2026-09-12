import { expect, type Locator, type Page } from "@playwright/test";

export async function stressSelection(page: Page, text: Locator, cycles = 35) {
  await text.scrollIntoViewIfNeeded();
  const rect = (await text.boundingBox())!;
  const x = rect.x + 4, y = rect.y + Math.min(10, rect.height / 2);
  const end = Math.min(rect.x + rect.width - 4, x + 140);
  for (let i = 0; i < cycles; i++) {
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(end, y, { steps: 2 });
    await page.mouse.up();
    await page.mouse.dblclick(x + 15, y);
    await page.mouse.click(rect.x + rect.width + 5, y);
  }
  const state = await page.evaluate(() => ({
    pointerEvents: getComputedStyle(document.body).pointerEvents,
    userSelect: getComputedStyle(document.body).userSelect,
    selection: getSelection()?.toString(),
    active: document.activeElement?.outerHTML.slice(0, 200),
  }));
  expect(state.pointerEvents, JSON.stringify(state)).not.toBe("none");
  expect(state.userSelect, JSON.stringify(state)).not.toBe("none");
}
