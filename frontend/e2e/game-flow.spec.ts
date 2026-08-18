import { expect, test, type Route } from '@playwright/test'

const script = {
  script_id: 'sample-midnight-call-v1',
  title: '零点来电',
  description: '原创纯文本简单本，4 人、2 轮递进线索，预计 25 分钟。',
  overview: '广播站旧址的最后一夜，四名工作人员拆穿一段伪造的存活广播。',
  tags: '原创样例,AI生成',
  difficulty: 1,
  player_count: 4,
  estimated_duration: 25,
  is_ai_generated: true,
}

const characters = [
  {
    character_id: 'human',
    name: '陆鸣',
    profile: '广播主持人',
    character_script: '你的个人剧本',
  },
  { character_id: 'ai-1', name: '姜芮', profile: '节目制作人' },
  { character_id: 'ai-2', name: '陈朔', profile: '音频工程师' },
  { character_id: 'ai-3', name: '许棠', profile: '实习编辑' },
]

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('大厅 → 选角 → 发言 → 推进 → 投票 → 复盘', async ({ page }) => {
  let stage: 'intro' | 'vote' | 'review' = 'intro'
  let currentSpeaker: string | null = 'human'
  let records: unknown[] = []

  await page.route(/https?:\/\/(?!127\.0\.0\.1:4173).*$/i, (route) =>
    route.abort('blockedbyclient'),
  )

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()

    if (path === '/api/v1/game/scripts') {
      return json(route, { success: true, scripts: [script] })
    }
    if (path.endsWith('/characters')) {
      return json(route, { success: true, characters })
    }
    if (path === '/api/v1/system/capabilities') {
      return json(route, {
        mode: 'local-first-single-user-single-process',
        models: [
          {
            provider: 'deepseek',
            provider_name: 'DeepSeek',
            model: 'deepseek-v4-flash',
            configured: true,
            reason: '已配置',
          },
        ],
        features: {},
      })
    }
    if (path === '/api/v1/game/create' && method === 'POST') {
      return json(route, { success: true, session_id: 'e2e-session' })
    }
    if (path.endsWith('/state')) {
      return json(route, {
        success: true,
        session_id: 'e2e-session',
        status: 'playing',
        current_stage: stage,
        current_round: stage === 'intro' ? 0 : 3,
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
        current_speaker_id: currentSpeaker,
        speech_queue: currentSpeaker ? [currentSpeaker] : [],
        has_all_spoken: false,
        human_character_id: 'human',
        script,
        characters: characters.map((character) => ({
          ...character,
          is_human: character.character_id === 'human',
        })),
        agent_llm_info: {},
        votes: {},
        vote_results: null,
      })
    }
    if (path.endsWith('/records')) {
      return json(route, { success: true, records, count: records.length })
    }
    if (path.endsWith('/speech') && method === 'POST') {
      currentSpeaker = null
      records = [
        {
          id: 1,
          session_id: 'e2e-session',
          stage: 'intro',
          speaker_id: 'human',
          speaker_name: '陆鸣',
          content: '我先说明停电时间。',
          record_type: 'speech',
          created_at: new Date().toISOString(),
        },
      ]
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'data: {"type":"reactions_done"}\n\n' +
          'data: {"type":"done","next_speaker_id":null}\n\n',
      })
    }
    if (path.endsWith('/advance') && method === 'POST') {
      stage = 'vote'
      currentSpeaker = null
      return json(route, {
        success: true,
        transition: {
          from_stage: 'intro',
          to_stage: 'vote',
          message: '进入投票阶段',
        },
      })
    }
    if (path.endsWith('/vote') && method === 'POST') {
      return json(route, { success: true, message: 'ok' })
    }
    if (path.endsWith('/finalize-voting') && method === 'POST') {
      stage = 'review'
      records = [
        ...records,
        {
          id: 2,
          session_id: 'e2e-session',
          stage: 'review',
          content: '真相揭晓：时间线已还原。',
          record_type: 'system',
          created_at: new Date().toISOString(),
        },
      ]
      return json(route, {
        success: true,
        vote_results: {
          vote_count: { 'ai-1': 3 },
          total_votes: 4,
          final_suspect: 'ai-1',
          final_suspect_votes: 3,
          details: {},
        },
        review_message: '真相揭晓：时间线已还原。',
        transition: {
          from_stage: 'vote',
          to_stage: 'review',
          message: '进入复盘',
        },
      })
    }
    if (path.endsWith('/end') || path.endsWith('/abandon')) {
      return json(route, { success: true, message: 'ok' })
    }
    return json(route, { success: true })
  })

  await page.goto('/')
  await expect(page.getByText('剧本大厅')).toBeVisible()
  await page.getByText('零点来电').first().click()
  await page.getByText('陆鸣', { exact: true }).click()
  await page.getByRole('button', { name: '开始游戏' }).click()

  await page.getByPlaceholder('输入你的发言...').fill('我先说明停电时间。')
  const historyReloaded = page.waitForResponse((response) => {
    const path = new URL(response.url()).pathname
    return response.request().method() === 'GET' && path.endsWith('/records')
  })
  await page.getByRole('button', { name: '完成发言' }).click()
  await historyReloaded
  // The optimistic record and its authoritative replacement overlap briefly
  // while AnimatePresence completes the exit animation. Wait for that bounded
  // visual transition, then assert the authoritative list has converged.
  const humanSpeech = page.getByText('我先说明停电时间。', { exact: true })
  await expect(humanSpeech.last()).toBeVisible()
  await page.waitForTimeout(500)
  await expect(humanSpeech).toHaveCount(1)
  await page.getByRole('button', { name: '进入下一阶段' }).click()

  await expect(page.getByText('请投票指认真凶')).toBeVisible()
  await page.getByRole('button', { name: /姜芮/ }).click()
  await page.getByRole('button', { name: '确认投票' }).click()

  await expect(page.getByRole('heading', { name: '复盘揭晓' })).toBeVisible()
  await expect(page.getByText(/真相揭晓/)).toBeVisible()
})
