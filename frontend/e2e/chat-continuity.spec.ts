import { expect, test, type Page } from '@playwright/test';
import { turnServer } from './turnServer';

async function watchBubble(page: Page, turnId: string) {
  await page.locator(`[data-turn-id="${turnId}"]`).waitFor();
  await page.evaluate(id => {
    const selector = `[data-turn-id="${id}"]`;
    const row = document.querySelector(selector)!;
    const avatar = row.firstElementChild;
    const body = row.querySelector('[data-speech-body]');
    const markdown = body?.querySelector('.markdown-content');
    const monitor = { failures: [] as string[], samples: 0, visible: false, text: '' };
    Object.assign(window, { bubbleMonitor: monitor });
    const check = () => {
      const now = document.querySelector(selector);
      monitor.samples++;
      if (!row.isConnected || now !== row) monitor.failures.push('bubble remounted or disappeared');
      if (now?.firstElementChild !== avatar || now?.querySelector('[data-speech-body]') !== body) monitor.failures.push('avatar or body remounted');
      if (now?.querySelector('.markdown-content') !== markdown) monitor.failures.push('markdown remounted');
      if (document.querySelectorAll(selector).length !== 1) monitor.failures.push('duplicate bubble');
      const opacity = Number(getComputedStyle(row).opacity);
      if (monitor.visible && opacity < 0.95) monitor.failures.push('entrance animation replayed');
      if (opacity >= 0.99) monitor.visible = true;
      const text = body?.querySelector('.markdown-content')?.textContent ?? '';
      if (monitor.text && !text.includes(monitor.text)) monitor.failures.push('text regressed');
      if (text && !text.includes('思考中')) monitor.text = text;
      requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  }, turnId);
}
async function checkMonitor(page: Page) {
  const result = await page.evaluate(() => (window as unknown as { bubbleMonitor: { failures: string[]; samples: number } }).bubbleMonitor);
  expect(result.samples).toBeGreaterThan(5);
  expect(result.failures).toEqual([]);
}

test('real segmented SSE keeps bubble and avatar through slow text, commit, EOF and reactions', async ({ page }) => {
  const server = await turnServer();
  try {
    await page.goto(server.url);
    await expect.poll(() => server.turn?.status).toBe('queued');
    const id = server.turn!.turn_id;
    const row = page.locator(`[data-turn-id="${id}"]`);
    await expect(row.getByText('思考中', { exact: true })).toBeVisible();
    await watchBubble(page, id);
    await page.waitForTimeout(500); // Slow first token must keep the optimistic row.
    server.update('speaking', '第一段。');
    await expect(row).toContainText('第一段。');
    await expect(page.locator('[data-game-composer]')).toContainText('姜芮 正在发言');
    server.duplicate();
    await page.waitForTimeout(200);
    server.update('speaking', '第一段。第二段。');
    await expect(row).toContainText('第二段。');
    server.update('committing');
    await expect(page.locator('[data-game-composer]')).toContainText('这段发言引发了大家思考');
    await page.waitForTimeout(300); // Delayed record commit, no cursor or placeholder reset.
    server.disconnect();
    await expect.poll(() => server.subscriptions).toBe(2);
    expect(server.posts).toBe(1);
    await expect(row).toContainText('第一段。第二段。');
    server.update('reacting');
    await page.waitForTimeout(300);
    server.update('completed');
    await expect(page.getByRole('textbox', { name: '发言输入框' })).toBeVisible();
    await expect(row).toHaveAttribute('data-record-id', '1');
    await expect(row).toContainText('第一段。第二段。');
    await checkMonitor(page);
  } finally { await server.close(); }
});

for (const phase of ['queued', 'speaking', 'committing', 'reacting'] as const) {
  test(`refresh in ${phase} reattaches original operation`, async ({ page }) => {
    const server = await turnServer();
    try {
      await page.goto(server.url);
      await expect.poll(() => server.turn?.status).toBe('queued');
      const id = server.turn!.turn_id;
      if (phase !== 'queued') server.update(phase, '刷新前的内容。');
      await page.reload();
      await expect.poll(() => server.subscriptions).toBe(2);
      const row = page.locator(`[data-turn-id="${id}"]`);
      await expect(row).toContainText(phase === 'queued' ? '思考中' : '刷新前的内容。');
      expect(server.posts).toBe(1);
      await watchBubble(page, id);
      if (phase !== 'reacting') {
        server.update('speaking', '刷新前的内容。接着输出。');
        await expect(row).toContainText('接着输出。');
        server.update('reacting');
      }
      await page.waitForTimeout(500);
      server.update('completed');
      await expect(page.getByRole('textbox', { name: '发言输入框' })).toBeVisible();
      await expect(row).toHaveAttribute('data-record-id', '1');
      await checkMonitor(page);
    } finally { await server.close(); }
  });
}

test('queued human wins next AI slot and remains the same row after acknowledgement', async ({ page }) => {
  const server = await turnServer('free_discussion');
  try {
    await page.goto(server.url);
    await expect.poll(() => server.posts).toBe(1);
    const composer = page.getByRole('textbox', { name: '发言输入框' });
    await composer.fill('我的原话保持在这里。');
    await composer.press('Control+Enter');
    const queued = page.locator('[data-message-key]').filter({ hasText: '我的原话保持在这里。' });
    await expect(queued).toHaveCount(1);
    const id = await queued.getAttribute('data-turn-id');
    await watchBubble(page, id!);
    server.update('speaking', 'AI 发言。');
    server.update('reacting');
    server.update('completed', undefined, 'ai'); // Same character may speak consecutively.
    await expect.poll(() => server.turn?.kind).toBe('human');
    expect(server.posts).toBe(2);
    expect(server.turn!.turn_id).toBe(id);
    server.update('reacting');
    await page.waitForTimeout(500);
    server.update('completed', undefined, 'human');
    await expect(queued).toHaveAttribute('data-record-id', '2');
    await checkMonitor(page);
  } finally { await server.close(); }
});

test('pause and unsent draft survive refresh, then the same AI gets a distinct next bubble', async ({ page }) => {
  const server = await turnServer('free_discussion');
  try {
    await page.goto(server.url);
    await expect.poll(() => server.posts).toBe(1);
    const firstId = server.turn!.turn_id;
    await page.getByRole('switch', { name: '让我想想', exact: true }).click();
    await page.getByRole('textbox', { name: '发言输入框' }).fill('保留未发送的草稿');
    await page.reload();
    await expect(page.getByRole('textbox', { name: '发言输入框' })).toHaveText('保留未发送的草稿');
    await expect(page.getByRole('switch', { name: '让我想想', exact: true })).toBeChecked();
    await expect.poll(() => server.subscriptions).toBe(2);
    await watchBubble(page, firstId);
    server.update('speaking', '第一轮发言。');
    server.update('reacting');
    server.update('completed', undefined, 'ai');
    await expect(page.getByRole('switch', { name: '让我想想', exact: true })).toBeChecked();
    await page.waitForTimeout(500);
    expect(server.posts).toBe(1);
    await page.getByRole('switch', { name: '让我想想', exact: true }).click();
    await expect.poll(() => server.posts).toBe(2);
    expect(server.turn!.turn_id).not.toBe(firstId);
    await expect(page.locator('[data-message-key]')).toHaveCount(2);
    await expect(page.locator(`[data-turn-id="${firstId}"]`)).toContainText('第一轮发言。');
    await expect(page.locator(`[data-turn-id="${server.turn!.turn_id}"]`)).toContainText('思考中');
    await expect(page.getByRole('button', { name: /查看.*的人物形象/ })).toHaveCount(0);
    await checkMonitor(page);
  } finally { await server.close(); }
});
