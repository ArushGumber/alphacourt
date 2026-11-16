// Shared setup for the Playwright scripts: browser location, a local server for a built or dev site.
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

export const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
// Browsers are not installed per project. This machine keeps one copy in the Finstinct web folder (read only here).
const candidates = [path.join(WEB, '.playwright')]
const home = candidates.find((p) => fs.existsSync(path.join(p, 'chromium-1255'))) ?? candidates[0]
process.env.PLAYWRIGHT_BROWSERS_PATH ||= home
const libs = path.join(home, 'libs')
if (fs.existsSync(libs)) process.env.LD_LIBRARY_PATH = [libs, process.env.LD_LIBRARY_PATH].filter(Boolean).join(':')

export const { chromium } = await import('playwright')

/** Serve a folder (a built site) on a free port. Returns { base, close }. */
export async function serveDir(dir) {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' }
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x')
    const f = path.join(dir, url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname))
    if (f.startsWith(dir) && fs.existsSync(f) && fs.statSync(f).isFile()) {
      res.writeHead(200, { 'Content-Type': types[path.extname(f)] ?? 'application/octet-stream' })
      return res.end(fs.readFileSync(f))
    }
    res.writeHead(404)
    res.end()
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  return { base: `http://127.0.0.1:${server.address().port}/`, close: () => server.close() }
}

/** Start the Vite dev server on a port and wait until it answers. Returns { base, close }. */
export async function devServer(port = 5199) {
  const p = spawn(process.execPath, [path.join(WEB, 'node_modules/vite/bin/vite.js'), '--port', String(port), '--strictPort', '--host', '127.0.0.1'], { cwd: WEB, stdio: 'ignore' })
  const base = `http://127.0.0.1:${port}/`
  for (let i = 0; i < 80; i++) {
    try {
      const r = await fetch(base)
      if (r.ok) return { base, close: () => p.kill() }
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 250))
  }
  p.kill()
  throw new Error('dev server did not start')
}
