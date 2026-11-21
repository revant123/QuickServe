import { useEffect, useRef } from 'react'

/** "Your cart has dishes from X. Start a new cart?" Orders come from one restaurant. */
export function ReplaceCartDialog({
  open,
  current,
  next,
  onConfirm,
  onCancel,
}: {
  open: boolean
  current: string
  next: string
  onConfirm: () => void
  onCancel: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal?.()
    if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog ref={ref} className="sheet" aria-labelledby="replace-title" onCancel={onCancel}>
      <h2 id="replace-title">Start a new cart?</h2>
      <p>
        Your cart has dishes from <strong>{current}</strong>. An order comes from one restaurant, so adding this dish
        from <strong>{next}</strong> will empty it.
      </p>
      <div className="row">
        <button type="button" className="btn ghost" onClick={onCancel}>
          Keep my cart
        </button>
        <button type="button" className="btn" onClick={onConfirm}>
          Start new cart
        </button>
      </div>
    </dialog>
  )
}
