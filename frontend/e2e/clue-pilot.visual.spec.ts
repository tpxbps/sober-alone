import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

// Opt-in real resource review. Regular CI remains offline and uses no private scripts.
const pilotUrl = process.env.CLUE_PILOT_URL;
test.skip(!pilotUrl, 'Set CLUE_PILOT_URL to a local clue-preview.html URL');
for (const device of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(device.name + ' watches every actual pilot scene', async ({ page }) => {
    test.setTimeout(150000);
    await page.setViewportSize(device);
    const url = new URL(pilotUrl!);
    const response = await page.request.get(new URL(url.searchParams.get('src')!, url.origin).href);
    const data = await response.json();
    const output = path.resolve('../output/playwright/clue-pilot');
    await mkdir(output, { recursive: true });
    await page.goto(pilotUrl!);
    for (const stage of data.clue_stages) {
      await page.getByRole('button', { name: '第 ' + stage.stage + ' 轮 · ' + stage.presentation.title }).click();
      await page.getByRole('button', { name: '播放本轮演出' }).click();
      for (const shot of stage.presentation.shots) {
        const title = page.locator('.cinema-copy h2');
        await expect(title).toHaveText(shot.title, { timeout: 16000 });
        await expect.poll(async () => title.evaluate(element => Number(getComputedStyle(element).opacity))).toBeGreaterThan(0.99);
        await expect(page.locator('.cinema-caption')).toHaveText(shot.caption);
        const bounds = await page.locator('.cinema-copy').boundingBox();
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(device.width);
        expect(bounds!.y + bounds!.height).toBeLessThan(device.height - 30);
        const image = page.locator('.cinema-art img').first();
        await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
        const before = await image.evaluate(element => getComputedStyle(element).transform);
        await page.waitForTimeout(200);
        expect(await image.evaluate(element => getComputedStyle(element).transform)).not.toBe(before);
        await page.screenshot({ path: path.join(output, device.name + '-' + stage.stage + '-' + shot.id + '.png') });
      }
      await expect(page.getByRole('button', { name: '继续推理' })).toBeVisible({ timeout: 16000 });
      await page.screenshot({ path: path.join(output, device.name + '-' + stage.stage + '-end.png') });
      await page.getByRole('button', { name: '继续推理' }).click();
    }
  });
}
