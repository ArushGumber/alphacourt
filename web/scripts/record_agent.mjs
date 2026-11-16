#!/usr/bin/env node
// Records the "A real agent, attached" replay (#/agent) at 1920x1080 to video/agent_session.webm, a fallback clip for the video.
//   node scripts/record_agent.mjs [--no-build] [--speed 1]
// Builds the site (npm run build), serves dist on a spare port, plays the page from the top at normal speed and stops a moment after the replay ends.
import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { WEB, chromium, serveDir } from './lib/browser.mjs'

const args = process.argv.slice(2)
if (!args.includes('--no-build')) {
  const r = spawnSync('npm', ['run', 'build'], { cwd: WEB, stdio: 'inherit', env: { ...process.env } })
  if (r.status !== 0) process.exit(r.status ?? 1)
}
const speed = args.includes('--speed') ? args[args.indexOf('--speed') + 1] : '1'
const outDir = path.join(WEB, 'video')
const tmp = path.join(outDir, '.rec')
fs.rmSync(tmp, { recursive: true, force: true })
fs.mkdirSync(tmp, { recursive: true })

const srv = await serveDir(path.join(WEB, 'dist'))
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: tmp, size: { width: 1920, height: 1080 } }, reducedMotion: 'no-preference' })
const page = await ctx.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
await page.goto(`${srv.base}#/agent`, { waitUntil: 'networkidle' })
await page.waitForSelector('[data-controls]')
if (speed !== '1') await page.getByRole('radio', { name: `${speed}×` }).click().catch(() => {})
await page.getByRole('button', { name: 'Replay' }).waitFor({ timeout: 180000 })
await page.waitForTimeout(3500)
const video = page.video()
await ctx.close()
await video.saveAs(path.join(outDir, 'agent_session.webm'))
await browser.close()
srv.close()
fs.rmSync(tmp, { recursive: true, force: true })
console.log('wrote video/agent_session.webm', (fs.statSync(path.join(outDir, 'agent_session.webm')).size / 1e6).toFixed(1) + ' MB', errors.length ? 'console errors: ' + errors.join(' | ') : 'no console errors')
