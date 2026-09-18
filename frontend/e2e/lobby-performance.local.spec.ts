import { test, expect } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

test('local controlled baseline and optimized cold starts', async ({ browser }, info) => {
  test.skip(process.env.LOBBY_PERFORMANCE_LOCAL !== '1', 'Requires the isolated baseline and optimized benchmark servers')
  test.setTimeout(360000)
  const results: unknown[] = []
  for (const port of [4211, 4212]) for (let run = 0; run < 3; run++) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
    const page = await context.newPage()
    const cdp = await context.newCDPSession(page)
    await cdp.send('Network.enable')
    await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 80, downloadThroughput: 1_000_000, uploadThroughput: 500_000 })
    await page.addInitScript(() => {
      const observer = new MutationObserver(() => {
        if (document.querySelector('.dream-lobby[data-renderer="webgl"]') && !performance.getEntriesByName('measured-first-frame').length) performance.mark('measured-first-frame')
      })
      observer.observe(document, { subtree: true, attributes: true, attributeFilter: ['data-renderer'] })
    })
    await page.goto(`http://127.0.0.1:${port}`, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('.dream-lobby')).toHaveAttribute('data-renderer', 'webgl', { timeout: 60000 })
    await expect.poll(() => page.locator('.lobby-card img').evaluateAll(images => images.filter(el => el.getBoundingClientRect().top < innerHeight).every(el => (el as HTMLImageElement).complete)), { timeout: 60000 }).toBe(true)
    await page.waitForTimeout(2000)
    results.push(await page.evaluate(({ port, run }) => {
      const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
      const dynamic = resources.find(r => r.name.includes('fluidAtmosphere-'))
      return { port, run, frame_ms: performance.getEntriesByName('measured-first-frame')[0]?.startTime,
        dynamic_ms: dynamic?.duration, dynamic_transfer: dynamic?.transferSize,
        image_bytes: resources.filter(r => r.name.includes('/images/')).reduce((sum,r) => sum + r.transferSize, 0),
        image_requests: resources.filter(r => r.name.includes('/images/')).length,
        dom_covers: [...document.querySelectorAll('.lobby-card img')].map(img => ({url:(img as HTMLImageElement).currentSrc, loaded:(img as HTMLImageElement).complete})) }
    }, { port, run }))
    if (run === 2) await page.screenshot({ path: info.outputPath(`lobby-${port}.png`) })
    await context.close()
  }
  await writeFile('../output/performance/results.json', JSON.stringify(results, null, 2))
})
