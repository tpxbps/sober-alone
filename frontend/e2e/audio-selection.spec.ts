import { expect, test } from '@playwright/test'

test('真实音频持续播放时消息文本保持选中并可复制', async ({ page, context }, testInfo) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  // Real PCM playback drives the production audio manager's animation-frame updates.
  const wav = Buffer.alloc(44 + 8000 * 2 * 20)
  wav.write('RIFF', 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28)
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34)
  wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40)
  await page.route('**/audio/selection.wav', (route) => route.fulfill({ contentType: 'audio/wav', body: wav }))
  const prose = '播放期间可以完整选中这段文字，并复制到剪贴板。'
  const characters = [{ character_id: 'human', name: '林岚', is_human: true, profile: '调查员' }]
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: unknown = { success: true, scripts: [], models: [] }
    if (path.endsWith('/state')) body = {
      success: true, session_id: 'audio-selection', status: 'in_progress', current_stage: 'intro', current_round: 0,
      human_character_id: 'human', current_speaker_id: 'human', speech_queue: ['human'],
      characters, script: { script_id: 'audio-script', title: '音频选择验证', player_count: 1 },
      player_states: [{ character_id: 'human', character_name: '林岚', is_human: true, remaining_speech_count: 1 }],
      votes: {}, agent_llm_info: {},
    }
    if (path.endsWith('/records')) body = { success: true, records: [
      { id: 1, session_id: 'audio-selection', record_type: 'system', stage: 'intro', content: prose, audio_url: '/audio/selection.wav' },
      { id: 2, session_id: 'audio-selection', record_type: 'speech', stage: 'intro', speaker_id: 'human', speaker_name: '林岚', content: '这是角色发言，也可以在系统音频播放期间选中。' },
    ] }
    if (path.endsWith('/system/capabilities')) body = { models: [], features: {
      static_tts: { enabled: true }, streaming_tts: { enabled: true }, rag: { enabled: false }, image: { enabled: false },
    } }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/?session=audio-selection')
  const message = page.locator('[data-record-id="1"]')
  await expect(message.getByText(prose)).toBeVisible()
  await message.getByRole('button', { name: '播放语音' }).click()
  await expect(message.getByRole('button', { name: '停止播放语音' })).toBeVisible()
  await expect(message).toContainText('0:01')
  for (const id of [1, 2]) {
    const paragraph = page.locator(`[data-record-id="${id}"] .markdown-content p`).first()
    const selected = await paragraph.evaluate((node) => {
      const range = document.createRange(); range.selectNodeContents(node)
      const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
      return selection.toString()
    })
    const originalNode = await paragraph.elementHandle()
    await page.waitForTimeout(1300)
    expect(await originalNode!.evaluate((node) => node.isConnected)).toBe(true)
    expect(await page.evaluate(() => window.getSelection()?.toString())).toBe(selected)
    await page.keyboard.press('Control+C')
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(selected)
  }
  await page.screenshot({ path: testInfo.outputPath('audio-selection-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(message.getByRole('button', { name: '停止播放语音' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('audio-selection-mobile.png') })
  await message.getByRole('button', { name: '停止播放语音' }).click()
})
