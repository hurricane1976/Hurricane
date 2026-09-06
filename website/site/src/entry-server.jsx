import { renderToString } from 'react-dom/server'
import App from './App.jsx'
import { ROUTES, SITE, FAQ } from './routes.js'

export { ROUTES, SITE, FAQ }

export function render(path) {
  return renderToString(<App path={path} />)
}
