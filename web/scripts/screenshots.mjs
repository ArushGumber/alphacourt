#!/usr/bin/env node
// Screenshots of every page at 1440 and 390 px wide, with console errors and horizontal overflow reported.
//   node scripts/screenshots.mjs [--only name,name] [--out shots] [baseUrl]
// With no baseUrl it starts the dev server (so the sample fixtures are available) and stops it afterwards.
import fs from 'node:fs'
import path from 'node:path'
import { WEB, chromium, devServer } from './lib/browser.mjs'

const args = process.argv.slice(2)
const flag = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined }
const only = flag('--only')?.split(',')
const out = path.resolve(WEB, flag('--out') ?? 'shots')
fs.mkdirSync(out, { recursive: true })
const given = args.find((a) => /^https?:/.test(a))
const srv = given ? { base: given, close() {} } : await devServer()

const PAGES = [
  { name: 'home', route: '/', wait: 1800 },
  { name: 'courtroom-start', route: '/courtroom?c=case-0041&at=1', wait: 1500 },
  { name: 'courtroom-mid', route: '/courtroom?c=case-0041&at=9', wait: 2200, freeze: true },
  { name: 'courtroom-guilty', route: '/courtroom?c=case-0041&end=1', wait: 2200 },
  { name: 'courtroom-innocent', route: '/courtroom?c=case-0042&end=1', wait: 2200 },
  { name: 'agent', route: '/agent?end=1', wait: 1200 },
  { name: 'studio', route: '/studio?end=1', wait: 1800 },
  { name: 'docket', route: '/docket', wait: 800 },
  { name: 'results', route: '/results', wait: 800 },
  { name: 'connect', route: '/connect', wait: 800 },
  { name: 'how-it-works', route: '/how-it-works', wait: 1800 },
  { name: 'about', route: '/about', wait: 800 },
]
const WIDTHS = [
  { tag: '1440', width: 1440, height: 900, mobile: false },
  { tag: '390', width: 390, height: 844, mobile: true },
]
const browser = await chromium.launch()
let problems = 0
for (const w of WIDTHS) {
  const ctx = await browser.newContext({ viewport: { width: w.width, height: w.height }, deviceScaleFactor: w.mobile ? 2 : 1, isMobile: w.mobile, hasTouch: w.mobile })
  for (const p of PAGES) {
    if (only && !only.includes(p.name)) continue
    const page = await ctx.newPage()
    const errors = []
    page.on('console', (m) => (m.type() === 'error' || m.type() === 'warning') && errors.push(`${m.type()}: ${m.text()}`))
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
    page.on('response', (r) => r.status() >= 400 && !/\/data\//.test(r.url()) && errors.push(`${r.status()}: ${r.url()}`))
    await page.goto(`${srv.base}#${p.route}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(p.wait)
    if (p.freeze) await page.evaluate(() => document.querySelector('button[aria-label="Pause"]')?.click())
    const overflow = await page.evaluate((vw) => document.documentElement.scrollWidth - vw, w.width)
    const file = path.join(out, `${p.name}-${w.tag}.png`)
    await page.screenshot({ path: file, fullPage: true })
    const note = [errors.length ? `${errors.length} console messages` : '', overflow > 0 ? `horizontal overflow ${overflow}px` : ''].filter(Boolean).join(', ')
    console.log(`${note ? '!!' : 'ok'} ${path.relative(process.cwd(), file)} ${note}`)
    for (const e of errors) console.log('   ', e.slice(0, 300))
    if (note) problems++
    await page.close()
  }
  await ctx.close()
}
await browser.close()
srv.close()
console.log(problems ? `${problems} page(s) with problems` : 'no problems found')
process.exitCode = problems ? 1 : 0
