import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { useAuth } from '../auth/AuthProvider'
import { TopBar } from '../components/ui'
import { safeNext } from '../lib/safeNext'


// The seed's local-only demo logins. The same three apps a real platform has:
// customers, restaurant partners and delivery partners.
const DEMO = [
  { label: 'customer', email: 'customer@quickserve.dev', password: 'customer-pass-123' },
  { label: 'restaurant owner', email: 'owner@quickserve.dev', password: 'owner-pass-123' },
  { label: 'rider', email: 'rider@quickserve.dev', password: 'rider-pass-123' },
]

export function LoginPage() {
  const { login, loggedIn } = useAuth()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (loggedIn) return <Navigate to={next} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email.trim(), password)
      navigate(next, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not log in.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <TopBar title="Log in" />
      <main className="stack">
        <form className="panel panel-body form" onSubmit={submit} noValidate>
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <label htmlFor="password">Password</label>
          <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="btn" disabled={busy || !email || !password}>
            {busy ? 'Logging in…' : 'Log in'}
          </button>
          <fieldset className="demo-logins">
            <legend className="small muted">Demo accounts (from the seed)</legend>
            {DEMO.map((d) => (
              <button
                key={d.email}
                type="button"
                className="btn ghost"
                onClick={() => {
                  setEmail(d.email)
                  setPassword(d.password)
                }}
              >
                Fill in the demo {d.label}
              </button>
            ))}
          </fieldset>
        </form>
        <p className="center">
          New here? <Link to={`/register?next=${encodeURIComponent(next)}`}>Create an account</Link>
        </p>
      </main>
    </div>
  )
}

export function RegisterPage() {
  const { register, loggedIn } = useAuth()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (loggedIn) return <Navigate to={next} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await register(name.trim(), email.trim(), password)
      navigate(next, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the account.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <TopBar title="Create account" />
      <main className="stack">
        <form className="panel panel-body form" onSubmit={submit}>
          <label htmlFor="name">Name</label>
          <input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} />
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            aria-describedby="pw-hint"
          />
          <p id="pw-hint" className="muted small">
            At least 8 characters.
          </p>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="btn" disabled={busy}>
            {busy ? 'Creating…' : 'Create account'}
          </button>
        </form>
        <p className="center">
          Already have one? <Link to={`/login?next=${encodeURIComponent(next)}`}>Log in</Link>
        </p>
      </main>
    </div>
  )
}

export function ProfilePage() {
  const { user, logout, loggedIn } = useAuth()
  const navigate = useNavigate()
  if (!loggedIn) return <Navigate to="/login?next=/profile" replace />
  return (
    <div className="page">
      <TopBar title="Profile" back={false} />
      <main className="stack">
        <section className="panel panel-body">
          <h2 className="section-title">{user?.name ?? '…'}</h2>
          <p className="muted">{user?.email}</p>
        </section>
        <button
          type="button"
          className="btn ghost"
          onClick={async () => {
            await logout()
            navigate('/', { replace: true })
          }}
        >
          Log out
        </button>
      </main>
    </div>
  )
}
