import { cartReducer, EMPTY, estimatedItemTotal, isOtherRestaurant, itemCount, MAX_QTY, type CartRestaurant, type CartState } from './cart'

const dhaba: CartRestaurant = { id: 'r1', name: 'Pal Dhaba', region: 'north' }
const dosa: CartRestaurant = { id: 'r2', name: 'Dosa Junction', region: 'south' }
const naan = { menuItemId: 'm1', name: 'Butter Naan', price: '50.00', isVeg: true }
const dal = { menuItemId: 'm2', name: 'Dal Makhani', price: '240.00', isVeg: true }

const add = (s: CartState, restaurant = dhaba, item = naan) => cartReducer(s, { type: 'add', restaurant, item })

describe('cart', () => {
  it('adds a dish, then increases its quantity', () => {
    const s = add(add(EMPTY))
    expect(s.lines).toEqual([{ ...naan, qty: 2 }])
    expect(itemCount(s)).toBe(2)
  })

  it('caps the quantity of one dish', () => {
    let s = EMPTY
    for (let i = 0; i < MAX_QTY + 5; i++) s = add(s)
    expect(s.lines[0]!.qty).toBe(MAX_QTY)
  })

  it('removing the last unit empties the cart and forgets the restaurant', () => {
    const s = cartReducer(add(EMPTY), { type: 'remove', menuItemId: 'm1' })
    expect(s).toEqual(EMPTY)
  })

  it('a dish from another restaurant starts a new cart (the screen asks first)', () => {
    const s = add(add(EMPTY), dhaba, dal)
    expect(isOtherRestaurant(s, 'r2')).toBe(true)
    const next = add(s, dosa, { menuItemId: 'm9', name: 'Masala Dosa', price: '150.00', isVeg: true })
    expect(next.restaurant).toEqual(dosa)
    expect(next.lines.map((l) => l.name)).toEqual(['Masala Dosa'])
  })

  it('estimates the item total in whole paise, without float drift', () => {
    let s = add(EMPTY, dhaba, { ...naan, price: '0.10' })
    s = add(s, dhaba, { ...dal, price: '0.20' })
    expect(estimatedItemTotal(s)).toBe('0.30') // 0.1 + 0.2 in floats is 0.30000000000000004
  })
})
