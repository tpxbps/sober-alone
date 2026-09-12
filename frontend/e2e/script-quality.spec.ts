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

async function ratingFixture(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path.endsWith('/game/scripts') ? { success: true, scripts: [{
      script_id: 's', title: '评分展示', difficulty: 1, player_count: 3, estimated_duration: 30,
      feedback_summary: { label: '多半好评', total: 10, positive: 7, positive_rate: .7, threshold: 5 },
      ai_review: { score: 78, model: 'gpt-6-astra', reviewed_at: '2026-09-10T00:00:00Z', rubric_version: 'script-quality-v2',
        dimensions: [{ key: 'narrative', label: '叙事与人物塑造', weight: 15, score: 3 }] },
    }] } : { success: true, models: [], characters: [] }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/')
}

test('评分同行展示，轻量说明及悬浮文字点击均打开对应剧本', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await ratingFixture(page)
  const rating = page.getByRole('button', { name: 'AI评分: 78，打开剧本详情' })
  const feedback = page.getByRole('button', { name: '多半好评（70%），打开剧本详情' })
  const tip = page.locator('[data-rating-explanation]')
  await expect.poll(async () => Math.abs((await rating.boundingBox())!.y - (await page.getByText('3人', {exact:true}).boundingBox())!.y)).toBeLessThan(4)
  await rating.hover()
  await expect(tip).toBeVisible()
  await expect(tip).toContainText('AI评分: 78 （GPT 6 ASTRA）')
  await expect(tip).toContainText('叙事与人物塑造 15%')
  await expect(tip).not.toContainText('2026')
  await expect(tip).not.toContainText('基于剧本文本')
  await page.screenshot({ path: testInfo.outputPath('rating-mobile.png') })
  await rating.click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await rating.hover()
  await expect(tip).toBeVisible()
  await tip.getByText('叙事与人物塑造', {exact:false}).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await feedback.focus()
  await expect(tip).toContainText('玩家推荐')
  await expect(tip).toContainText('完成投票并揭晓真相后可评价')
  await expect(tip).not.toContainText('条反馈')
  await expect(tip).not.toContainText('浏览器')
  await expect(tip).not.toContainText('5 票')
  await tip.getByText('玩家推荐', {exact:true}).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await feedback.focus()
  await feedback.press('Enter')
  await expect(page.getByRole('dialog')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('手机轻触评分直接打开剧本详情', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ viewport: {width:390, height:844}, hasTouch:true, baseURL })
  const page = await context.newPage()
  await ratingFixture(page)
  await page.getByRole('button', { name: 'AI评分: 78，打开剧本详情' }).tap()
  await expect(page.getByRole('dialog')).toBeVisible()
  await context.close()
})
