/**
 * Server state, fetched and cached by TanStack Query.
 *
 * Keys starting with 'public' are the same for every visitor (restaurants,
 * menus, search); everything else belongs to the logged-in user and is dropped
 * at logout. staleTime is how long data counts as fresh before a refetch:
 * restaurant lists change slowly, an order's status changes every few minutes.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, unwrap } from './client'
import type { SortBy } from './types'

export function useNearby(lat: number, lng: number, sort: SortBy) {
  return useQuery({
    queryKey: ['public', 'near', lat, lng, sort],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/restaurants/near', { params: { query: { lat, lng, sort, limit: 50 } }, signal })),
    staleTime: 60_000,
    placeholderData: keepPreviousData, // keep the old list on screen while a new sort loads
  })
}

export function useRestaurant(id: string) {
  return useQuery({
    queryKey: ['public', 'restaurant', id],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/restaurants/{restaurant_id}', { params: { path: { restaurant_id: id } }, signal })),
    staleTime: 5 * 60_000,
  })
}

export function useMenu(id: string) {
  return useQuery({
    queryKey: ['public', 'menu', id],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/restaurants/{restaurant_id}/menu', { params: { path: { restaurant_id: id } }, signal })),
    staleTime: 30_000, // stock badges ("Only 3 left") go stale quickly
  })
}

export function useReviews(id: string) {
  return useQuery({
    queryKey: ['public', 'reviews', id],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/restaurants/{restaurant_id}/reviews', {
          params: { path: { restaurant_id: id }, query: { limit: 5 } },
          signal,
        }),
      ),
    staleTime: 5 * 60_000,
  })
}

export function useSearch(q: string, lat: number, lng: number) {
  return useQuery({
    queryKey: ['public', 'search', q, lat, lng],
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/search', { params: { query: { q, lat, lng } }, signal })),
    enabled: q.trim().length >= 2,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  })
}

export function useCoupons(restaurantId: string | undefined) {
  return useQuery({
    queryKey: ['public', 'coupons', restaurantId],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/coupons', { params: { query: { restaurant_id: restaurantId } }, signal })),
    enabled: restaurantId !== undefined,
    staleTime: 5 * 60_000,
  })
}

const ACTIVE = new Set(['PLACED', 'PAID', 'ACCEPTED', 'PREPARING', 'READY', 'OUT_FOR_DELIVERY'])

export function useOrder(id: string) {
  return useQuery({
    queryKey: ['order', id],
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/orders/{order_id}', { params: { path: { order_id: id } }, signal })),
    // Poll while the order is moving; stop once it's delivered or cancelled.
    // (Server-sent events or WebSockets would push changes instead: README.)
    refetchInterval: (query) => (query.state.data && ACTIVE.has(query.state.data.status) ? 5000 : false),
  })
}

export function useTimeline(id: string, status: string | undefined) {
  return useQuery({
    queryKey: ['order', id, 'timeline', status],
    queryFn: async ({ signal }) =>
      unwrap(await api.GET('/api/v1/orders/{order_id}/timeline', { params: { path: { order_id: id } }, signal })),
    enabled: status !== undefined,
  })
}

export function useMyOrders(enabled: boolean) {
  return useQuery({
    queryKey: ['orders'],
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/orders', { params: { query: { limit: 30 } }, signal })),
    enabled,
  })
}
