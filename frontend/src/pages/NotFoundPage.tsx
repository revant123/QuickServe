import { Link } from 'react-router'
import { TopBar } from '../components/ui'
import { Drawing } from '../theme/Art'

export function NotFoundPage() {
  return (
    <div className="page">
      <TopBar title="Not found" />
      <main className="stack center">
        <Drawing id="i-thali" size={140} />
        <p className="empty">This page isn't on the menu.</p>
        <Link to="/" className="btn">
          Back to home
        </Link>
      </main>
    </div>
  )
}
