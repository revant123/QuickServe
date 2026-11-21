import { useState } from 'react'
import { useCart } from './CartProvider'
import { isOtherRestaurant, type CartLine, type CartRestaurant } from './cart'

/** Add, but ask first if the cart holds another restaurant's dishes. */
export function useAddToCart() {
  const { cart, dispatch } = useCart()
  const [pending, setPending] = useState<{ restaurant: CartRestaurant; item: Omit<CartLine, 'qty'> } | null>(null)

  function add(restaurant: CartRestaurant, item: Omit<CartLine, 'qty'>) {
    if (isOtherRestaurant(cart, restaurant.id)) setPending({ restaurant, item })
    else dispatch({ type: 'add', restaurant, item })
  }

  return {
    cart,
    add,
    remove: (menuItemId: string) => dispatch({ type: 'remove', menuItemId }),
    pending,
    confirm: () => {
      if (pending) dispatch({ type: 'add', ...pending })
      setPending(null)
    },
    cancel: () => setPending(null),
  }
}
