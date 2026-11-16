// Figure 1 of the paper: the architecture figure at a fixed width, bare, for capture by scripts/figure.mjs (#/figure).
import { useEffect, useState } from 'react'
import { Architecture } from '../components/Architecture'

export default function Figure() {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    document.documentElement.style.background = '#ffffff'
    document.body.style.background = '#ffffff'
    document.fonts.ready.then(() => setReady(true))
  }, [])
  return (
    <div id="figure" data-ready={ready ? 'yes' : 'no'} style={{ width: 1100, background: '#ffffff' }}>
      <Architecture interactive={false} />
    </div>
  )
}
