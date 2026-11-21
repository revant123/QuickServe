import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, unwrap, type Schemas } from '../api/client'
import { useBoard } from '../api/partner'
import type { OrderStatus } from '../api/types'
import { ErrorBox, Loading } from '../components/ui'
import { rupees } from '../lib/money'
import { STATUS_LABEL } from '../lib/status'
import { ago, countdown, secondsLeft, useNow } from '../lib/time'
import { useCurrentRestaurant } from './PartnerApp'

type Ticket = Schemas['KitchenOrder']
type Tab = 'new' | 'preparing' | 'ready' | 'past'

const TABS: { id: Tab; label: string; statuses: OrderStatus[] }[] = [
  { id: 'new', label: 'New', statuses: ['PAID'] },
  { id: 'preparing', label: 'Preparing', statuses: ['ACCEPTED', 'PREPARING'] },
  { id: 'ready', label: 'Ready', statuses: ['READY'] },
  { id: 'past', label: 'Past', statuses: [] },
]

// What the kitchen does next, per status. The API decides whether it's allowed.
const NEXT: Partial<Record<OrderStatus, { to: OrderStatus; label: string }>> = {
  ACCEPTED: { to: 'PREPARING', label: 'Start preparing' },
  PREPARING: { to: 'READY', label: 'Mark ready for pickup' },
}

const REJECT_REASONS = ['An item is out of stock', 'Kitchen is closing', 'Too busy right now']

export function OrdersBoard() {
  const restaurant = useCurrentRestaurant()
  const [tab, setTab] = useState<Tab>('new')
  const active = useBoard(restaurant.id, 'active')
  const past = useBoard(restaurant.id, 'recent', tab === 'past')
  const now = useNow(1000)
  const [rejecting, setRejecting] = useState<Ticket | null>(null)

  const tickets = active.data ?? []
  const count = (t: Tab) => tickets.filter((o) => TABS.find((x) => x.id === t)!.statuses.includes(o.status)).length
  const newCount = count('new')

  // A busy kitchen keeps this screen open in a tab: the title shows waiting orders.
  useEffect(() => {
    const before = document.title
    document.title = newCount > 0 ? `(${newCount}) New order${newCount === 1 ? '' : 's'} · QuickServe Partner` : 'QuickServe Partner'
    return () => {
      document.title = before
    }
  }, [newCount])

  const shown = tab === 'past' ? (past.data ?? []) : tickets.filter((o) => TABS.find((x) => x.id === tab)!.statuses.includes(o.status))
  const query = tab === 'past' ? past : active

  return (
    <main className="stack">
      <div className="tabs" role="tablist" aria-label="Orders">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className="tab" onClick={() => setTab(t.id)}>
            {t.label}
            {t.id !== 'past' && count(t.id) > 0 && <span className={`badge ${t.id === 'new' ? 'hot' : ''}`}>{count(t.id)}</span>}
          </button>
        ))}
      </div>

      {!restaurant.is_open && <p className="notice">You're not accepting new orders. Orders already placed still need finishing.</p>}

      {query.isPending ? (
        <Loading label="Loading orders" />
      ) : query.isError ? (
        <ErrorBox error={query.error} onRetry={() => query.refetch()} />
      ) : shown.length === 0 ? (
        <p className="empty">{tab === 'new' ? 'No new orders. New ones appear here within 10 seconds.' : 'Nothing here.'}</p>
      ) : (
        <ul className="plain-list" aria-label={`${TABS.find((t) => t.id === tab)!.label} orders`}>
          {shown.map((o) => (
            <li key={o.id}>
              <TicketCard ticket={o} now={now} onReject={() => setRejecting(o)} />
            </li>
          ))}
        </ul>
      )}
      <RejectDialog ticket={rejecting} onClose={() => setRejecting(null)} />
    </main>
  )
}

function useStatusChange(restaurantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, status, note }: { id: string; status: OrderStatus; note?: string }) =>
      unwrap(await api.PATCH('/api/v1/orders/{order_id}/status', { params: { path: { order_id: id } }, body: { status, note } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['partner', 'board', restaurantId] }),
  })
}

