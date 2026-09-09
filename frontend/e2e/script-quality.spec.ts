import { expect, test } from '@playwright/test'

test('审稿独立确认、意见草稿刷新保留、终稿单独编辑', async ({ page }, testInfo) => {
  let step = 'review_report'
  const state = {
    workflow_mode: 'create', script_id: 'quality-script', script_title: '质量测试',
    first_draft: '这里是完整初稿。', review_opinion: '原始审稿意见', human_review: '',
    final_draft: '修订后的完整终稿。', characters: [], prompts: {},
  }
  const response = () => ({ success: true, thread_id: 'quality-thread', current_step: step, is_complete: false, state,
    interrupt: { step, step_label: step, generated_content: step === 'review_report' ? state.review_opinion : state.final_draft,
      first_draft: state.first_draft, human_review: state.human_review, prompt_used: '' } })
  await page.addInitScript(() => localStorage.setItem('editorSession', JSON.stringify({ threadId: 'quality-thread', currentStep: 'review_report' })))
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const send = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (path.endsWith('/state')) return send(response())
    if (path.endsWith('/resume')) {
      const body = route.request().postDataJSON()
      expect(body.content).toBe('修正后的审稿意见')
      expect(body.human_review).toBe('保留角色的辩解空间')
      state.review_opinion = body.content; state.human_review = body.human_review; step = 'review_final'
      return send({ success: true, operation_id: 'op', target_step: 'review_report', operation_status: 'queued' })
    }
    if (path.endsWith('/operations/op')) return send({ ...response(), operation_id: 'op', operation_status: 'complete' })
    if (path.endsWith('/history')) return send({ success: true, checkpoints: [] })
    if (path.endsWith('/game/scripts')) return send({ success: true, scripts: [] })
    if (path.endsWith('/model-health')) return send({ models: [] })
    return send({ success: true, progress: null })
  })
  await page.goto('/?editor=resume')
  await page.getByRole('button', { name: '展开初稿' }).click()
  await expect(page.getByRole('region', { name: '初稿全文' })).toContainText('完整初稿')
  await page.getByRole('textbox', { name: 'AI 审稿意见', exact: true }).fill('修正后的审稿意见')
  await page.getByRole('textbox', { name: '补充审稿意见', exact: true }).fill('保留角色的辩解空间')
  await page.screenshot({ path: testInfo.outputPath('review-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: testInfo.outputPath('review-mobile.png') })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.reload()
  await expect(page.getByRole('textbox', { name: '补充审稿意见', exact: true })).toHaveValue('保留角色的辩解空间')
  await page.getByRole('button', { name: '确认意见并生成终稿' }).click()
  await expect(page.getByRole('button', { name: '确认终稿并拆分' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '补充审稿意见', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '编辑终稿' }).click()
  await page.getByRole('textbox', { name: '终稿正文' }).fill('人工编辑的终稿')
  await page.reload()
  await expect(page.getByText('人工编辑的终稿', { exact: true })).toBeVisible()
})

test('质量检查失败明确标识，重试后风险确认失效', async ({ page }) => {
  let reportId = 'first-report'
  let acceptedId = ''
  const response = () => ({ success: true, thread_id: 'quality-check', current_step: 'review_quality', is_complete: false,
    state: { prompts: {}, quality_report: { report_id: reportId, content_fingerprint: 'fp', status: 'incomplete', findings: [], error: '模型暂时不可用' } },
    interrupt: { step: 'review_quality', generated_content: '', quality_report: { report_id: reportId, content_fingerprint: 'fp', status: 'incomplete', findings: [], error: '模型暂时不可用' } } })
  await page.addInitScript(() => localStorage.setItem('editorSession', JSON.stringify({ threadId: 'quality-check', currentStep: 'review_quality' })))
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = { success: true, checkpoints: [], models: [], scripts: [] }
    if (path.endsWith('/state')) body = response()
    if (path.endsWith('/resume')) {
      const request = route.request().postDataJSON()
      if (request.action === 'retry_quality') reportId = 'second-report'
      if (request.action === 'accept_risk') acceptedId = request.quality_report_id
      body = { success: true, operation_id: 'op', operation_status: 'queued' }
    }
    if (path.endsWith('/operations/op')) body = { ...response(), operation_status: 'complete' }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?editor=resume')
  await expect(page.getByRole('heading', { name: '质量检查未完成' })).toBeVisible()
  const acceptance = page.getByRole('button', { name: '接受风险并继续保存' })
  await expect(acceptance).toBeDisabled()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: '重新检查' }).click()
  await expect(page.getByRole('checkbox')).not.toBeChecked()
  await expect(acceptance).toBeDisabled()
  await page.getByRole('checkbox').check()
  await acceptance.click()
  await expect.poll(() => acceptedId).toBe('second-report')
})

test('卡片评分支持窄屏点击与键盘说明且不暴露评分原文', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path.endsWith('/game/scripts') ? { success: true, scripts: [{
      script_id: 's', title: '评分展示', difficulty: 1, player_count: 3, estimated_duration: 30,
      feedback_summary: { label: '多半好评', total: 10, positive: 7, positive_rate: .7, threshold: 5 },
      ai_review: { score: 78, model: 'gpt-6-astra', reviewed_at: '2026-09-10T00:00:00Z', rubric_version: 'v1',
        dimensions: [{ key: 'fairness', label: '角色公平性与辩解空间', weight: 15, score: 3 }] },
    }] } : { success: true, models: [] }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/')
  const rating = page.getByRole('button', { name: 'AI综合评分 78/100，查看评分说明' })
  await rating.click()
  await expect(page.getByText(/来自 GPT 6 ASTRA/)).toBeVisible()
  await expect(page.getByText('角色公平性与辩解空间')).toBeVisible()
  await rating.press('Escape')
  await page.getByRole('button', { name: '多半好评（70%），查看评分说明' }).focus()
  await expect(page.getByText('玩家推荐', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
