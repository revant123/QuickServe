import { Link } from 'react-router'
import { useMyOrders } from '../api/queries'
import { useAuth } from '../auth/AuthProvider'
import { ErrorBox, Loading, TopBar } from '../components/ui'
import { rupees } from '../lib/money'
import { STATUS_LABEL } from '../lib/status'

export function OrdersPage() {
  const { loggedIn } = useAuth()
  const orders = useMyOrders(loggedIn)
  return (
    <div className="page">
      <TopBar title="My orders" back={false} />
      <main className="stack">
        {orders.isPending && <Loading label="Loading your orders" />}
        {orders.isError && <ErrorBox error={orders.error} onRetry={() => orders.refetch()} />}
        {orders.data?.length === 0 && (
          <div className="center stack">
            <p className="empty">No orders yet.</p>
            <Link to="/" className="btn">
              Order something
            </Link>
          </div>
        )}
        <ul className="plain-list">
          {orders.data?.map((o) => (
            <li key={o.id}>
              <Link to={`/orders/${o.id}`} className="order-row">
                <div>
                  <strong>{o.restaurant_name}</strong>
                  <span className="muted small">
                    {new Date(o.created_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })} · {o.item_count} item
                    {o.item_count === 1 ? '' : 's'}
                  </span>
                </div>
                <div className="right">
                  <strong>{rupees(o.grand_total)}</strong>
                  <span className={`status s-${o.status.toLowerCase()}`}>{STATUS_LABEL[o.status]}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </main>
    </div>
  )
}
