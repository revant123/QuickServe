/**
 * The API sends money as decimal STRINGS ("324.68"), never as floats: 0.1 + 0.2
 * isn't 0.3 in binary floating point. This app only displays money; every sum
 * is done by the server, which is the only place a price is decided.
 */
const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
const inrWhole = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

export function rupees(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return ''
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return ''
  return Number.isInteger(n) ? inrWhole.format(n) : inr.format(n)
}

/** Paise as integers for the cart's *estimate* only (the server's quote is the truth). */
export function toPaise(value: string | number): number {
  return Math.round(Number(value) * 100)
}

export function fromPaise(paise: number): string {
  return (paise / 100).toFixed(2)
}
