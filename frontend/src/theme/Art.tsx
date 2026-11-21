import { FOOD, PATTERNS } from './art'
import { REGIONS, type Region } from './regions'

/** Rendered once at the top of the app: the patterns and drawings everything else points at. */
export function ArtDefs() {
  return (
    <svg
      aria-hidden="true"
      width="0"
      height="0"
      style={{ position: 'absolute' }}
      // Constant, project-authored SVG (see art.ts), never user content.
      dangerouslySetInnerHTML={{ __html: `<defs>${PATTERNS}${FOOD}</defs>` }}
    />
  )
}

export function RegionStrip({ region, height = 12 }: { region: Region; height?: number }) {
  return (
    <svg aria-hidden="true" width="100%" height={height} style={{ display: 'block' }}>
      <rect width="100%" height={height} fill={`url(#${REGIONS[region].pattern})`} />
    </svg>
  )
}

/** A region's pattern filling its parent, softened so a picture can sit on top. */
export function RegionWash({ region, strength = 0.38 }: { region: Region; strength?: number }) {
  return (
    <svg aria-hidden="true" width="100%" height="100%" className="wash">
      <rect width="100%" height="100%" fill={`url(#${REGIONS[region].pattern})`} />
      <rect width="100%" height="100%" fill="#FBF5E9" opacity={1 - strength} />
    </svg>
  )
}

export function Drawing({ id, size, label }: { id: string; size: number; label?: string }) {
  return (
    <svg
      width={size}
      height={size}
      className="drawing"
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
    >
      <use href={`#${id}`} />
    </svg>
  )
}

/** The ogee (jharokha-style) arch drawn behind the logo. */
export function Arch() {
  return (
    <svg aria-hidden="true" viewBox="0 0 350 118" className="arch" preserveAspectRatio="xMidYMax meet">
      <path
        d="M8,118 L8,66 C8,44 40,34 74,30 C112,26 150,16 175,2 C200,16 238,26 276,30 C310,34 342,44 342,66 L342,118"
        fill="none"
        stroke="#C9A03C"
        strokeWidth="1.6"
      />
      <path
        d="M18,118 L18,68 C18,50 46,42 78,38 C114,34 150,25 175,12 C200,25 236,34 272,38 C304,42 332,50 332,68 L332,118"
        fill="none"
        stroke="#C9A03C"
        strokeWidth="0.8"
        strokeDasharray="2 3"
      />
    </svg>
  )
}
