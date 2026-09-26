import { expect, test, type Page } from '@playwright/test'

async function chat(page: Page, review = false) {
  const calls = { saves: 0, fail: false }
  let feedback: { recommended: boolean; comment?: string } | null = null
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (path.endsWith('/feedback')) {
      if (route.request().method() === 'PUT') {
        calls.saves++
        await new Promise(resolve => setTimeout(resolve, 200))
        if (calls.fail) return json({ message: 'retry' }, 503)
        feedback = { ...feedback, ...route.request().postDataJSON() }
      }
      return json({ success: true, feedback })
    }
    const characters = [{ character_id: 'human', name: '记录员', is_human: true }, { character_id: 'ai', name: '调查员', is_human: false }]
    if (path.endsWith('/state')) return json({
      success: true, session_id: 'polish', status: 'playing', current_stage: review ? 'review' : 'free_discussion',
      current_round: 2, human_character_id: 'human', current_speaker_id: 'human', speech_queue: ['human'],
      script: { script_id: 'polish', title: '界面回归' }, characters, votes: {}, vote_results: null,
      agent_llm_info: { ai: { model: 'doubao-seed-2-0-lite-260215' } },
      player_states: characters.map(c => ({ ...c, has_spoken_this_round: true, remaining_speech_count: 1, suspicion_reasons: {}, suspected_by: {}, player_perspectives: {} })),
      public_clues: [1, 2].map(i => ({ id: `c0${i}`, summary: `材料${i}`, content: `材料${i}开始。\n\n${'需要核实这段记录的细节。\n\n'.repeat(60)}材料${i}结束。`, stage: i })),
    })
    if (path.endsWith('/records')) return json({ success: true, records: [
      { id: 1, record_type: 'speech', speaker_id: 'ai', speaker_name: '调查员', stage: 'free_discussion',
        content: '先看c01那条材料。[至于c02材料，需要对照[c01]再核实][c01][c02]。后面[c02]，[仍然不能定案][c01,c02]。', clue_refs: ['c01', 'c02'] },
      ...(review ? [{ id: 2, record_type: 'system', stage: 'review', content: '本局推理结束。', clue_refs: [] }] : []),
    ] })
    if (path.endsWith('/capabilities')) return json({
      mode: 'local-first-single-user-single-process',
      models: [{ id: 'doubao-seed-2-0-lite-260215', name: 'doubao-seed-2.0-lite', model: 'doubao-seed-2-0-lite-260215', configured: true }],
      features: { rag: { enabled: false }, image: { enabled: false }, static_tts: { enabled: false }, streaming_tts: { enabled: false } },
    })
    return json({ success: true })
  })
  await page.goto('/?session=polish')
  await expect(page.locator('[data-record-id="1"]')).toBeVisible()
  return calls
}

for (const viewport of [{ width: 1920, height: 1080 }, { width: 1280, height: 720 }, { width: 390, height: 844 }]) {
  test(`malformed citation recovery and viewport-bounded scrolling ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await chat(page)
    const message = page.locator('[data-record-id="1"]')
    await expect(message.locator('[data-clue-citation]')).toHaveCount(4)
    await expect(message).not.toContainText(/c0[12]/)
    await expect(message).toContainText('(doubao-seed-2.0-lite)')
    const citation = message.getByLabel('查看 2 条引用线索').first()
    await citation.hover()
    const panel = page.getByRole('tooltip')
    await expect(panel).toBeVisible()
    const bounds = await panel.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(10)
    expect(bounds!.y).toBeGreaterThanOrEqual(10)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width - 10)
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height - 10)
    const scroll = panel.locator('.overflow-y-auto')
    expect(await scroll.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
    await scroll.evaluate(el => { el.scrollTop = el.scrollHeight })
    await expect(panel.getByText('材料2结束。')).toBeInViewport()
    await page.mouse.move(1, 1)
    await expect(panel).toBeHidden()
    await citation.click()
    await page.mouse.move(1, 1)
    await expect(panel).toBeHidden()
  })
}

for (const width of [1440, 390]) {
  test(`feedback shows status on demand and retains draft through save and retry ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const calls = await chat(page, true)
    const section = page.getByRole('region', { name: '剧本体验评价' })
    const recommend = section.getByRole('button', { name: '推荐', exact: true })
    await expect(recommend).toBeEnabled()
    await expect(section.getByRole('status')).toHaveCount(0)
    await page.waitForTimeout(400)
    const before = await section.boundingBox()
    await recommend.click()
    await expect(section.getByRole('status')).toContainText('正在保存')
    expect(await recommend.evaluate(el => getComputedStyle(el).opacity)).toBe('1')
    const saving = await section.boundingBox()
    expect(saving!.height).toBeGreaterThan(before!.height)
    expect(saving!.x).toBe(before!.x)
    expect(saving!.width).toBe(before!.width)
    await expect(recommend).toHaveAttribute('aria-pressed', 'true')
    await expect(section.getByRole('status')).toContainText('评价已保存')
    expect((await section.boundingBox())!.height).toBe(saving!.height)
    await expect(page.locator('[data-record-id="1"]')).toContainText('仍然不能定案')
    await recommend.click()
    expect(calls.saves).toBe(1)
    await section.getByRole('button', { name: '留下体验意见（可选）' }).click()
    const input = section.getByRole('textbox', { name: '剧本体验意见' })
    await expect(input).toHaveAttribute('placeholder', /文字仅供维护者查看，不公开展示。/)
    await expect(section.getByText('文字仅供维护者查看，不公开展示。', { exact: true })).toHaveCount(0)
    await input.fill('我希望更多说明。')
    calls.fail = true
    await section.getByRole('button', { name: '提交体验意见', exact: true }).click()
    await expect(section.getByRole('alert')).toContainText('请重试')
    await expect(input).toHaveValue('我希望更多说明。')
    calls.fail = false
    await section.getByRole('button', { name: '提交体验意见', exact: true }).click()
    await expect(section.getByRole('status')).toContainText('体验意见已保存')
    await section.getByRole('button', { name: '不推荐', exact: true }).click()
    await expect(section.getByRole('button', { name: '不推荐', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(calls.saves).toBe(4)
  })
}
