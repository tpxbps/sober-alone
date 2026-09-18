import { expect, test, type Page } from '@playwright/test';

const sections = () => ({
  title: '暮雨旅馆', difficulty: 2, player_count: 3, overview: '最后一场告别宴，让旧日伙伴重逢。', description: '暴雨中的旅馆，三位老朋友各自带着未说出口的往事。', tags: '悬疑,情感',
  opening: '清晨，众人在旅馆大厅相遇。', truth_reveal: '昨夜的故事终于完整。', full_truth: '杯子被调换，意外导致死亡。',
  clue_stages: [{ stage: 1, overview: '书房里的遗留物', items: [{ id: 'c01', stage: 1, summary: '杯底残留', content: '检验发现杯底有残留。' }, { id: 'c02', stage: 1, summary: '旧账册', content: '账册记录了共同交易。' }], free_discussion_notice: '请结合各自经历讨论。' }], free_speech_limits: [2],
  game_flow: [{ type: 'initial', system_notice: '清晨，众人在旅馆大厅相遇。' }, { type: 'advancement', children: [{ system_notice: '线索' }, { system_notice: '讨论' }] }, { type: 'vote', children: [{ system_notice: '请总结你的判断。' }, { system_notice: '请指认真凶。' }] }, { type: 'review', system_notice: '昨夜的故事终于完整。' }],
  character_scripts: {},
  character_data: ['许舟', '陆宁', '顾青'].map((name, index) => ({ character_id: ['a', 'z', 'm'][index], name, gender: '男', age: 30, occupation: '旅馆老客人', profile: `${name}和馆主相识多年。`, appearance: '深色外套，略显疲惫。', script_summary: '我记得昨晚的争执。', character_script: `我是${name}。昨晚，我再次来到这家旅馆。\n\n` + '我和馆主曾经自愿合作，彼此都清楚账目里的秘密。'.repeat(12), system_prompt: '依照个人经历扮演角色。', step_voice_id: 'cixingnansheng' })),
});

async function setup(page: Page, step = 'review_game_data', qualityFailure = false) {
  let data = sections();
  let checkpoint = 'cp1';
  let current = step;
  // Older servers serialize an unrequested quality report as an empty object.
  let quality: unknown = {};
  let qualityAttempted = false;
  let busy = false;
  let failed = false;
  const submissions: Record<string, unknown>[] = [];
  const state = () => ({ workflow_mode: 'create', script_id: 'ux-script', script_title: data.title, player_count: 3, difficulty: 2, num_clue_rounds: 1, prompts: {}, error_message: '', first_draft: '模型原稿', outline: '', final_draft: '', characters: data.character_data, game_data_sections: data, quality_report: quality, quality_check_attempted: qualityAttempted });
  const response = () => ({ success: true, thread_id: 'ux-thread', checkpoint_id: checkpoint, current_step: current, is_complete: false, state: state(), interrupt: { step: current, step_label: '初稿审阅', generated_content: current === 'review_first_draft' ? '模型原稿' : '新的审稿意见', prompt_used: '', game_data_sections: data, quality_report: quality } });
  await page.addInitScript(() => { if (!localStorage.getItem('editorSession')) localStorage.setItem('editorSession', JSON.stringify({ threadId: 'ux-thread', currentStep: 'review_game_data' })); });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const send = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/state')) return send(response());
    if (path.endsWith('/history')) return send({ success: true, checkpoints: [] });
    if (path.endsWith('/progress-stream')) return route.fulfill({ contentType: 'text/event-stream', body: ': heartbeat\n\n' });
    if (path.endsWith('/asset-progress') || path.endsWith('/convert-progress')) return send({ success: true, progress: null });
    if (path.endsWith('/resume')) {
      const body = route.request().postDataJSON(); submissions.push(body);
      if (body.action === 'quality_check') qualityAttempted = true;
      if (body.game_data_sections) data = body.game_data_sections;
      if (body.action === 'quality_check') quality = { report_id: 'report-once', content_fingerprint: 'fp', status: qualityFailure ? 'incomplete' : 'blocked', error: qualityFailure ? '本次检查未完成，仍可继续创作。' : undefined, source_sections: structuredClone(data), findings: qualityFailure ? [] : [{ severity: 'major', impact: '请核对这段记忆是否发生在开局前。', evidence: '我记得昨晚的争执。', suggestion: '仅保留开局已经知道的内容。', field: 'characters[2].character_script_summary', target: { section: 'characters', entity_id: 'z', field: 'character_script_summary', label: '角色 → 陆宁 → 角色速览' } }] };
      else if (current === 'review_first_draft' && !failed) current = 'review_report';
      else if (current === 'review_final' && !failed) current = 'review_game_data';
      checkpoint = 'cp2';
      return send({ success: true, thread_id: 'ux-thread', operation_id: body.request_id, operation_status: 'queued', target_step: step });
    }
    if (path.includes('/operations/')) return send(failed ? { operation_status: 'failed', error_message: '暂时无法生成，请重试。' } : busy ? { operation_id: path.split('/').at(-1), operation_status: 'running', current_step: step === 'review_final' ? 'convert_to_game_data' : 'review_by_llm', progress: { message: '进行中' } } : { ...response(), operation_id: path.split('/').at(-1), operation_status: 'complete' });
    return send({ success: true, scripts: [], voices: [], models: [], features: {} });
  });
  await page.goto('/?editor=resume');
  return { submissions, setFailed: (value: boolean) => { failed = value; }, setBusy: (value: boolean) => { busy = value; }, reorder: () => { data.character_data.reverse(); }, data: () => data };
}

