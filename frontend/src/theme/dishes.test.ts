import { drawingFor } from './dishes'

describe('drawingFor', () => {
  it.each([
    ['Dal Baati Churma', 'i-dalbaati'], // baati before dal
    ['Gujarati Thali', 'i-thali'], // thali before anything else
    ['Masala Dosa', 'i-dosa'],
    ['Veg Steamed Momos', 'i-momos'],
    ['Khaman Dhokla', 'i-dhokla'],
    ['Butter Chicken', 'i-butterchicken'],
    ['Dal Makhani', 'i-dalmakhani'],
    ['Methi Thepla', 'i-naan'],
    ['Filter Coffee', 'i-coffee'],
    ['Rasmalai', 'i-thali'], // no drawing yet: a thali
  ])('%s -> %s', (name, id) => {
    expect(drawingFor(name)).toBe(id)
  })
})
