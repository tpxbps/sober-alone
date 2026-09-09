import { expect, test, type Route } from '@playwright/test'

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('创作长任务在刷新和返回大厅后仍恢复到同一工作流', async ({ page }) => {
  let allowComplete = false
  let startRequests = 0
  let operationRequests = 0
  let stateRequests = 0

  const workflowState = {
    workflow_mode: 'create',
    script_title: '恢复测试剧本',
    script_id: '',
    user_idea: '一座封闭灯塔中的失踪案',
    player_count: 4,
    difficulty: 1,
    num_clue_rounds: 2,
    outline: '灯塔管理员失踪，四名访客各自隐瞒了到访时间。',
    characters: [],
    first_draft: '',
    review_opinion: '',
    final_draft: '',
    character_scripts: {},
    game_data_sections: {},
    prompts: { generate_outline: '测试提示词' },
    cover_image_url: '',
    character_avatars: {},
    error_message: '',
    safety_passed: false,
    data_validation_errors: [],
  }
  const completed = {
    success: true,
    thread_id: 'recovery-thread',
    operation_id: 'start-operation',
    operation_status: 'complete',
    target_step: 'generate_outline',
    current_step: 'review_outline',
    is_complete: false,
    state: workflowState,
    interrupt: {
      step: 'review_outline',
      step_label: '大纲审阅',
      generated_content: workflowState.outline,
      prompt_used: '测试提示词',
      workflow_mode: 'create',
    },
  }

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/game/scripts') {
      return json(route, { success: true, scripts: [] })
    }
    if (path === '/api/v1/system/model-health') {
      return json(route, { models: [], cached: false })
    }
    if (path === '/api/v1/script-editor/start') {
      startRequests += 1
      expect(route.request().headers()['x-sober-author-key']).toBeTruthy()
      return json(route, {
        success: true,
        thread_id: 'recovery-thread',
        operation_id: 'start-operation',
        operation_status: 'queued',
        target_step: 'generate_outline',
      })
    }
    if (path.endsWith('/recovery-thread/operations/start-operation')) {
      operationRequests += 1
      return json(
        route,
        allowComplete
          ? completed
          : {
              success: true,
              thread_id: 'recovery-thread',
              operation_id: 'start-operation',
              operation_status: 'running',
              target_step: 'generate_outline',
              progress: { message: '后台执行中' },
            },
      )
    }
    if (path.endsWith('/recovery-thread/state')) {
      stateRequests += 1
      return json(route, completed)
    }
    if (path.endsWith('/history')) {
      return json(route, { success: true, checkpoints: [] })
    }
    return json(route, { success: true })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /创作工坊/ }).click()
  await page.getByPlaceholder(/描述你想要创作的剧本杀故事构想/).fill('一座封闭灯塔中的失踪案')
  await page.getByRole('button', { name: '开始创作' }).click()

  await expect(page).toHaveURL(/editor=resume/)
  await expect(page.getByText('正在构思剧本大纲...')).toBeVisible()
  await expect(page.getByText(/流程中断/)).toHaveCount(0)

  await page.reload()
  await expect(page.getByText('正在构思剧本大纲...')).toBeVisible()
  await expect(page.getByText(/流程中断/)).toHaveCount(0)

  allowComplete = true
  await expect(page.getByText('灯塔管理员失踪，四名访客各自隐瞒了到访时间。')).toBeVisible({
    timeout: 12_000,
  })
  expect(startRequests).toBe(1)
  expect(operationRequests).toBeGreaterThan(1)

  await page.getByRole('button', { name: '返回剧本大厅' }).click()
  await expect(page.getByRole('heading', { name: '剧本大厅' })).toBeVisible()
  await page.getByRole('button', { name: /创作工坊/ }).click()

  await expect(page.getByText('灯塔管理员失踪，四名访客各自隐瞒了到访时间。')).toBeVisible()
  expect(startRequests).toBe(1)
  await expect.poll(() => stateRequests).toBeGreaterThan(0)
})

test('刷新后仍展示未完成的资源任务而不是误报创作完成', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      'editorSession',
      JSON.stringify({ threadId: 'asset-thread', currentStep: 'generate_assets' }),
    )
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/asset-thread/state')) {
      return json(route, {
        success: true,
        thread_id: 'asset-thread',
        current_step: 'generate_assets',
        is_complete: true,
        interrupt: null,
        state: {
          workflow_mode: 'create',
          script_id: 'asset-script',
          script_title: '资源恢复测试',
        },
      })
    }
    if (path.endsWith('/asset-thread/asset-progress')) {
      return json(route, {
        success: true,
        progress: {
          isComplete: false,
          phases: [
            {
              id: 'vectorize',
              label: '角色剧本向量化',
              tech: 'Embedding',
              tasks: [
                {
                  id: 'vector_char-a',
                  label: '甲 个人剧本向量化',
                  status: 'failed',
                  reason: 'temporary collection lock',
                },
              ],
            },
          ],
        },
      })
    }
    if (path.endsWith('/asset-thread/convert-progress')) {
      return json(route, { success: true, progress: null })
    }
    if (path.endsWith('/history')) {
      return json(route, { success: true, checkpoints: [] })
    }
    if (path === '/api/v1/game/scripts') {
      return json(route, { success: true, scripts: [] })
    }
    if (path === '/api/v1/system/model-health') {
      return json(route, { models: [], cached: false })
    }
    return json(route, { success: true })
  })

  await page.goto('/?editor=resume')

  await expect(page.getByRole('heading', { name: '资源生成', exact: true })).toBeVisible()
  await expect(page.getByText('甲 个人剧本向量化')).toBeVisible()
  await expect(page.getByText('剧本创建完成！')).toHaveCount(0)
})
