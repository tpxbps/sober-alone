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
const testArt = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="#21364a"/></svg>';
function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}
async function images(page: Page, broken = false, version = 1) {
  await page.route(url => url.pathname.startsWith('/images/'), route => {
    if (route.request().url().endsWith('preview.json')) return json(route, { title: '验证资源', clue_stages: [{ ...stage, presentation: { ...presentation, version } }] });
    return route.fulfill({ status: broken ? 404 : 200, contentType: broken ? 'text/plain' : 'image/svg+xml', body: broken ? 'Image unavailable' : testArt });
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
  expect(thumbnail!.width).toBeGreaterThan(300);
  expect(thumbnail!.height).toBe(164);
  await expect(tooltip.getByText('场景示意', { exact: true })).toHaveCount(0);
  await tooltip.locator('section').last().scrollIntoViewIfNeeded();
  await expect(tooltip.getByRole('heading', { name: /窗台红泥/ })).toBeInViewport();
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 844 });
  await citation.click();
  const sheet = page.getByRole('dialog', { name: '引用线索 · 2' });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole('heading', { name: /门锁痕迹/ })).toBeVisible();
  await sheet.locator('section').last().scrollIntoViewIfNeeded();
  await expect(sheet.getByRole('heading', { name: /窗台红泥/ })).toBeInViewport();
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
  const transforms = () => page.locator('.cinema-space, .cinema-card, .cinema-card img, .cinema-copy, .cinema-backdrop').evaluateAll(elements => elements.map(el => [getComputedStyle(el).transform, getComputedStyle(el).opacity, getComputedStyle(el).clipPath]));
  const paused = await transforms();
  await page.waitForTimeout(300);
  expect(await transforms()).toEqual(paused);
  await expect(page.locator('.cinema-progress, .cinema-trace')).toHaveCount(0);
  await expect(page.getByText('场景示意', { exact: true })).toHaveCount(0);
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
  const art = dialog.locator('.cinema-art img').first();
  const position = await art.evaluate(el => getComputedStyle(el).transform);
  await page.waitForTimeout(700);
  expect(await art.evaluate(el => getComputedStyle(el).transform)).toBe(position);
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

for (const template of ['cinematic', 'dossier']) {
  test(template + ': 收拢时上一幕字幕原位结束，结束语才居中', async ({ page }) => {
    await images(page, false, 2);
    await page.route(url => url.pathname.endsWith('/preview.json'), route => json(route, { clue_stages: [{ ...stage, presentation: {
      ...presentation, version: 2, template, shots: [
        { ...presentation.shots[0], id: 'question', duration_ms: 10000, title: '仍有疑问待解释' },
        { ...presentation.shots[0], id: 'closing', duration_ms: 2000, clue_ids: [], title: '开始本轮推理' },
      ],
    } }] }));
    await page.goto('/clue-preview.html?src=/images/scripts/test/preview.json');
    await page.getByRole('button', { name: '播放本轮演出' }).click();
    await expect(page.locator('.cinema-copy h2')).toHaveText('仍有疑问待解释');
    await page.locator('.cinema-immersive').evaluate(element => {
      const capture = () => ({ title: element.querySelector('h2')?.textContent, align: getComputedStyle(element.querySelector('.cinema-copy')!).textAlign });
      const observed = [capture()];
      (window as unknown as { observedCaptions: typeof observed }).observedCaptions = observed;
      new MutationObserver(() => observed.push(capture())).observe(element, { attributes: true, attributeFilter: ['data-phase'] });
    });
    await expect(page.locator('.cinema-copy h2')).toHaveText('开始本轮推理', { timeout: 20000 });
    await expect(page.locator('.cinema-copy')).toHaveCSS('text-align', 'center');
    const observed = await page.evaluate(() => (window as unknown as { observedCaptions: { title: string; align: string }[] }).observedCaptions);
    expect(observed.filter(item => item.title === '仍有疑问待解释').every(item => item.align === 'left')).toBe(true);
    expect(observed.some(item => item.title === '开始本轮推理' && item.align === 'center')).toBe(true);
  });
}

