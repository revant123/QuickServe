import { useState } from 'react'
import { useBestSellers, useSales } from '../api/partner'
import { ErrorBox, Loading, Ornament } from '../components/ui'
import { rupees } from '../lib/money'
import { todayLocal } from '../lib/time'
import { useCurrentRestaurant } from './PartnerApp'

export function SalesPage() {
  const restaurant = useCurrentRestaurant()
  const [day, setDay] = useState(todayLocal())
  const sales = useSales(restaurant.id, day)
  const best = useBestSellers(restaurant.id)

  return (
    <main className="stack">
      <div className="row between">
        <label htmlFor="sales-day" className="small">
          Day
        </label>
        <input id="sales-day" type="date" value={day} max={todayLocal()} onChange={(e) => setDay(e.target.value || todayLocal())} />
      </div>

      {sales.isPending ? (
        <Loading label="Adding up the day" />
      ) : sales.isError ? (
        <ErrorBox error={sales.error} onRetry={() => sales.refetch()} />
      ) : (
        <>
          <section className="panel payout" aria-labelledby="payout-title">
            <div className="panel-body">
              <p className="eyebrow">Estimated payout</p>
              <h2 id="payout-title" className="payout-amount">
                {rupees(sales.data.estimated_payout)}
              </h2>
              <dl className="bill-lines">
                <div>
                  <dt>Food sales (delivered, with packing)</dt>
                  <dd>{rupees(sales.data.food_sales)}</dd>
                </div>
                <div>
                  <dt>Your offers</dt>
                  <dd>− {rupees(sales.data.restaurant_discounts)}</dd>
                </div>
                <div>
                  <dt>Commission ({Number(sales.data.commission_percent)}%)</dt>
                  <dd>− {rupees(sales.data.commission)}</dd>
                </div>
                <div>
                  <dt>GST on commission</dt>
                  <dd>− {rupees(sales.data.gst_on_commission)}</dd>
                </div>
              </dl>
              <p className="muted small">
                Delivery and platform fees are the platform's, so they're not in your sales. Days are counted in {sales.data.timezone.replace('_', ' ')} time.
              </p>
            </div>
          </section>

          <div className="stat-grid">
            <Stat label="Delivered" value={sales.data.orders_delivered} />
            <Stat label="In progress" value={sales.data.orders_in_progress} />
            <Stat label="Cancelled or rejected" value={sales.data.orders_cancelled} />
            <Stat label="Missed (not accepted in time)" value={sales.data.orders_missed} warn={sales.data.orders_missed > 0} />
            <Stat label="Average prep time" value={sales.data.avg_prep_minutes == null ? '–' : `${sales.data.avg_prep_minutes} min`} />
          </div>

          {sales.data.top_items.length > 0 && (
            <section className="panel" aria-labelledby="top-title">
              <div className="panel-body">
                <h2 id="top-title" className="section-title">
                  Most ordered that day
                </h2>
                <ol className="ranked">
                  {sales.data.top_items.map((t) => (
                    <li key={t.name}>
                      {t.name} <span className="muted">× {t.quantity}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </section>
          )}
        </>
      )}

      <Ornament>Best sellers, last 7 days</Ornament>
      {best.isPending ? (
        <Loading />
      ) : best.isError ? (
        <ErrorBox error={best.error} />
      ) : best.data.filter((b) => b.units_sold > 0).length === 0 ? (
        <p className="empty">No sales in the last 7 days yet.</p>
      ) : (
        <ol className="ranked panel panel-body" aria-label="Best sellers">
          {best.data.filter((b) => b.units_sold > 0).slice(0, 5).map((b) => (
            <li key={b.menu_item_id}>
              <strong>{b.name}</strong>
              <span className="muted small">
                {' '}
                {b.units_sold} sold · {b.units_per_hour.toFixed(1)} per hour on sale
                {b.sell_through != null ? ` · ${Math.round(b.sell_through * 100)}% sell-through` : ''}
                {b.sold_out_cycles > 0 ? ` · sold out ${b.sold_out_cycles}×` : ''}
              </span>
            </li>
          ))}
        </ol>
      )}
      <p className="footnote">Ranked by sales per hour while in stock, so a dish that sold out early isn't punished for it.</p>
    </main>
  )
}

function Stat({ label, value, warn = false }: { label: string; value: number | string; warn?: boolean }) {
  return (
    <div className={`stat ${warn ? 'warn' : ''}`}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}
