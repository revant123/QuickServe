import { type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from './AuthProvider'

/** Screens that need a login send you to it, then back where you were. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { loggedIn } = useAuth()
  const location = useLocation()
  if (!loggedIn) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
  return <>{children}</>
}
