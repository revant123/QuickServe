/**
 * Server state for the restaurant partner and rider screens (Phase 14).
 *
 * None of these keys start with 'public': they belong to the logged-in partner
 * and are dropped at logout like the customer's orders.
 *
 * How fresh each needs to be is a business choice:
 * - the order board refetches every 10 s: a new order has 4 minutes to be
 *   accepted, so 10 s of delay is a few percent of that window;
 * - a rider's current delivery refetches every 5 s: the "food is ready" moment matters;
 * - sales and menu counters refresh when the screen is opened or refocused.
 */
import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from './client'

export type BoardView = 'active' | 'recent'

export function useMyRestaurants(enabled = true) {
  return useQuery({
    queryKey: ['partner', 'restaurants'],
    queryFn: async () => unwrap(await api.GET('/api/v1/restaurants/mine')),
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useBoard(restaurantId: string, view: BoardView, enabled = true) {
  return useQuery({
    queryKey: ['partner', 'board', restaurantId, view],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/restaurants/{restaurant_id}/orders', {
          params: { path: { restaurant_id: restaurantId }, query: { view } },
          signal,
        }),
      ),
    enabled: enabled && restaurantId !== '',
    refetchInterval: view === 'active' ? 10_000 : false,
  })
}

export function useSales(restaurantId: string, day: string | undefined) {
  return useQuery({
    queryKey: ['partner', 'sales', restaurantId, day ?? 'today'],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/restaurants/{restaurant_id}/sales', {
          params: { path: { restaurant_id: restaurantId }, query: day ? { day } : {} },
          signal,
        }),
      ),
    enabled: restaurantId !== '',
  })
}

export function useBestSellers(restaurantId: string) {
  return useQuery({
    queryKey: ['partner', 'best-sellers', restaurantId],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/restaurants/{restaurant_id}/best-sellers', {
          params: { path: { restaurant_id: restaurantId }, query: { days: 7 } },
          signal,
        }),
      ),
    enabled: restaurantId !== '',
    staleTime: 5 * 60_000,
  })
}

export function useManagedMenu(restaurantId: string) {
  return useQuery({
    queryKey: ['partner', 'menu', restaurantId],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/restaurants/{restaurant_id}/menu/manage', {
          params: { path: { restaurant_id: restaurantId } },
          signal,
        }),
      ),
    enabled: restaurantId !== '',
  })
}

export function useRestockSuggestion(itemId: string | null) {
  return useQuery({
    queryKey: ['partner', 'restock-suggestion', itemId],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/menu/{menu_item_id}/restock-suggestion', {
          params: { path: { menu_item_id: itemId ?? '' } },
          signal,
        }),
      ),
    enabled: itemId !== null,
  })
}

export function useOffers(restaurantId: string) {
  return useQuery({
    queryKey: ['partner', 'offers', restaurantId],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/coupons', { params: { query: { restaurant_id: restaurantId } }, signal })),
    enabled: restaurantId !== '',
  })
}

// ----- riders -----

export function useRiderDay() {
  return useQuery({
    queryKey: ['rider', 'me'],
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/rider/me', { signal })),
    refetchInterval: 5_000,
  })
}

export function usePool(enabled: boolean) {
  return useQuery({
    queryKey: ['rider', 'pool'],
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/rider/pool', { signal })),
    enabled,
    refetchInterval: enabled ? 10_000 : false,
  })
}
