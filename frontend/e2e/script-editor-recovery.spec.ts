import { expect, test, type Route } from '@playwright/test'

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('转换失败刷新后保留通用错误并仅提交失败任务重试', async ({ page }) => {
  let retryAction = ''
  await page.addInitScript(() => {
    localStorage.setItem('editorSession', JSON.stringify({ threadId: 'failed-thread', currentStep: 'convert_to_game_data' }))
  })
  const failure = {
    success: true, thread_id: 'failed-thread', current_step: 'convert_to_game_data', is_complete: false,
    interrupt: { step: 'convert_to_game_data', failed: true, retry_step: 'convert_to_game_data' },
    state: { workflow_mode: 'create', script_title: '转换失败测试', error_message: '抱歉！系统发生未知错误，请稍后重试。', retry_step: 'convert_to_game_data' },
  }
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/failed-thread/state')) return json(route, failure)
    if (path.endsWith('/failed-thread/resume')) {
      retryAction = route.request().postDataJSON().action
      return json(route, failure)
    }
    if (path.endsWith('/convert-progress')) return json(route, { success: true, progress: { isComplete: false, phases: [{ id: 'convert', label: '转换', tasks: [{ id: 'scenes', label: '场景', status: 'failed' }] }] } })
    if (path.endsWith('/asset-progress')) return json(route, { success: true, progress: null })
    if (path.endsWith('/history')) return json(route, { success: true, checkpoints: [] })
    if (path.endsWith('/model-health')) return json(route, { models: [], cached: false })
    return json(route, { success: true, scripts: [] })
  })
  await page.goto('/?editor=resume')
  await expect(page.getByText('抱歉！系统发生未知错误，请稍后重试。')).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeVisible()
  await expect(page.getByText('剧本创建完成！')).toHaveCount(0)
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect.poll(() => retryAction).toBe('retry_failed')
})

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
  await page.getByRole('button', { name: '创作工坊', exact: true }).click()
  await page.getByLabel("故事创意", { exact: true }).fill('一座封闭灯塔中的失踪案')
  await page.getByRole('button', { name: '开始创作' }).click()

  await expect(page).toHaveURL(/editor=resume/)
  await expect(page.getByTestId('outline-workspace').or(page.getByText('正在构思剧本大纲...'))).toBeVisible()
  await expect(page.getByText(/流程中断/)).toHaveCount(0)

  await page.reload()
  await expect(page.getByTestId('outline-workspace').or(page.getByText('正在构思剧本大纲...'))).toBeVisible()
  await expect(page.getByText(/流程中断/)).toHaveCount(0)

  allowComplete = true
  await expect(page.getByText('灯塔管理员失踪，四名访客各自隐瞒了到访时间。')).toBeVisible({
    timeout: 12_000,
  })
  expect(startRequests).toBe(1)
  expect(operationRequests).toBeGreaterThan(1)

  await page.getByRole('button', { name: '返回剧本大厅' }).click()
  await expect(page.getByRole('region', { name: '剧本大厅' })).toBeVisible()
  await page.getByRole('button', { name: '创作工坊', exact: true }).click()

  await expect(page.getByText('灯塔管理员失踪，四名访客各自隐瞒了到访时间。')).toBeVisible()
  expect(startRequests).toBe(1)
  await expect.poll(() => stateRequests).toBeGreaterThan(0)
})

