import { regionFor } from './regions'

describe('regionFor', () => {
  it.each([
    [['Rajasthani'], 'raj'],
    [['Gujarati'], 'guj'],
    [['South Indian'], 'south'],
    [['Northeast', 'Assamese', 'Naga'], 'ne'], // several words, one region
    [['North Indian', 'Punjabi'], 'north'],
  ])('%j wears the %s accent', (cuisines, region) => {
    expect(regionFor(cuisines)).toBe(region)
  })

  it('uses the plain border for no cuisines, unknown ones, or a mix of regions', () => {
    expect(regionFor([])).toBe('plain')
    expect(regionFor(['Sweets', 'Street Food'])).toBe('plain')
    expect(regionFor(['North Indian', 'South Indian'])).toBe('plain')
  })

  it('matches whole cuisine names, not parts of words', () => {
    expect(regionFor(['Indian'])).toBe('plain')
    expect(regionFor(['north indian'])).toBe('north') // any case
  })
})
