import { createContext, useContext, useEffect, useMemo, useReducer, type ReactNode } from 'react'
import { cartReducer, EMPTY, type CartAction, type CartState } from './cart'

const KEY = 'qs.cart'

function load(): CartState {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null') as CartState | null
    if (saved && Array.isArray(saved.lines)) return saved
  } catch {
    /* a broken saved cart is just an empty cart */
  }
  return EMPTY
}

const Ctx = createContext<{ cart: CartState; dispatch: (a: CartAction) => void } | null>(null)

export function CartProvider({ children }: { children: ReactNode }) {
  const [cart, dispatch] = useReducer(cartReducer, undefined, load)
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(cart))
    } catch {
      /* not saved; still works for this visit */
    }
  }, [cart])
  const value = useMemo(() => ({ cart, dispatch }), [cart])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useCart() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useCart must be used inside <CartProvider>')
  return ctx
}
