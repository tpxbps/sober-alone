import { expect, test } from '@playwright/test'

for (const width of [1280, 390]) {
  test(`个人本提醒 ${width}：常驻预览、统一已读、刷新和新对局`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      let body: unknown = { success: true, scripts: [], models: [] }
      if (path.endsWith('/state')) body = {
        success: true, session_id: path.split('/').at(-2), status: 'playing', current_stage: 'intro', current_round: 0,
        human_character_id: 'human', current_speaker_id: 'human', speech_queue: ['human'],
        script: { script_id: 'fixture', title: '旅馆来信', player_count: 3 },
        characters: [{ character_id: 'human', name: '林岚', is_human: true, character_script: '我拿走了旅馆的账本，没有告诉任何人。', character_script_summary: '**你的经历**：你曾拿走一本账本，那是你亲手做的。' }],
        player_states: [{ character_id: 'human', character_name: '林岚', is_human: true, remaining_speech_count: 1 }], votes: {}, agent_llm_info: {},
      }
      if (path.endsWith('/records')) body = { success: true, records: [] }
      if (path.endsWith('/system/capabilities')) body = { models: [], features: { static_tts: { enabled: false }, streaming_tts: { enabled: false }, rag: { enabled: false } } }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.goto('/?session=first-read')
    const hint = page.locator('[data-personal-script-hint]:visible')
    await expect(hint).toContainText('林岚的个人剧本')
    await expect(hint).toContainText('你曾拿走一本账本')
    const box = (await hint.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(16)
    expect(box.x + box.width).toBeLessThanOrEqual(width - 16)
    const input = (await page.getByRole('textbox').boundingBox())!
    if (width < 1024) expect(box.y).toBeGreaterThanOrEqual(input.y + input.height)
    else {
      const continueButton = page.getByRole('button', { name: /继续发言/ })
      const controls = await continueButton.boundingBox()
      if (controls) expect(box.x).toBeGreaterThanOrEqual(controls.x + controls.width)
    }
    await expect.poll(() => hint.evaluate(element => {
      let opacity = 1;
      for (let node: Element | null = element; node; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity);
      return opacity;
    })).toBe(1)
    await page.screenshot({ path: testInfo.outputPath(`hint-${width}.png`) })
    await hint.getByRole('button', { name: '阅读我的剧本' }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('dialog', { name: '林岚的剧本' })).toBeVisible()
    await expect(hint).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.locator('[data-personal-script-trigger]:visible')).toBeFocused()
    await page.reload()
    await expect(page.locator('[data-personal-script-trigger]:visible')).toBeVisible()
    await expect(hint).toHaveCount(0)
    await page.goto('/?session=second-read')
    await expect(hint).toBeVisible()
    await page.locator('[data-personal-script-trigger]:visible').click()
    await expect(page.getByRole('dialog', { name: '林岚的剧本' })).toBeVisible()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('script_opened_second-read'))).toBe('true')
    await page.keyboard.press('Escape')
    await expect(hint).toHaveCount(0)
  })
}
