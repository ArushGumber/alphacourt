// Prints figure/architecture.svg to figure/architecture.pdf (vector, one page) for the paper's Figure 1.
//   node scripts/figure_pdf.mjs [scale]
// The paper prints the figure at 7.0 in wide (504 pt) for 1100 SVG units, so 1 unit = 0.4582 pt. Text is enlarged by `scale`
// (default 1.14) so that the smallest label (13 units) prints at 6.5 pt or more. Boxes and arrows keep their geometry; the
// script reports any text that then leaves its box and any two texts that overlap.
import fs from 'node:fs'
import path from 'node:path'
import { WEB, chromium } from './lib/browser.mjs'

const scale = Number(process.argv[2] ?? 1.14)
const interUrl = 'file://' + path.join(WEB, 'node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2')
const svg = fs.readFileSync(path.join(WEB, 'figure/architecture.svg'), 'utf8')
const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport: { width: 1100, height: 566 } })
  const tmp = path.join(WEB, 'figure/_print.html')
  fs.writeFileSync(tmp, `<!doctype html><html><head><style>@font-face{font-family:'Inter Variable';src:url('${interUrl}');font-weight:100 900}@page{size:1100px 566px;margin:0}html,body{margin:0;padding:0;background:#fff}svg{display:block}</style></head><body>${svg.replace(/^<\?xml[^>]*>\s*/, '')}</body></html>`)
  await page.goto('file://' + tmp)
  await page.evaluate(() => document.fonts.ready)
  const report = await page.evaluate((k) => {
    const root = document.querySelector('svg')
    root.querySelectorAll('text').forEach((t) => {
      const fs0 = parseFloat(t.getAttribute('font-size') || getComputedStyle(t).fontSize)
      t.setAttribute('font-size', String(fs0 * k))
      // keep the left edge or centre of each line: only the size changes
    })
    const texts = [...root.querySelectorAll('text')].filter((t) => t.getBoundingClientRect().height > 0)
    const sizes = texts.map((t) => parseFloat(t.getAttribute('font-size')))
    const spill = []
    root.querySelectorAll('.figure-node').forEach((g) => {
      const r = g.querySelector('rect').getBoundingClientRect()
      g.querySelectorAll('text').forEach((t) => { const b = t.getBoundingClientRect(); if (b.right > r.right + 1 || b.bottom > r.bottom + 1 || b.left < r.left - 1) spill.push(t.textContent.slice(0, 24)) })
    })
    const overlaps = []
    for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
      const a = texts[i].getBoundingClientRect(), b = texts[j].getBoundingClientRect()
      if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps.push([texts[i].textContent.slice(0, 18), texts[j].textContent.slice(0, 18)])
    }
    return { minUnits: Math.min(...sizes), spill, overlaps }
  }, scale)
  const pt = report.minUnits * (504 / 1100)
  console.log(`smallest text ${report.minUnits.toFixed(2)} units = ${pt.toFixed(2)} pt at 7.0 in wide`)
  console.log(`text outside its box: ${report.spill.length ? report.spill.join('; ') : 'none'}`)
  console.log(`overlapping texts: ${report.overlaps.length ? JSON.stringify(report.overlaps) : 'none'}`)
  await page.pdf({ path: path.join(WEB, 'figure/architecture.pdf'), width: '1100px', height: '566px', printBackground: true, pageRanges: '1' })
  await page.screenshot({ path: path.join(WEB, 'figure/architecture_print_check.png') })
  fs.rmSync(tmp)
  process.exitCode = pt >= 6.5 && !report.spill.length && !report.overlaps.length ? 0 : 1
} finally { await browser.close() }
