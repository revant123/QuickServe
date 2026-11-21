import { errorMessage } from './client'
import { safeNext } from '../lib/safeNext'
import { rupees } from '../lib/money'

describe('errorMessage', () => {
  it('reads a domain error', () => {
    expect(errorMessage({ detail: 'Restaurant is closed' }, 422)).toBe('Restaurant is closed')
  })
  it('reads the first field of a validation error', () => {
    expect(errorMessage({ detail: [{ loc: ['body', 'email'], msg: 'value is not a valid email address' }] }, 422)).toBe(
      'email: value is not a valid email address',
    )
  })
  it('hides server internals behind a friendly sentence', () => {
    expect(errorMessage('Internal Server Error', 500)).toMatch(/our side/)
  })
})

describe('safeNext (open redirects)', () => {
  it.each([
    ['/cart', '/cart'],
    ['/orders/1?x=2', '/orders/1?x=2'],
    ['https://evil.example', '/'],
    ['//evil.example', '/'],
    ['/\\evil.example', '/'],
    [null, '/'],
  ])('%s -> %s', (input, out) => {
    expect(safeNext(input)).toBe(out)
  })
})

describe('rupees', () => {
  it('formats decimal strings the Indian way', () => {
    expect(rupees('240.00')).toBe('₹240')
    expect(rupees('324.68')).toBe('₹324.68')
    expect(rupees('125000')).toBe('₹1,25,000')
  })
})
