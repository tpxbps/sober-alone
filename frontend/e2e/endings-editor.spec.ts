import { expect, test } from '@playwright/test'

test('多结局可编辑、刷新恢复并作为结构化数据提交', async ({ page }, testInfo) => {
  const data = {
    title: '结局验证', player_count: 1, difficulty: 1, overview: '概述', description: '描述', tags: '',
    full_truth: '固定的案件事实。', opening: '开场', truth_reveal: '真相', clue_stages: [],
    game_flow: [{ type: "review", stage_title: "真相揭晓", system_notice: "固定真相" }], free_speech_limits: [], character_scripts: { 林岚: '角色稿' },
    character_data: [{ character_id: 'human', name: '林岚', gender: '女', system_prompt: '角色提示', character_script: '角色稿' }],
  }
  let submitted: Record<string, unknown> | null = null
  await page.addInitScript(() => localStorage.setItem('editorSession', JSON.stringify({ threadId: 'ending-editor', currentStep: 'review_game_data' })))
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = { success: true, scripts: [], models: [], checkpoints: [] }
    if (path.endsWith('/state')) body = { success: true, thread_id: 'ending-editor', current_step: 'review_game_data',
      state: { workflow_mode: 'create', prompts: {}, game_data_sections: data },
      interrupt: { step: 'review_game_data', generated_content: '', game_data_sections: data } }
    if (path.endsWith('/resume')) {
      submitted = route.request().postDataJSON().game_data_sections
      body = { success: true, operation_id: 'op', operation_status: 'queued' }
    }
    if (path.endsWith('/operations/op')) body = { success: true, operation_status: 'complete', current_step: 'review_quality', state: { prompts: {} },
      interrupt: { step: 'review_quality', quality_report: { report_id: 'r', status: 'passed', findings: [] } } }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?editor=resume')
  await page.getByRole('button', { name: '剧本流程数据' }).click()
  await expect(page.getByLabel('结局模式', { exact: true })).toHaveValue('single')
  await page.getByLabel('结局模式', { exact: true }).selectOption('multiple')
  await page.getByLabel('真凶', { exact: true }).selectOption('human')
  for (const label of ['正确指认', '错误指认', '平票', '无有效票']) {
    await page.getByLabel(`${label}结局正文`, { exact: true }).fill(`${label}后的故事正文。`)
  }
  await page.reload()
  await page.getByRole('button', { name: '剧本流程数据' }).click()
  await expect(page.getByLabel('平票结局正文', { exact: true })).toHaveValue('平票后的故事正文。')
  await page.screenshot({ path: testInfo.outputPath('endings-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('endings-mobile.png') })
  await page.getByRole('button', { name: /确认.*数据|确认并/ }).click()
  await expect.poll(() => submitted?.ending_config).toMatchObject({ mode: 'multiple', culprit_character_id: 'human', branches: expect.any(Array) })
})
