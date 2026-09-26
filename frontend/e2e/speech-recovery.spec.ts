import { expect, test } from '@playwright/test'

for (const width of [1440, 390]) {
  test(`失败刷新不重启，重试和跳过只提交当前执行 ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    let automatic = 0, retries = 0, skips = 0
    let status = 'failed', remaining = 2, speaker: string | null = 'ai'
    const generation = () => ({ generation_id: 'g1', attempt_id: 'a2', character_id: 'ai', status,
      stage: 'free_discussion', round: 1, attempt: 2, reason: 'first_visible_timeout',
      partial_content: '这段发言尚未完成。', started_at: '', deadline_at: '' })
    const characters = [{ character_id: 'human', name: '真人', is_human: true }, { character_id: 'ai', name: '甲', is_human: false }]
    const state = () => ({ success: true, session_id: 'recovery', status: 'playing', current_stage: 'free_discussion',
      current_round: 1, human_character_id: 'human', current_speaker_id: speaker, speech_queue: [],
      speech_generation: generation(), characters, script: { script_id: 's', title: '恢复测试' },
      player_states: characters.map(c => ({ character_id: c.character_id, is_human: c.is_human,
        has_spoken_this_round: true, remaining_speech_count: c.is_human ? 2 : remaining,
        suspicion_reasons: {}, suspected_by: {}, player_perspectives: {} })), public_clues: [], votes: {}, agent_llm_info: {} })
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      const json = (value: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) })
      if (path.endsWith('/state')) return json(state())
      if (path.endsWith('/records')) return json({ success: true, records: [] })
      if (path.includes('/ai-speech/')) automatic++
      if (path.endsWith('/speech/retry')) {
        retries++
        expect(route.request().postDataJSON().generation_id).toBe('g1')
        return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ type: 'speech_status', generation: generation() })}\n\n` })
      }
      if (path.endsWith('/speech/skip')) {
        expect(route.request().postDataJSON().generation_id).toBe('g1')
        skips++; status = 'skipped'; remaining--; speaker = 'human'
        return json(state())
      }
      if (path.endsWith('/capabilities')) return json({ models: [], features: { streaming_tts: { enabled: false } } })
      return json({ success: true })
    })
    await page.goto('/?session=recovery')
    const panel = page.getByRole('region', { name: '发言恢复' })
    await expect(panel).toBeVisible()
    await expect(panel).toContainText('这段发言尚未完成')
    // Already spoke, but still has turns: both microphones remain available.
    await expect(page.locator('.lucide-mic-off')).toHaveCount(0)
    const draft = page.getByRole('textbox', { name: '发言输入框' })
    await draft.fill('保留我的草稿')
    await expect(page.getByRole('button', { name: '完成发言' })).toBeDisabled()
    await panel.getByRole('button', { name: '重试', exact: true }).click()
    await expect(panel.getByRole('button', { name: '重试', exact: true })).toBeEnabled()
    expect(retries).toBe(1)
    await expect(draft).toContainText('保留我的草稿')
    await page.reload()
    await expect(panel).toBeVisible()
    expect(automatic).toBe(0)
    await panel.getByRole('button', { name: '跳过本次发言' }).click()
    await expect(panel).toBeHidden()
    expect(skips).toBe(1)
    await expect(page.locator('.lucide-mic-off')).toHaveCount(0)
    expect(remaining).toBe(1)
    remaining = 0
    await page.reload()
    await expect(page.locator('.lucide-mic-off')).toHaveCount(1)
  })
}

test('投票气泡与复盘汇总均解析直接和关联引用', async ({ page }) => {
  const characters = [{ character_id: 'human', name: '真人', is_human: true }, { character_id: 'ai', name: '甲' }]
  const clues = [{ id: 'c01', summary: '门锁', content: '门锁未被撬动', stage: 1 }]
  const content = '投票给甲：核对[c01]，[门锁未撬][c01]。'
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (path.endsWith('/state')) return json({ success: true, session_id: 'votes', status: 'review', current_stage: 'review', current_round: 3,
      human_character_id: 'human', characters, public_clues: clues, player_states: [], speech_queue: [], votes: {},
      script: { script_id: 's', title: '投票测试' }, agent_llm_info: { ai: { model: 'deepseek-flash', provider: 'deepseek' } } })
    if (path.endsWith('/records')) return json({ success: true, records: [
      { id: 1, record_type: 'vote', stage: 'vote', speaker_id: 'ai', speaker_name: '甲', content, clue_refs: ['c01'] },
      { id: 2, record_type: 'system', stage: 'review', content: `投票结果收集如下\n\n- ${content}`, clue_refs: ['c01'] },
    ] })
    if (path.endsWith('/capabilities')) return json({ models: [{ id: 'deepseek-flash', name: 'deepseek-v4.1-flash', model: 'deepseek-v4.1-flash' }], features: { streaming_tts: { enabled: false } } })
    return json({ success: true, feedback: null })
  })
  await page.goto('/?session=votes')
  await expect(page.locator('[data-clue-citation]')).toHaveCount(4)
  await expect(page.locator('[data-record-id="1"]')).toContainText('deepseek-v4.1-flash')
  await expect(page.locator('[data-record-id="1"]')).not.toContainText('[c01]')
})
