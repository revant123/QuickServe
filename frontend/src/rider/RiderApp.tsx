import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Suspense, useState, type FormEvent } from 'react'
import { Outlet } from 'react-router'
import { api, ApiError, unwrap, type Schemas } from '../api/client'
import { usePool, useRiderDay } from '../api/partner'
import { useAuth } from '../auth/AuthProvider'
import { RequireRole } from '../auth/RequireRole'
import { BottomNav, ErrorBox, Loading, type NavItem } from '../components/ui'
import { rupees } from '../lib/money'
import { ago, clock, useNow } from '../lib/time'
import { ArtDefs, RegionStrip } from '../theme/Art'

type Job = Schemas['RiderOrder']

const NAV: NavItem[] = [
  { to: '/rider', label: 'Deliveries', icon: 'M5 17a2 2 0 1 0 0 .01M19 17a2 2 0 1 0 0 .01M5 17h2l3-7h5l4 7M10 10l-2-4H5' },
  { to: '/rider/earnings', label: 'Earnings', icon: 'M6 4h12M6 9h12M8 4c5 0 5 9 0 9l8 7' },
]

export function RiderApp() {
  const { user, logout } = useAuth()
  return (
    <div className="app rider">
      <ArtDefs />
      <RequireRole role="RIDER">
        <header className="partner-header">
          <div className="partner-header-row">
            <div className="grow">
              <p className="eyebrow">QuickServe Delivery</p>
              <h1 className="partner-name">{user?.name}</h1>
            </div>
            <button type="button" className="link-btn small" onClick={() => void logout()}>
              Log out
            </button>
          </div>
          <RegionStrip region="plain" height={10} />
        </header>
        <Suspense fallback={<Loading />}>
          <Outlet />
        </Suspense>
        <BottomNav items={NAV} label="Delivery" />
      </RequireRole>
    </div>
  )
}

