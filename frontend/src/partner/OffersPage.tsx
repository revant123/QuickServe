import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, unwrap, type Schemas } from '../api/client'
import { useOffers } from '../api/partner'
import { ErrorBox, Loading } from '../components/ui'
import { rupees } from '../lib/money'
import { useCurrentRestaurant } from './PartnerApp'

type Kind = Schemas['CouponKind']

export function OffersPage() {
  const restaurant = useCurrentRestaurant()
  const offers = useOffers(restaurant.id)

  return (
    <main className="stack offers">
      <p className="muted small">
        Offers you create here are <strong>funded by you</strong>: the discount comes out of your payout, as on Zomato and Swiggy. Platform offers (like WELCOME50)
        are paid for by QuickServe.
      </p>
      {offers.isPending ? (
        <Loading />
      ) : offers.isError ? (
        <ErrorBox error={offers.error} onRetry={() => offers.refetch()} />
      ) : (
        <ul className="plain-list" aria-label="Live offers">
          {offers.data.map((c) => (
            <li key={c.code} className="offer-card">
              <strong className="coupon-code">{c.code}</strong>
              <span>{c.description}</span>
              <span className="muted small">
                {c.kind === 'PERCENT' ? `${Number(c.value)}% off${c.max_discount ? ` up to ${rupees(c.max_discount)}` : ''}` : `${rupees(c.value)} off`}
                {Number(c.min_order_value) > 0 ? ` · orders over ${rupees(c.min_order_value)}` : ''}
                {' · '}
                {c.funded_by === 'RESTAURANT' ? 'funded by you' : 'funded by QuickServe'}
              </span>
            </li>
          ))}
          {offers.data.length === 0 && <p className="empty">No live offers.</p>}
        </ul>
      )}
      <NewOffer />
    </main>
  )
}

function NewOffer() {
  const restaurant = useCurrentRestaurant()
  const queryClient = useQueryClient()
  const [code, setCode] = useState('')
  const [kind, setKind] = useState<Kind>('FLAT')
  const [value, setValue] = useState('')
  const [maxDiscount, setMaxDiscount] = useState('')
  const [minOrder, setMinOrder] = useState('')

  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/api/v1/coupons', {
          body: {
            code: code.trim().toUpperCase(),
            description: kind === 'PERCENT' ? `${value}% off at ${restaurant.name}` : `Rs ${value} off at ${restaurant.name}`,
            kind,
            value,
            max_discount: kind === 'PERCENT' && maxDiscount ? maxDiscount : null,
            min_order_value: minOrder || '0',
            restaurant_id: restaurant.id,
            max_uses_per_user: 1,
            first_order_only: false,
          },
        }),
      ),
    onSuccess: () => {
      setCode('')
      setValue('')
      setMaxDiscount('')
      setMinOrder('')
      queryClient.invalidateQueries({ queryKey: ['partner', 'offers', restaurant.id] })
      queryClient.invalidateQueries({ queryKey: ['public', 'coupons', restaurant.id] })
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    create.mutate()
  }

  return (
    <form className="panel panel-body form" onSubmit={submit} aria-labelledby="new-offer-title">
      <h2 id="new-offer-title" className="section-title">
        New offer
      </h2>
      <label htmlFor="offer-code">Code</label>
      <input id="offer-code" value={code} onChange={(e) => setCode(e.target.value)} pattern="[A-Za-z0-9]{3,30}" placeholder="DHABA50" required autoCapitalize="characters" />
      <fieldset className="row">
        <legend className="small">Type</legend>
        <label className="check">
          <input type="radio" name="kind" checked={kind === 'FLAT'} onChange={() => setKind('FLAT')} /> Flat amount
        </label>
        <label className="check">
          <input type="radio" name="kind" checked={kind === 'PERCENT'} onChange={() => setKind('PERCENT')} /> Percent
        </label>
      </fieldset>
      <label htmlFor="offer-value">{kind === 'PERCENT' ? 'Percent off' : 'Rupees off'}</label>
      <input id="offer-value" type="number" inputMode="decimal" min={1} max={kind === 'PERCENT' ? 100 : 10000} step="1" value={value} onChange={(e) => setValue(e.target.value)} required />
      {kind === 'PERCENT' && (
        <>
          <label htmlFor="offer-cap">Maximum discount (Rs, optional)</label>
          <input id="offer-cap" type="number" inputMode="decimal" min={1} step="1" value={maxDiscount} onChange={(e) => setMaxDiscount(e.target.value)} />
        </>
      )}
      <label htmlFor="offer-min">Minimum order (Rs)</label>
      <input id="offer-min" type="number" inputMode="decimal" min={0} step="1" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} />
      {create.isError && <ErrorBox error={create.error} />}
      <button type="submit" className="btn" disabled={create.isPending || !code || !value}>
        {create.isPending ? 'Creating…' : 'Create offer'}
      </button>
      <p className="muted small">One use per customer. GST on the food is worked out after the discount.</p>
    </form>
  )
}
