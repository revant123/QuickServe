import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useMyRestaurants } from '../api/partner'
import { fakeApi, renderAt } from '../test/render'
import { MenuManager } from './MenuManager'
import { OrdersBoard } from './OrdersBoard'
import { PartnerApp, PartnerTestProvider } from './PartnerApp'
import { SalesPage } from './SalesPage'

const OWNER = { id: 'o1', name: 'Demo Owner', email: 'owner@x.dev', role: 'RESTAURANT_OWNER' }
const RESTAURANT = {
  id: 'r1',
  owner_id: 'o1',
  name: 'Marwar Rasoi',
  address: 'Sector 21',
  is_open: true,
  packaging_charge: '10.00',
  latitude: '30.727',
  longitude: '76.793',
  delivery_radius_km: '6.0',
  cuisines: ['Rajasthani'],
  avg_prep_minutes: 25,
  rating: null,
  rating_count: 0,
}
const ticket = (over: object) => ({
  id: 'aaaaaaaa-0000-0000-0000-00000000beef',
  short_id: 'BEEF',
  status: 'PAID',
  created_at: new Date(Date.now() - 60_000).toISOString(),
  accept_by: new Date(Date.now() + 180_000).toISOString(),
  items: [{ name: 'Dal Baati Churma', quantity: 2 }],
  item_total: '520.00',
  packaging_charge: '10.00',
  customer_first_name: 'Asha',
  rider_name: null,
  cancel_reason: null,
  ...over,
})

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  sessionStorage.setItem('qs.token', 'test-token')
})

function baseApi(extra: (url: URL, request: Request) => { status?: number; body: unknown } | undefined) {
  return fakeApi((url, request) => {
    if (url.pathname === '/api/v1/users/me') return { body: OWNER }
    if (url.pathname === '/api/v1/restaurants/mine') return { body: [RESTAURANT] }
    return extra(url, request)
  })
}

describe('Partner app', () => {
  it('shows the restaurant and its accepting-orders switch, and turns it off', async () => {
    const api = baseApi((url, request) =>
      url.pathname === '/api/v1/restaurants/r1/open' && request.method === 'PUT' ? { body: { ...RESTAURANT, is_open: false } } : undefined,
    )
    renderAt('/partner', [{ path: '/partner', element: <PartnerApp /> }])
    expect(await screen.findByRole('heading', { name: 'Marwar Rasoi' })).toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: 'Accepting orders' })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(toggle)
    expect(await screen.findByRole('button', { name: 'Not accepting' })).toHaveAttribute('aria-pressed', 'false')
    expect(api.calls.find((c) => c.method === 'PUT')?.body).toEqual({ is_open: false })
  })

  it('tells a customer this screen is for restaurant partners', async () => {
    fakeApi((url) => (url.pathname === '/api/v1/users/me' ? { body: { ...OWNER, role: 'CUSTOMER', name: 'Asha' } } : undefined))
    renderAt('/partner', [{ path: '/partner', element: <PartnerApp /> }])
    expect(await screen.findByText(/This screen is for restaurant partners/)).toBeInTheDocument()
  })
})

describe('OrdersBoard', () => {
  it('counts down, accepts, and sends the reason when rejecting', async () => {
    let board = [ticket({}), ticket({ id: 'bbbbbbbb-0000-0000-0000-00000000cafe', short_id: 'CAFE' })]
    const api = baseApi((url, request) => {
      if (url.pathname === '/api/v1/restaurants/r1/orders') return { body: board }
      if (url.pathname.endsWith('/status') && request.method === 'PATCH') {
        board = board.slice(1)
        return { body: {} }
      }
      return undefined
    })
    renderAt('/partner', [{ path: '/partner', element: <WithRestaurant><OrdersBoard /></WithRestaurant> }])

    const first = await screen.findByRole('article', { name: '#BEEF' })
    expect(within(first).getByRole('timer')).toHaveTextContent(/Accept within [23]:\d\d/)
    expect(within(first).getByText(/2 ×/)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /New/ })).toHaveTextContent('2')
    expect(document.title).toBe('(2) New orders · QuickServe Partner')

    await userEvent.click(within(first).getByRole('button', { name: 'Accept' }))
    const accepted = api.calls.find((c) => c.method === 'PATCH')
    expect(accepted?.path).toContain('/orders/aaaaaaaa-0000-0000-0000-00000000beef/status')
    expect(accepted?.body).toMatchObject({ status: 'ACCEPTED' })

    const second = await screen.findByRole('article', { name: '#CAFE' })
    await userEvent.click(within(second).getByRole('button', { name: 'Reject' }))
    await userEvent.click(screen.getByLabelText('Kitchen is closing'))
    await userEvent.click(screen.getByRole('button', { name: 'Reject order' }))
    const rejected = api.calls.filter((c) => c.method === 'PATCH').at(-1)
    expect(rejected?.body).toMatchObject({ status: 'REJECTED', note: 'Kitchen is closing' })
  })

  it("won't let the kitchen accept once the timer has run out", async () => {
    baseApi((url) => (url.pathname === '/api/v1/restaurants/r1/orders' ? { body: [ticket({ accept_by: new Date(Date.now() - 1000).toISOString() })] } : undefined))
    renderAt('/partner', [{ path: '/partner', element: <WithRestaurant><OrdersBoard /></WithRestaurant> }])
    expect(await screen.findByText(/Time is up/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled()
  })
})

