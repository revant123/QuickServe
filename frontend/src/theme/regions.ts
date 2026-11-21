/**
 * Which regional accent a restaurant wears, picked from its cuisines
 * (the `cuisines` field added in Phase 12).
 *
 * Exactly one region matched: that region. None, or several (a "North Indian,
 * South Indian" place): the plain gold zari border. Guessing one region for a
 * mixed menu would be wrong for half of it.
 */
export type Region = 'raj' | 'guj' | 'south' | 'ne' | 'north' | 'plain'

const KEYWORDS: [Exclude<Region, 'plain'>, string[]][] = [
  ['raj', ['rajasthani', 'marwari']],
  ['guj', ['gujarati', 'kathiyawadi', 'kutchi']],
  ['south', ['south indian', 'tamil', 'chettinad', 'kerala', 'andhra', 'udupi', 'karnataka', 'hyderabadi']],
  ['ne', ['northeast', 'north east', 'assamese', 'naga', 'manipuri', 'mizo', 'khasi', 'tripuri']],
  ['north', ['north indian', 'punjabi', 'mughlai', 'awadhi']],
]

export function regionFor(cuisines: readonly string[]): Region {
  const found = new Set<Region>()
  for (const cuisine of cuisines) {
    const c = cuisine.trim().toLowerCase()
    for (const [region, words] of KEYWORDS) {
      if (words.some((w) => c === w || c.startsWith(w + ' '))) found.add(region)
    }
  }
  return found.size === 1 ? [...found][0]! : 'plain'
}

export interface RegionInfo {
  label: string // for filter chips
  craft: string // the textile tradition the border nods to
  accent: string // buttons and small marks; all pass 4.5:1 on ivory
  pattern: string // the <pattern> id in theme/art.ts
}

export const REGIONS: Record<Region, RegionInfo> = {
  raj: { label: 'Rajasthani', craft: 'Block print', accent: '#A3271F', pattern: 'raj' },
  guj: { label: 'Gujarati', craft: 'Bandhani', accent: '#A61E22', pattern: 'guj' },
  south: { label: 'South Indian', craft: 'Temple border', accent: '#1F5A3A', pattern: 'south' },
  ne: { label: 'Northeast', craft: 'Handloom weave', accent: '#1E1A18', pattern: 'ne' },
  north: { label: 'North Indian', craft: 'Phulkari', accent: '#7A1324', pattern: 'north' },
  plain: { label: 'Other', craft: 'Zari', accent: '#6E1423', pattern: 'zari' },
}

export const FILTER_REGIONS: Exclude<Region, 'plain'>[] = ['raj', 'guj', 'south', 'ne', 'north']
