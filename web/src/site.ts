// Names, links and people shown in the header, the home page, the footer and About. One place to change them.
//
// Build-time settings (Vite env vars; set them in web/.env.production):
//   VITE_LIVE_URL   the live demo. Unset or empty: "Try it live" opens the Studio page.
//   VITE_PAPER_URL  the paper. Unset: the paper link goes to the About page, which says where it will appear.
//   VITE_CODE_URL   the code repository. Unset: the same.
//   VITE_API_BASE   the gateway that serves /api and /mcp ("/" for the same address). Unset: static files only.

import { LIVE } from './data/api'

const env = import.meta.env as Record<string, string | undefined>
const clean = (v: string | undefined) => (v ?? '').trim()

export const SITE = {
  name: 'AlphaCourt',
  tagline: 'No alpha without a trial.',
  description: 'AlphaCourt is a gateway between an AI research agent and deployment. A strategy that asks for capital is held and tried by a prosecutor, a defence and a judge, and a finding without an exhibit is struck.',
}

export const LINKS = {
  live: LIVE ? '' : clean(env.VITE_LIVE_URL),
  paper: clean(env.VITE_PAPER_URL),
  code: clean(env.VITE_CODE_URL),
}

/** Where a link with no address yet points: the About page section that says so. */
export const PENDING = '/about?s=links'

export const LICENCE = { name: 'MIT licence', file: 'LICENSE' }

export const AUTHORS = [
  { name: 'Arush Gumber', affiliation: 'IIIT-Delhi and StarkVision Research', email: 'arush23136@iiitd.ac.in' },
  { name: 'Sidhant Gumber', affiliation: 'Independent Researcher', email: 'gumbersidhant@gmail.com' },
  { name: 'Pranav Viksar Garg', affiliation: 'University of Manchester', email: 'pranav.garg@student.manchester.ac.uk' },
]