describe('OrdersBoard on a desktop', () => {
  afterEach(() => {
    // @ts-expect-error: back to jsdom's default (no matchMedia)
    delete window.matchMedia
  })

  it('shows New, Preparing and Ready side by side instead of tabs', async () => {
    window.matchMedia = ((query: string) => ({
      matches: query === '(min-width: 1024px)',
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia
    baseApi((url) =>
      url.pathname === '/api/v1/restaurants/r1/orders'
        ? { body: [ticket({}), ticket({ id: 'cccccccc-0000-0000-0000-00000000d00d', short_id: 'D00D', status: 'PREPARING', accept_by: null })] }
        : undefined,
    )
    renderAt('/partner', [{ path: '/partner', element: <WithRestaurant><OrdersBoard /></WithRestaurant> }])
    const fresh = await screen.findByRole('region', { name: /^New/ })
    expect(within(fresh).getByRole('article', { name: '#BEEF' })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: /^Preparing/ })).getByRole('article', { name: '#D00D' })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: /^Ready/ })).getByText('Nothing here.')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Live orders/ })).toHaveTextContent('2')
  })
})

describe('Menu and sales', () => {
  it('switches a dish off until a time', async () => {
    const item = {
      id: 'm1',
      restaurant_id: 'r1',
      name: 'Laal Maas',
      description: '',
      price: '420.00',
      is_veg: false,
      is_available: true,
      unavailable_until: null,
      track_stock: true,
      stock: 20,
      consumed: 3,
      available: 17,
      cycle_no: 1,
      cycle_started_at: new Date().toISOString(),
    }
    const api = baseApi((url, request) => {
      if (url.pathname === '/api/v1/restaurants/r1/menu/manage') return { body: [item] }
      if (url.pathname === '/api/v1/menu/m1/availability' && request.method === 'PATCH') return { body: item }
      return undefined
    })
    renderAt('/partner', [{ path: '/partner', element: <WithRestaurant><MenuManager /></WithRestaurant> }])
    expect(await screen.findByText('17 left')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Laal Maas: on the menu' }))
    await userEvent.click(screen.getByRole('button', { name: 'For 2 hours' }))
    const patch = api.calls.find((c) => c.method === 'PATCH')
    expect(patch?.body).toMatchObject({ is_available: false })
    expect((patch?.body as { unavailable_until: string }).unavailable_until).toMatch(/T/)
  })

  it('shows the payout with commission and GST taken off', async () => {
    baseApi((url) => {
      if (url.pathname === '/api/v1/restaurants/r1/sales')
        return {
          body: {
            day: '2026-11-21',
            timezone: 'Asia/Kolkata',
            orders_delivered: 3,
            orders_in_progress: 1,
            orders_cancelled: 0,
            orders_missed: 1,
            food_sales: '780.00',
            restaurant_discounts: '50.00',
            commission_percent: '20',
            commission: '146.00',
            gst_on_commission: '26.28',
            estimated_payout: '557.72',
            avg_prep_minutes: 18.5,
            top_items: [{ name: 'Dal Baati Churma', quantity: 3 }],
          },
        }
      if (url.pathname === '/api/v1/restaurants/r1/best-sellers') return { body: [] }
      return undefined
    })
    renderAt('/partner', [{ path: '/partner', element: <WithRestaurant><SalesPage /></WithRestaurant> }])
    expect(await screen.findByRole('heading', { name: '₹557.72' })).toBeInTheDocument()
    expect(screen.getByText('Commission (20%)')).toBeInTheDocument()
    expect(screen.getByText('Missed (not accepted in time)').closest('.stat')).toHaveClass('warn')
    expect(screen.getByText('18.5 min')).toBeInTheDocument()
  })
})


/** The partner screens read the current restaurant from PartnerApp's context. */
function WithRestaurant({ children }: { children: React.ReactNode }) {
  const list = useMyRestaurants()
  if (!list.data) return null
  return <PartnerTestProvider restaurant={list.data[0]!}>{children}</PartnerTestProvider>
}
