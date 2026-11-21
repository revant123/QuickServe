/**
 * The cart: a pure reducer, so its rules are easy to test without a browser.
 *
 * It lives in the browser (localStorage), because a cart is a draft: nothing is
 * reserved or priced until checkout asks the server for a quote. The prices
 * shown here are an estimate; the server's quote is the only real bill.
 */
import { fromPaise, toPaise } from '../lib/money'
import type { Region } from '../theme/regions'

export const MAX_QTY = 20 // the API allows 50; a food cart rarely needs more than this per dish

export interface CartLine {
  menuItemId: string
  name: string
  price: string // decimal string, as the API sends it
  isVeg: boolean
  qty: number
}

export interface CartRestaurant {
  id: string
  name: string
  region: Region
}

export interface CartState {
  restaurant: CartRestaurant | null
  lines: CartLine[]
}

export type CartAction =
  | { type: 'add'; restaurant: CartRestaurant; item: Omit<CartLine, 'qty'> }
  | { type: 'remove'; menuItemId: string }
  | { type: 'clear' }

export const EMPTY: CartState = { restaurant: null, lines: [] }

/** Orders come from one restaurant, like on Swiggy and Zomato: one kitchen, one rider. */
export function isOtherRestaurant(state: CartState, restaurantId: string): boolean {
  return state.restaurant !== null && state.lines.length > 0 && state.restaurant.id !== restaurantId
}

export function cartReducer(state: CartState, action: CartAction): CartState {
  switch (action.type) {
    case 'add': {
      // Adding from another restaurant starts a new cart. The screen asks first.
      const base = isOtherRestaurant(state, action.restaurant.id) ? EMPTY : state
      const existing = base.lines.find((l) => l.menuItemId === action.item.menuItemId)
      const lines = existing
        ? base.lines.map((l) => (l === existing ? { ...l, qty: Math.min(MAX_QTY, l.qty + 1) } : l))
        : [...base.lines, { ...action.item, qty: 1 }]
      return { restaurant: action.restaurant, lines }
    }
    case 'remove': {
      const lines = state.lines
        .map((l) => (l.menuItemId === action.menuItemId ? { ...l, qty: l.qty - 1 } : l))
        .filter((l) => l.qty > 0)
      return lines.length ? { ...state, lines } : EMPTY
    }
    case 'clear':
      return EMPTY
  }
}

export function itemCount(state: CartState): number {
  return state.lines.reduce((n, l) => n + l.qty, 0)
}

/** Sum in whole paise, so 0.1 + 0.2 problems can't creep into the estimate. */
export function estimatedItemTotal(state: CartState): string {
  return fromPaise(state.lines.reduce((sum, l) => sum + toPaise(l.price) * l.qty, 0))
}

export function qtyOf(state: CartState, menuItemId: string): number {
  return state.lines.find((l) => l.menuItemId === menuItemId)?.qty ?? 0
}
