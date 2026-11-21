import { useLocation, useNavigate, useParams } from 'react-router'
import { useMenu, useRestaurant, useReviews } from '../api/queries'
import type { RestaurantCard } from '../api/types'
import { DishPicture } from '../components/DishPicture'
import { ReplaceCartDialog } from '../components/ReplaceCartDialog'
import { CartBar, ErrorBox, Loading, Ornament, RatingBadge, Stepper, VegMark } from '../components/ui'
import { MAX_QTY, qtyOf } from '../cart/cart'
import { useAddToCart } from '../cart/useAddToCart'
import { rupees } from '../lib/money'
import { Drawing, RegionWash } from '../theme/Art'
import { drawingFor, photoFor, SIGNATURE } from '../theme/dishes'
import { REGIONS, regionFor } from '../theme/regions'

const BADGE_TEXT: Record<string, string> = {
  SELLING_FAST: 'Selling fast',
  ONLY_N_LEFT: 'Only a few left',
  SOLD_OUT: 'Sold out',
}

export function RestaurantPage() {
  const { id = '' } = useParams()
  const card = (useLocation().state as { card?: RestaurantCard } | null)?.card
  const restaurant = useRestaurant(id)
  const menu = useMenu(id)
  const reviews = useReviews(id)
  const { cart, add, remove, pending, confirm, cancel } = useAddToCart()
  const navigate = useNavigate()

  if (restaurant.isPending) return <Loading label="Opening the menu" />
  if (restaurant.isError) return <ErrorBox error={restaurant.error} onRetry={() => restaurant.refetch()} />

  const r = restaurant.data
  const region = regionFor(r.cuisines)
  const info = REGIONS[region]
  const hero = SIGNATURE[region]
  const heroPhoto = photoFor(hero)

  return (
    <div className="page restaurant">
      <header className="menu-hero">
        <RegionWash region={region} strength={0.9} />
        <button type="button" className="icon-btn floating" aria-label="Back to restaurants" onClick={() => (history.length > 1 ? navigate(-1) : navigate('/'))}>
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div className="hero-dish">{heroPhoto ? <img src={heroPhoto} alt="" /> : <Drawing id={drawingFor(hero)} size={160} />}</div>
        <div className="cartouche">
          <span className="eyebrow" style={{ color: info.accent }}>
            {region === 'plain' ? r.cuisines.join(' · ') || 'Restaurant' : `${info.craft} · ${info.label}`}
          </span>
          <h1>{r.name}</h1>
        </div>
      </header>

      <div className="menu-meta">
        <p className="meta-line">
          <RatingBadge rating={r.rating} count={r.rating_count} />
          <span className="muted">
            {r.rating_count} review{r.rating_count === 1 ? '' : 's'}
          </span>
          {card && (
            <>
              · {card.eta_text} · {card.distance_km} km
            </>
          )}
        </p>
        <p className="muted">
          {r.address}
          {!r.is_open && ' · Closed right now'}
        </p>
      </div>

      <main className="menu-card">
        <Ornament accent={info.accent}>Menu</Ornament>
        {menu.isPending && <Loading label="Loading dishes" />}
        {menu.isError && <ErrorBox error={menu.error} onRetry={() => menu.refetch()} />}
        {menu.data?.length === 0 && <p className="empty">No dishes are available right now.</p>}
        <ul className="dishes">
          {menu.data?.map((d) => {
            const qty = cart.restaurant?.id === r.id ? qtyOf(cart, d.id) : 0
            const badge = d.badge === 'ONLY_N_LEFT' && d.units_left ? `Only ${d.units_left} left` : d.badge ? BADGE_TEXT[d.badge] : null
            return (
              <li key={d.id} className={`dish ${d.orderable ? '' : 'sold-out'}`}>
                <div className="dish-text">
                  <div className="dish-marks">
                    <VegMark veg={d.is_veg} />
                    {badge && <span className="tag soft">{badge}</span>}
                  </div>
                  <h3>{d.name}</h3>
                  <p className="price">{rupees(d.price)}</p>
                  {d.description && <p className="muted small">{d.description}</p>}
                </div>
                <div className="dish-pic">
                  <DishPicture name={d.name} region={region} size={112} />
                  {d.orderable && r.is_open ? (
                    <Stepper
                      floating
                      qty={qty}
                      name={d.name}
                      accent={info.accent}
                      disabled={qty >= MAX_QTY || (d.units_left !== null && d.units_left !== undefined && qty >= d.units_left)}
                      onAdd={() => add({ id: r.id, name: r.name, region }, { menuItemId: d.id, name: d.name, price: d.price, isVeg: d.is_veg })}
                      onRemove={() => remove(d.id)}
                    />
                  ) : (
                    <span className="stepper floating disabled">{r.is_open ? 'Sold out' : 'Closed'}</span>
                  )}
                </div>
              </li>
            )
          })}
        </ul>

        {reviews.data && reviews.data.rating_count > 0 && (
          <section aria-labelledby="reviews-title" className="reviews">
            <Ornament accent={info.accent}>
              <span id="reviews-title">What people say</span>
            </Ornament>
            <ul className="plain-list">
              {reviews.data.reviews.map((rv) => (
                <li key={rv.id} className="review">
                  <span className="stars" aria-label={`${rv.rating} out of 5`}>
                    {'★'.repeat(rv.rating)}
                    <span aria-hidden="true" className="dim">
                      {'★'.repeat(5 - rv.rating)}
                    </span>
                  </span>
                  <strong>{rv.reviewer}</strong>
                  {rv.comment && <p>{rv.comment}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>
      <CartBar />
      <ReplaceCartDialog
        open={pending !== null}
        current={cart.restaurant?.name ?? ''}
        next={pending?.restaurant.name ?? ''}
        onConfirm={confirm}
        onCancel={cancel}
      />
    </div>
  )
}
