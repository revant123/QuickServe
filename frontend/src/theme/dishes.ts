import { slugify } from '../lib/slug'
import type { Region } from './regions'

/** The dish that represents a region on cards and menu headers. */
export const SIGNATURE: Record<Region, string> = {
  raj: 'Dal Baati',
  guj: 'Dhokla',
  south: 'Masala Dosa',
  ne: 'Momos',
  north: 'Thali',
  plain: 'Samosa',
}

/**
 * Which drawing stands in for a dish, from words in its name. Checked in order,
 * so "Dal Baati Churma" matches baati before dal, and "Gujarati Thali" is a thali.
 */
const RULES: [RegExp, string][] = [
  [/thali|thaal/, 'i-thali'],
  [/dosa|uttapam/, 'i-dosa'],
  [/idli|vada/, 'i-idli'],
  [/coffee|chai|tea\b/, 'i-coffee'],
  [/momo/, 'i-momos'],
  [/baati/, 'i-dalbaati'],
  [/dhokla|khaman|khandvi/, 'i-dhokla'],
  [/biryani|pulao/, 'i-biryani'],
  [/samosa|kachori|pakora/, 'i-samosa'],
  [/naan|roti|kulcha|paratha|thepla|bhature|rotli/, 'i-naan'],
  [/paneer|sabzi|gatte|undhiyu|sangri|kofta|thukpa/, 'i-kadhaipaneer'],
  [/chicken|mutton|maas|pork|fish|tenga|keema|egg/, 'i-butterchicken'],
  [/dal|daal|makhani|kadhi|rajma|chole|sambar/, 'i-dalmakhani'],
]

export function drawingFor(dishName: string): string {
  const name = dishName.toLowerCase()
  return RULES.find(([re]) => re.test(name))?.[1] ?? 'i-thali'
}

/**
 * Your own photos, if you put any in src/photos/ (ignored by git, see its README).
 * import.meta.glob runs at BUILD time: only photos that exist are bundled, each
 * with a content hash in its URL, so a dish without a photo costs no request
 * and no 404, and photos can be cached for a year.
 */
const photos = import.meta.glob<string>('../photos/*.{webp,jpg,jpeg,png}', {
  eager: true,
  query: '?url',
  import: 'default',
})

const bySlug = new Map<string, string>(
  Object.entries(photos).map(([path, url]) => [path.split('/').pop()!.replace(/\.[a-z]+$/, ''), url]),
)

export function photoFor(dishName: string): string | undefined {
  return bySlug.get(slugify(dishName))
}
