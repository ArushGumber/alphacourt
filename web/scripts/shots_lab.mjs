// Flaw Lab screenshots: static walk-through, then the live flow against a gateway (LAB_LIVE=http://host:port, which serves the site).
import path from 'node:path'
import fs from 'node:fs'
import { chromium, serveDir, WEB } from './lib/browser.mjs'

const out = path.join(WEB, 'shots/lab')
fs.mkdirSync(out, { recursive: true })
const live = process.env.LAB_LIVE
const browser = await chromium.launch()

async function run(w, h, tag) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.log('pageerror', e.message))
  if (!live) {
    const srv = await serveDir(path.join(WEB, 'dist'))
    await page.goto(`${srv.base}#/lab`)
    await page.waitForSelector('text=Recorded walk-through, text=recorded walk-through', { timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: 'Same bar and revised data' }).click()
    await page.waitForTimeout(1200)
    await page.screenshot({ path: path.join(out, `static-${tag}.png`), fullPage: true })
    srv.close()
  } else {
    await page.goto(`${live}/#/lab`)
    await page.waitForSelector('[role=switch]', { timeout: 15000 })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: path.join(out, `live-honest-${tag}.png`), fullPage: true })
    await page.getByRole('switch', { name: 'Trade on the same bar' }).click()
    await page.getByRole('switch', { name: 'Use revised data' }).click()
    await page.waitForTimeout(2500)
    await page.screenshot({ path: path.join(out, `live-flaws-${tag}.png`), fullPage: true })
    if (process.env.LAB_TRIAL) {
      await page.getByRole('button', { name: 'Send to court' }).click()
      await page.waitForSelector('#truth, [aria-label="The truth"]', { timeout: 240000 })
      await page.waitForTimeout(2500)
      await page.screenshot({ path: path.join(out, `live-truth-${tag}.png`), fullPage: true })
    }
  }
  await ctx.close()
}
await run(1440, 900, '1440')
await run(390, 844, '390')
await browser.close()
