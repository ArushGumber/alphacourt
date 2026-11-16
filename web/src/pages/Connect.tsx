import { useState } from 'react'
import { API_BASE, LIVE, MCP_URL} from '../data/api'
import { LINKS } from '../site'
import { Page } from '../components/Layout'
import { CopyButton, PageHeader, SectionTitle, Segmented, Note } from '../components/ui'

const TOOLS = [
  { n: 'list_fields()', d: 'The fields in the data room, with when each is available.' },
  { n: 'field_info(name)', d: 'The description and availability of one field. Honest, but a careless agent can still use a leaky field.' },
  { n: 'read_page(url)', d: 'A page from the alpha web: a blog post, a forum thread or a paper abstract. The gateway records which pages were read.' },
  { n: 'run_backtest(spec)', d: 'Runs a plain backtest on the research period, with no extra checks. Each run is logged, and the court counts how many were tried.' },
  { n: 'submit_strategy(spec, claim, requested_capital)', d: 'Ask for capital. Returns a case id with status held and a link to watch the trial.' },
  { n: 'get_verdict(case_id)', d: 'The ruling once the trial ends: deploy, paper only or reject, with the findings.' },
]

function origin(): string {
  if (API_BASE) return API_BASE
  if (LIVE && typeof window !== 'undefined') return window.location.origin
  if (LINKS.live) return LINKS.live.replace(/\/+$/, '')
  return 'https://YOUR-ALPHACOURT-HOST'
}

export default function Connect() {
  const url = MCP_URL || `${origin()}/mcp`
  const placeholder = url.includes('YOUR-ALPHACOURT-HOST')
  const [tab, setTab] = useState<'claude' | 'codex' | 'gemini'>('claude')
  // the same lines as examples/mcp/ in the repository
  const cmds = {
    claude: { label: 'Claude Code', text: `claude mcp add --transport http alphacourt ${url}`, alt: `{"mcpServers": {"alphacourt": {"type": "http", "url": "${url}"}}}`, altWhere: 'Or save this as a file and pass it with --mcp-config. For claude -p, allow the tools with --allowedTools "mcp__alphacourt__*".', where: 'Run it once in a terminal, then start claude.' },
    codex: { label: 'Codex', text: `codex mcp add alphacourt --url ${url}`, alt: '', altWhere: '', where: 'Run it once in a terminal, then start codex (or codex exec "<brief>").' },
    gemini: { label: 'Gemini CLI', text: `gemini mcp add --transport http alphacourt ${url}`, alt: `{"mcpServers": {"alphacourt": {"httpUrl": "${url}"}}}`, altWhere: 'Or add this to ~/.gemini/settings.json.', where: 'Run it once in a terminal, then start gemini.' },
  }
  const c = cmds[tab]
  return (
    <Page>
      <PageHeader title="Connect your agent">
        <p>Any AI agent that supports MCP can connect to AlphaCourt with one line. Ask it for a trading strategy, and it will do its research through AlphaCourt. When it submits, you can watch the trial.</p>
      </PageHeader>

      <section id="attach" aria-labelledby="line-h">
        <SectionTitle title="One line" id="line-h" />
        <Segmented label="Agent" value={tab} onChange={setTab} options={(Object.keys(cmds) as (keyof typeof cmds)[]).map((k) => ({ value: k, label: cmds[k].label }))} />
        <div className="mt-4 max-w-[820px] rounded-[8px] border border-line bg-bg-1">
          <div className="flex items-start justify-between gap-3 px-4 pt-3.5">
            <pre className="mono min-w-0 flex-1 overflow-x-auto whitespace-pre pb-3.5 text-[13.5px] leading-relaxed text-ink" tabIndex={0} aria-label={`${c.label} command`}>{c.text}</pre>
            <CopyButton text={c.text} />
          </div>
        </div>
        <p className="mt-3 text-[14px] text-ink-3">{c.where}</p>
        {c.alt && (
          <div className="mt-4 max-w-[820px] rounded-[8px] border border-line bg-bg-1">
            <div className="flex items-start justify-between gap-3 px-4 pt-3.5">
              <pre className="mono min-w-0 flex-1 overflow-x-auto whitespace-pre pb-3.5 text-[13.5px] leading-relaxed text-ink" tabIndex={0} aria-label={`${c.label} JSON configuration`}>{c.alt}</pre>
              <CopyButton text={c.alt} />
            </div>
          </div>
        )}
        {c.altWhere && <p className="mt-3 text-[14px] text-ink-3">{c.altWhere}</p>}
        {placeholder && <Note className="mt-4 max-w-[820px]">The address above is a placeholder. When a live server is configured (live.json next to index.html), this page shows its address.</Note>}
        <p className="mt-4 max-w-[720px] text-[14.5px] leading-relaxed text-ink-2">Then ask: &ldquo;Use the alphacourt tools to find a strategy with a Sharpe above 2.5, and submit it.&rdquo; The tools are sandboxed to the simulated data room. No real order can be placed.</p>
      </section>

      <section className="mt-14" aria-labelledby="tools-h">
        <SectionTitle title="The six tools" id="tools-h" />
        <dl className="max-w-[820px] divide-y divide-line border-y border-line">
          {TOOLS.map((t) => (
            <div key={t.n} className="grid gap-x-8 gap-y-1 py-3.5 sm:grid-cols-[320px_minmax(0,1fr)]">
              <dt className="mono break-words text-[13px] font-medium text-ink">{t.n}</dt>
              <dd className="text-[14.5px] leading-relaxed text-ink-2">{t.d}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 max-w-[720px] text-[14px] leading-relaxed text-ink-3">A strategy is a fixed recipe, never free code: a signal formula plus settings such as delay and costs. That is what lets every test re-run it exactly.</p>
      </section>
    </Page>
  )
}
