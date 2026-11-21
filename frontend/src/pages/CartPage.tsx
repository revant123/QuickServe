import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, ApiError, unwrap, type Schemas } from '../api/client'
import { useCoupons } from '../api/queries'
import { useAuth } from '../auth/AuthProvider'
import { useCart } from '../cart/CartProvider'
import { estimatedItemTotal, MAX_QTY, type CartState } from '../cart/cart'
import { ErrorBox, Loading, Stepper, TopBar, VegMark } from '../components/ui'
import { useLocationPlace, type Place } from '../location/location'
import { rupees } from '../lib/money'
import { RegionStrip } from '../theme/Art'
import { REGIONS } from '../theme/regions'

const ADDRESS_KEY = 'qs.address'

function orderBody(cart: CartState, place: Place, address: string, coupon: string): Schemas['OrderCreate'] {
  return {
    restaurant_id: cart.restaurant!.id,
    delivery_address: address.trim(),
    delivery_location: { lat: place.lat, lng: place.lng },
    items: cart.lines.map((l) => ({ menu_item_id: l.menuItemId, quantity: l.qty })),
    coupon_code: coupon.trim() || null,
  }
}

export function CartPage() {
  const { cart, dispatch } = useCart()
  const { loggedIn } = useAuth()
  const { place } = useLocationPlace()
  const [address, setAddress] = useState(() => localStorage.getItem(ADDRESS_KEY) ?? '')
  const [couponText, setCouponText] = useState('')
  const [coupon, setCoupon] = useState('')
  const [priceNotice, setPriceNotice] = useState<string | null>(null)
  const coupons = useCoupons(cart.restaurant?.id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  useEffect(() => {
    try {
      localStorage.setItem(ADDRESS_KEY, address)
    } catch {
      /* fine */
    }
  }, [address])

  // The bill comes from the server: POST /orders/quote prices the cart right
  // now (fees, surge, GST, coupon), and reserves nothing.
  const quote = useQuery({
    queryKey: ['quote', cart.restaurant?.id, cart.lines.map((l) => [l.menuItemId, l.qty]), coupon, place.lat, place.lng],
    queryFn: async () =>
      unwrap(await api.POST('/api/v1/orders/quote', { body: orderBody(cart, place, address || 'quote', coupon) })),
    enabled: loggedIn && cart.lines.length > 0,
    staleTime: 30_000,
    retry: false,
  })

  const placeOrder = useMutation({
    mutationFn: async () => {
      // A coupon the quote refused (say WELCOME50 on a second order) isn't in
      // the quoted total, so it isn't sent either: the order matches the bill shown.
      const usable = quote.data!.coupon_error ? '' : coupon
      const body = { ...orderBody(cart, place, address, usable), expected_total: quote.data!.grand_total }
      return unwrap(await api.POST('/api/v1/orders', { body }))
    },
    onSuccess: (order) => {
      dispatch({ type: 'clear' })
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.setQueryData(['order', order.id], order)
      navigate(`/orders/${order.id}`, { replace: true })
    },
    onError: (e) => {
      // 409 PriceChanged: the bill moved between the quote and the tap (surge
      // started, a coupon ran out). Show the new total; never charge it silently.
      if (e instanceof ApiError && e.status === 409) {
        const newTotal = (e.body as { new_grand_total?: string } | undefined)?.new_grand_total
        setPriceNotice(newTotal ? `The price changed to ${rupees(newTotal)}. Please check the new bill.` : e.message)
        queryClient.invalidateQueries({ queryKey: ['quote'] })
      }
    },
  })

  if (cart.lines.length === 0 || !cart.restaurant) {
    return (
      <div className="page">
        <TopBar title="Cart" />
        <main className="stack center">
          <p className="empty">Your cart is empty.</p>
          <Link to="/" className="btn">
            Find something to eat
          </Link>
        </main>
      </div>
    )
  }

  const accent = REGIONS[cart.restaurant.region].accent
  const canOrder = loggedIn && quote.isSuccess && address.trim().length >= 5 && !placeOrder.isPending

  return (
    <div className="page cart">
      <TopBar title="Cart" />
      <main className="stack two-col">
        {/* On a wide screen: the cart on the left, the bill beside it. On a
            phone both wrappers are display: contents, so it's one column. */}
        <div className="col-main">
          <section className="panel">
            <RegionStrip region={cart.restaurant.region} height={10} />
            <div className="panel-body">
              <Link to={`/r/${cart.restaurant.id}`}>
                <h2 className="section-title">{cart.restaurant.name}</h2>
              </Link>
              <ul className="plain-list">
                {cart.lines.map((l) => (
                  <li key={l.menuItemId} className="cart-line">
                    <VegMark veg={l.isVeg} />
                    <span className="grow">{l.name}</span>
                    <Stepper
                      qty={l.qty}
                      name={l.name}
                      accent={accent}
                      disabled={l.qty >= MAX_QTY}
                      onAdd={() => dispatch({ type: 'add', restaurant: cart.restaurant!, item: l })}
                      onRemove={() => dispatch({ type: 'remove', menuItemId: l.menuItemId })}
                    />
                    <span className="amount">{rupees(Number(l.price) * l.qty)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="panel">
            <div className="panel-body">
              <label htmlFor="address" className="section-title">
                Delivery address
              </label>
              <p className="muted small">Delivering to the pin for {place.label}. Add the house number and landmark.</p>
              <textarea
                id="address"
                rows={2}
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="House 12, Sector 22-B, near the gurdwara"
                maxLength={500}
              />
            </div>
          </section>

          <section className="panel">
            <form
              className="panel-body"
              onSubmit={(e) => {
                e.preventDefault()
                setCoupon(couponText.trim().toUpperCase())
              }}
            >
              <label htmlFor="coupon" className="section-title">
                Coupon
              </label>
              <div className="row nowrap">
                <input id="coupon" value={couponText} onChange={(e) => setCouponText(e.target.value)} placeholder="WELCOME50" maxLength={30} autoCapitalize="characters" />
                <button type="submit" className="btn ghost">
                  Apply
                </button>
              </div>
              {coupons.data && coupons.data.length > 0 && (
                <div className="chips">
                  {coupons.data.map((c) => (
                    <button
                      key={c.code}
                      type="button"
                      className="chip"
                      aria-pressed={coupon === c.code}
                      onClick={() => {
                        setCouponText(c.code)
                        setCoupon(c.code)
                      }}
                      title={c.description}
                    >
                      {c.code}
                    </button>
                  ))}
                </div>
              )}
            </form>
          </section>
        </div>

        <div className="col-side">
          <section className="panel bill" aria-labelledby="bill-title">
            <div className="panel-body">
              <h2 id="bill-title" className="section-title">
                Bill
              </h2>
              {!loggedIn && (
                <>
                  <p>
                    Dishes: <strong>{rupees(estimatedItemTotal(cart))}</strong>
                  </p>
                  <p className="muted small">Fees, taxes and coupons are worked out by the server once you log in.</p>
                  <Link to="/login?next=/cart" className="btn">
                    Log in to see the bill
                  </Link>
                </>
              )}
              {loggedIn && quote.isPending && <Loading label="Working out your bill" />}
              {loggedIn && quote.isError && <ErrorBox error={quote.error} onRetry={() => quote.refetch()} />}
              {quote.data && (
                <>
                  {quote.data.coupon_error && (
                    <div className="notice row between" role="alert">
                      <span>
                        <strong>{coupon}</strong> can't be used: {quote.data.coupon_error}
                      </span>
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={() => {
                          setCoupon('')
                          setCouponText('')
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  )}
                  <dl className="bill-lines">
                    {quote.data.lines.map((line) => (
                      <div key={line.key} className={Number(line.amount) < 0 ? 'discount' : ''}>
                        <dt>
                          {line.label}
                          {line.note && <span className="muted small"> · {line.note}</span>}
                        </dt>
                        <dd>{rupees(line.amount)}</dd>
                      </div>
                    ))}
                    <div className="total">
                      <dt>To pay</dt>
                      <dd>{rupees(quote.data.grand_total)}</dd>
                    </div>
                  </dl>
                </>
              )}
              {priceNotice && (
                <p className="notice" role="alert">
                  {priceNotice}
                </p>
              )}
              {placeOrder.isError && !(placeOrder.error instanceof ApiError && placeOrder.error.status === 409) && (
                <ErrorBox error={placeOrder.error} />
              )}
            </div>
          </section>
        </div>
      </main>
      {loggedIn && (
        <div className="cart-bar">
          <RegionStrip region="plain" height={8} />
          <button
            type="button"
            onClick={() => {
              setPriceNotice(null)
              placeOrder.mutate()
            }}
            disabled={!canOrder}
          >
            <span>{address.trim().length < 5 ? 'Add your address to order' : placeOrder.isPending ? 'Placing your order…' : 'Place order'}</span>
            <span className="cart-bar-cta">{quote.data ? rupees(quote.data.grand_total) : ''}</span>
          </button>
        </div>
      )}
    </div>
  )
}
