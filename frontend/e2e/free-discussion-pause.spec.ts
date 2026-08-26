import { expect, test, type Route } from '@playwright/test'

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('让我想想暂停待发言 AI 且开关圆点保持在轨道内', async ({ page }) => {
  let aiSpeakRequests = 0
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
        current_speaker_id: 'ai-1',
        next_speaker_id: 'ai-1',
        speech_queue: ['ai-1'],
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

  await page.goto('/?session=pause-session')
  const pauseSwitch = page.getByRole('switch', { name: '让我想想' })
  await expect(pauseSwitch).toBeVisible()
  await pauseSwitch.click()
  await expect(pauseSwitch).toHaveAttribute('data-state', 'checked')

  const nextAiCard = page.getByRole('button', { name: '在输入框引用 姜芮' })
  await expect(nextAiCard.locator('.breathing')).toHaveCount(0)

  const thumb = pauseSwitch.locator('[data-state="checked"]')
  const [trackBox, thumbBox, countBox] = await Promise.all([
    pauseSwitch.boundingBox(),
    thumb.boundingBox(),
    page.getByText('剩余发言次数: 1').boundingBox(),
  ])
  expect(trackBox).not.toBeNull()
  expect(thumbBox).not.toBeNull()
  expect(countBox).not.toBeNull()
  expect(thumbBox!.x).toBeGreaterThanOrEqual(trackBox!.x)
  expect(thumbBox!.x + thumbBox!.width).toBeLessThanOrEqual(
    trackBox!.x + trackBox!.width + 0.5,
  )
  expect(trackBox!.x).toBeLessThan(countBox!.x)

  await page.waitForTimeout(1700)
  expect(aiSpeakRequests).toBe(0)
})