/** Google Maps directions to a point. Opens the Maps app on a phone. */
function mapsLink(lat: string | null | undefined, lng: string | null | undefined, fallback: string): string {
  const destination = lat && lng ? `${lat},${lng}` : fallback
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}`
}

export function RiderHome() {
  const day = useRiderDay()
  const pool = usePool(day.isSuccess && !day.data.active)

  if (day.isPending) return <Loading label="Checking your deliveries" />
  if (day.isError) return <ErrorBox error={day.error} onRetry={() => day.refetch()} />
  if (day.data.active) return <ActiveDelivery job={day.data.active} />

  return (
    <main className="stack">
      <h2 className="section-title">Orders near you</h2>
      <p className="muted small">Accept one and ride to the restaurant while it's cooked. You see the customer's address after you accept.</p>
      {pool.isPending ? (
        <Loading label="Looking for orders" />
      ) : pool.isError ? (
        <ErrorBox error={pool.error} onRetry={() => pool.refetch()} />
      ) : pool.data.length === 0 ? (
        <p className="empty">No orders waiting right now. This list refreshes every 10 seconds.</p>
      ) : (
        <ul className="plain-list job-grid" aria-label="Orders waiting for a rider">
          {pool.data.map((p) => (
            <li key={p.id}>
              <PoolCard order={p} />
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}

function PoolCard({ order: p }: { order: Schemas['PoolOrder'] }) {
  const queryClient = useQueryClient()
  const now = useNow(30_000)
  const claim = useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/v1/orders/{order_id}/claim', { params: { path: { order_id: p.id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rider'] }),
    // Someone else was faster (409): refresh the list so the order disappears.
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) queryClient.invalidateQueries({ queryKey: ['rider', 'pool'] })
    },
  })
  return (
    <article className="job-card" aria-labelledby={`p-${p.id}`}>
      <div className="row between nowrap">
        <h3 id={`p-${p.id}`} className="dish-name">
          {p.restaurant_name}
        </h3>
        <strong className="pay">{rupees(p.rider_pay)}</strong>
      </div>
      <p className="muted small">{p.restaurant_address}</p>
      <p className="small">
        <span className={`status-chip ${p.status === 'READY' ? 'go' : ''}`}>{p.status === 'READY' ? 'Food ready' : 'Being cooked'}</span> {p.distance_km} km to the customer ·{' '}
        {p.item_count} item{p.item_count === 1 ? '' : 's'} · {ago(p.created_at, now)}
      </p>
      {claim.isError && <ErrorBox error={claim.error} />}
      <button type="button" className="btn big" onClick={() => claim.mutate()} disabled={claim.isPending}>
        {claim.isPending ? 'Accepting…' : `Accept · ${rupees(p.rider_pay)}`}
      </button>
    </article>
  )
}

function ActiveDelivery({ job }: { job: Job }) {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['rider'] })
  const [code, setCode] = useState('')
  const pickedUp = job.status === 'OUT_FOR_DELIVERY'

  const status = useMutation({
    mutationFn: async (body: { status: 'OUT_FOR_DELIVERY' | 'DELIVERED'; delivery_code?: string }) =>
      unwrap(await api.PATCH('/api/v1/orders/{order_id}/status', { params: { path: { order_id: job.id } }, body })),
    onSuccess: () => {
      setCode('')
      refresh()
    },
  })
  const release = useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/v1/orders/{order_id}/release', { params: { path: { order_id: job.id } } })),
    onSuccess: refresh,
  })

  function deliver(e: FormEvent) {
    e.preventDefault()
    status.mutate({ status: 'DELIVERED', delivery_code: code })
  }

  return (
    <main className="stack">
      <ol className="steps" aria-label="Delivery progress">
        <li className={pickedUp ? 'done' : 'now'} aria-current={pickedUp ? undefined : 'step'}>
          Pick up from {job.restaurant_name}
        </li>
        <li className={pickedUp ? 'now' : ''} aria-current={pickedUp ? 'step' : undefined}>
          Deliver to the customer
        </li>
      </ol>

      {!pickedUp ? (
        <section className="panel job-step" aria-labelledby="pickup-title">
          <div className="panel-body">
            <h2 id="pickup-title" className="section-title">
              {job.restaurant_name}
            </h2>
            <p>{job.restaurant_address}</p>
            <a className="btn ghost" href={mapsLink(job.restaurant_latitude, job.restaurant_longitude, job.restaurant_address)} target="_blank" rel="noopener noreferrer">
              Directions to the restaurant
            </a>
            <p className="small">
              {job.item_count} item{job.item_count === 1 ? '' : 's'} · you earn <strong>{rupees(job.rider_pay)}</strong>
            </p>
            {job.status === 'READY' ? (
              <p className="notice small">The food is packed and waiting.</p>
            ) : (
              <p className="muted small">The kitchen is still {job.status === 'ACCEPTED' ? 'starting' : 'cooking'}. You can pick up once it's marked ready.</p>
            )}
            {status.isError && <ErrorBox error={status.error} />}
            <button type="button" className="btn big" disabled={job.status !== 'READY' || status.isPending} onClick={() => status.mutate({ status: 'OUT_FOR_DELIVERY' })}>
              I've picked it up
            </button>
            <button type="button" className="link-btn small" onClick={() => release.mutate()} disabled={release.isPending}>
              I can't take this order
            </button>
            {release.isError && <ErrorBox error={release.error} />}
          </div>
        </section>
      ) : (
        <section className="panel job-step" aria-labelledby="drop-title">
          <div className="panel-body">
            <h2 id="drop-title" className="section-title">
              Deliver to
            </h2>
            <p>{job.delivery_address}</p>
            <a className="btn ghost" href={mapsLink(job.delivery_latitude, job.delivery_longitude, job.delivery_address)} target="_blank" rel="noopener noreferrer">
              Directions to the customer
            </a>
            <form className="form" onSubmit={deliver}>
              <label htmlFor="delivery-code">Customer's 4-digit delivery code</label>
              <input
                id="delivery-code"
                className="code-input"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{4}"
                maxLength={4}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
                aria-describedby="code-hint"
              />
              <p id="code-hint" className="muted small">
                Ask for it at the door, after you hand over the food. A wrong code is counted; 5 wrong codes lock the order.
              </p>
              {status.isError && <ErrorBox error={status.error} />}
              <button type="submit" className="btn big" disabled={code.length !== 4 || status.isPending}>
                {status.isPending ? 'Checking…' : 'Mark delivered'}
              </button>
            </form>
          </div>
        </section>
      )}
    </main>
  )
}

export function EarningsPage() {
  const day = useRiderDay()
  if (day.isPending) return <Loading />
  if (day.isError) return <ErrorBox error={day.error} onRetry={() => day.refetch()} />
  return (
    <main className="stack">
      <section className="panel payout" aria-labelledby="earn-title">
        <div className="panel-body">
          <p className="eyebrow">Today</p>
          <h2 id="earn-title" className="payout-amount">
            {rupees(day.data.earnings_today)}
          </h2>
          <p className="muted">
            {day.data.deliveries_today} deliver{day.data.deliveries_today === 1 ? 'y' : 'ies'}
          </p>
        </div>
      </section>
      <ul className="plain-list" aria-label="Today's deliveries">
        {day.data.delivered_today.map((j) => (
          <li key={j.id} className="offer-card">
            <span className="row between">
              <strong>{j.restaurant_name}</strong>
              <strong>{rupees(j.rider_pay)}</strong>
            </span>
            <span className="muted small">
              {clock(j.created_at)} · {j.distance_km} km
            </span>
          </li>
        ))}
      </ul>
      <p className="footnote">Pay per order: a base amount plus an amount per km, shown before you accept. Example rates, not any platform's real ones.</p>
    </main>
  )
}
