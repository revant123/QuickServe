import { type ReactNode } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import type { Schemas } from '../api/client'
import { Loading } from '../components/ui'
import { useAuth } from './AuthProvider'

type Role = Schemas['Role']

/**
 * A screen for one kind of account. The check here is only for the user's
 * convenience: the API refuses the data anyway (403) if the role is wrong,
 * which is the check that actually protects anything.
 */
export function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { loggedIn, loading, user, logout } = useAuth()
  const location = useLocation()
  if (!loggedIn) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
  if (loading || !user) return <Loading />
  if (user.role !== role) {
    return (
      <main className="stack center">
        <p className="notice">
          This screen is for {role === 'RIDER' ? 'delivery partners' : 'restaurant partners'}. You're logged in as {user.name}.
        </p>
        <Link to="/" className="btn ghost">
          Go home
        </Link>
        <button type="button" className="btn ghost" onClick={() => void logout()}>
          Log out
        </button>
      </main>
    )
  }
  return <>{children}</>
}

/** Where each kind of account starts. */
export function homeFor(role: Role | undefined): string {
  if (role === 'RESTAURANT_OWNER') return '/partner'
  if (role === 'RIDER') return '/rider'
  return '/'
}
