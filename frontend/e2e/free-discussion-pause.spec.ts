import { expect, test, type Route } from '@playwright/test'

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
test(`让我想想在输入框上方暂停、继续与发送后恢复 ${viewport.width}`, async ({ page }) => {
  await page.setViewportSize(viewport)
  let aiSpeakRequests = 0
  let humanSpeakRequests = 0
  let currentSpeaker = 'ai-1'
  let finishAiResponse!: () => void
  const aiResponse = new Promise<void>(resolve => { finishAiResponse = resolve })
  const characters = [
    {
      character_id: 'human',
      name: '陆鸣',
      occupation: '主持人',
      profile: '广播主持人',
      character_script: '你的个人剧本',
      is_human: true,
    },
    {
      character_id: 'ai-1',
      name: '姜芮',
      occupation: '节目制作人',
      profile: '节目制作人',
      is_human: false,
    },
  ]
  const playerStates = characters.map((character) => ({
    character_id: character.character_id,
    character_name: character.name,
    is_human: character.character_id === 'human',
    has_spoken_this_round: false,
    remaining_speech_count: 1,
    suspicion_reasons: {},
    suspected_by: {},
    player_perspectives: {},
  }))

  await page.addInitScript(() => {
    localStorage.setItem('sober_alone_session', 'pause-session')
  })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/pause-session/state')) {
      return json(route, {
        success: true,
        session_id: 'pause-session',
        status: 'playing',
        current_stage: 'free_discussion',
        current_round: 1,
        player_states: playerStates,
        current_speaker_id: currentSpeaker,
        next_speaker_id: currentSpeaker,
        speech_queue: [currentSpeaker],
        has_all_spoken: false,
        human_character_id: 'human',
        script: {
          script_id: 'pause-script',
          title: '暂停测试',
          description: '测试自由讨论暂停',
          difficulty: 1,
          player_count: 2,
          estimated_duration: 10,
        },
        characters,
        agent_llm_info: {},
        votes: {},
        vote_results: null,
      })
    }
    if (path.endsWith('/pause-session/records')) {
      return json(route, { success: true, records: [], count: 0 })
    }
    if (path.endsWith('/ai-speech/ai-1')) {
      aiSpeakRequests += 1
      await aiResponse
      currentSpeaker = 'human'
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type":"done","next_speaker_id":null}\n\n',
      })
    }
    if (path.endsWith('/pause-session/speech')) {
      humanSpeakRequests += 1
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"done","next_speaker_id":null}\n\n' })
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

  await page.goto('/?session=pause-session')
  const pauseButton = page.getByRole('button', { name: '让我想想', exact: true })
  await expect(pauseButton).toBeVisible()
  const composer = page.getByRole('textbox', { name: '发言输入框' })
  const [buttonBox, composerBox] = await Promise.all([pauseButton.boundingBox(), composer.boundingBox()])
  expect(buttonBox!.height).toBeGreaterThanOrEqual(44)
  expect(buttonBox!.y + buttonBox!.height).toBeLessThan(composerBox!.y)
  expect(buttonBox!.x).toBeGreaterThanOrEqual(0)
  expect(buttonBox!.x + buttonBox!.width).toBeLessThanOrEqual(viewport.width)
  await pauseButton.focus()
  await page.keyboard.press('Space')
  const resumeButton = page.getByRole('button', { name: '继续讨论', exact: true })
  await expect(resumeButton).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('AI 已暂停，慢慢写')).toBeVisible()

  const nextAiCard = page.getByRole('button', { name: '在输入框引用 姜芮' })
  await expect(nextAiCard.locator('.breathing')).toHaveCount(0)

  await page.waitForTimeout(1700)
  expect(aiSpeakRequests).toBe(0)
  await resumeButton.click()
  await expect.poll(() => aiSpeakRequests).toBe(1)
  await expect(pauseButton).toHaveAttribute('aria-pressed', 'false')
  await pauseButton.click()
  await expect(page.getByText('当前回应结束后暂停')).toBeVisible()
  finishAiResponse()
  await expect(page.getByText('AI 已暂停，慢慢写')).toBeVisible()
  await page.waitForTimeout(1700)
  expect(aiSpeakRequests).toBe(1)
  await composer.fill('我想先核对这段记录。')
  await composer.press('Control+Enter')
  await expect.poll(() => humanSpeakRequests).toBe(1)
  await expect(pauseButton).toHaveAttribute('aria-pressed', 'false')
})
}
