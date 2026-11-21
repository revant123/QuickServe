import { useRef, useState } from 'react'
import { PRESETS, useLocationPlace } from '../location/location'

/** The "Deliver to …" button and the dialog it opens. Uses the native <dialog>: focus trapping and Esc for free. */
export function LocationPicker() {
  const { place, setPlace, locate } = useLocationPlace()
  const ref = useRef<HTMLDialogElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function useMine() {
    setBusy(true)
    setError(null)
    try {
      await locate()
      ref.current?.close()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not get your location.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button type="button" className="deliver-to" onClick={() => ref.current?.showModal()}>
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#E8C66A" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" />
          <circle cx="12" cy="9.5" r="2.5" />
        </svg>
        <span>
          Deliver to <strong>{place.label}</strong>
        </span>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#E8C66A" strokeWidth="2" strokeLinecap="round">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      <dialog ref={ref} className="sheet" aria-labelledby="loc-title">
        <h2 id="loc-title">Where should we deliver?</h2>
        <button type="button" className="btn" onClick={useMine} disabled={busy}>
          {busy ? 'Finding you…' : 'Use my current location'}
        </button>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <p className="muted">Or pick a demo area (the seed data's restaurants are here):</p>
        <ul className="plain-list">
          {PRESETS.map((p) => (
            <li key={p.label}>
              <button
                type="button"
                className={`choice ${p.label === place.label ? 'on' : ''}`}
                aria-pressed={p.label === place.label}
                onClick={() => {
                  setPlace(p)
                  ref.current?.close()
                }}
              >
                {p.label}
              </button>
            </li>
          ))}
        </ul>
        <button type="button" className="btn ghost" onClick={() => ref.current?.close()}>
          Close
        </button>
      </dialog>
    </>
  )
}