function TicketCard({ ticket: o, now, onReject }: { ticket: Ticket; now: number; onReject: () => void }) {
  const restaurant = useCurrentRestaurant()
  const change = useStatusChange(restaurant.id)
  const next = NEXT[o.status]
  const left = o.accept_by ? secondsLeft(o.accept_by, now) : null

  return (
    <article className={`ticket ${o.status === 'PAID' ? 'ticket-new' : ''}`} aria-labelledby={`t-${o.id}`}>
      <header className="ticket-head">
        <h2 id={`t-${o.id}`} className="ticket-id">
          #{o.short_id}
        </h2>
        <span className="muted small">
          {o.customer_first_name} · {ago(o.created_at, now)}
        </span>
        <span className="status-chip">{STATUS_LABEL[o.status]}</span>
      </header>
      <ul className="ticket-items">
        {o.items.map((it) => (
          <li key={it.name}>
            <strong>{it.quantity} ×</strong> {it.name}
          </li>
        ))}
      </ul>
      <p className="row between small">
        <span className="muted">Items {rupees(o.item_total)} + packing {rupees(o.packaging_charge)}</span>
        <strong>{rupees(Number(o.item_total) + Number(o.packaging_charge))}</strong>
      </p>

      {o.status === 'PAID' && left !== null && (
        <p className={`accept-timer ${left <= 60 ? 'urgent' : ''}`} role="timer" aria-live={left <= 60 ? 'polite' : 'off'}>
          {left > 0 ? `Accept within ${countdown(o.accept_by!, now)}, or it's rejected and refunded automatically` : 'Time is up: this order is being rejected'}
        </p>
      )}
      {o.status === 'READY' && <p className="muted small">{o.rider_name ? `${o.rider_name} is picking it up` : 'Waiting for a delivery partner'}</p>}
      {(o.status === 'ACCEPTED' || o.status === 'PREPARING') && o.rider_name && <p className="muted small">{o.rider_name} is on the way</p>}
      {o.cancel_reason && <p className="muted small">Reason: {o.cancel_reason}</p>}
      {change.isError && <ErrorBox error={change.error} />}

      {o.status === 'PAID' && (
        <div className="row">
          <button type="button" className="btn ghost danger" onClick={onReject} disabled={change.isPending}>
            Reject
          </button>
          <button type="button" className="btn grow" onClick={() => change.mutate({ id: o.id, status: 'ACCEPTED' })} disabled={change.isPending || (left !== null && left <= 0)}>
            {change.isPending ? 'Accepting…' : 'Accept'}
          </button>
        </div>
      )}
      {next && (
        <button type="button" className="btn" onClick={() => change.mutate({ id: o.id, status: next.to })} disabled={change.isPending}>
          {change.isPending ? 'Saving…' : next.label}
        </button>
      )}
    </article>
  )
}

function RejectDialog({ ticket, onClose }: { ticket: Ticket | null; onClose: () => void }) {
  const restaurant = useCurrentRestaurant()
  const change = useStatusChange(restaurant.id)
  const ref = useRef<HTMLDialogElement>(null)
  const [reason, setReason] = useState(REJECT_REASONS[0]!)

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (ticket && !d.open) d.showModal?.()
    if (!ticket && d.open) d.close()
  }, [ticket])

  return (
    <dialog ref={ref} className="sheet" aria-labelledby="reject-title" onCancel={onClose}>
      <h2 id="reject-title">Reject order #{ticket?.short_id}?</h2>
      <p className="muted small">The customer is refunded in full and told the reason.</p>
      <fieldset className="reasons">
        <legend className="small">Reason</legend>
        {REJECT_REASONS.map((r) => (
          <label key={r}>
            <input type="radio" name="reject-reason" value={r} checked={reason === r} onChange={() => setReason(r)} /> {r}
          </label>
        ))}
      </fieldset>
      {change.isError && <ErrorBox error={change.error} />}
      <div className="row">
        <button type="button" className="btn ghost" onClick={onClose}>
          Keep it
        </button>
        <button
          type="button"
          className="btn danger"
          disabled={change.isPending || !ticket}
          onClick={() => ticket && change.mutate({ id: ticket.id, status: 'REJECTED', note: reason }, { onSuccess: onClose })}
        >
          Reject order
        </button>
      </div>
    </dialog>
  )
}
