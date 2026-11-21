import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createContext, Suspense, useContext, useState, type ReactNode } from 'react'
import { Outlet } from 'react-router'
import { api, unwrap, type Schemas } from '../api/client'
import { useMyRestaurants } from '../api/partner'
import { useAuth } from '../auth/AuthProvider'
import { RequireRole } from '../auth/RequireRole'
import { BottomNav, ErrorBox, Loading, type NavItem } from '../components/ui'
import { ArtDefs, RegionStrip } from '../theme/Art'
import { regionFor } from '../theme/regions'

type Restaurant = Schemas['RestaurantOut']

const Ctx = createContext<Restaurant | null>(null)

/** The restaurant the partner is managing right now. */
export function useCurrentRestaurant(): Restaurant {
  const r = useContext(Ctx)
  if (!r) throw new Error('useCurrentRestaurant outside PartnerApp')
  return r
}

/** For tests of a single partner screen, without the whole shell. */
export function PartnerTestProvider({ restaurant, children }: { restaurant: Restaurant; children: ReactNode }) {
  return <Ctx.Provider value={restaurant}>{children}</Ctx.Provider>
}

const NAV: NavItem[] = [
  { to: '/partner', label: 'Orders', icon: 'M6 3h12l1 18H5zM9 8a3 3 0 0 0 6 0' },
  { to: '/partner/menu', label: 'Menu', icon: 'M4 6h16M4 12h16M4 18h10' },
  { to: '/partner/sales', label: 'Sales', icon: 'M4 20V10M10 20V4M16 20v-7M22 20H2' },
  { to: '/partner/offers', label: 'Offers', icon: 'M20 12l-8 8-9-9V3h8zM7.5 7.5h.01' },
]

const STORE_KEY = 'qs.partner.restaurant'

export function PartnerApp() {
  return (
    <div className="app partner">
      <ArtDefs />
      <RequireRole role="RESTAURANT_OWNER">
        <PartnerShell />
      </RequireRole>
    </div>
  )
}

function PartnerShell() {
  const restaurants = useMyRestaurants()
  const [selected, setSelected] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORE_KEY)
    } catch {
      return null
    }
  })

  if (restaurants.isPending) return <Loading label="Loading your restaurants" />
  if (restaurants.isError) return <ErrorBox error={restaurants.error} onRetry={() => restaurants.refetch()} />
  const list = restaurants.data
  const current = list.find((r) => r.id === selected) ?? list[0]
  if (!current) {
    return (
      <main className="stack">
        <p className="notice">You don't have a restaurant yet. Create one with POST /api/v1/restaurants (see /docs).</p>
      </main>
    )
  }

  function choose(id: string) {
    setSelected(id)
    try {
      localStorage.setItem(STORE_KEY, id)
    } catch {
      /* private mode: remember for this visit only */
    }
  }

  return (
    <Ctx.Provider value={current}>
      <PartnerHeader restaurants={list} current={current} onChoose={choose} />
      <Suspense fallback={<Loading />}>
        <Outlet />
      </Suspense>
      <BottomNav items={NAV} label="Partner" />
    </Ctx.Provider>
  )
}

function PartnerHeader({ restaurants, current, onChoose }: { restaurants: Restaurant[]; current: Restaurant; onChoose: (id: string) => void }) {
  const queryClient = useQueryClient()
  const { logout } = useAuth()
  const toggle = useMutation({
    mutationFn: async (isOpen: boolean) =>
      unwrap(await api.PUT('/api/v1/restaurants/{restaurant_id}/open', { params: { path: { restaurant_id: current.id } }, body: { is_open: isOpen } })),
    onSuccess: (updated) => {
      queryClient.setQueryData<Restaurant[]>(['partner', 'restaurants'], (old) => old?.map((r) => (r.id === updated.id ? updated : r)))
      // Customers' "near me" lists should drop or show it again soon.
      queryClient.invalidateQueries({ queryKey: ['public'] })
    },
  })
  return (
    <header className="partner-header">
      <div className="partner-header-row">
        <div className="grow">
          <p className="eyebrow">QuickServe Partner</p>
          {restaurants.length > 1 ? (
            <select aria-label="Restaurant" value={current.id} onChange={(e) => onChoose(e.target.value)} className="restaurant-select">
              {restaurants.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          ) : (
            <h1 className="partner-name">{current.name}</h1>
          )}
        </div>
        <button
          type="button"
          className={`switch ${current.is_open ? 'on' : ''}`}
          aria-pressed={current.is_open}
          onClick={() => toggle.mutate(!current.is_open)}
          disabled={toggle.isPending}
        >
          <span className="switch-knob" aria-hidden="true" />
          {current.is_open ? 'Accepting orders' : 'Not accepting'}
        </button>
      </div>
      {toggle.isError && <ErrorBox error={toggle.error} />}
      <button type="button" className="link-btn small" onClick={() => void logout()}>
        Log out
      </button>
      <RegionStrip region={regionFor(current.cuisines)} height={10} />
    </header>
  )
}
