// Captures the architecture figure for the paper from the print route (#/figure).
//   node scripts/figure.mjs   builds the site, checks the figure, writes figure/architecture.png (2x) and figure/architecture.svg
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { WEB, chromium, serveDir } from './lib/browser.mjs'

const out = fs.mkdtempSync(path.join(os.tmpdir(), 'alphacourt-figure-'))
execFileSync(process.execPath, [path.join(WEB, 'node_modules/vite/bin/vite.js'), 'build', '--outDir', out, '--emptyOutDir', '--logLevel', 'error'], { cwd: WEB, stdio: 'inherit' })
const srv = await serveDir(out)
const dest = path.join(WEB, 'figure')
fs.mkdirSync(dest, { recursive: true })
const browser = await chromium.launch()
const fails = []
const check = (ok, what) => { console.log(`${ok ? 'ok' : '!!'} ${what}`); if (!ok) fails.push(what) }
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 700 }, deviceScaleFactor: 2 })
  const errors = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  await page.goto(`${srv.base}#/figure`, { waitUntil: 'networkidle' })
  await page.waitForSelector('#figure[data-ready="yes"]')
  await page.waitForTimeout(300)
  const box = await page.$eval('#figure', (e) => ({ w: e.offsetWidth, h: e.offsetHeight }))
  check(box.w === 1100, `fixed width ${box.w} by ${box.h} CSS pixels`)
  const small = await page.$$eval('#figure svg text', (ts) => ts.filter((t) => t.getBoundingClientRect().height > 0 && parseFloat(getComputedStyle(t).fontSize) * (t.ownerSVGElement.getBoundingClientRect().width / 1100) < 12).map((t) => t.textContent.slice(0, 20)))
  check(small.length === 0, `no text under 12 px${small.length ? ': ' + small.slice(0, 3).join('; ') : ''}`)
  // text must stay inside its box: compare every leaf label with its group's rectangle
  const spill = await page.$$eval('#figure .figure-node', (gs) => gs.flatMap((g) => {
    const r = g.querySelector('rect').getBoundingClientRect()
    return [...g.querySelectorAll('text')].filter((t) => { const b = t.getBoundingClientRect(); return b.right > r.right + 1 || b.bottom > r.bottom + 1 || b.left < r.left - 1 }).map((t) => t.textContent.slice(0, 24))
  }))
  check(spill.length === 0, `text inside its box${spill.length ? ': ' + spill.join('; ') : ''}`)
  check(errors.length === 0, 'no console errors')
  await (await page.$('#figure')).screenshot({ path: path.join(dest, 'architecture.png') })
  const svg = await page.$eval('#architecture-svg', (e) => {
    const c = e.cloneNode(true)
    c.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    c.setAttribute('width', '1100'); c.setAttribute('height', '566'); c.removeAttribute('class'); c.removeAttribute('style')
    c.querySelectorAll('[tabindex],[role="button"]').forEach((n) => { n.removeAttribute('tabindex'); n.removeAttribute('role'); n.removeAttribute('aria-label'); n.removeAttribute('style') })
    return c.outerHTML
  })
  fs.writeFileSync(path.join(dest, 'architecture.svg'), `<?xml version="1.0" encoding="UTF-8"?>\n<svg font-family="Inter, Helvetica, Arial, sans-serif"${svg.slice(4)}\n`)
  console.log('wrote figure/architecture.png and figure/architecture.svg')
} finally {
  await browser.close(); srv.close(); fs.rmSync(out, { recursive: true, force: true })
}
console.log(fails.length ? `${fails.length} check(s) failed` : 'figure: all checks passed')
process.exitCode = fails.length ? 1 : 0