test('大图未返回时等待，全部就绪才从头播放且请求不重复', async ({ page }) => {
  let release!: () => void;
  const delayed = new Promise<void>(resolve => { release = resolve; });
  let fullRequests = 0;
  const progressiveMedia = { ...media, thumbnail_url: '/images/scripts/test/tiny.svg' };
  await page.route(url => url.pathname.endsWith('/preview.json'), route => json(route, { clue_stages: [{ ...stage,
    items: clues.map(clue => ({ ...clue, media: progressiveMedia })),
    presentation: { ...presentation, version: 2, background: progressiveMedia },
  }] }));
  await page.route('**/tiny.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: testArt }));
  await page.route('**/art.svg', async route => {
    fullRequests++; await delayed;
    await route.fulfill({ contentType: 'image/svg+xml', body: testArt });
  });
  try {
    await page.goto('/clue-preview.html?src=/images/scripts/test/preview.json', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: '播放本轮演出' }).click();
    await expect(page.getByRole('status')).toHaveText('正在准备本轮演出…');
    await page.waitForTimeout(600);
    await expect(page.locator('.cinema-copy, .cinema-card')).toHaveCount(0);
    release();
    await expect(page.locator('.cinema-copy h2')).toHaveText('观察现场');
    await expect(page.locator('.cinema-card img').first()).toHaveAttribute('src', media.image_url);
    expect(fullRequests).toBe(1);
  } finally { release(); }
});

test('图片全部损坏时自动显示正文摘要，确认仍由玩家触发', async ({ page }) => {
  await images(page, true, 2);
  await page.goto('/clue-preview.html?src=/images/scripts/test/preview.json');
  await page.getByRole('button', { name: '播放本轮演出' }).click();
  await expect(page.getByRole('button', { name: '继续推理' })).toBeVisible();
  await page.getByText('门锁痕迹', { exact: true }).last().click();
  await expect(page.getByRole('dialog').getByText('门锁没有撬动痕迹。')).toBeVisible();
  await page.route('**/art.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: testArt }));
  await page.getByRole('button', { name: '重试加载演出' }).click();
  await expect(page.locator('.cinema-copy h2')).toHaveText('观察现场');
});

test('仅一张必需图片损坏也不播放残缺动画', async ({ page }) => {
  await images(page, false, 2);
  const missing = { ...media, image_url: '/images/scripts/test/missing.webp' };
  await page.route(url => url.pathname.endsWith('/preview.json'), route => json(route, { clue_stages: [{ ...stage,
    items: [clues[0], { ...clues[1], media: missing }], presentation: { ...presentation, version: 2 },
  }] }));
  await page.route('**/missing.webp', route => route.fulfill({ status: 404, body: 'missing' }));
  await page.goto('/clue-preview.html?src=/images/scripts/test/preview.json');
  await page.getByRole('button', { name: '播放本轮演出' }).click();
  await expect(page.getByRole('button', { name: '继续推理' })).toBeVisible();
  await expect(page.locator('.cinema-card')).toHaveCount(0);
});

test('线索圆圈按轮次回看，关闭恢复焦点且不触发阶段确认', async ({ page }) => {
  await images(page);
  await page.route(url => url.pathname.endsWith('/preview.json'), route => json(route, { clue_stages: [stage, { ...stage, stage: 2,
    items: [{ ...clues[0], id: 'c03', stage: 2, summary: '后来公开的材料' }], presentation: { ...presentation, title: '第二轮' },
  }] }));
  await page.goto('/clue-preview.html?src=/images/scripts/test/preview.json');
  const trigger = page.getByRole('button', { name: '查看已公开线索（2条）' });
  await trigger.click();
  const archive = page.getByRole('dialog', { name: '线索档案' });
  await expect(archive.locator('summary')).toHaveCount(2);
  await expect(archive.getByRole('button', { name: /第 2 轮/ })).toHaveCount(0);
  await archive.getByText('门锁痕迹', { exact: true }).click();
  await expect(archive.getByText('门锁没有撬动痕迹。')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await page.getByRole('button', { name: '第 2 轮 · 第二轮' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '查看已公开线索（3条）' }).click();
  await expect(archive.getByText('后来公开的材料')).toBeVisible();
  await archive.getByRole('button', { name: /第 1 轮/ }).click();
  await expect(archive.locator('summary')).toHaveCount(2);
  await expect(archive.getByText('后来公开的材料')).toHaveCount(0);
  await expect(archive.getByRole('button', { name: '继续推理' })).toHaveCount(0);
  await archive.getByRole('button', { name: '返回讨论' }).click();
  await expect(archive).toBeHidden();
});
