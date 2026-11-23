import { useEffect, useState } from 'react'
import App from './App'
import { wantsDemo } from './dev/devPreview'
import Experience from './screens/Experience'

export type Route = 'standby' | 'active' | 'hud'

/**
 * `#/` opens the Standby (the product's first screen), `#/active` opens straight on the active screen (the activation plays from
 * its start), `#/hud` opens the earlier HoloDrive prototype. `?demo` after the hash adds the development state switcher.
 */
export function routeFromHash(hash: string): Route {
  const path = hash.split('?')[0]
  return path === '#/hud' ? 'hud' : path === '#/active' ? 'active' : 'standby'
}

export { wantsDemo } // (lives in dev/devPreview.ts so the 3D stage can use it without an import cycle)

function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}

/**
 * The application shell. The Standby is the default and makes no network request; the active screen starts its read-only service
 * checks only once it is on stage. The HoloDrive prototype stays reachable only on purpose, through its own hash.
 */
export default function Root() {
  const hash = useHash()
  const route = routeFromHash(hash)
  if (route === 'hud') return <App />
  return <Experience key={route} initial={route === 'active' ? 'activating' : 'standby'} demo={wantsDemo(hash)} />
}
