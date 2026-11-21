import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { fakeApi, renderAt } from '../test/render'
import { HomePage } from './HomePage'

const card = (id: string, name: string, cuisines: string[], rating: string | null, count: number) => ({
  id,
  name,
  address: 'Chandigarh',
  cuisines,
  distance_km: '2.8',
  eta_minutes: 28,
  eta_text: '25-30 min',
  rating,
  rating_count: count,
  delivery_fee: '30.00',
  free_delivery_above: '299.00',
  packaging_charge: '10.00',
})

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

describe('Home', () => {
  it('lists restaurants near the chosen place, with regional filters', async () => {
    const api = fakeApi((url) =>
      url.pathname === '/api/v1/restaurants/near'
        ? {
            body: {
              total: 3,
              restaurants: [
                card('1', 'Pal Dhaba', ['North Indian', 'Punjabi'], '4.6', 10),
                card('2', 'Dosa Junction', ['South Indian'], null, 1),
                card('3', 'Marwar Rasoi', ['Rajasthani'], '4.3', 3),
              ],
            },
          }
        : undefined,
    )
    renderAt('/', [{ path: '/', element: <HomePage /> }])

    expect(await screen.findByText('Pal Dhaba')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '3 restaurants near you' })).toBeInTheDocument()
    // The default place is Sector 22, sent to the API as lat/lng.
    expect(api.calls[0]!.path).toContain('lat=30.7333')
    // Fewer than 3 reviews: "New", not a misleading 5.0.
    const dosa = screen.getByRole('link', { name: /Dosa Junction/ })
    expect(within(dosa).getByText('New')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Rajasthani' }))
    expect(screen.getByRole('button', { name: 'Rajasthani' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByText('Pal Dhaba')).not.toBeInTheDocument()
    expect(screen.getByText('Marwar Rasoi')).toBeInTheDocument()
  })

  it('asks the API again when the sort changes', async () => {
    const api = fakeApi(() => ({ body: { total: 0, restaurants: [] } }))
    renderAt('/', [{ path: '/', element: <HomePage /> }])
    expect(await screen.findByText(/No restaurant delivers here yet/)).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Sort by'), 'rating')
    await vi.waitFor(() => expect(api.calls.some((c) => c.path.includes('sort=rating'))).toBe(true))
  })

  it('shows a readable error with a retry button when the API is down', async () => {
    fakeApi(() => ({ status: 503, body: { detail: 'Service unavailable' } }))
    renderAt('/', [{ path: '/', element: <HomePage /> }])
    expect(await screen.findByRole('alert')).toHaveTextContent('Service unavailable')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
