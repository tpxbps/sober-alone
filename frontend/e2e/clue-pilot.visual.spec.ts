import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

// Opt-in real resource review. Regular CI remains offline and uses no private scripts.
const pilotUrl = process.env.CLUE_PILOT_URL;
test.skip(!pilotUrl, 'Set CLUE_PILOT_URL to a local clue-preview.html URL');
test.use({ video: 'on' });
for (const device of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(device.name + ' watches every actual pilot scene', async ({ page }) => {
    test.setTimeout(150000);
    await page.setViewportSize(device);
    const url = new URL(pilotUrl!);
    const response = await page.request.get(new URL(url.searchParams.get('src')!, url.origin).href);
    const data = await response.json();
    const label = (process.env.CLUE_REVIEW_LABEL || 'clue-pilot-ready').replace(/[^a-zA-Z0-9_-]/g, '-');
    const output = path.resolve('../output/playwright', label);
    await mkdir(output, { recursive: true });
    await page.goto(pilotUrl!);
    for (const stage of data.clue_stages) {
      await page.getByRole('button', { name: '第 ' + stage.stage + ' 轮 · ' + stage.presentation.title }).click();
      await page.getByRole('button', { name: '播放本轮演出' }).click();
      await expect(page.locator('.cinema-immersive')).toBeVisible();
      await page.locator('.cinema-immersive').evaluate(element => {
        const observed: { phase: string | null; title: string | null | undefined }[] = [];
        (window as unknown as { captionPhases: typeof observed }).captionPhases = observed;
        new MutationObserver(() => observed.push({ phase: element.getAttribute('data-phase'), title: element.querySelector('h2')?.textContent }))
          .observe(element, { attributes: true, attributeFilter: ['data-phase'] });
      });
      for (const shot of stage.presentation.shots) {
        const title = page.locator('.cinema-copy h2');
        await expect(title).toHaveText(shot.title, { timeout: 16000 });
        await expect.poll(async () => page.locator('.cinema-copy').evaluate(element => Number(getComputedStyle(element).opacity)),
          { intervals: [16, 33, 50] }).toBeGreaterThan(0.99);
        await expect(page.locator('.cinema-progress, .cinema-trace')).toHaveCount(0);
        if (shot.caption) await expect(page.locator('.cinema-caption')).toHaveText(shot.caption);
        else await expect(page.locator('.cinema-caption')).toHaveCount(0);
        const bounds = await page.locator('.cinema-copy').boundingBox();
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(device.width);
        expect(bounds!.y + bounds!.height).toBeLessThan(device.height - 30);
        const immersive = stage.presentation.version === 2;
        const image = page.locator(immersive ? '.cinema-card img' : '.cinema-art img').first();
        await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
        const moving = immersive ? page.locator('.cinema-space') : image;
        if (immersive) await expect(page.locator('.cinema-card')).toHaveCount(stage.items.length);
        const before = await moving.evaluate(element => getComputedStyle(element).transform);
        await page.waitForTimeout(200);
        expect(await moving.evaluate(element => getComputedStyle(element).transform)).not.toBe(before);
        await page.screenshot({ path: path.join(output, device.name + '-' + stage.stage + '-' + shot.id + '.png') });
        if (shot === stage.presentation.shots.at(-1) && !shot.clue_ids.length) {
          const pause = page.getByRole('button', { name: '暂停演出' });
          await pause.focus();
          await expect.poll(() => page.locator('.cinema-immersive').getAttribute('data-gathered'),
            { intervals: [16, 33, 50] }).toBe('true');
          // Keyboard activation avoids waiting out the hover transition in the short final hold.
          await pause.press('Enter');
          const cards = await page.locator('.cinema-card').evaluateAll(elements => elements.map(element => {
            const box = element.getBoundingClientRect();
            return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
          }));
          for (const card of cards) {
            expect(card.left).toBeGreaterThanOrEqual(0);
            expect(card.right).toBeLessThanOrEqual(device.width);
            expect(card.top).toBeGreaterThan(60);
            expect(card.bottom).toBeLessThan(device.height - 100);
          }
          await page.screenshot({ path: path.join(output, device.name + '-' + stage.stage + '-gathered.png') });
          await page.getByRole('button', { name: '继续播放' }).click();
        }
      }
      await expect(page.getByRole('button', { name: '继续推理' })).toBeVisible({ timeout: 16000 });
      const phases = await page.evaluate(() => (window as unknown as { captionPhases: { phase: string; title: string }[] }).captionPhases);
      const gathered = phases.filter(item => item.phase === 'gather');
      expect(gathered.length).toBeGreaterThan(0);
      expect(gathered.every(item => item.title === stage.presentation.shots.at(-1).title)).toBe(true);
      await page.screenshot({ path: path.join(output, device.name + '-' + stage.stage + '-end.png') });
      await page.locator('.cinema-evidence-list summary').first().click();
      await expect(page.locator('.cinema-evidence-body').first()).toBeVisible();
      await page.screenshot({ path: path.join(output, device.name + '-' + stage.stage + '-reading.png') });
      await page.getByRole('button', { name: '继续推理' }).click();
      const sampleIds = stage.items.slice(0, 2).map((clue: { id: string }) => clue.id).join(',');
      await page.getByRole('textbox', { name: '发言输入框' }).fill(`[材料之间的联系仍需核实][${sampleIds}]`);
      await page.getByRole('button', { name: '预览发言', exact: true }).click();
      await page.getByLabel('查看 2 条引用线索', { exact: true }).hover();
      const details = page.getByRole('tooltip');
      await expect(details.locator('section')).toHaveCount(2);
      const thumbnail = await details.locator('img').first().boundingBox();
      expect(thumbnail!.width).toBeGreaterThan(300);
      expect(thumbnail!.height).toBe(164);
      await expect(details.locator('img').first()).not.toHaveAttribute('alt', /场景示意/);
      await expect(details.getByText('场景示意', { exact: true })).toHaveCount(0);
      await page.screenshot({ path: path.join(output, device.name + '-' + stage.stage + '-details.png') });
      await page.keyboard.press('Escape');

    }
  });
}
