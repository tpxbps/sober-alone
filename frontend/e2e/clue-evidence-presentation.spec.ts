import { expect, test, type Page, type Route } from '@playwright/test';

const media = { image_url: '/images/scripts/test/art.svg', thumbnail_url: '/images/scripts/test/art.svg', alt: '测试场景', focus: [0.5, 0.5], status: 'ready' };
const clues = [
  { id: 'c01', summary: '门锁痕迹', content: '门锁没有撬动痕迹。', stage: 1, media },
  { id: 'c02', summary: '窗台红泥', content: '窗台留有红泥。\n\n' + '补充材料。'.repeat(60), stage: 1, media },
];
const presentation = {
  version: 1, revision: 'test-v1', template: 'cinematic', title: '线索演出',
  status: 'ready', background: media,
  shots: [{ id: 'scene', duration_ms: 15000, clue_ids: ['c01', 'c02'], title: '观察现场', caption: '两处痕迹，等待解释。', emphasis: '等待解释', motion: 'split', labels: [] }],
};
const stage = { stage: 1, overview: '材料', free_discussion_notice: '讨论', items: clues, presentation };
function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}
async function images(page: Page, broken = false, version = 1) {
  await page.route(url => url.pathname.startsWith('/images/'), route => {
    if (route.request().url().endsWith('preview.json')) return json(route, { title: '验证资源', clue_stages: [{ ...stage, presentation: { ...presentation, version } }] });
    return route.fulfill({ status: broken ? 404 : 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="#21364a"/></svg>' });
  });
}
test('引用编辑、多选、换行、重开、复制删除与手机详情', async ({ page }) => {
  await images(page);
  await page.goto('/clue-preview.html?src=/images/scripts/test/preview.json');
  const editor = page.getByRole('textbox', { name: '发言输入框' });
  await editor.fill('/');
  await editor.press('Enter');
  const panel = page.getByRole('dialog', { name: '编辑线索引用' });
  const reason = page.getByRole('textbox', { name: '相关推理' });
  await expect(reason).toBeFocused();
  await reason.fill('第一行[解释]');
  await reason.press('Enter');
  await reason.pressSequentially('第二行');
  await panel.getByRole('checkbox', { name: /窗台红泥/ }).check();
  await reason.press('Control+Enter');
  await expect(panel).toBeHidden();
  await expect(editor).toBeFocused();
  await editor.getByRole('button').click();
  await expect(reason).toHaveValue('第一行[解释]\n第二行');
  await reason.press('Escape');
  const serialized = page.getByLabel('引用序列化文本');
  await expect(serialized).toContainText('c01,c02');
  await editor.press('Control+A');
  const copied = await editor.evaluate(element => {
    const transfer = new DataTransfer();
    element.dispatchEvent(new ClipboardEvent('copy', { bubbles: true, clipboardData: transfer }));
    return transfer.getData('text/plain');
  });
  expect(copied).toContain('[c01,c02]');
  await page.getByRole('button', { name: '预览发言', exact: true }).click();
  const citation = page.getByRole('button', { name: '查看 2 条引用线索' });
  await expect(citation).toBeVisible();
  await citation.hover();
  const tooltip = page.getByRole('tooltip');
  await expect(tooltip.locator('section')).toHaveCount(2);
  await expect(tooltip.locator('img')).toHaveCount(2);
  const thumbnail = await tooltip.locator('img').first().boundingBox();
  expect(thumbnail!.width).toBeLessThanOrEqual(96);
  expect(thumbnail!.height).toBeLessThanOrEqual(64);
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 844 });
  await citation.click();
  const sheet = page.getByRole('dialog', { name: '引用线索 · 2' });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole('heading', { name: /门锁痕迹/ })).toBeVisible();
  await sheet.getByRole('button', { name: '关闭线索详情' }).click();
  await editor.fill('/');
  await editor.press('Enter');
  await reason.fill('未应用也会发送');
  await page.getByRole('button', { name: '预览发言', exact: true }).click();
  await expect(page.getByRole('button', { name: '查看 1 条引用线索' })).toHaveText('未应用也会发送1');
  await editor.fill('/');
  await editor.press('Enter');
  await reason.press('Escape');
  await editor.press('Control+A');
  await editor.press('Backspace');
  await expect(serialized).toBeEmpty();
  // IME Enter must never submit the composer; oversized input restores the last valid document.
  await editor.fill('已保存');
  await editor.dispatchEvent('compositionstart');
  await editor.dispatchEvent('keydown', { key: 'Enter', isComposing: true, keyCode: 229 });
  await expect(serialized).toHaveText('已保存');
  await editor.dispatchEvent('compositionend');
  await editor.fill('字'.repeat(3001));
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(serialized).toHaveText('已保存');
});

