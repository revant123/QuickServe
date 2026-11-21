import { type ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router'
import { useCart } from '../cart/CartProvider'
import { estimatedItemTotal, itemCount } from '../cart/cart'
import { rupees } from '../lib/money'
import { RegionStrip } from '../theme/Art'

export function VegMark({ veg }: { veg: boolean }) {
  // The FSSAI marks used on Indian food packs: green square + dot for veg,
  // brown square + triangle for non-veg.
  return veg ? (
    <svg role="img" aria-label="Vegetarian" width="15" height="15" viewBox="0 0 14 14" className="veg-mark">
      <rect x="1" y="1" width="12" height="12" fill="none" stroke="#1E7B34" strokeWidth="1.6" />
      <circle cx="7" cy="7" r="3.2" fill="#1E7B34" />
    </svg>
  ) : (
    <svg role="img" aria-label="Non-vegetarian" width="15" height="15" viewBox="0 0 14 14" className="veg-mark">
      <rect x="1" y="1" width="12" height="12" fill="none" stroke="#7B3F00" strokeWidth="1.6" />
      <polygon points="7,3.4 10.6,10 3.4,10" fill="#7B3F00" />
    </svg>
  )
}

export function RatingBadge({ rating, count }: { rating: string | null | undefined; count: number }) {
  if (rating === null || rating === undefined) {
    return (
      <span className="badge-new" title={`${count} review${count === 1 ? '' : 's'} so far`}>
        New
      </span>
    )
  }
  return (
    <span className="rating" aria-label={`Rated ${rating} out of 5 from ${count} reviews`}>
      {rating}
      <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24">
        <path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5L2.5 9.4l6.6-.9z" fill="currentColor" />
      </svg>
    </span>
  )
}

export function Stepper({
  qty,
  name,
  accent,
  onAdd,
  onRemove,
  disabled,
  floating,
}: {
  qty: number
  name: string
  accent: string
  onAdd: () => void
  onRemove: () => void
  disabled?: boolean
  floating?: boolean
}) {
  const cls = floating ? 'stepper floating' : 'stepper'
  if (qty === 0) {
    return (
      <button type="button" className={`${cls} add`} style={{ color: accent, borderColor: accent }} onClick={onAdd} disabled={disabled} aria-label={`Add ${name}`}>
        ADD
      </button>
    )
  }
  return (
    <div className={`${cls} on`} role="group" aria-label={`${name} quantity`} style={{ background: accent }}>
      <button type="button" onClick={onRemove} aria-label={`Remove one ${name}`}>
        −
      </button>
      <span aria-live="polite">{qty}</span>
      <button type="button" onClick={onAdd} disabled={disabled} aria-label={`Add one more ${name}`}>
        +
      </button>
    </div>
  )
}

export function TopBar({ title, back = true }: { title: string; back?: boolean }) {
  const navigate = useNavigate()
  return (
    <>
      <header className="topbar">
        {back && (
          <button type="button" className="icon-btn" aria-label="Back" onClick={() => (history.length > 1 ? navigate(-1) : navigate('/'))}>
            <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
        )}
        <h1>{title}</h1>
      </header>
      <RegionStrip region="plain" height={10} />
    </>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}…
    </div>
  )
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div className="error-box" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="btn ghost" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function Ornament({ children, accent = '#7A1324' }: { children: ReactNode; accent?: string }) {
  return (
    <div className="ornament">
      <svg aria-hidden="true" width="56" height="10" viewBox="0 0 60 10">
        <path d="M0 5h48" stroke="#C9A03C" strokeWidth="1.2" />
        <polygon points="54,0 59,5 54,10 49,5" fill={accent} />
      </svg>
      <h2>{children}</h2>
      <svg aria-hidden="true" width="56" height="10" viewBox="0 0 60 10">
        <polygon points="6,0 11,5 6,10 1,5" fill={accent} />
        <path d="M12 5h48" stroke="#C9A03C" strokeWidth="1.2" />
      </svg>
    </div>
  )
}

/** The maroon "View cart" bar, shown while the cart has something in it. */
export function CartBar() {
  const { cart } = useCart()
  const n = itemCount(cart)
  if (n === 0) return null
  return (
    <div className="cart-bar">
      <RegionStrip region="plain" height={8} />
      <Link to="/cart">
        <span>
          <strong>
            {n} item{n === 1 ? '' : 's'}
          </strong>{' '}
          · {rupees(estimatedItemTotal(cart))} · {cart.restaurant?.name}
        </span>
        <span className="cart-bar-cta">View cart ›</span>
      </Link>
    </div>
  )
}

const NAV = [
  { to: '/', label: 'Home', icon: 'M3 11l9-7 9 7M5 10v10h14V10' },
  { to: '/search', label: 'Search', icon: 'M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14M20 20l-3.5-3.5' },
  { to: '/orders', label: 'Orders', icon: 'M6 3h12l1 18H5zM9 8a3 3 0 0 0 6 0' },
  { to: '/profile', label: 'Profile', icon: 'M12 4a4 4 0 1 0 0 8a4 4 0 1 0 0-8M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6' },
]

export function BottomNav() {
  return (
    <nav aria-label="Main" className="bottom-nav">
      {NAV.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.to === '/'}>
          <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d={n.icon} />
          </svg>
          {n.label}
        </NavLink>
      ))}
    </nav>
  )
}
