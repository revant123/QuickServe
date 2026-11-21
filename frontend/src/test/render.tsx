import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { type ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { AuthProvider } from '../auth/AuthProvider'
import { CartProvider } from '../cart/CartProvider'
import { LocationProvider } from '../location/location'
import { ArtDefs } from '../theme/Art'

/** Render a screen with every provider the real app has, at a given URL. */
export function renderAt(path: string, routes: { path: string; element: ReactElement }[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <LocationProvider>
            <CartProvider>
              <ArtDefs />
              <Routes>
                {routes.map((r) => (
                  <Route key={r.path} path={r.path} element={r.element} />
                ))}
              </Routes>
            </CartProvider>
          </LocationProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

type Handler = (url: URL, request: Request) => { status?: number; body: unknown } | undefined

/** A fake API: each handler returns a response for the URLs it knows. Records every request. */
export function fakeApi(handler: Handler) {
  const calls: { method: string; path: string; body: unknown }[] = []
  const fetchMock = vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    const text = request.method === 'GET' ? '' : await request.clone().text()
    let body: unknown = text
    try {
      body = text ? JSON.parse(text) : undefined
    } catch {
      /* form bodies stay text */
    }
    calls.push({ method: request.method, path: url.pathname + url.search, body })
    const res = handler(url, request)
    if (!res) return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404, headers: { 'Content-Type': 'application/json' } })
    return new Response(JSON.stringify(res.body), { status: res.status ?? 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}
