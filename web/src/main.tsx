import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '@fontsource-variable/source-serif-4/opsz.css'
import '@fontsource-variable/jetbrains-mono'
import './styles.css'
import { initRuntime } from './data/api'

// live.json must be read before the app loads: site.ts and the pages decide live or static at import time
initRuntime()
  .then(() => import('./App'))
  .then(({ default: App }) =>
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    ),
  )
