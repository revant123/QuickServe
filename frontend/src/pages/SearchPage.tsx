import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useSearch } from '../api/queries'
import { DishPicture } from '../components/DishPicture'
import { ReplaceCartDialog } from '../components/ReplaceCartDialog'
import { CartBar, ErrorBox, Loading, RatingBadge, Stepper, TopBar, VegMark } from '../components/ui'
import { MAX_QTY, qtyOf } from '../cart/cart'
import { useAddToCart } from '../cart/useAddToCart'
import { useLocationPlace } from '../location/location'
import { rupees } from '../lib/money'
import { RegionStrip } from '../theme/Art'
import { REGIONS, regionFor } from '../theme/regions'

/** Wait until typing pauses, so "paneer" is one request, not six. */
function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebounced(text.trim(), 300)
  const { place } = useLocationPlace()
  const search = useSearch(q, place.lat, place.lng)
  const { cart, add, remove, pending, confirm, cancel } = useAddToCart()

  // Keep the URL in step, so a search can be shared or survives a refresh.
  useEffect(() => {
    setParams(q ? { q } : {}, { replace: true })
  }, [q, setParams])

  const result = search.data
  return (
    <div className="page search">
      <TopBar title="Search" />
      <main className="stack">
        <div className="search-box">
          <label htmlFor="search-q" className="visually-hidden">
            Search dishes or restaurants
          </label>
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6E1423" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <input
            id="search-q"
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paneer, dosa, Rajasthani…"
            autoFocus
            autoComplete="off"
            maxLength={60}
          />
        </div>
        <p className="muted small">Delivering to {place.label}</p>

        {q.length < 2 && <p className="empty">Type at least two letters. Typos are fine: try "paner".</p>}
        {search.isPending && q.length >= 2 && <Loading label="Searching" />}
        {search.isError && <ErrorBox error={search.error} onRetry={() => search.refetch()} />}

        {result && q.length >= 2 && (
          <>
            {result.matched === 'fuzzy' && (
              <div className="notice" role="status">
                <strong>Nothing called "{result.query}", so here are close matches.</strong>
              </div>
            )}
            {result.matched === 'none' && <p className="empty">Nothing near you matches "{result.query}". Try another dish or a cuisine.</p>}

            {result.restaurants.length > 0 && (
              <section aria-labelledby="r-title">
                <h2 id="r-title" className="section-title">
                  Restaurants
                </h2>
                <ul className="plain-list compact-cards">
                  {result.restaurants.map((r) => (
                    <li key={r.id}>
                      <Link to={`/r/${r.id}`} state={{ card: r }} className="compact-card">
                        <RegionStrip region={regionFor(r.cuisines)} height={8} />
                        <div>
                          <strong>{r.name}</strong>
                          <span className="muted small">
                            {r.cuisines.join(', ')} · {r.eta_text} · {r.distance_km} km
                          </span>
                        </div>
                        <RatingBadge rating={r.rating} count={r.rating_count} />
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {result.dishes.length > 0 && (
              <section aria-labelledby="d-title">
                <h2 id="d-title" className="section-title">
                  Dishes that deliver to you
                </h2>
                <ul className="plain-list">
                  {result.dishes.map((d) => {
                    const region = regionFor(d.restaurant.cuisines)
                    const qty = cart.restaurant?.id === d.restaurant.id ? qtyOf(cart, d.id) : 0
                    return (
                      <li key={d.id} className="dish-hit">
                        <DishPicture name={d.name} region={region} size={92} />
                        <div className="dish-hit-text">
                          <div className="dish-marks">
                            <VegMark veg={d.is_veg} />
                            <h3>{d.name}</h3>
                          </div>
                          <Link to={`/r/${d.restaurant.id}`} state={{ card: d.restaurant }} className="muted small">
                            {d.restaurant.name} · {d.restaurant.eta_text}
                          </Link>
                          <div className="row between">
                            <span className="price">{rupees(d.price)}</span>
                            <Stepper
                              qty={qty}
                              name={d.name}
                              accent={REGIONS[region].accent}
                              disabled={qty >= MAX_QTY}
                              onAdd={() =>
                                add(
                                  { id: d.restaurant.id, name: d.restaurant.name, region },
                                  { menuItemId: d.id, name: d.name, price: d.price, isVeg: d.is_veg },
                                )
                              }
                              onRemove={() => remove(d.id)}
                            />
                          </div>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}
          </>
        )}
      </main>
      <CartBar />
      <ReplaceCartDialog open={pending !== null} current={cart.restaurant?.name ?? ''} next={pending?.restaurant.name ?? ''} onConfirm={confirm} onCancel={cancel} />
    </div>
  )
}
