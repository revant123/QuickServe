import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, unwrap, type Schemas } from '../api/client'
import { useManagedMenu, useRestockSuggestion } from '../api/partner'
import { ErrorBox, Loading, VegMark } from '../components/ui'
import { rupees } from '../lib/money'
import { clock } from '../lib/time'
import { useCurrentRestaurant } from './PartnerApp'

type Item = Schemas['MenuItemOut']

/** When a switched-off dish comes back by itself (Zomato's "out of stock until"). */
function untilOptions(now = new Date()): { label: string; until: string | null }[] {
  const inTwoHours = new Date(now.getTime() + 2 * 3600_000)
  const tomorrow9 = new Date(now)
  tomorrow9.setDate(now.getDate() + 1)
  tomorrow9.setHours(9, 0, 0, 0)
  return [
    { label: 'For 2 hours', until: inTwoHours.toISOString() },
    { label: 'Until 9 am tomorrow', until: tomorrow9.toISOString() },
    { label: 'Until I switch it back on', until: null },
  ]
}

export function MenuManager() {
  const restaurant = useCurrentRestaurant()
  const menu = useManagedMenu(restaurant.id)
  const [restocking, setRestocking] = useState<Item | null>(null)

  if (menu.isPending) return <Loading label="Loading the menu" />
  if (menu.isError) return <ErrorBox error={menu.error} onRetry={() => menu.refetch()} />

  return (
    <main className="stack">
      <p className="muted small">
        Stock counts what you've prepared this cycle. A restock closes the cycle and keeps its numbers, so best sellers and restock suggestions get better over time.
      </p>
      <ul className="plain-list" aria-label="Dishes">
        {menu.data.map((item) => (
          <li key={item.id}>
            <MenuRow item={item} onRestock={() => setRestocking(item)} />
          </li>
        ))}
      </ul>
      <RestockDialog item={restocking} onClose={() => setRestocking(null)} />
    </main>
  )
}

function useMenuUpdate() {
  const restaurant = useCurrentRestaurant()
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ['partner', 'menu', restaurant.id] })
    // The customer menu is cached for everyone; the API clears its own cache,
    // this clears the copy in this browser.
    queryClient.invalidateQueries({ queryKey: ['public', 'menu', restaurant.id] })
  }
}

function MenuRow({ item, onRestock }: { item: Item; onRestock: () => void }) {
  const refresh = useMenuUpdate()
  const [choosing, setChoosing] = useState(false)
  const availability = useMutation({
    mutationFn: async (body: { is_available: boolean; unavailable_until: string | null }) =>
      unwrap(await api.PATCH('/api/v1/menu/{menu_item_id}/availability', { params: { path: { menu_item_id: item.id } }, body })),
    onSuccess: () => {
      setChoosing(false)
      refresh()
    },
  })

  const offUntil = !item.is_available && item.unavailable_until ? ` until ${clock(item.unavailable_until)}` : ''
  const soldOut = item.track_stock && item.available === 0

  return (
    <article className="menu-admin-row" aria-labelledby={`m-${item.id}`}>
      <div className="row nowrap between">
        <div className="grow">
          <h2 id={`m-${item.id}`} className="dish-name">
            <VegMark veg={item.is_veg} /> {item.name}
          </h2>
          <p className="muted small">
            {rupees(item.price)} ·{' '}
            {item.track_stock ? (
              <>
                <strong className={soldOut ? 'text-danger' : ''}>{item.available} left</strong> of {item.stock} · cycle {item.cycle_no}
              </>
            ) : (
              'stock not tracked'
            )}
          </p>
        </div>
        <button
          type="button"
          className={`switch small ${item.is_available ? 'on' : ''}`}
          aria-pressed={item.is_available}
          aria-label={`${item.name}: ${item.is_available ? 'on the menu' : `switched off${offUntil}`}`}
          onClick={() => (item.is_available ? setChoosing((c) => !c) : availability.mutate({ is_available: true, unavailable_until: null }))}
          disabled={availability.isPending}
        >
          <span className="switch-knob" aria-hidden="true" />
          {item.is_available ? 'On' : `Off${offUntil}`}
        </button>
      </div>
      {choosing && (
        <div className="row" role="group" aria-label={`Switch off ${item.name}`}>
          {untilOptions().map((o) => (
            <button key={o.label} type="button" className="chip" onClick={() => availability.mutate({ is_available: false, unavailable_until: o.until })}>
              {o.label}
            </button>
          ))}
        </div>
      )}
      {availability.isError && <ErrorBox error={availability.error} />}
      {item.track_stock && (
        <button type="button" className="btn ghost" onClick={onRestock}>
          Restock
        </button>
      )}
    </article>
  )
}

function RestockDialog({ item, onClose }: { item: Item | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const refresh = useMenuUpdate()
  const suggestion = useRestockSuggestion(item?.id ?? null)
  const [quantity, setQuantity] = useState('')
  const [carryOver, setCarryOver] = useState(false)

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (item && !d.open) {
      setQuantity('')
      setCarryOver(false)
      d.showModal?.()
    }
    if (!item && d.open) d.close()
  }, [item])

  const restock = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/api/v1/menu/{menu_item_id}/restock', {
          params: { path: { menu_item_id: item!.id } },
          body: { quantity: Number(quantity), carry_over_leftover: carryOver },
        }),
      ),
    onSuccess: () => {
      refresh()
      onClose()
    },
  })

  const suggested = suggestion.data?.suggested_quantity
  function submit(e: FormEvent) {
    e.preventDefault()
    restock.mutate()
  }

  return (
    <dialog ref={ref} className="sheet" aria-labelledby="restock-title" onCancel={onClose}>
      <form className="form" onSubmit={submit}>
        <h2 id="restock-title">Restock {item?.name}</h2>
        {suggestion.isPending ? (
          <p className="muted small">Working out a suggestion…</p>
        ) : suggested != null ? (
          <div className="notice small">
            <p>
              Suggested: <strong>{suggested}</strong>
            </p>
            <ul>
              {suggestion.data?.explanation.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="muted small">Not enough history for a suggestion yet.</p>
        )}
        <label htmlFor="restock-qty">Units prepared for the new cycle</label>
        <input id="restock-qty" type="number" inputMode="numeric" min={0} max={10000} value={quantity} onChange={(e) => setQuantity(e.target.value)} required />
        {suggested != null && quantity === '' && (
          <button type="button" className="link-btn small" onClick={() => setQuantity(String(suggested))}>
            Use {suggested}
          </button>
        )}
        <label className="check">
          <input type="checkbox" checked={carryOver} onChange={(e) => setCarryOver(e.target.checked)} /> Add the {item?.available ?? 0} unsold units (packaged items only)
        </label>
        {restock.isError && <ErrorBox error={restock.error} />}
        <div className="row">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn" disabled={restock.isPending || quantity === ''}>
            Start new cycle
          </button>
        </div>
      </form>
    </dialog>
  )
}