test('连续镜头保留所有物证，暂停冻结运动，结尾仍可读正文', async ({ page }) => {
  await images(page, false, 2);
  await page.goto('/clue-preview.html?src=/images/scripts/test/preview.json');
  await page.getByRole('button', { name: '播放本轮演出' }).click();
  await expect(page.locator('.cinema-card')).toHaveCount(2);
  await expect.poll(() => page.locator('.cinema-card').first().evaluate(el => Number(getComputedStyle(el).opacity))).toBeGreaterThan(0.5);
  await page.getByRole('button', { name: '暂停演出' }).click();
  const transforms = () => page.locator('.cinema-space, .cinema-card').evaluateAll(elements => elements.map(el => getComputedStyle(el).transform));
  const paused = await transforms();
  await page.waitForTimeout(300);
  expect(await transforms()).toEqual(paused);
  await page.getByRole('button', { name: '继续播放' }).click();
  await expect.poll(transforms).not.toEqual(paused);
  await page.getByRole('button', { name: '跳至结尾' }).click();
  await page.getByText('门锁痕迹', { exact: true }).last().click();
  await expect(page.getByRole('dialog').getByText('门锁没有撬动痕迹。')).toBeVisible();
  await page.getByRole('button', { name: '继续推理' }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
});
test('暂停、跳至结尾、确认失败重试、刷新与多标签页恢复', async ({ page, context }) => {
  await images(page);
  let acknowledged = false, acknowledgements = 0, aiRequests = 0;
  const characters = [{ character_id: 'human', name: '真人', character_script: '资料', is_human: true }, { character_id: 'ai', name: '甲', is_human: false }];
  const state = () => ({
    success: true, session_id: 'cinema', status: 'playing', current_stage: 'clue_analysis', current_round: 1,
    current_speaker_id: acknowledged ? 'human' : null, speech_queue: ['human', 'ai'], human_character_id: 'human',
    public_clues: clues, characters, script: { script_id: 'test', title: '演出测试' }, agent_llm_info: {}, votes: {},
    player_states: characters.map(c => ({ character_id: c.character_id, character_name: c.name, is_human: c.is_human, has_spoken_this_round: false, remaining_speech_count: 1, suspicion_reasons: {}, suspected_by: {}, player_perspectives: {} })),
    clue_presentation: { presentation_id: '1:test-v1', round: 1, status: acknowledged ? 'acknowledged' : 'pending', presentation, clues },
  });
  await context.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/state')) return json(route, state());
    if (path.endsWith('/records')) return json(route, { success: true, records: [] });
    if (path.endsWith('/clue-presentation/ack')) {
      expect(route.request().postDataJSON().presentation_id).toBe('1:test-v1');
      if (++acknowledgements === 1) return json(route, { detail: 'retry' }, 503);
      acknowledged = true; return json(route, state());
    }
    if (path.includes('ai-speech')) aiRequests++;
    return json(route, { success: true });
  });
  await page.goto('/?session=cinema');
  const dialog = page.getByRole('dialog', { name: '线索演出' });
  await expect(dialog).toBeVisible();
  await page.getByRole('button', { name: '暂停演出' }).click();
  const progress = await dialog.locator('.cinema-progress-bars i').getAttribute('style');
  await page.waitForTimeout(700);
  expect(await dialog.locator('.cinema-progress-bars i').getAttribute('style')).toBe(progress);
  await page.getByRole('button', { name: '跳至结尾' }).click();
  await expect(page.getByRole('button', { name: '继续推理' })).toBeVisible();
  expect(acknowledgements).toBe(0); expect(aiRequests).toBe(0);
  await page.reload();
  await expect(page.getByRole('button', { name: '跳至结尾' })).toBeVisible();
  await page.getByRole('button', { name: '跳至结尾' }).click();
  const other = await context.newPage();
  await images(other);
  await other.goto('/?session=cinema');
  await expect(other.getByRole('dialog', { name: '线索演出' })).toBeVisible();
  await page.getByRole('button', { name: '继续推理' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '暂时无法确认' })).toBeVisible();
  await page.getByRole('button', { name: '继续推理' }).click();
  await expect(dialog).toBeHidden();
  await expect(other.getByRole('dialog', { name: '线索演出' })).toBeHidden({ timeout: 6000 });
  await page.reload();
  await expect(page.getByRole('textbox', { name: '发言输入框' })).toBeVisible();
  await expect(dialog).toBeHidden();
  expect(aiRequests).toBe(0);
  await other.close();
});
test('资源失效与减少动态效果仍有可读摘要和继续入口', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await images(page, true);
  await page.goto('/clue-preview.html?src=/images/scripts/test/preview.json');
  await page.getByRole('button', { name: '播放本轮演出' }).click();
  await expect(page.getByRole('button', { name: '继续推理' })).toBeVisible();
  await page.getByText('门锁痕迹', { exact: true }).last().click();
  await expect(page.getByRole('dialog').getByText('门锁没有撬动痕迹。')).toBeVisible();
  await page.getByRole('button', { name: '继续推理' }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
});
