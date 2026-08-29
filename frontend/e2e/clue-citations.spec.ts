import { expect, test, type Route } from '@playwright/test'

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('斜杠选择公开线索并在发言气泡展示可访问引用', async ({ page }) => {
  let submitted = ''
  let historyReloaded = false
  let records: unknown[] = []
  const characters = [
    { character_id: 'human', name: '陆鸣', character_script: '个人剧本', is_human: true },
    { character_id: 'ai-1', name: '姜芮', is_human: false },
  ]
  const publicClues = [
    {
      id: 'c01',
      summary: '门锁痕迹',
      content: '门锁没有撬动痕迹。',
      stage: 1,
    },
    {
      id: 'c02',
      summary: '窗台红泥',
      content: '窗台留有只在北岸出现的红泥。',
      stage: 1,
    },
    ...Array.from({ length: 8 }, (_, index) => ({
      id: `c${String(index + 3).padStart(2, '0')}`,
      summary: `补充线索 ${index + 3}`,
      content: `第 ${index + 3} 条补充线索的完整内容。`,
      stage: 1,
    })),
  ]

  await page.addInitScript(() => {
    localStorage.setItem('sober_alone_session', 'clue-session')
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/clue-session/state')) {
      return json(route, {
        success: true,
        session_id: 'clue-session',
        status: 'playing',
        current_stage: 'free_discussion',
        current_round: 1,
        current_speaker_id: 'human',
        speech_queue: ['human'],
        human_character_id: 'human',
        public_clues: publicClues,
        player_states: characters.map((character) => ({
          character_id: character.character_id,
          character_name: character.name,
          is_human: character.character_id === 'human',
          has_spoken_this_round: false,
          remaining_speech_count: 1,
          suspicion_reasons: {},
          suspected_by: {},
          player_perspectives: {},
        })),
        script: { script_id: 'clue-script', title: '线索测试' },
        characters,
        agent_llm_info: {},
        votes: {},
      })
    }
    if (path.endsWith('/clue-session/records')) {
      if (submitted) historyReloaded = true
      return json(route, { success: true, records, count: records.length })
    }
    if (path.endsWith('/clue-session/speech')) {
      submitted = route.request().postDataJSON().content
      records = [
        {
          id: 1,
          session_id: 'clue-session',
          stage: 'free_discussion',
          speaker_id: 'human',
          speaker_name: '陆鸣',
          content: '设备日志在关键时刻被清空。[c02] 这比口头证词更可靠。',
          clue_refs: ['c02'],
          record_type: 'speech',
          created_at: new Date().toISOString(),
        },
      ]
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type":"done","next_speaker_id":null}\n\n',
      })
    }
    if (path === '/api/v1/system/capabilities') {
      return json(route, {
        mode: 'local-first-single-user-single-process',
        models: [],
        features: {
          rag: { enabled: false, reason: '未配置' },
          image: { enabled: false, reason: '未配置' },
          static_tts: { enabled: false, reason: '未配置' },
          streaming_tts: { enabled: false, reason: '未配置' },
        },
      })
    }
    return json(route, { success: true })
  })

  await page.goto('/?session=clue-session')
  const composer = page.getByRole('textbox', { name: '发言输入框' })
  await composer.click()
  await composer.pressSequentially('/')
  const clueListbox = page.getByRole('listbox', { name: '已公开线索' })
  await expect(clueListbox).toBeVisible()
  for (let index = 0; index < 8; index += 1) await composer.press('ArrowDown')
  await expect(clueListbox.getByRole('option', { selected: true })).toContainText('补充线索 9')
  expect(await clueListbox.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  await composer.press('Escape')
  await composer.press('Control+A')
  await composer.press('Backspace')
  await expect(page.getByText('0/3000', { exact: true })).toBeVisible()
  await composer.pressSequentially('/')
  await composer.press('ArrowDown')
  await composer.press('Enter')
  await composer.pressSequentially(' 我认为这条线索最关键。')
  await page.getByRole('button', { name: '完成发言' }).click()

  await expect.poll(() => submitted).toContain('[c02]')
  await expect.poll(() => historyReloaded).toBe(true)
  const persistedRecord = page.locator('[data-record-id="1"]')
  await expect(persistedRecord).toContainText('设备日志在关键时刻被清空。')
  await expect(persistedRecord).toContainText('这比口头证词更可靠。')
  const citation = persistedRecord.getByRole('button', { name: '查看线索 窗台红泥' })
  await expect(citation).toBeVisible()
  const inlineHtml = await persistedRecord.locator('.markdown-content').innerHTML()
  expect(inlineHtml.indexOf('设备日志在关键时刻被清空')).toBeLessThan(inlineHtml.indexOf('查看线索 窗台红泥'))
  expect(inlineHtml.indexOf('查看线索 窗台红泥')).toBeLessThan(inlineHtml.indexOf('这比口头证词更可靠'))
  const clueTooltip = page.getByRole('tooltip').filter({ hasText: '窗台留有只在北岸出现的红泥。' })
  await citation.hover()
  await expect(clueTooltip).toBeVisible()
  await clueTooltip.getByText('窗台留有只在北岸出现的红泥。').hover()
  await expect(clueTooltip).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(clueTooltip).toBeHidden()
  await composer.focus()
  await citation.click()
  await expect(clueTooltip).toBeVisible()
  await expect(citation).toHaveAttribute('aria-expanded', 'true')
  await expect(clueTooltip).not.toContainText('c02')
  await citation.click()
  await expect(citation).toHaveAttribute('aria-expanded', 'false')
  await expect(clueTooltip).toBeHidden()
})
