import { expect, test } from '@playwright/test';

test.use({ reducedMotion: 'reduce' });

test('历史自我介绍不会在公开线索后获得引用权限，个人剧本强调清晰', async ({ page }, info) => {
  let revealed = false;
  let speechRequests = 0;
  const clue = { id: 'c01', summary: '门锁痕迹', content: '只有第一轮才能看到的证据内容。', stage: 1 };
  const character = { character_id: 'human', name: '林岚', occupation: '调查员', is_human: true,
    character_script: '这里是正文。**这是必须记住的秘密**。\n\n' + '普通段落用于验证长文阅读。\n\n'.repeat(30),
    character_script_summary: '你需要**守住钥匙的秘密**。' };
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = { success: true, scripts: [], models: [] };
    if (path.endsWith('/state')) data = {
      success: true, session_id: 'boundary-ui', status: 'playing', current_stage: revealed ? 'free_discussion' : 'intro',
      current_round: revealed ? 1 : 0, current_speaker_id: 'human', human_character_id: 'human', speech_queue: ['human'],
      script: { script_id: 'scope', title: '阶段验证' }, characters: [character], public_clues: revealed ? [clue] : [],
      player_states: [{ character_id: 'human', character_name: '林岚', is_human: true, remaining_speech_count: 1 }],
      agent_llm_info: {}, votes: {},
    };
    if (path.endsWith('/records')) data = { success: true, records: [
      { id: 1, session_id: 'boundary-ui', record_type: 'speech', stage: 'intro', speaker_id: 'ai', speaker_name: '馆长', content: '我是馆长。[c01]', clue_refs: [] },
      { id: 2, session_id: 'boundary-ui', record_type: 'speech', stage: 'intro', speaker_id: 'ai', speaker_name: '馆长', content: '旧版本异常元数据。[c01]', clue_refs: ['c01'] },
      ...(revealed ? [{ id: 3, session_id: 'boundary-ui', record_type: 'speech', stage: 'free_discussion', speaker_id: 'ai', speaker_name: '馆长', content: '现在才看到证据。[c01]', clue_refs: ['c01'] }] : []),
    ] };
    if (path.endsWith('/capabilities')) data = { models: [], features: {
      static_tts: { enabled: false }, streaming_tts: { enabled: false }, rag: { enabled: false }, image: { enabled: false },
    } };
    if (path.includes('/tts')) speechRequests++;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto('/?session=boundary-ui');
  await expect(page.locator('[data-record-id="1"]')).toContainText('[c01]');
  revealed = true;
  await page.reload();
  for (const id of [1, 2]) {
    await expect(page.locator(`[data-record-id="${id}"]`)).toContainText('[c01]');
    await expect(page.locator(`[data-record-id="${id}"]`).getByRole('button', { name: '查看线索 门锁痕迹' })).toHaveCount(0);
  }
  await expect(page.locator('[data-record-id="3"]').getByRole('button', { name: '查看线索 门锁痕迹' })).toBeVisible();
  await expect(page.locator('[data-record-id="3"]').getByTitle('TTS 未启用')).toBeVisible();
  expect(speechRequests).toBe(0);
  await page.screenshot({ path: info.outputPath('history-scope.png') });
  await page.getByRole('button', { name: /查看.*剧本|我的剧本/ }).focus();
  await page.keyboard.press('Enter');
  const strong = page.locator('[data-player-script-content] strong').first();
  await expect(strong).toHaveCSS('color', 'rgb(242, 223, 185)');
  await expect(strong).toHaveCSS('font-weight', '700');
  await page.getByRole('button', { name: '快速了解' }).click();
  await expect(page.locator('#player-quick-overview strong')).toHaveCSS('color', 'rgb(242, 223, 185)');
  await page.screenshot({ path: info.outputPath('private-script-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(strong).toBeVisible();
  await page.screenshot({ path: info.outputPath('private-script-mobile.png') });
});
