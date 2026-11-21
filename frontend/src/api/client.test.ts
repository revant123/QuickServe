import { api, ApiError, errorMessage, unwrap } from './client'
import { fakeApi } from '../test/render'
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

describe('trace IDs (Phase 15)', () => {
  it('keeps the X-Trace-Id of a failed request on the error', async () => {
    fakeApi(() => ({ status: 500, body: { detail: 'Internal server error' }, headers: { 'X-Trace-Id': '4bf92f3577b34da6a3ce929d0e0e4736' } }))
    const error = await api.GET('/api/v1/pricing').then(unwrap).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).traceId).toBe('4bf92f3577b34da6a3ce929d0e0e4736')
  })
})
