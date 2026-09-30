import { expect, test } from '@playwright/test'
import { turnServer } from './turnServer'

for (const width of [1440, 390]) {
  test(`失败刷新保留原气泡，重试同一回合且不自动扣次 ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const server = await turnServer('free_discussion')
    try {
      await page.goto(server.url)
      await expect.poll(() => server.posts).toBe(1)
      const id = server.turn!.turn_id
      server.update('failed', '这段发言尚未完成。')
      const bubble = page.locator(`[data-turn-id="${id}"]`)
      await expect(bubble).toContainText('这段发言尚未完成。')
      await expect(bubble.getByRole('button', { name: '重试本轮' })).toBeVisible()
      const draft = page.getByRole('textbox', { name: '发言输入框' })
      await draft.fill('保留我的草稿')
      await page.reload()
      await expect(bubble).toContainText('这段发言尚未完成。')
      await expect(draft).toHaveText('保留我的草稿')
      expect(server.posts).toBe(1)
      await bubble.getByRole('button', { name: '重试本轮' }).click()
      await expect.poll(() => server.retries).toBe(1)
      await expect(bubble).toContainText('思考中')
      server.update('speaking', '新尝试的完整正文。')
      server.update('reacting')
      server.update('completed', undefined, 'human')
      await expect(bubble).toContainText('新尝试的完整正文。')
      await expect(bubble).not.toContainText('尚未完成')
      await expect(page.locator('[data-message-key]')).toHaveCount(1)
      expect(server.posts).toBe(1)
    } finally { await server.close() }
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