for (const width of [1280, 390]) {
  test(`终稿拆分完成后未质检也能进入游戏数据，刷新不白屏 ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const fixture = await setup(page, 'review_final');
    await page.getByRole('button', { name: '编辑终稿', exact: true }).click();
    await page.getByLabel('终稿正文').fill('作者确认终稿：角色只知道各自亲历的事实。');
    fixture.setBusy(true);
    await page.getByRole('button', { name: '确认终稿并拆分' }).click();
    await expect.poll(() => fixture.submissions.length).toBe(1);
    expect(fixture.submissions[0].content).toBe('作者确认终稿：角色只知道各自亲历的事实。');
    await expect(page.getByRole('heading', { name: '结构化数据转化' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: '结构化数据转化' })).toBeVisible();
    fixture.setBusy(false);
    await expect(page.getByTestId('game-data-workspace')).toBeVisible({ timeout: 12000 });
    await expect(page.getByRole('button', { name: '质量检查（可选）' })).toBeVisible();
    await expect(page.getByRole('button', { name: '下一步 · 生成资源' })).toBeEnabled();
    expect(fixture.submissions).toHaveLength(1);
    await page.reload();
    await expect(page.getByTestId('game-data-workspace')).toBeVisible();
    expect(errors).toEqual([]);
  });
}

for (const width of [1280, 390]) {
  test(`工作区导航、长文与报告定位 ${width}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const fixture = await setup(page);
    await expect(page.getByTestId('game-data-workspace')).toBeVisible();
    if (width < 768) await page.getByLabel('编辑章节').selectOption('characters');
    else await page.getByRole('button', { name: '角色 每个人眼中的真相' }).click();
    await page.getByRole('button', { name: '陆宁', exact: true }).click();
    await page.getByLabel('个人剧本', { exact: true }).fill('作者修订：双方自愿合作，昨晚我独自取了账册。');
    await page.getByRole('button', { name: '外貌描述说明' }).scrollIntoViewIfNeeded();
    await page.getByRole('button', { name: '外貌描述说明' }).hover();
    await expect(page.getByRole('tooltip')).toContainText('将用于角色形象生成');
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '质量检查（可选）' }).click();
    await expect(page.getByRole('dialog', { name: '游戏数据质检报告' })).toBeVisible();
    expect(fixture.submissions.filter(s => s.action === 'quality_check')).toHaveLength(1);
    await page.getByRole('button', { name: /定位：角色 → 陆宁/ }).click();
    await expect(page.getByLabel('角色姓名')).toHaveValue('陆宁');
    await expect(page.getByLabel('角色速览', { exact: true })).toBeFocused();
    await page.getByLabel('角色速览', { exact: true }).fill('我昨晚取走了账册。');
    await page.getByRole('button', { name: '质检报告', exact: true }).click();
    await expect(page.getByText('检查后内容已有变化。', { exact: false })).toBeVisible();
    await page.getByRole('button', { name: '关闭', exact: true }).click();
    fixture.reorder();
    await page.reload();
    await page.getByRole('button', { name: '质检报告', exact: true }).click();
    await page.getByRole('button', { name: /定位：角色 → 陆宁/ }).click();
    await expect(page.getByLabel('角色姓名')).toHaveValue('陆宁');
    expect(fixture.submissions.filter(s => s.action === 'quality_check')).toHaveLength(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(page.getByRole('dialog', { name: '游戏数据质检报告' })).not.toBeVisible();
    await page.screenshot({ path: info.outputPath(`workspace-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: '下一步 · 生成资源' }).click();
    await expect.poll(() => fixture.submissions.at(-1)?.action).toBe('confirm');
  });
}

test('未点保存直接继续，等待页与刷新均保留本次提交稿', async ({ page }) => {
  const fixture = await setup(page, 'review_first_draft');
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByLabel('剧本正文').fill('人工新版：彼此自愿合作，保留无预谋主题。');
  fixture.setBusy(true);
  await page.getByRole('button', { name: '确认并继续' }).click();
  await expect.poll(() => fixture.submissions.length).toBe(1);
  expect(fixture.submissions[0].content).toBe('人工新版：彼此自愿合作，保留无预谋主题。');
  expect(fixture.submissions[0].expected_checkpoint_id).toBe('cp1');
  await expect(page.getByText('人工新版：彼此自愿合作，保留无预谋主题。', { exact: true })).toBeVisible();
  await expect(page.getByText('模型原稿', { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('人工新版：彼此自愿合作，保留无预谋主题。', { exact: true })).toBeVisible();
  fixture.setBusy(false);
  await expect(page.getByLabel('AI 审稿意见', { exact: true })).toBeVisible({ timeout: 12000 });
});

test('方向性重写提交反馈和当前编辑稿，可用键盘完成', async ({ page }) => {
  const fixture = await setup(page, 'review_first_draft');
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByLabel('剧本正文').fill('当前正在编辑的稿件');
  await page.getByRole('button', { name: '输入改进方向 · 重新生成' }).click();
  await expect(page.getByLabel('改进方向', { exact: true })).toBeFocused();
  await expect(page.getByRole('button', { name: '按此方向改写' })).toBeDisabled();
  await page.getByLabel('改进方向', { exact: true }).fill('让冲突更加克制');
  await page.keyboard.press('Tab'); await page.keyboard.press('Enter');
  await expect.poll(() => fixture.submissions[0]?.feedback).toBe('让冲突更加克制');
  expect(fixture.submissions[0].content).toBe('当前正在编辑的稿件');
});

test('未检查与检查失败都能直接下一步', async ({ page }) => {
  const fixture = await setup(page, 'review_game_data', true);
  await page.getByRole('button', { name: '下一步 · 生成资源' }).click();
  await expect.poll(() => fixture.submissions[0]?.action).toBe('confirm');
  await page.getByRole('button', { name: '质量检查（可选）' }).click();
  await expect(page.getByText('本次检查未完成，仍可继续创作。')).toBeVisible();
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '下一步 · 生成资源' }).click();
  await expect.poll(() => fixture.submissions.filter(s => s.action === 'confirm').length).toBe(2);
});

test('创意打字提示不写入输入值，聚焦停止且支持减少动态效果', async ({ page }) => {
  await page.route('**/api/v1/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ scripts: [], models: [], features: {} }) }));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/?editor=resume');
  const idea = page.getByLabel('故事创意', { exact: true });
  await expect(idea).toHaveValue('');
  await expect(idea).toHaveAttribute('placeholder', /故事发生在某家互联网大厂/);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await idea.focus();
  const value = await idea.getAttribute('placeholder');
  await page.waitForTimeout(160);
  expect(await idea.getAttribute('placeholder')).toBe(value);
  await expect(idea).toHaveValue('');
});


test('生成失败后的未保存编辑稿刷新仍可恢复', async ({ page }) => {
  const fixture = await setup(page, 'review_first_draft');
  fixture.setFailed(true);
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByLabel('剧本正文').fill('失败也应保留的作者新版');
  await page.getByRole('button', { name: '确认并继续' }).click();
  await expect(page.getByText('暂时无法生成，请重试。')).toBeVisible();
  await page.reload();
  await expect(page.getByText('失败也应保留的作者新版', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByLabel('剧本正文')).toHaveValue('失败也应保留的作者新版');
});


for (const width of [390, 1280]) {
  test(`各文本节点操作按钮保持同排 ${width}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 844 });
    for (const step of ['review_first_draft', 'review_report', 'review_final']) {
      await setup(page, step);
      const refine = page.getByRole('button', { name: '输入改进方向 · 重新生成' });
      const confirm = page.getByRole('button', { name: /^(确认并继续|确认意见并生成终稿|确认终稿并拆分)$/ });
      await expect(refine).toBeVisible();
      await expect(confirm).toBeVisible();
      const left = (await refine.boundingBox())!, right = (await confirm.boundingBox())!;
      expect(Math.abs((left.y + left.height / 2) - (right.y + right.height / 2))).toBeLessThan(2);
      expect(left.x + left.width).toBeLessThan(right.x);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: info.outputPath(`${step}-${width}.png`) });
    }
  });
}

test('长等待显示静态提示且不显示小游戏或提交横幅', async ({ page }) => {
  await page.clock.install();
  const fixture = await setup(page, 'review_first_draft');
  fixture.setBusy(true);
  await page.getByRole('button', { name: '确认并继续' }).click();
  await expect.poll(() => fixture.submissions.length).toBe(1);
  await page.clock.fastForward(11000);
  await expect(page.getByText('单个节点可能耗时数分钟，且剧本越复杂耗时越久，请耐心等待～', { exact: true })).toBeVisible();
  await expect(page.getByText(/打地鼠|当前显示本次提交内容|稳定执行/)).toHaveCount(0);
});
