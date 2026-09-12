import { expect, test, type Route } from '@playwright/test'

const script = {
  script_id: 'sample-midnight-call-v1',
  title: '零点来电',
  description: '纯文本剧本',
  overview: '广播站旧址的最后一夜。',
  tags: '原创样例',
  difficulty: 1,
  player_count: 2,
  estimated_duration: 20,
  is_ai_generated: true,
  can_manage: false,
}

const characters = [
  { character_id: 'human', name: '陆鸣', profile: '广播主持人' },
  { character_id: 'ai-1', name: '姜芮', profile: '节目制作人' },
]

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('未配置主模型时选角安全降级且不会产生页面异常', async ({ page }) => {
  const pageErrors: Error[] = []
  page.on('pageerror', (error) => pageErrors.push(error))

  await page.route((url) => !["127.0.0.1", "localhost"].includes(url.hostname), (route) =>
    route.abort('blockedbyclient'),
  )
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
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
            model: 'deepseek-flash',
            configured: false,
            reason: '未配置 deepseek API Key',
          },
        ],
        features: {
          rag: { enabled: false, reason: '未配置' },
          image: { enabled: false, reason: '未配置' },
          static_tts: { enabled: false, reason: '未配置' },
          streaming_tts: { enabled: false, reason: '未配置' },
        },
      })
    }
    if (path === '/api/v1/system/model-health') {
      return json(route, { models: [], cached: false })
    }
    return json(route, { success: true })
  })

  await page.goto('/')
  await page.getByText('零点来电').first().click()
  await page.getByText('陆鸣', { exact: true }).click()

  await expect(page.getByText(/暂不可分配 AI 模型/)).toBeVisible()
  await expect(page.getByRole('button', { name: '开始游戏' })).toBeDisabled()
  expect(pageErrors).toEqual([])
})

test('模型服务偏慢时只提示体验风险且仍可选择并开始游戏', async ({ page }) => {
  await page.route((url) => !["127.0.0.1", "localhost"].includes(url.hostname), (route) =>
    route.abort('blockedbyclient'),
  )
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
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
            id: 'deepseek-flash',
            name: 'deepseek-flash',
            provider: 'deepseek',
            provider_name: 'DeepSeek',
            model: 'deepseek-flash',
            configured: true,
            reason: '已配置',
          },
          {
            id: 'hy3',
            name: 'hy3',
            provider: 'hunyuan',
            provider_name: 'Tencent Hunyuan',
            model: 'hy3',
            configured: true,
            reason: '已配置',
          },
        ],
        features: {
          rag: { enabled: false, reason: '未配置' },
          image: { enabled: false, reason: '未配置' },
          static_tts: { enabled: false, reason: '未配置' },
          streaming_tts: { enabled: false, reason: '未配置' },
        },
      })
    }
    if (path === '/api/v1/system/model-health') {
      return json(route, {
        cached: false,
        models: [
          {
            model: 'deepseek-flash',
            status: 'normal',
            latency_ms: 420,
            first_token_latency_ms: 420,
            reaction_latency_ms: 1480,
            slow_dimensions: [],
            message: '响应正常',
            checked_at: '2026-08-28T00:00:00Z',
          },
          {
            model: 'hy3',
            status: 'slow',
            latency_ms: 920,
            first_token_latency_ms: 920,
            reaction_latency_ms: 15420,
            slow_dimensions: ['reaction'],
            message: '响应较慢',
            checked_at: '2026-08-28T00:00:00Z',
          },
        ],
      })
    }
    return json(route, { success: true })
  })

  await page.goto('/')
  await page.getByText('零点来电').first().click()
  await page.getByText('陆鸣', { exact: true }).click()
  await page.getByRole('combobox').click()
  const slowOption = page.getByRole('option', { name: 'hy3' })
  await expect(slowOption).toBeVisible()
  await expect(page.getByText('响应较慢', { exact: true })).toBeVisible()
  await slowOption.click()

  await expect(page.getByText('响应较慢')).toBeVisible()
  await expect(page.getByRole('button', { name: '开始游戏' })).toBeEnabled()
})
