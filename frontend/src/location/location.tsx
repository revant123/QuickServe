import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

export interface Place {
  lat: number
  lng: number
  label: string
}

/** Points the seed data covers, so the app works without sharing your location. */
export const PRESETS: Place[] = [
  { lat: 30.7333, lng: 76.7794, label: 'Sector 22, Chandigarh' },
  { lat: 30.723, lng: 76.7595, label: 'Sector 35, Chandigarh' },
  { lat: 30.7046, lng: 76.7179, label: 'Phase 7, Mohali' },
]

const KEY = 'qs.place'

function load(): Place {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Place | null
    if (saved && Number.isFinite(saved.lat) && Number.isFinite(saved.lng) && saved.label) return saved
  } catch {
    /* fall through to the default */
  }
  return PRESETS[0]!
}

interface LocationApi {
  place: Place
  setPlace: (p: Place) => void
  locate: () => Promise<void>
}

const Ctx = createContext<LocationApi | null>(null)

export function LocationProvider({ children }: { children: ReactNode }) {
  const [place, setPlaceState] = useState<Place>(load)

  const setPlace = useCallback((p: Place) => {
    setPlaceState(p)
    try {
      localStorage.setItem(KEY, JSON.stringify(p))
    } catch {
      /* not saved; still used for this visit */
    }
  }, [])

  const locate = useCallback(
    () =>
      new Promise<void>((resolve, reject) => {
        if (!('geolocation' in navigator)) return reject(new Error('This browser cannot share a location.'))
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            // 4 decimals is about 11 m: plenty for delivery, and less precise than the raw fix.
            const round = (x: number) => Math.round(x * 1e4) / 1e4
            setPlace({ lat: round(pos.coords.latitude), lng: round(pos.coords.longitude), label: 'Current location' })
            resolve()
          },
          (err) => reject(new Error(err.code === err.PERMISSION_DENIED ? 'Location permission was denied.' : 'Could not get your location.')),
          { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
        )
      }),
    [setPlace],
  )

  const value = useMemo(() => ({ place, setPlace, locate }), [place, setPlace, locate])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useLocationPlace(): LocationApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useLocationPlace must be used inside <LocationProvider>')
  return ctx
}