test('资源最多重试三次，刷新保留进度，耗尽后显示创作完成', async ({ page }) => {
  let attempts = 0;
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const progress = () => ({ isComplete: attempts >= 3, phases: [{ id: 'image', label: '剧本图片生成', tech: 'Text-to-Image', tasks: [{ id: 'cover', label: '剧本概览封面', status: attempts >= 3 ? 'skipped' : 'failed', retry_count: attempts, retry_exhausted: attempts >= 3, fallback: attempts >= 3, reason: '图片暂不可用' }] }] });
  const response = () => ({ success: true, thread_id: 'bounded-assets', current_step: 'generate_assets', is_complete: attempts >= 3, interrupt: null, state: { workflow_mode: 'create', script_id: 'bounded-script', script_title: '资源回退测试', asset_progress: progress() } });
  await page.addInitScript(() => localStorage.setItem('editorSession', JSON.stringify({ threadId: 'bounded-assets', currentStep: 'generate_assets' })));
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/state')) return json(route, response());
    if (path.endsWith('/asset-progress')) return json(route, { success: true, progress: progress() });
    if (path.endsWith('/convert-progress')) return json(route, { success: true, progress: null });
    if (path.endsWith('/progress-stream')) return route.fulfill({ contentType: 'text/event-stream', body: ': heartbeat\n\n' });
    if (path.endsWith('/resume')) {
      const body = route.request().postDataJSON();
      expect(body.action).toBe('retry_asset');
      expect(body.asset_task_id).toBe('cover');
      attempts++;
      return json(route, { success: true, thread_id: 'bounded-assets', operation_id: body.request_id, operation_status: 'queued', target_step: 'generate_assets' });
    }
    if (path.includes('/operations/')) return json(route, { ...response(), operation_status: 'complete', operation_id: path.split('/').at(-1) });
    return json(route, { success: true, scripts: [], models: [], checkpoints: [] });
  });
  await page.goto('/?editor=resume');
  for (let i = 1; i <= 3; i++) {
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await expect.poll(() => attempts).toBe(i);
    if (i < 3) {
      await expect(page.getByRole('button', { name: '重试', exact: true })).toBeEnabled();
      await page.reload();
    }
  }
  await expect(page.getByText('剧本创建完成！')).toBeVisible();
  await expect(page.getByText('部分资源暂不可用，已使用默认展示或文本模式，不影响开始游戏。')).toBeVisible();
  await expect(page.getByRole('button', { name: '重试', exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

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


for (const pendingKind of ['start', 'outline']) {
  test(`失败的${pendingKind}操作刷新后解除输入锁并停止观察`, async ({ page }) => {
    let operationReads = 0;
    await page.addInitScript(kind => localStorage.setItem('editorSession', JSON.stringify({
      threadId: 'failed-outline', currentStep: 'generate_outline', operationId: 'failed-op',
      ...(kind === 'start' ? { pendingKind: 'start' } : {}),
    })), pendingKind);
    const question = { id: 'q1', title: '请决定方向', question: '人物关系如何发展？', options: [
      { id: 'a', label: '自愿合作', impact: '保留共同经历' }, { id: 'b', label: '昔日竞争', impact: '增加旧事' },
    ] };
    const session = { protocol_version: 3, revision: 1, status: 'awaiting_answer', segments: [], events: [],
      pending_question: question, decisions: [], final_outline: '', questions_asked: 1 };
    const state = { workflow_mode: 'create', script_title: '恢复输入测试', outline: '', outline_session: session, prompts: {}, error_message: '' };
    const result = { success: true, thread_id: 'failed-outline', current_step: 'outline_wait', is_complete: false,
      state, interrupt: { step: 'outline_wait', question },
      outline_progress: { revision: 1, seq: 1, session, live: null, control: { revision: 1, paused: false } } };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.includes('/operations/')) { operationReads++; return json(route, { ...result, operation_id: 'failed-op', operation_status: 'failed', error_message: '本轮提问未完成' }); }
      if (path.endsWith('/state')) return json(route, result);
      if (path.endsWith('/convert-progress') || path.endsWith('/asset-progress')) return json(route, { success: true, progress: null });
      if (path.endsWith('/progress-stream')) return route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"done"}\n\n' });
      return json(route, { success: true, scripts: [], checkpoints: [], models: [] });
    });
    await page.goto('/?editor=resume');
    await expect(page.getByLabel('其他想法或补充说明')).toBeEnabled();
    await page.getByLabel('其他想法或补充说明').fill('继续保持自愿合作');
    await expect(page.getByRole('button', { name: '提交想法' })).toBeEnabled();
    const reads = operationReads;
    await page.waitForTimeout(6000);
    expect(operationReads).toBe(reads);
    expect(JSON.parse(await page.evaluate(() => localStorage.getItem('editorSession') || '{}')).operationId).toBeUndefined();
  });
}
