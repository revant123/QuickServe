import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { api, ApiError, unwrap } from '../api/client'
import { useOrder, useTimeline } from '../api/queries'
import type { OrderStatus } from '../api/types'
import { ErrorBox, Loading, TopBar } from '../components/ui'
import { rupees } from '../lib/money'
import { STATUS_LABEL } from '../lib/status'

const STEPS: { status: OrderStatus; label: string }[] = [
  { status: 'PLACED', label: 'Order placed' },
  { status: 'PAID', label: 'Paid' },
  { status: 'ACCEPTED', label: 'Restaurant accepted' },
  { status: 'PREPARING', label: 'Being cooked' },
  { status: 'READY', label: 'Packed' },
  { status: 'OUT_FOR_DELIVERY', label: 'On the way' },
  { status: 'DELIVERED', label: 'Delivered' },
]

const ENDED: Partial<Record<OrderStatus, string>> = {
  CANCELLED: 'This order was cancelled.',
  REJECTED: 'The restaurant could not take this order. Any payment is refunded.',
  PAYMENT_FAILED: 'This order was not paid in time, so it was cancelled.',
}


export function OrderPage() {
  const { id = '' } = useParams()
  const order = useOrder(id)
  const timeline = useTimeline(id, order.data?.status)
  const queryClient = useQueryClient()

  // One Idempotency-Key per payment ATTEMPT (Phase 4): a double tap or a retry
  // after a network error reuses it, so the server charges once. After a real
  // answer (paid or declined) it's dropped, so "try again" is a new attempt.
  const attemptKey = useRef<string | null>(null)
  const pay = useMutation({
    mutationFn: async (outcome: 'success' | 'failure') => {
      attemptKey.current ??= crypto.randomUUID()
      return unwrap(
        await api.POST('/api/v1/orders/{order_id}/payments', {
          params: { path: { order_id: id }, query: { simulate: outcome }, header: { 'Idempotency-Key': attemptKey.current } },
        }),
      )
    },
    onSettled: (_data, error) => {
      if (!(error instanceof TypeError)) attemptKey.current = null // TypeError = network failure: keep the key and retry safely
      queryClient.invalidateQueries({ queryKey: ['order', id] })
    },
  })

  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/v1/orders/{order_id}/cancel', { params: { path: { order_id: id } }, body: { reason: 'Cancelled by the customer in the app' } })),
    onSuccess: (o) => {
      queryClient.setQueryData(['order', id], o)
      queryClient.invalidateQueries({ queryKey: ['orders'] })
    },
  })

  if (order.isPending) return <Loading label="Loading your order" />
  if (order.isError) return <ErrorBox error={order.error} onRetry={() => order.refetch()} />

  const o = order.data
  const reached = STEPS.findIndex((s) => s.status === o.status)
  const ended = ENDED[o.status]
  const lastPayment = pay.data

  return (
    <div className="page order">
      <TopBar title="Your order" />
      <main className="stack">
        <section className="panel">
          <div className="panel-body">
            <p className="eyebrow">{STATUS_LABEL[o.status]}</p>
            <h2 className="section-title">Order #{o.id.slice(0, 8)}</h2>
            <Link to={`/r/${o.restaurant_id}`} className="small">
              View the restaurant
            </Link>
            {ended ? (
              <p className="notice">{ended}</p>
            ) : (
              <ol className="steps" aria-label="Order progress">
                {STEPS.map((s, i) => (
                  <li key={s.status} className={i < reached ? 'done' : i === reached ? 'now' : ''} aria-current={i === reached ? 'step' : undefined}>
                    {s.label}
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>

        {o.status === 'PLACED' && (
          <section className="panel" aria-labelledby="pay-title">
            <div className="panel-body">
              <h2 id="pay-title" className="section-title">
                Pay {rupees(o.grand_total)}
              </h2>
              <p className="muted small">
                Payments are simulated (Phase 4). Pay by {new Date(o.pay_by).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}, or the
                order is cancelled and the dishes go back on sale.
              </p>
              {lastPayment?.status === 'FAILED' && (
                <p className="form-error" role="alert">
                  Payment declined{lastPayment.failure_reason ? `: ${lastPayment.failure_reason}` : ''}. You can try again.
                </p>
              )}
              {pay.isError && <ErrorBox error={pay.error} />}
              <div className="row">
                <button type="button" className="btn" onClick={() => pay.mutate('success')} disabled={pay.isPending}>
                  {pay.isPending ? 'Paying…' : `Pay ${rupees(o.grand_total)}`}
                </button>
                <button type="button" className="btn ghost" onClick={() => pay.mutate('failure')} disabled={pay.isPending}>
                  Try a declined card
                </button>
              </div>
            </div>
          </section>
        )}

        <section className="panel" aria-labelledby="items-title">
          <div className="panel-body">
            <h2 id="items-title" className="section-title">
              Bill
            </h2>
            <dl className="bill-lines">
              {o.items.map((it) => (
                <div key={it.menu_item_id}>
                  <dt>
                    {it.item_name} × {it.quantity}
                  </dt>
                  <dd>{rupees(it.line_total)}</dd>
                </div>
              ))}
              <BillRow label="Packaging" amount={o.packaging_charge} />
              <BillRow label="Delivery fee" amount={o.delivery_fee} />
              <BillRow label="Small order fee" amount={o.small_order_fee} />
              <BillRow label={`Surge${o.surge_reasons ? ` (${o.surge_reasons.replace(',', ', ')})` : ''}`} amount={o.surge_fee} />
              <BillRow label="Platform fee" amount={o.platform_fee} />
              <BillRow label={`Discount${o.coupon_code ? ` (${o.coupon_code})` : ''}`} amount={o.discount} negative />
              <BillRow label="GST on food" amount={o.gst_food} />
              <BillRow label="GST on fees" amount={o.gst_fees} />
              <div className="total">
                <dt>Total</dt>
                <dd>{rupees(o.grand_total)}</dd>
              </div>
            </dl>
            <p className="muted small">Deliver to: {o.delivery_address}</p>
          </div>
        </section>

        {(o.status === 'PLACED' || o.status === 'PAID') && (
          <button type="button" className="btn ghost danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            {cancel.isPending ? 'Cancelling…' : o.status === 'PAID' ? 'Cancel order (full refund)' : 'Cancel order'}
          </button>
        )}
        {cancel.isError && <ErrorBox error={cancel.error} />}

        {o.status === 'DELIVERED' && <ReviewForm orderId={o.id} restaurantId={o.restaurant_id} />}

        {timeline.data && timeline.data.length > 0 && (
          <details className="panel">
            <summary className="panel-body">Timeline</summary>
            <ul className="plain-list timeline">
              {timeline.data.map((ev) => (
                <li key={`${ev.to_status}-${ev.created_at}`}>
                  <time dateTime={ev.created_at}>{new Date(ev.created_at).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}</time>{' '}
                  {STATUS_LABEL[ev.to_status]} <span className="muted small">({ev.actor})</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </main>
    </div>
  )
}

function BillRow({ label, amount, negative }: { label: string; amount: string; negative?: boolean }) {
  if (Number(amount) === 0) return null
  return (
    <div className={negative ? 'discount' : ''}>
      <dt>{label}</dt>
      <dd>
        {negative ? '−' : ''}
        {rupees(amount)}
      </dd>
    </div>
  )
}

function ReviewForm({ orderId, restaurantId }: { orderId: string; restaurantId: string }) {
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState('')
  const queryClient = useQueryClient()
  const review = useMutation({
    mutationFn: async () => unwrap(await api.POST('/api/v1/orders/{order_id}/review', { params: { path: { order_id: orderId } }, body: { rating, comment } })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['public', 'reviews', restaurantId] })
      queryClient.invalidateQueries({ queryKey: ['public', 'restaurant', restaurantId] })
    },
  })
  const already = review.error instanceof ApiError && review.error.status === 409

  if (review.isSuccess || already) {
    return (
      <section className="panel">
        <div className="panel-body">
          <p className="notice">{already ? 'You have already rated this order. Thank you!' : 'Thanks for rating your order!'}</p>
        </div>
      </section>
    )
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (rating > 0) review.mutate()
  }

  return (
    <section className="panel" aria-labelledby="rate-title">
      <form className="panel-body" onSubmit={submit}>
        <h2 id="rate-title" className="section-title">
          How was it?
        </h2>
        <fieldset className="star-input">
          <legend className="visually-hidden">Rating</legend>
          {[1, 2, 3, 4, 5].map((n) => (
            <label key={n} className={n <= rating ? 'on' : ''}>
              <input type="radio" name="rating" value={n} checked={rating === n} onChange={() => setRating(n)} />
              <span aria-hidden="true">★</span>
              <span className="visually-hidden">
                {n} star{n === 1 ? '' : 's'}
              </span>
            </label>
          ))}
        </fieldset>
        <label htmlFor="comment" className="visually-hidden">
          Comment
        </label>
        <textarea id="comment" rows={2} maxLength={500} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="What did you like? (optional)" />
        {review.isError && !already && <ErrorBox error={review.error} />}
        <button type="submit" className="btn" disabled={rating === 0 || review.isPending}>
          {review.isPending ? 'Sending…' : 'Submit rating'}
        </button>
      </form>
    </section>
  )
}
