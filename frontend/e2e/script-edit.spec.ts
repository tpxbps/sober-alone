import { expect, test, type Route } from '@playwright/test'

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

test('作者从大厅编辑结构化数据并选择性更新资源', async ({ page }) => {
  let title = '可编辑剧本'
  let resumeCount = 0
  const operationResponses = new Map<string, unknown>()
  const characters = [
    {
      character_id: 'c1',
      name: '林岚',
      gender: '女',
      age: 28,
      occupation: '记者',
      character_script: '个人秘密',
      script_summary: '摘要',
      profile: '简介',
      appearance: '黑色风衣',
      system_prompt: '保持冷静',
      step_voice_id: 'voice-1',
    },
  ]
  const sections = () => ({
    title,
    difficulty: 1,
    player_count: 1,
    opening: '开场',
    clue_stages: [],
    truth_reveal: '真相',
    full_truth: '完整真相',
    game_flow: [
      { type: 'initial', stage_title: '开场', system_notice: '开场' },
      { type: 'review', stage_title: '真相', system_notice: '真相' },
    ],
    free_speech_limits: [],
    character_scripts: { 林岚: '个人秘密' },
    character_data: characters,
    overview: '概述',
    tags: '悬疑',
    description: '详细描述',
  })
  const state = () => ({
    workflow_mode: 'edit',
    script_title: title,
    script_id: 'owned-script',
    user_idea: '',
    player_count: 1,
    difficulty: 1,
    num_clue_rounds: 0,
    outline: '',
    characters,
    first_draft: '',
    review_opinion: '',
    final_draft: '',
    character_scripts: { 林岚: '个人秘密' },
    game_data_sections: sections(),
    prompts: {},
    cover_image_url: '/images/old.png',
    character_avatars: {},
    error_message: '',
    safety_passed: true,
    data_validation_errors: [],
  })

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/game/scripts') {
      return json(route, {
        success: true,
        scripts: [
          {
            script_id: 'owned-script',
            title,
            description: '详细描述',
            overview: '概述',
            tags: '悬疑',
            difficulty: 1,
            player_count: 1,
            estimated_duration: 20,
            is_ai_generated: true,
            can_manage: true,
          },
        ],
      })
    }
    if (path === '/api/v1/system/capabilities') {
      return json(route, { mode: 'local-first-single-user-single-process', models: [], features: {} })
    }
    if (path.endsWith('/scripts/owned-script/edit')) {
      expect(route.request().headers()['x-sober-author-key']).toBeTruthy()
      operationResponses.set('edit-start', {
        success: true,
        thread_id: 'edit-thread',
        operation_id: 'edit-start',
        operation_status: 'complete',
        target_step: 'review_game_data',
        script_id: 'owned-script',
        script_title: title,
        current_step: 'review_game_data',
        interrupt: {
          step: 'review_game_data',
          step_label: '游戏数据确认',
          workflow_mode: 'edit',
          game_data_sections: sections(),
          prompt_used: '',
        },
        state: state(),
      })
      return json(route, {
        success: true,
        thread_id: 'edit-thread',
        operation_id: 'edit-start',
        operation_status: 'queued',
        target_step: 'review_game_data',
      })
    }
    if (path.endsWith('/edit-thread/resume')) {
      expect(route.request().headers()['x-sober-author-key']).toBeTruthy()
      const request = route.request().postDataJSON()
      resumeCount += 1
      if (resumeCount === 1) {
        title = request.game_data_sections.title
        operationResponses.set('resume-1', {
          success: true,
          thread_id: 'edit-thread',
          operation_id: 'resume-1',
          operation_status: 'complete',
          target_step: 'review_game_data',
          current_step: 'review_asset_plan',
          is_complete: false,
          interrupt: {
            step: 'review_asset_plan',
            step_label: '资源更新确认',
            workflow_mode: 'edit',
            asset_plan: [
              {
                id: 'cover',
                phase: 'image',
                phase_label: '剧本图片生成',
                label: '剧本概览封面',
                changed: true,
                missing: false,
                available: true,
                unavailable_reason: '',
                default_selected: true,
                change_reason: '依赖字段已修改',
              },
              {
                id: 'tts_c1',
                phase: 'tts',
                phase_label: '语音资源生成',
                label: '林岚个人剧本 TTS',
                changed: false,
                missing: false,
                available: true,
                unavailable_reason: '',
                default_selected: false,
                change_reason: '依赖字段未变化',
              },
            ],
          },
          state: state(),
        })
        return json(route, {
          success: true,
          thread_id: 'edit-thread',
          operation_id: 'resume-1',
          operation_status: 'queued',
          target_step: 'review_game_data',
        })
      }
      expect(request.selected_asset_ids).toEqual(['cover'])
      operationResponses.set('resume-2', {
        success: true,
        thread_id: 'edit-thread',
        operation_id: 'resume-2',
        operation_status: 'complete',
        target_step: 'review_asset_plan',
        current_step: 'generate_assets',
        is_complete: true,
        interrupt: null,
        state: state(),
      })
      return json(route, {
        success: true,
        thread_id: 'edit-thread',
        operation_id: 'resume-2',
        operation_status: 'queued',
        target_step: 'review_asset_plan',
      })
    }
    if (path.includes('/edit-thread/operations/')) {
      const operationId = path.split('/').at(-1) || ''
      return json(route, operationResponses.get(operationId) || { operation_status: 'running' })
    }
    if (path.endsWith('/progress-stream')) {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type":"done"}\n\n',
      })
    }
    if (path.endsWith('/history')) return json(route, { success: true, checkpoints: [] })
    return json(route, { success: true })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '管理剧本 可编辑剧本' }).click()
  await page.getByRole('button', { name: '编辑剧本', exact: true }).click()
  await expect(page.getByText('游戏数据确认')).toBeVisible()
  await page.getByRole('button', { name: /角色数据/ }).click()
  const voiceHelp = page.getByRole('button', { name: 'Voice ID 说明与可选音色' })
  await voiceHelp.hover()
  const voiceTooltip = page.getByRole('tooltip')
  await expect(voiceTooltip).toContainText('游戏实时 TTS 音色')
  await expect(voiceTooltip).toContainText('磁性男声')
  await expect(voiceTooltip).toContainText('温柔淑女')
  await expect(voiceTooltip).toContainText('cixingnansheng')
  await expect(voiceTooltip).toContainText('wenroushunv')
  await expect(
    page.locator('.scrollbar-thin').filter({ hasText: '游戏实时 TTS 音色' }).last(),
  ).toBeVisible()
  await page.mouse.move(0, 0)
  await page.getByRole('button', { name: '剧本元数据' }).click()
  await page.locator('input[value="可编辑剧本"]').fill('修改后的剧本')
  await page.getByRole('button', { name: '确认并保存' }).click()

  await expect(page.getByText('确认本次资源更新')).toBeVisible()
  const assetPlanScroll = page.getByTestId('asset-plan-scroll')
  await expect(assetPlanScroll).toHaveCSS('overflow-y', 'auto')
  await expect(assetPlanScroll).toHaveClass(/scrollbar-thin/)
  await expect(page.getByRole('checkbox').first()).toBeChecked()
  await expect(page.getByRole('checkbox').nth(1)).not.toBeChecked()
  await page.getByRole('button', { name: '确认保存并执行所选资源' }).click()

  await expect(page.getByText('剧本修改完成！')).toBeVisible()
  await page.getByRole('button', { name: '返回剧本大厅', exact: true }).last().click()
  await expect(page.getByText('修改后的剧本').first()).toBeVisible()
})
