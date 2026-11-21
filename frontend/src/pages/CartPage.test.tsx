import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { fakeApi, renderAt } from '../test/render'
import { CartPage } from './CartPage'

const cart = {
  restaurant: { id: 'r1', name: 'Pal Dhaba', region: 'north' },
  lines: [{ menuItemId: 'm1', name: 'Dal Makhani', price: '240.00', isVeg: true, qty: 2 }],
}
const quote = (total: string) => ({
  restaurant_id: 'r1',
  distance_km: '3.4',
  surge_reasons: [],
  coupon_code: null,
  coupon_error: null,
  item_total: '480.00',
  discount: '0.00',
  grand_total: total,
  lines: [
    { key: 'items', label: 'Item total', amount: '480.00', note: null },
    { key: 'gst_food', label: 'GST on food (5%)', amount: '24.00', note: null },
  ],
})

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  localStorage.setItem('qs.cart', JSON.stringify(cart))
  localStorage.setItem('qs.address', 'House 12, Sector 22-B')
})

describe('Cart', () => {
  it('shows an estimate and asks to log in before showing the real bill', async () => {
    const api = fakeApi(() => ({ body: [] }))
    renderAt('/cart', [{ path: '/cart', element: <CartPage /> }])
    expect(screen.getByText('₹480', { selector: 'strong' })).toBeInTheDocument() // the estimate
    expect(screen.getByRole('link', { name: 'Log in to see the bill' })).toHaveAttribute('href', '/login?next=/cart')
    expect(api.calls.some((c) => c.path.includes('/orders/quote'))).toBe(false)
  })

  it('never charges a changed price: a 409 shows the new total and refetches the bill', async () => {
    sessionStorage.setItem('qs.token', 'test-token')
    let quotes = 0
    const api = fakeApi((url, request) => {
      if (url.pathname === '/api/v1/users/me') return { body: { id: 'u1', name: 'Demo Customer', email: 'c@x.dev', role: 'CUSTOMER' } }
      if (url.pathname === '/api/v1/coupons') return { body: [] }
      if (url.pathname === '/api/v1/orders/quote') return { body: quote(++quotes === 1 ? '504.00' : '514.00') }
      if (url.pathname === '/api/v1/orders' && request.method === 'POST')
        return { status: 409, body: { detail: 'The price changed', new_grand_total: '514.00' } }
      return undefined
    })
    renderAt('/cart', [{ path: '/cart', element: <CartPage /> }])

    expect(await screen.findByText('GST on food (5%)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Place order/ }))

    expect(await screen.findByText('The price changed to ₹514. Please check the new bill.')).toBeInTheDocument()
    const placed = api.calls.find((c) => c.method === 'POST' && c.path === '/api/v1/orders')
    // The order carried the total the customer saw, so the server could refuse it.
    expect(placed?.body).toMatchObject({ expected_total: '504.00', delivery_address: 'House 12, Sector 22-B' })
    await vi.waitFor(() => expect(quotes).toBe(2))
    // The cart is kept: nothing was ordered.
    expect(JSON.parse(localStorage.getItem('qs.cart')!).lines).toHaveLength(1)
    // Every API call carried the token.
    expect(api.fetchMock.mock.calls.every(([r]) => (r as Request).headers.get('Authorization') === 'Bearer test-token')).toBe(true)
  })

  it('does not send a coupon the quote refused, so the order matches the bill shown', async () => {
    sessionStorage.setItem('qs.token', 'test-token')
    const api = fakeApi((url, request) => {
      if (url.pathname === '/api/v1/users/me') return { body: { id: 'u1', name: 'Demo', email: 'c@x.dev', role: 'CUSTOMER' } }
      if (url.pathname === '/api/v1/coupons') return { body: [] }
      if (url.pathname === '/api/v1/orders/quote')
        return { body: { ...quote('504.00'), coupon_error: 'Only for your first order' } }
      if (url.pathname === '/api/v1/orders' && request.method === 'POST') return { status: 201, body: { id: 'o1' } }
      return undefined
    })
    renderAt('/cart', [
      { path: '/cart', element: <CartPage /> },
      { path: '/orders/:id', element: <p>order page</p> },
    ])
    await userEvent.type(await screen.findByLabelText('Coupon'), 'welcome50')
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(await screen.findByText(/can't be used: Only for your first order/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Place order/ }))
    expect(await screen.findByText('order page')).toBeInTheDocument()
    const placed = api.calls.find((c) => c.method === 'POST' && c.path === '/api/v1/orders')
    expect(placed?.body).toMatchObject({ coupon_code: null, expected_total: '504.00' })
    expect(localStorage.getItem('qs.cart')).toContain('"lines":[]') // ordered: the cart is empty
  })
})
