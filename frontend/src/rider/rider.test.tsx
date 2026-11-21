import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OrderPage } from '../pages/OrderPage'
import { fakeApi, renderAt } from '../test/render'
import { RiderHome } from './RiderApp'

const RIDER = { id: 'd1', name: 'Demo Rider', email: 'rider@x.dev', role: 'RIDER' }
const job = (over: object) => ({
  id: 'o1',
  status: 'PREPARING',
  restaurant_name: 'Marwar Rasoi',
  restaurant_address: 'Sector 21',
  restaurant_latitude: '30.727',
  restaurant_longitude: '76.793',
  delivery_address: 'House 12, Sector 22-B',
  delivery_latitude: '30.7333',
  delivery_longitude: '76.7794',
  distance_km: '2.0',
  item_count: 1,
  rider_pay: '32.00',
  assigned_at: new Date().toISOString(),
  created_at: new Date().toISOString(),
  ...over,
})
const day = (active: object | null) => ({ active, delivered_today: [], deliveries_today: 0, earnings_today: '0' })

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  sessionStorage.setItem('qs.token', 'test-token')
})

describe('Rider', () => {
  it('lists waiting orders without addresses and explains when someone else was faster', async () => {
    const api = fakeApi((url, request) => {
      if (url.pathname === '/api/v1/users/me') return { body: RIDER }
      if (url.pathname === '/api/v1/rider/me') return { body: day(null) }
      if (url.pathname === '/api/v1/rider/pool')
        return {
          body: [
            {
              id: 'o1',
              status: 'READY',
              restaurant_name: 'Marwar Rasoi',
              restaurant_address: 'Sector 21',
              distance_km: '2.0',
              item_count: 1,
              rider_pay: '32.00',
              created_at: new Date().toISOString(),
            },
          ],
        }
      if (url.pathname === '/api/v1/orders/o1/claim' && request.method === 'POST')
        return { status: 409, body: { detail: 'Another delivery partner has taken this order' } }
      return undefined
    })
    renderAt('/rider', [{ path: '/rider', element: <RiderHome /> }])
    expect(await screen.findByText('Food ready')).toBeInTheDocument()
    expect(screen.queryByText(/House 12/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Accept · ₹32' }))
    expect(await screen.findByText('Another delivery partner has taken this order')).toBeInTheDocument()
    // The list is fetched again so the taken order disappears.
    expect(api.calls.filter((c) => c.path === '/api/v1/rider/pool').length).toBeGreaterThan(1)
  })

  it("can't pick up before the food is ready", async () => {
    fakeApi((url) => {
      if (url.pathname === '/api/v1/users/me') return { body: RIDER }
      if (url.pathname === '/api/v1/rider/me') return { body: day(job({ status: 'PREPARING' })) }
      return undefined
    })
    renderAt('/rider', [{ path: '/rider', element: <RiderHome /> }])
    expect(await screen.findByRole('button', { name: "I've picked it up" })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Directions to the restaurant' })).toHaveAttribute(
      'href',
      'https://www.google.com/maps/dir/?api=1&destination=30.727%2C76.793',
    )
  })

  it('takes only digits for the delivery code and sends it with DELIVERED', async () => {
    const api = fakeApi((url, request) => {
      if (url.pathname === '/api/v1/users/me') return { body: RIDER }
      if (url.pathname === '/api/v1/rider/me') return { body: day(job({ status: 'OUT_FOR_DELIVERY' })) }
      if (url.pathname === '/api/v1/orders/o1/status' && request.method === 'PATCH')
        return { status: 422, body: { detail: 'That code is wrong. 4 tries left.' } }
      return undefined
    })
    renderAt('/rider', [{ path: '/rider', element: <RiderHome /> }])
    const input = await screen.findByLabelText("Customer's 4-digit delivery code")
    await userEvent.type(input, '7a8-34')
    expect(input).toHaveValue('7834')
    await userEvent.click(screen.getByRole('button', { name: 'Mark delivered' }))
    expect(await screen.findByText('That code is wrong. 4 tries left.')).toBeInTheDocument()
    expect(api.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'DELIVERED', delivery_code: '7834' })
  })
})

describe('Customer order page', () => {
  it('shows the delivery code and who is delivering', async () => {
    fakeApi((url) => {
      if (url.pathname === '/api/v1/users/me') return { body: { id: 'c1', name: 'Asha', email: 'a@x.dev', role: 'CUSTOMER' } }
      if (url.pathname === '/api/v1/orders/o1/timeline') return { body: [] }
      if (url.pathname === '/api/v1/orders/o1')
        return {
          body: {
            id: 'o1',
            customer_id: 'c1',
            restaurant_id: 'r1',
            status: 'PREPARING',
            delivery_address: 'House 12',
            item_total: '260.00',
            packaging_charge: '10.00',
            delivery_fee: '30.00',
            platform_fee: '10.00',
            small_order_fee: '0.00',
            surge_fee: '0.00',
            surge_reasons: null,
            discount: '0.00',
            coupon_code: null,
            gst_food: '13.50',
            gst_fees: '7.20',
            grand_total: '330.70',
            distance_km: '2.0',
            pay_by: new Date().toISOString(),
            paid_at: new Date().toISOString(),
            accept_by: null,
            cancel_reason: null,
            created_at: new Date().toISOString(),
            items: [],
            rider_name: 'Demo Rider',
            delivery_code: '7834',
          },
        }
      return undefined
    })
    renderAt('/orders/o1', [{ path: '/orders/:id', element: <OrderPage /> }])
    expect(await screen.findByLabelText('Delivery code 7 8 3 4')).toHaveTextContent('7834')
    expect(screen.getByText(/Demo Rider is delivering your order/)).toBeInTheDocument()
  })
})
